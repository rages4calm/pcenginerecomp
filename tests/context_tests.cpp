// Original executable TAM-context fixture. The generated module is static CFG
// output; captures below only measure execution and never supply translations.
#include "pce/runtime.hpp"
#include "pce/code_capture.hpp"
#include "context_fixture.hpp"
#include "reset_probe_support.hpp"
#include <filesystem>
#include <memory>
#include <string>

namespace {
std::vector<std::uint64_t> state(const pce::Bus& b,const pce::Cpu& c) {
    std::vector<std::uint64_t> out{c.pc,c.a,c.x,c.y,c.sp,c.p,c.clock_divisor,c.ticks};
    for(auto v:c.mpr)out.push_back(v);
    out.insert(out.end(),{c.mpr_latch,(*b.bytes)[0x1F0010],(*b.bytes)[0x1F0011],pce::Bus::physical(c,c.pc)});
    return out;
}
void require(bool ok,const char* message){if(!ok)throw std::runtime_error(message);}
unsigned guards(pce::Bus& b,const pce::Cpu& original) {
    unsigned count=0;
    auto check=[&](pce::Cpu c,std::uint64_t deadline,pce::Exit expected) {
        auto before=state(b,c);auto gen=b.generation;
        const auto cycles=c.cycles,n=c.native_steps,i=c.interpreter_steps;
        const auto ram=reset_probe::hash(b.bytes->data()+0x1F0000,8192);
        const auto io=b.io_latch;const auto reads=b.cd.reads,writes=b.cd.writes;
        require(pce::generated_step(b,c,deadline)==expected,"Context guard exit differs");
        require(state(b,c)==before && gen==b.generation && c.cycles==cycles &&
            c.native_steps==n && c.interpreter_steps==i &&
            ram==reset_probe::hash(b.bytes->data()+0x1F0000,8192) &&
            b.io_latch==io && b.cd.reads==reads && b.cd.writes==writes,"Context guard mutated state");
        ++count;
    };
    check(original,original.ticks,pce::Exit::budget);
    auto wrong=original;wrong.mpr[3]=0x77;check(wrong,10000000,pce::Exit::miss);
    // Change each actual instruction byte without advancing a generation:
    // the exact source-byte guard remains the authority, including operands.
    const auto pa=pce::Bus::physical(original,original.pc);
    const auto opcode=*b.peek(pa);
    const unsigned length=opcode==0xAD || opcode==0x8D || opcode==0x4C?3:
        opcode==0xA9 || opcode==0xA2 || opcode==0x53 || opcode==0xD0 || opcode==0x80?2:1;
    for(unsigned byte=0;byte<length;++byte) {
        const auto mapped=pce::Bus::physical(original,static_cast<std::uint16_t>(original.pc+byte));
        const auto backing=b.backing_address(mapped);const auto old=(*b.bytes)[backing];
        (*b.bytes)[backing]=static_cast<std::uint8_t>(old^0xFF);
        check(original,10000000,pce::Exit::miss);(*b.bytes)[backing]=old;
    }
    return count;
}
struct Work{std::uint64_t native=0,interpreted=0;unsigned guards=0,checks=0;};
void execute(bool native,bool probe,const std::vector<std::uint8_t>& rom,pce::CodeCapture* capture,Work& work,bool& first) {
    for(unsigned divisor:{3U,12U}) {
        pce::Bus b;pce::Cpu c;b.configure_hucard(rom);b.power_on_cpu(c,0,0);c.clock_divisor=divisor;
        const auto& expected=divisor==3?context_expected_3:context_expected_12;
        for(unsigned index=0;index<context_steps;++index) {
            if(native)work.guards+=guards(b,c);
            pce::CodeCapture::Pending pending;if(capture)pending=capture->before(b,c);
            const auto result=native?pce::generated_step(b,c,10000000):pce::interpret_step(b,c,10000000);
            require(result==pce::Exit::executed,"Static context dispatch missed; no interpreter bridge permitted");
            if(capture)capture->after(pending,c);
            const auto actual=state(b,c);
            if(actual!=std::vector<std::uint64_t>(expected[index].begin(),expected[index].end()))
                throw std::runtime_error("Independent context literal differs at step "+std::to_string(index+1)+" divisor "+std::to_string(divisor));
            work.checks+=20;if(probe)reset_probe::record(first,"cpu",actual);
        }
        require(c.native_steps==(native?context_steps:0) && c.interpreter_steps==(native?0:context_steps),
            "Actual context execution tier differs");
        work.native+=c.native_steps;work.interpreted+=c.interpreter_steps;
    }
}
}
int main(int argc,char**argv) {
    try {
        const bool probe=argc==5 && std::string(argv[1])=="--probe";
        if(argc!=1 && !probe)throw std::runtime_error("context-tests [--probe ROM native|interpreted NEW_CAPTURE]");
        auto rom=context_rom();bool first=true;Work work;
        if(probe) {
            require(reset_probe::rom(argv[2])==rom,"Probe ROM differs from authored firmware");
            const std::string tier=argv[3];require(tier=="native" || tier=="interpreted","Explicit tier required");
            pce::CodeCapture capture(argv[4],1024);std::cout<<'[';
            execute(tier=="native",true,rom,&capture,work,first);capture.finish();std::cout<<"]\n";
        } else {
            execute(false,false,rom,nullptr,work,first);execute(true,false,rom,nullptr,work,first);
            std::cout<<work.checks<<" independent TAM/context literals; "<<work.guards<<" pure guard negatives\n";
        }
        std::cerr<<"CONTEXT_WORK "<<work.native<<' '<<work.interpreted<<' '<<work.guards<<' '<<work.checks<<'\n';
        return 0;
    }catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
}
