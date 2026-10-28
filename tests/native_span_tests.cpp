// Authored per-boundary native dispatch tests. No retail source or data.
#include "pce/native_span.hpp"
#include "pce/code_capture.hpp"
#include <algorithm>
#include <charconv>
#include <chrono>
#include <filesystem>
#include <iostream>
#include <iomanip>
#include <limits>
#include <string>
#include <vector>

namespace {
unsigned checks=0;
void require(bool value,const char* message) {++checks;if(!value)throw std::runtime_error(message);}
std::uint64_t hash(const std::uint8_t* data,unsigned length) {
    std::uint64_t value=14695981039346656037ULL;
    for(unsigned i=0;i<length;++i){value^=data[i];value*=1099511628211ULL;}
    return value;
}
std::vector<std::uint64_t> state(const pce::Bus& b,const pce::Cpu& c) {
    std::vector<std::uint64_t> out{c.pc,c.a,c.x,c.y,c.sp,c.p,c.cycles,c.ticks,c.clock_divisor,
        c.mpr_latch,c.irq_sampled,c.irq_entries,c.rti_steps,c.vdc_wait_ticks,c.block_bytes,
        c.native_block_steps+c.interpreter_block_steps};
    for(auto value:c.mpr)out.push_back(value);
    out.insert(out.end(),{hash(b.bytes->data()+0x1F0000,8192),hash(b.bytes->data()+0x100000,8192),
        hash(b.bytes->data()+0x102000,8192),b.generation[0xF8],b.generation[0x80],b.generation[0x81],
        b.io_latch,b.irq.master_ticks,b.irq.external});
    return out;
}
void place(pce::Bus& b,unsigned pc,std::initializer_list<unsigned> data,unsigned bank=0x80) {
    for(auto value:data)(*b.bytes)[(bank<<13)|(pc++&8191)]=static_cast<std::uint8_t>(value);
}
void setup(pce::Bus& b,pce::Cpu& c,unsigned pc) {
    b.kind[0xF8]=b.kind[0x80]=b.kind[0x81]=pce::BankKind::ram;c.pc=static_cast<std::uint16_t>(pc);
    place(b,0x4000,{0xA2,7,0xE8,0xE0,10,0xD0,0xFB,0x4C,0,0x41});
    place(b,0x4100,{0xA9,42,0x80,0xFE});
    place(b,0x4200,{0xA9,0x0B,0x8D,5,0x42,0xEA});
    place(b,0x4300,{0xA9,43,0x8D,6,0x43,0xA2,7,0xEA});
    place(b,0x4400,{0xA9,129,0x53,4});place(b,0x4404,{0xA9,42,0x43,4,0xEA},0x81);
    place(b,0x4500,{0x58,0xEA,0xEA});place(b,0x4600,{0x40});
    place(b,0x4700,{0x73,0,0x48,9,0x47,2,0,0xA9,1,0xA2,7});place(b,0x4800,{0xA2,43});
    place(b,0x4900,{0xAD,0,0x80});place(b,0x4950,{0x58,0xEA});
    place(b,0x4A00,{0x54,0xEA,0xD4,0xEA});
    place(b,0x5000,{0xA5,0x10,0x18,0x69,3,0x85,0x10,0xE8,0xD0,0xF6,0xE6,0x11,0x4C,0,0x50});
    if(pc==0x4500 || pc==0x4950) {
        b.enable_interrupts();b.irq.external=2;b.kind[0]=pce::BankKind::rom;
        (*b.bytes)[0x1FF8]=0;(*b.bytes)[0x1FF9]=0x46;
        if(pc==0x4950)b.kind[0xF8]=pce::BankKind::rom;
    }
}
struct Trace {
    pce::CodeCapture capture;
    pce::CodeCapture::Pending pending;
    unsigned before_count=0,after_count=0;
    bool throw_before=false,throw_after=false,saw_abort=false;
    unsigned stop_after=0;
    pce::NativeSpan* active=nullptr;
    std::uint64_t n=0,i=0;
    std::vector<std::vector<std::uint64_t>> states;
    explicit Trace(const std::filesystem::path& path):capture(path,1024) {}
    static bool before(void* opaque,pce::Bus& b,pce::Cpu& c) {
        auto& t=*static_cast<Trace*>(opaque);++t.before_count;
        if(t.throw_before)throw std::runtime_error("before observer");
        if(t.stop_after && t.states.size()>=t.stop_after)return false;
        t.n=c.native_steps;t.i=c.interpreter_steps;t.pending=t.capture.before(b,c);return true;
    }
    static void after(void* opaque,pce::Bus& b,pce::Cpu& c) {
        auto& t=*static_cast<Trace*>(opaque);++t.after_count;
        if(t.active && t.active->aborting)t.saw_abort=true;
        t.capture.after(t.pending,c);
        if(c.native_steps!=t.n || c.interpreter_steps!=t.i)t.states.push_back(state(b,c));
        if(t.throw_after)throw std::runtime_error("after observer");
    }
    pce::SpanHooks hooks() {return {this,before,after};}
};
struct Result {
    pce::Exit exit=pce::Exit::executed;
    std::string fault;
    std::vector<std::uint64_t> endpoint;
    std::vector<std::vector<std::uint64_t>> states;
    std::uint64_t native=0,interpreted=0,guards=0,completed=0,calls=0,local=0;
    unsigned before=0,after=0;
    bool abort=false;
};
Result run(const std::filesystem::path& directory,const std::string& name,unsigned pc,
           unsigned count,unsigned span_limit,bool allow,std::uint64_t deadline=10000000,
           unsigned stop_after=0,bool throw_before=false,bool throw_after=false) {
    pce::Bus b;pce::Cpu c;setup(b,c,pc);
    Trace trace(directory/(name+".json"));trace.stop_after=stop_after;
    trace.throw_before=throw_before;trace.throw_after=throw_after;
    Result result;
    try {
        if(!span_limit) {
            for(unsigned k=0;k<count;++k) {
                if(!Trace::before(&trace,b,c))break;
                try {result.exit=pce::step(b,c,deadline,allow);}
                catch(...) {Trace::after(&trace,b,c);throw;}
                Trace::after(&trace,b,c);
                if(result.exit!=pce::Exit::executed)break;
            }
        } else {
            while(result.completed<count) {
                pce::NativeSpan span(static_cast<unsigned>(std::min<std::uint64_t>(span_limit,count-result.completed)),trace.hooks());
                trace.active=&span;
                try {result.exit=pce::dispatch_span(b,c,deadline,allow,span,pce::generated_span);}
                catch(...) {
                    result.completed+=span.completed;result.calls+=span.generated_calls;result.local+=span.local_continuations;
                    trace.active=nullptr;throw;
                }
                result.completed+=span.completed;result.calls+=span.generated_calls;result.local+=span.local_continuations;
                trace.active=nullptr;
                if(result.exit!=pce::Exit::executed || !span.completed || trace.stop_after)break;
            }
        }
    } catch(const std::exception& e) {result.fault=e.what();}
    result.endpoint=state(b,c);result.states=trace.states;
    result.native=c.native_steps;result.interpreted=c.interpreter_steps;result.guards=c.guard_misses;
    if(!span_limit)result.completed=c.native_steps+c.interpreter_steps;
    result.before=trace.before_count;result.after=trace.after_count;result.abort=trace.saw_abort;
    trace.capture.finish();return result;
}
void equal(const Result& a,const Result& b) {
    require(a.exit==b.exit && a.fault==b.fault,"span stop/fault differs from single-step");
    require(a.endpoint==b.endpoint && a.states==b.states,"span instruction boundary differs from single-step");
    require(a.native==b.native && a.interpreted==b.interpreted && a.guards==b.guards &&
        a.completed==b.completed,"span actual retirement/guard count differs");
    require(a.before==b.before && a.after==b.after,"span callback count differs");
}
int benchmark(std::string mode,std::string_view iterations) {
    unsigned count=0;
    const auto parsed=std::from_chars(iterations.data(),iterations.data()+iterations.size(),count);
    require(parsed.ec==std::errc{} && parsed.ptr==iterations.data()+iterations.size() &&
        count && count<=10000000,"benchmark requires 1..10000000 actual retirements");
    const unsigned cap=mode=="legacy"?0:mode=="span1"?1:mode=="span16"?16:mode=="span64"?64:999;
    require(cap!=999,"benchmark mode requires legacy/span1/span16/span64");
    pce::Bus b;pce::Cpu c;setup(b,c,0x5000);(*b.bytes)[0x1F0010]=17;
    const auto forever=std::numeric_limits<std::uint64_t>::max();
    std::uint64_t calls=0,continuations=0,batches=0;
    const auto start=std::chrono::steady_clock::now();
    if(!cap) {
        for(unsigned k=0;k<count;++k) {
            if(pce::step(b,c,forever,false)!=pce::Exit::executed)
                throw std::runtime_error("legacy benchmark left native module");
            ++calls;
        }
    } else while(c.native_steps<count) {
        pce::NativeSpan span(std::min<unsigned>(cap,static_cast<unsigned>(count-c.native_steps)));
        if(pce::dispatch_span(b,c,forever,false,span,pce::generated_span)!=pce::Exit::executed)
            throw std::runtime_error("span benchmark left native module");
        if(!span.completed || span.native_completed!=span.completed || span.interpreted_completed)
            throw std::runtime_error("span benchmark did not retire selected native work");
        calls+=span.generated_calls;continuations+=span.local_continuations;++batches;
    }
    const double seconds=std::chrono::duration<double>(std::chrono::steady_clock::now()-start).count();
    require(c.native_steps==count && !c.interpreter_steps && !c.guard_misses,"benchmark actual native work differs");
    std::cout<<"{\"schema\":1,\"mode\":\""<<mode<<"\",\"semantic\":{\"retirements\":"<<count
        <<",\"native_steps\":"<<c.native_steps<<",\"interpreter_steps\":"<<c.interpreter_steps
        <<",\"guard_misses\":"<<c.guard_misses<<",\"pc\":"<<c.pc<<",\"a\":"<<unsigned(c.a)
        <<",\"x\":"<<unsigned(c.x)<<",\"y\":"<<unsigned(c.y)<<",\"sp\":"<<unsigned(c.sp)
        <<",\"p\":"<<unsigned(c.p)<<",\"cycles\":"<<c.cycles<<",\"ticks\":"<<c.ticks
        <<",\"divisor\":"<<c.clock_divisor<<",\"mpr_latch\":"<<unsigned(c.mpr_latch)<<",\"mpr\":[";
    for(unsigned index=0;index<8;++index)std::cout<<(index?",":"")<<unsigned(c.mpr[index]);
    std::cout<<"],\"wram_hash64\":"<<hash(b.bytes->data()+0x1F0000,8192)
        <<",\"code_hash64\":"<<hash(b.bytes->data()+0x100000,8192)
        <<",\"generation_f8\":"<<b.generation[0xF8]<<",\"generation_80\":"<<b.generation[0x80]
        <<",\"sum\":"<<unsigned((*b.bytes)[0x1F0010])<<",\"wraps\":"<<unsigned((*b.bytes)[0x1F0011])
        <<"},\"dispatch\":{\"generated_calls\":"<<calls<<",\"span_batches\":"<<batches
        <<",\"local_continuations\":"<<continuations<<"},\"simulation_seconds\":"
        <<std::setprecision(12)<<seconds<<"}\n";
    return 0;
}
}
int main(int argc,char** argv) {
    try {
        if(argc==4 && std::string(argv[1])=="--benchmark")return benchmark(argv[2],argv[3]);
        require(argc==2,"new capture directory required");const std::filesystem::path out=argv[1];
        require(std::filesystem::is_directory(out),"capture directory missing");
        unsigned serial=0;
        auto execute=[&](unsigned pc,unsigned count,unsigned cap,bool allow=true,std::uint64_t deadline=10000000) {
            return run(out,"case-"+std::to_string(serial++),pc,count,cap,allow,deadline);
        };
        const auto basic=execute(0x4000,18,0);
        require(basic.native==18 && !basic.interpreted && basic.endpoint[0]==0x4102 &&
            basic.endpoint[2]==10 && basic.endpoint[6]==54 && basic.endpoint[7]==162,"basic independent endpoint differs");
        for(unsigned cap:{1U,2U,3U,16U,256U}) {
            auto candidate=execute(0x4000,18,cap);equal(basic,candidate);
            require(candidate.calls<=18,"span global call count inflated");
            require(cap==1 ? candidate.local==0:candidate.local>0,"local continuation accounting absent");
        }
        for(auto pc:{0x4200U,0x4300U,0x4400U,0x4500U,0x4700U,0x4900U,0x4950U,0x4A00U}) {
            const unsigned count=pc==0x4400?5:pc==0x4500 || pc==0x4700?3:4;
            for(bool allow:{false,true}) {
                auto reference=execute(pc,count,0,allow);
                for(unsigned cap:{1U,2U,16U,256U})equal(reference,execute(pc,count,cap,allow));
            }
        }
        auto modified=execute(0x4300,4,16);
        require(modified.native==3 && modified.interpreted==1 && modified.guards==1 &&
            modified.endpoint[2]==43 && modified.endpoint[0]==0x4308 && modified.endpoint[7]==33,
            "self-modified operand did not miss and interpret exactly once");
        auto mapping=execute(0x4400,5,16);
        require(mapping.native==5 && !mapping.interpreted && !mapping.guards && mapping.endpoint[0]==0x4409 &&
            mapping.endpoint[1]==129 && mapping.endpoint[9]==129 && mapping.endpoint[18]==129 && mapping.endpoint[7]==45,
            "TAM context redispatch did not preserve full mapping/latch");
        auto irq=execute(0x4500,3,16);
        require(irq.endpoint[0]==0x4502 && irq.endpoint[11]==1 && irq.endpoint[12]==1 && irq.endpoint[7]==57,
            "IRQ entry/RTI boundary endpoint differs");
        auto block=execute(0x4700,3,16);
        require(block.native==2 && block.interpreted==1 && block.guards==1 && block.endpoint[2]==43 &&
            block.endpoint[15]==1 && block.endpoint[14]==2 && block.endpoint[7]==99,
            "block write/source guard/clock endpoint differs");
        for(auto deadline:{0ULL,18ULL,43ULL,10000000ULL}) {
            auto reference=execute(0x4A00,4,0,true,deadline);
            for(unsigned cap:{1U,2U,16U,256U})equal(reference,execute(0x4A00,4,cap,true,deadline));
        }
        auto speed=execute(0x4A00,4,16);
        require(speed.endpoint[6]==10 && speed.endpoint[7]==75 && speed.endpoint[8]==3,"speed boundary timing differs");
        auto fault=execute(0x4950,4,16);
        require(fault.native==2 && fault.completed==2 && fault.before==2 && fault.after==2 &&
            fault.abort && fault.endpoint[7]==12,"retired opcode before IRQ fault was not closed once");
        auto after=run(out,"after-throws",0x4000,4,16,true,10000000,0,false,true);
        require(after.fault=="after observer" && after.native==1 && after.completed==1 && after.after==1,
            "after exception was replaced or callback repeated");
        auto before=run(out,"before-throws",0x4000,4,16,true,10000000,0,true,false);
        require(before.fault=="before observer" && !before.completed && before.before==1 && !before.after,
            "before exception was replaced or called after without pending attempt");
        auto stopped=run(out,"observer-stops",0x4000,18,16,true,10000000,3);
        require(stopped.native==3 && stopped.completed==3 && stopped.before==4 && stopped.after==3,
            "observer yield opened an extra instruction");
        pce::Bus b;pce::Cpu c;setup(b,c,0x4000);
        for(unsigned cap:{0U,257U}) {
            bool rejected=false;try {pce::NativeSpan span(cap);}catch(const pce::Fault&){rejected=true;}
            require(rejected,"invalid span limit accepted");
        }
        pce::NativeSpan empty(1);bool rejected=false;
        try {pce::dispatch_span(b,c,10000,false,empty,nullptr);}catch(const pce::Fault&){rejected=true;}
        require(rejected && !c.native_steps && !empty.completed,"missing explicit span entry accepted");
        for(unsigned kind:{0U,1U,2U}) {
            pce::Bus bad_bus;pce::Cpu bad_cpu;setup(bad_bus,bad_cpu,0x4000);
            pce::NativeSpan malformed(4);
            const pce::GeneratedSpan bad=kind==0 ? +[](pce::Bus&,pce::Cpu&,std::uint64_t,pce::NativeSpan&){return pce::Exit::executed;}:
                kind==1 ? +[](pce::Bus& bus,pce::Cpu& cpu,std::uint64_t deadline,pce::NativeSpan& span){
                    cpu.retire(2,true);cpu.retire(2,true);span.commit(bus,cpu,deadline);return pce::Exit::executed;}:
                +[](pce::Bus& bus,pce::Cpu& cpu,std::uint64_t deadline,pce::NativeSpan& span){
                    cpu.retire(2,true);--cpu.native_steps;span.commit(bus,cpu,deadline);return pce::Exit::executed;};
            bool stopped=false;
            try {pce::dispatch_span(bad_bus,bad_cpu,10000000,false,malformed,bad);}
            catch(const pce::Fault&){stopped=true;}
            require(stopped && !malformed.completed,"malformed native operations escaped per-instruction check");
        }
        std::cout<<"{\"passed\":true,\"checks\":"<<checks<<",\"cases\":"<<serial
                 <<",\"basic_native\":18,\"basic_ticks\":162,\"operand_promotion_native\":3,\"operand_fallback\":1}\n";
        return 0;
    } catch(const std::exception& error) {std::cerr<<error.what()<<'\n';return 1;}
}
