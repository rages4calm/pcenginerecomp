// Authored software-primer fixture: direct static operations, no opcode bridge.
#include "pce/runtime.hpp"
#include "pce/code_capture.hpp"
#include "speed_trace_fixture.hpp"
#include "reset_probe_support.hpp"
#include "reference_trace_support.hpp"
#include <memory>
#include <string>
namespace {
void require(bool ok,const std::string& why){if(!ok)throw std::runtime_error(why);}
reference_trace::State observe(const pce::Bus& b,const pce::Cpu& c){
    reference_trace::State s;s.pc=c.pc;s.a=c.a;s.x=c.x;s.y=c.y;s.sp=c.sp;s.p=c.p;
    s.mpr=c.mpr;s.mpr_latch=c.mpr_latch;s.clock_divisor=c.clock_divisor;s.ticks=c.ticks;
    s.wram_sha256=reference_trace::hash(std::span<const std::uint8_t>(b.bytes->data()+0x1F0000,8192));return s;
}
std::vector<std::uint64_t> values(const pce::Bus& b,const pce::Cpu& c,std::uint64_t origin){
    std::vector<std::uint64_t> row{c.pc,c.a,c.x,c.y,c.sp,c.p,c.clock_divisor,c.ticks-origin};
    for(auto m:c.mpr)row.push_back(m);
    const auto& t=b.irq;row.insert(row.end(),{c.mpr_latch,unsigned(t.timer_enabled),t.timer_reload,t.timer_counter,unsigned(t.timer_pending),t.mask,t.timer_enabled?t.timer_deadline-c.ticks:t.timer_frozen_phase});
    for(unsigned i=0;i<4;++i)row.push_back((*b.bytes)[0x1F00F0+i]);return row;
}
void execute(const std::vector<std::uint8_t>& rom,bool native,bool trace,pce::CodeCapture* capture){
    auto bus=std::make_unique<pce::Bus>();auto& b=*bus;pce::Cpu c;
    b.configure_hucard(rom);b.enable_video();b.enable_interrupts();b.enable_psg();b.enable_joypad(false,false);b.power_on_cpu(c,0,0);
    auto step=[&]{pce::CodeCapture::Pending pending;if(capture)pending=capture->before(b,c);
        const auto result=native?pce::generated_step(b,c,100000000):pce::interpret_step(b,c,100000000);
        require(result==pce::Exit::executed,"Authored static speed dispatch missed; fallback forbidden");if(capture)capture->after(pending,c);};
    for(unsigned i=0;i<speed_primer_steps;++i)step();
    require(c.pc==speed_marker && c.clock_divisor==12 && c.sp==255 && c.a==0 && c.x==0 && c.y==0 && c.p==6,"Software primer CPU contract");
    require(c.mpr==std::array<std::uint8_t,8>{0,248,255,0,0,0,0,0} && c.mpr_latch==255,"Software primer mapping contract");
    const auto initial=observe(b,c);const auto origin=c.ticks;
    if(native){const auto before=values(b,c,origin);const auto generation=b.generation;
        require(pce::generated_step(b,c,c.ticks)==pce::Exit::budget,"Deadline guard failed");
        auto wrong=c;wrong.mpr[3]=7;require(pce::generated_step(b,wrong,100000000)==pce::Exit::miss,"Full MPR guard failed");
        require(values(b,c,origin)==before && observe(b,c).wram_sha256==initial.wram_sha256 && b.generation==generation,"Pure guards mutated state");}
    if(trace)reference_trace::write_initial(std::cout,initial);
    for(unsigned i=0;i<speed_trace_steps;++i){
        const auto entry=observe(b,c);step();const auto row=values(b,c,origin);
        if(row!=std::vector<std::uint64_t>(speed_expected_runtime[i].begin(),speed_expected_runtime[i].end())){std::cerr<<"ACTUAL";for(auto v:row)std::cerr<<' '<<v;std::cerr<<"\nEXPECTED";for(auto v:speed_expected_runtime[i])std::cerr<<' '<<v;std::cerr<<'\n';throw std::runtime_error("Independent runtime literal differs at measured ordinal "+std::to_string(i+1));}
        if(trace){reference_trace::write_instruction(std::cout,i+1,entry,observe(b,c));std::cerr<<"SPEED_DEVICE "<<i+1;for(auto v:row)std::cerr<<' '<<v;std::cerr<<'\n';}
    }
    require(c.native_steps==(native?speed_primer_steps+speed_trace_steps:0) && c.interpreter_steps==(native?0:speed_primer_steps+speed_trace_steps),"Actual tier retirement differs");
    require((*b.bytes)[0x1F00F1]==4 && (*b.bytes)[0x1F00F2]==7 && (*b.bytes)[0x1F00F3]==0,"Real timer request/mask/ack controls failed");
    if(trace)reference_trace::write_final(std::cout,speed_trace_steps);
    std::cerr<<"SPEED_WORK "<<c.native_steps<<' '<<c.interpreter_steps<<' '<<speed_trace_steps*27<<' '<<origin<<'\n';
}
}
int main(int argc,char**argv){try{
    if(argc==1){const auto rom=speed_rom();execute(rom,false,false,nullptr);execute(rom,true,false,nullptr);return 0;}
    require(argc==5 && std::string(argv[1])=="--probe","speed-trace-tests [--probe ROM native|interpreted NEW_CAPTURE]");
    const auto rom=reset_probe::rom(argv[2]);require(rom==speed_rom(),"Exact authored firmware required");
    const std::string tier=argv[3];require(tier=="native" || tier=="interpreted","Explicit execution tier required");
    pce::CodeCapture capture(argv[4],1024);execute(rom,tier=="native",true,&capture);capture.finish();return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
