// Real authored guest instruction execution through both toolkit tiers.
#include "pce/runtime.hpp"
#include "pce/code_capture.hpp"
#include "vdc_scroll_fixture.hpp"
#include "vdc_scroll_support.hpp"
#include "irq_trace_support.hpp"
#include <memory>
#include <optional>
#include <sstream>

namespace {
template<class Tag,typename Tag::type Pointer>struct Access {friend typename Tag::type member(Tag){return Pointer;}};
#define FIELD(Tag,Type,Name) struct Tag {using type=Type pce::VideoOutput::*;friend type member(Tag);};template struct Access<Tag,&pce::VideoOutput::Name>;
FIELD(X,std::uint16_t,scroll_x_)
FIELD(Y,std::uint16_t,scroll_y_)
FIELD(Counter,std::uint16_t,counter_y_)
FIELD(Pending,bool,y_pending_)
FIELD(XClock,int,latch_x_clock_)
FIELD(YClock,int,latch_y_clock_)
FIELD(LsbClock,int,byr_lsb_write_clock_)
FIELD(BxrBefore,bool,bxr_written_before_latch_)
using Pixels=std::array<std::uint16_t,1024>;
FIELD(LinePixels,Pixels,indices_)
#undef FIELD
scroll_probe::State observe(const pce::Bus& bus) {
    const auto& v=bus.vdc.video;
    scroll_probe::State out{v.*member(X{}),v.*member(Y{}),v.*member(Counter{}),v.*member(Pending{}),
        v.*member(XClock{}),v.*member(YClock{}),v.*member(LsbClock{}),v.*member(BxrBefore{})};
    for(unsigned i=0;i<16;++i)out.pixels[i]=(v.*member(LinePixels{}))[i];
    return out;
}
const ScrollCase& selected(const std::string& id) {
    for(const auto& c:scroll_cases)if(id==c.id)return c;
    throw std::runtime_error("Unknown authored scroll case");
}
struct Result {scroll_probe::State scroll;std::string guest;std::string actions;std::uint64_t native,interpreted,blocks,guards;};
Result execute(const ScrollCase& c,bool native,const char* capture_path=nullptr,bool output=true) {
    auto owned=std::make_unique<pce::Bus>();auto& b=*owned;pce::Cpu cpu;
    const auto rom=scroll_rom(c.id);b.configure_system_card(pce::SystemCardProfile::standard,rom);
    if(output)b.enable_continuous_video();else b.enable_video();
    b.enable_interrupts();b.power_on_cpu(cpu,0,0);
    std::optional<pce::CodeCapture> capture;if(capture_path)capture.emplace(capture_path,8192);
    std::ostringstream actions;actions<<'[';unsigned action=0;
    for(unsigned i=0;i<c.steps;++i) {
        const bool measured=action<c.count && c.actions[action].step==i;
        const auto before=observe(b);const auto entry=cpu.ticks;
        if(measured)scroll_probe::require(entry+6==c.actions[action].effect,"Authored guest port-entry phase differs");
        pce::CodeCapture::Pending pending;if(capture)pending=capture->before(b,cpu);
        const auto result=native?pce::generated_step(b,cpu,UINT64_MAX):pce::interpret_step(b,cpu,UINT64_MAX);
        scroll_probe::require(result==pce::Exit::executed,"Actual scroll opcode missed; fallback forbidden");
        if(capture)capture->after(pending,cpu);
        if(measured) {
            const auto after=observe(b);
            actions<<(action?",":"")<<"{\"step\":"<<i<<",\"entry_ticks\":"<<entry<<",\"after_ticks\":"<<cpu.ticks
                   <<",\"effect_ticks\":"<<c.actions[action].effect<<",\"port\":"<<c.actions[action].port
                   <<",\"value\":"<<c.actions[action].value<<",\"before\":";
            scroll_probe::state(actions,before);actions<<",\"after\":";scroll_probe::state(actions,after);actions<<'}';++action;
        }
    }
    actions<<']';const auto state=observe(b);scroll_probe::require(state==observe(b),"Scroll observation mutated state");
    scroll_probe::expected(state,c);
    scroll_probe::require(cpu.ticks==c.ticks && cpu.pc==c.end_pc && cpu.vdc_wait_ticks==0,"Independent guest final phase/PC/wait literal differs");
    scroll_probe::require(action==c.count && cpu.native_steps==(native?c.steps:0) && cpu.interpreter_steps==(native?0:c.steps) && cpu.guard_misses==0,"Actual scroll source accounting differs");
    std::ostringstream guest;guest<<"{\"pc\":"<<cpu.pc<<",\"ticks\":"<<cpu.ticks<<",\"a\":"<<unsigned(cpu.a)
        <<",\"x\":"<<unsigned(cpu.x)<<",\"y\":"<<unsigned(cpu.y)<<",\"sp\":"<<unsigned(cpu.sp)
        <<",\"p\":"<<unsigned(cpu.p)<<",\"mpr\":[";
    for(unsigned i=0;i<8;++i)guest<<(i?",":"")<<unsigned(cpu.mpr[i]);
    guest<<"],\"wram_sha256\":\""<<irq_trace::hash(std::span<const std::uint8_t>(b.bytes->data()+0x1F0000,8192))<<"\"}";
    if(capture)capture->finish();
    return {state,guest.str(),actions.str(),cpu.native_steps,cpu.interpreter_steps,cpu.native_block_steps+cpu.interpreter_block_steps,cpu.guard_misses};
}
}
int main(int argc,char** argv) {try {
    if(argc==1) {
        std::uint64_t native=0,interpreted=0;
        for(const auto& c:scroll_cases) {
            const auto n=execute(c,true),i=execute(c,false),no_output=execute(c,true,nullptr,false);
            scroll_probe::require(n.scroll==i.scroll && n.guest==i.guest && n.actions==i.actions,"Native/interpreter scroll execution differs");
            scroll_probe::require(n.scroll==no_output.scroll && n.guest==no_output.guest,"Host framebuffer production changed guest scroll state");
            native+=n.native;interpreted+=i.interpreted;
        }
        std::cout<<std::size(scroll_cases)<<" authored scroll race profiles; "<<native<<" native, "<<interpreted<<" interpreted, zero fallback; output-disabled guest state matched\n";
        return 0;
    }
    scroll_probe::require(argc==4,"scroll-probe CASE native|interpreter NEW_CAPTURE");
    const std::string tier=argv[2];scroll_probe::require(tier=="native" || tier=="interpreter","Explicit scroll tier required");
    const auto& c=selected(argv[1]);const auto r=execute(c,tier=="native",argv[3]);
    std::cout<<"{\"schema\":1,\"case\":\""<<c.id<<"\",\"tier\":\""<<tier<<"\",\"guest\":"<<r.guest
       <<",\"native_steps\":"<<r.native<<",\"interpreter_steps\":"<<r.interpreted<<",\"block_steps\":"<<r.blocks<<",\"guard_misses\":"<<r.guards<<",\"scroll\":";
    scroll_probe::state(std::cout,r.scroll);std::cout<<",\"actions\":"<<r.actions<<"}\n";return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
