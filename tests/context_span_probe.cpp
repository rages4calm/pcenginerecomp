// Authored per-retirement observation of an optional multi-instruction module.
#include "pce/runtime.hpp"
#include "pce/native_span.hpp"
#include "pce/code_capture.hpp"
#include "context_fixture.hpp"
#include "reset_probe_support.hpp"
#include <algorithm>
#include <memory>
#include <string>

namespace {
using Row=std::vector<std::uint64_t>;
Row state(const pce::Bus& b,const pce::Cpu& c) {
    Row out{c.pc,c.a,c.x,c.y,c.sp,c.p,c.clock_divisor,c.ticks};
    for(auto value:c.mpr)out.push_back(value);
    out.insert(out.end(),{c.mpr_latch,(*b.bytes)[0x1F0010],(*b.bytes)[0x1F0011],pce::Bus::physical(c,c.pc)});
    return out;
}
void require(bool ok,const char* message){if(!ok)throw std::runtime_error(message);}
struct Work {
    std::uint64_t native=0,interpreted=0,calls=0,attempts=0,after=0;
    std::uint64_t generated_calls=0,local_continuations=0;
    unsigned guards=0,checks=0,max_batch=0;
    std::vector<unsigned> batches;
};
#if defined(PCE_NATIVE_SPAN)
unsigned guards(pce::Bus& b,const pce::Cpu& original) {
    unsigned count=0;
    auto check=[&](pce::Cpu c,std::uint64_t deadline,pce::Exit expected) {
        auto before=state(b,c);auto generation=b.generation;
        const auto cycles=c.cycles,n=c.native_steps,i=c.interpreter_steps;
        const auto ram=reset_probe::hash(b.bytes->data()+0x1F0000,8192);
        const auto io=b.io_latch;const auto reads=b.cd.reads,writes=b.cd.writes;
        pce::NativeSpan span(1);
        require(pce::generated_span(b,c,deadline,span)==expected && span.completed==0,
                "Span pure guard exit/work differs");
        require(state(b,c)==before && generation==b.generation && c.cycles==cycles &&
            c.native_steps==n && c.interpreter_steps==i &&
            ram==reset_probe::hash(b.bytes->data()+0x1F0000,8192) && b.io_latch==io &&
            b.cd.reads==reads && b.cd.writes==writes,"Span guard mutated state");
        ++count;
    };
    check(original,original.ticks,pce::Exit::budget);
    auto wrong=original;wrong.mpr[3]=0x77;check(wrong,10000000,pce::Exit::miss);
    const auto opcode=*b.peek(pce::Bus::physical(original,original.pc));
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
#endif
struct Observation {
    pce::CodeCapture* capture;
    pce::CodeCapture::Pending pending;
    Work* work;
    bool* first;
    unsigned divisor,index=0;
    std::uint64_t before_work=0;
    bool native;
};
bool before(void* context,pce::Bus& b,pce::Cpu& c) {
    auto& o=*static_cast<Observation*>(context);
    require(o.index<context_steps,"Span attempted past independent extent");
    ++o.work->attempts;
#if defined(PCE_NATIVE_SPAN)
    if(o.native)o.work->guards+=guards(b,c);
#endif
    o.before_work=c.native_steps+c.interpreter_steps;
    o.pending=o.capture->before(b,c);
    return true;
}
void after(void* context,pce::Bus& b,pce::Cpu& c) {
    auto& o=*static_cast<Observation*>(context);++o.work->after;
    o.capture->after(o.pending,c);
    if(c.native_steps+c.interpreter_steps==o.before_work)return;
    require(c.native_steps+c.interpreter_steps==o.before_work+1,"Span hid retirements from observer");
    const auto& expected=o.divisor==3?context_expected_3:context_expected_12;
    const auto actual=state(b,c);
    require(actual==Row(expected[o.index].begin(),expected[o.index].end()),
            "Independent per-retirement context literal differs");
    reset_probe::record(*o.first,"cpu",actual);
    ++o.index;o.work->checks+=20;
}
void execute(bool native,unsigned limit,const std::vector<std::uint8_t>& rom,
             pce::CodeCapture& capture,Work& work,bool& first) {
    for(unsigned divisor:{3U,12U}) {
        pce::Bus b;pce::Cpu c;b.configure_hucard(rom);b.power_on_cpu(c,0,0);c.clock_divisor=divisor;
        Observation observer{&capture,{},&work,&first,divisor,0,0,native};
        while(observer.index<context_steps) {
            ++work.calls;
            if(native) {
#if defined(PCE_NATIVE_SPAN)
                pce::NativeSpan span(std::min(limit,context_steps-observer.index),{&observer,before,after});
                const auto result=pce::dispatch_span(b,c,10000000,false,span,pce::generated_span);
                require(result==pce::Exit::executed && span.completed>0,
                        "Actual span execution failed or made no progress");
                work.max_batch=std::max(work.max_batch,static_cast<unsigned>(span.completed));
                work.batches.push_back(static_cast<unsigned>(span.completed));
                work.generated_calls+=span.generated_calls;work.local_continuations+=span.local_continuations;
#else
                throw std::runtime_error("Native span mode requires an opted-in generated module");
#endif
            } else {
                require(before(&observer,b,c),"Interpreted observer rejected attempt");
                require(pce::interpret_step(b,c,10000000)==pce::Exit::executed,
                        "Authored interpreter bootstrap failed");
                after(&observer,b,c);work.max_batch=1;work.batches.push_back(1);
            }
        }
        require(c.native_steps==(native?context_steps:0) && c.interpreter_steps==(native?0:context_steps),
                "Actual span capture execution tier differs");
        work.native+=c.native_steps;work.interpreted+=c.interpreter_steps;
    }
}
}
int main(int argc,char** argv) {
    try {
        require((argc==5 || argc==6) && std::string(argv[1])=="--probe",
                "context-span-probe --probe ROM interpreted|native NEW_CAPTURE [LIMIT]");
        const std::string tier=argv[3];require(tier=="native" || tier=="interpreted","Explicit tier required");
        const auto rom=reset_probe::rom(argv[2]);require(rom==context_rom(),"Authored ROM differs");
        unsigned limit=1;
        if(argc==6) {
            const std::string value=argv[5];std::size_t used=0;
            limit=static_cast<unsigned>(std::stoul(value,&used));
            require(used==value.size() && limit>=1 && limit<=256,"Span limit must be1..256");
        }
        pce::CodeCapture capture(argv[4],1024);Work work;bool first=true;std::cout<<'[';
        execute(tier=="native",limit,rom,capture,work,first);capture.finish();std::cout<<"]\n";
        require(work.attempts==work.after && work.attempts==80,"One observed attempt/retirement required");
        std::cerr<<"SPAN_WORK {\"native\":"<<work.native<<",\"interpreted\":"<<work.interpreted
            <<",\"limit\":"<<limit<<",\"calls\":"<<work.calls<<",\"attempts\":"<<work.attempts
            <<",\"after\":"<<work.after<<",\"max_batch\":"<<work.max_batch
            <<",\"guards\":"<<work.guards<<",\"literal_checks\":"<<work.checks<<",\"batches\":[";
        for(unsigned index=0;index<work.batches.size();++index){if(index)std::cerr<<',';std::cerr<<work.batches[index];}
        std::cerr<<"],\"generated_calls\":"<<work.generated_calls
            <<",\"local_continuations\":"<<work.local_continuations<<"}\n";
        return 0;
    }catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
}
