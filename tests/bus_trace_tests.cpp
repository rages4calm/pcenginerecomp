#include "pce/bus_trace.hpp"
#include "pce/checkpoint.hpp"
#include "pce/checkpoint_file.hpp"
#include "bus_trace_fixture.hpp"
#include "bus_reference_fixture.hpp"
#include <fstream>
#include <iostream>
#include <limits>
#include <thread>

namespace {
constexpr auto forever=std::numeric_limits<std::uint64_t>::max();
unsigned checks=0;
void require(bool value,const char* message){++checks;if(!value)throw std::runtime_error(message);}
template<class F>void refuses(F f,const char* message){bool failed=false;try{f();}catch(const pce::Fault&){failed=true;}require(failed,message);}
void initialize(pce::Bus& bus,pce::Cpu& cpu) {
    cpu=pce::Cpu{};cpu.mpr.fill(0xF8);cpu.p=pce::I;cpu.a=0x93;cpu.x=0x17;cpu.y=0x29;
    bus.kind[0xF8]=pce::BankKind::ram;
    for(auto [physical,value]:bus_trace_program)(*bus.bytes)[physical]=value;
    for(unsigned i=0;i<3;++i)(*bus.bytes)[0x1F0030+i]=static_cast<std::uint8_t>(0x51+i*17);
}
pce::BusTraceMetadata metadata(){return {"toolkit-unit",std::string(40,'a'),std::string(64,'b'),std::string(64,'c'),std::string(64,'d'),"authored-unit",std::nullopt};}
void scalar_and_parity() {
    for(auto policy:{pce::ExecutionPolicy::native_only,pce::ExecutionPolicy::interpreter_only})
    for(unsigned divisor:{3U,12U}) {
        pce::Bus observed,plain;pce::Cpu a,b;initialize(observed,a);initialize(plain,b);
        a.clock_divisor=b.clock_divisor=divisor;
        a.pc=b.pc=0x2800;
        pce::BusTrace trace({4,32});trace.attach(observed,a);
        for(auto pc:{0x2800,0x2803,0x2806,0x2807}) {
            a.pc=b.pc=static_cast<std::uint16_t>(pc);
            require(pce::step(observed,a,forever,policy)==pce::Exit::executed,"observed scalar execution");
            require(pce::step(plain,b,forever,policy)==pce::Exit::executed,"disabled scalar execution");
            require(pce::encode_checkpoint(observed,a)==pce::encode_checkpoint(plain,b),"observer changed complete guest checkpoint");
        }
        require(trace.complete() && trace.calls().size()==4 && trace.events().size()==4,"scalar callback/call count");
        const std::array<unsigned,4> addresses{0x2030,0x2031,0x21FF,0x21FF};
        const std::array<unsigned,4> ticks{0,5*divisor,10*divisor,13*divisor};
        for(unsigned i=0;i<4;++i) {
            const auto& event=trace.events()[i];
            require(event.ordinal==i+1 && event.call==i+1 && event.logical==addresses[i],"event chronology/address");
            require(event.physical==0x1F0000+(addresses[i]&8191) && event.mpr==a.mpr,"access mapping");
            require(event.ticks==ticks[i] && event.value==0x51,"literal software callback clocks/value");
        }
        require(trace.events()[0].direction==pce::BusTraceDirection::read &&
            trace.events()[1].direction==pce::BusTraceDirection::write &&
            trace.events()[2].direction==pce::BusTraceDirection::write &&
            trace.events()[3].direction==pce::BusTraceDirection::read,"read/write and real stack ordering");
        auto encoded=trace.jsonl(metadata());
        require(encoded.find("\"fetch\":false")!=std::string::npos && encoded.find("\"complete\":true")!=std::string::npos,"trace capability/closure");
        // A successful finite window detaches; subsequent guest execution and
        // inspection cannot invalidate it or append hidden guard/peek events.
        a.pc=0x2870;pce::step(observed,a,forever,policy);observed.peek(0x1F0030);observed.read(a,0x2030);
        require(trace.complete() && trace.calls().size()==4 && trace.events().size()==4 && trace.jsonl(metadata())==encoded,"bounded window did not remain frozen");
    }
}
void block() {
    for(auto policy:{pce::ExecutionPolicy::native_only,pce::ExecutionPolicy::interpreter_only})
    for(unsigned divisor:{3U,12U}) {
        pce::Bus bus,plain;pce::Cpu cpu,other;initialize(bus,cpu);initialize(plain,other);
        cpu.pc=other.pc=0x2840;cpu.clock_divisor=other.clock_divisor=divisor;
        pce::BusTrace trace({1,32});trace.attach(bus,cpu);
        require(pce::step(bus,cpu,forever,policy)==pce::Exit::executed,"block step");
        pce::step(plain,other,forever,policy);
        require(pce::encode_checkpoint(bus,cpu)==pce::encode_checkpoint(plain,other),"block observation mutated guest");
        require(trace.complete() && trace.events().size()==12 && trace.calls()[0].block_bytes==3,"block fetch excluded or data/stack duplicate");
        for(unsigned i=0;i<3;++i) {
            const auto& read=trace.events()[3+2*i];const auto& write=trace.events()[4+2*i];
            require(read.logical==0x2030+i && write.logical==0x2040+i,"block actual copy addresses");
            require(read.ticks==(14+6*i)*divisor && write.ticks==read.ticks && read.value==write.value,"block post-group cadence/value");
        }
    }
}
void negative_and_sources() {
    pce::Bus bus;pce::Cpu cpu;initialize(bus,cpu);cpu.pc=0x2800;
    pce::BusTrace trace({1,8});trace.attach(bus,cpu);
    (*bus.bytes)[0x1F0801]=0x31;
    const auto before=pce::encode_checkpoint(bus,cpu);
    require(pce::step(bus,cpu,forever,pce::ExecutionPolicy::native_only)==pce::Exit::miss,"real source guard negative");
    require(trace.events().empty() && trace.calls()[0].native==0 && trace.calls()[0].interpreted==0 && cpu.ticks==0,"native guard reads became guest callbacks");
    require(trace.calls()[0].source.bytes[1]==0x31 && trace.calls()[0].source.available,"entry source captured changed overlay");
    require(trace.jsonl(metadata()).find("\"retired\":0")!=std::string::npos,"zero-retirement call serialization");
    // Only the deliberate guard counter changes at a native miss.
    --cpu.guard_misses;require(pce::encode_checkpoint(bus,cpu)==before,"guard negative changed guest state");
    pce::Bus second;pce::Cpu s;initialize(second,s);s.pc=0x2800;
    pce::BusTrace ordinary({1,8});ordinary.attach(second,s);pce::step(second,s,forever,pce::ExecutionPolicy::native_only);
    require(ordinary.calls()[0].source.sha256!=trace.calls()[0].source.sha256,"same-PC mutable source digest collision");
    pce::BusTrace partial({2,8});s.pc=0x2800;partial.attach(second,s);pce::step(second,s,forever,pce::ExecutionPolicy::native_only);partial.detach();
    require(!partial.complete() && partial.jsonl(metadata()).find("\"stop\":\"cancelled\"")!=std::string::npos,"partial observation incorrectly completed");
    pce::BusTrace overflow({1,1});s.pc=0x2840;overflow.attach(second,s);pce::step(second,s,forever,pce::ExecutionPolicy::native_only);
    require(!overflow.complete() && overflow.events().size()==1 && overflow.stop_reason()=="event-limit" && s.block_bytes==3,"event limit altered guest or claimed completion");
    refuses([]{pce::BusTrace invalid({0,10});},"invalid trace bound accepted");
    auto invalid=metadata();invalid.binary_sha256="bad";
    refuses([&]{ordinary.jsonl(invalid);},"unbound producer identity accepted");
}
void fixed_and_irq() {
    for(auto policy:{pce::ExecutionPolicy::native_only,pce::ExecutionPolicy::interpreter_only}) {
        pce::Bus bus;pce::Cpu cpu;initialize(bus,cpu);bus.enable_vdc();cpu.pc=0x2850;
        pce::BusTrace fixed({1,8});fixed.attach(bus,cpu);pce::step(bus,cpu,forever,policy);
        require(fixed.events().size()==1 && fixed.events()[0].space==pce::BusTraceSpace::fixed_vdc &&
            !fixed.events()[0].mpr && !fixed.events()[0].logical && fixed.events()[0].physical==0 && fixed.events()[0].value==5,"fixed VDC fabricated mapping");
        cpu.pc=0x2870;cpu.p=0;bus.enable_interrupts();bus.irq.external=2;
        (*bus.bytes)[0x1F1FF8]=0x00;(*bus.bytes)[0x1F1FF9]=0x29;
        pce::BusTrace irq({1,16});irq.attach(bus,cpu);pce::step(bus,cpu,forever,policy);
        require(irq.events().size()==5 && irq.calls()[0].irq_entries==1 && irq.calls()[0].native+irq.calls()[0].interpreted==1,"IRQ invented extra opcode or omitted stack/vector");
        require(irq.events()[0].logical==0x21FF && irq.events()[3].logical==0xFFF8 && irq.events()[4].logical==0xFFF9,"IRQ actual callback order");
    }
}
void zero_retirement_and_limits() {
    pce::Bus bus;pce::Cpu cpu;initialize(bus,cpu);cpu.pc=0x2870;
    pce::BusTrace budget({1,8});budget.attach(bus,cpu);
    require(pce::step(bus,cpu,0,pce::ExecutionPolicy::native_only)==pce::Exit::budget,"budget result");
    require(budget.complete() && budget.events().empty() && budget.calls()[0].native==0 && cpu.ticks==0,"budget fabricated accesses/clocks/retirement");
    cpu.pc=0x2890;(*bus.bytes)[0x1F0890]=0x0B;
    pce::BusTrace unknown({1,8});unknown.attach(bus,cpu);
    require(pce::step(bus,cpu,forever,pce::ExecutionPolicy::interpreter_only)==pce::Exit::unsupported,"unknown opcode did not refuse");
    require(unknown.complete() && unknown.events().empty() && unknown.calls()[0].interpreted==0 && cpu.ticks==0,"unsupported fetch fabricated data/cycles/retirement");
    cpu.pc=0x2880;cpu.mpr[0]=0xFF;bus.kind[255]=pce::BankKind::io;
    pce::BusTrace fault({1,8});fault.attach(bus,cpu);
    refuses([&]{pce::step(bus,cpu,forever,pce::ExecutionPolicy::interpreter_only);},"unimplemented data access unexpectedly succeeded");
    require(!fault.complete() && fault.stop_reason()=="fault" && fault.calls()[0].faulted && fault.events().empty() && cpu.ticks==0,"faulting access became successful event/retirement");
    require(fault.jsonl(metadata()).find("\"complete\":false")!=std::string::npos,"fault trace claimed completion");
    cpu.mpr.fill(0xF8);cpu.pc=0x2870;
    pce::BusTrace retirement({10,8,1,60000});retirement.attach(bus,cpu);
    pce::step(bus,cpu,forever,pce::ExecutionPolicy::native_only);
    require(retirement.complete() && retirement.calls().size()==1 && retirement.jsonl(metadata()).find("retirement-limit")!=std::string::npos,"retirement bound not enforced/frozen");
    pce::BusTrace wall({10,8,10,1});wall.attach(bus,cpu);
    std::this_thread::sleep_for(std::chrono::milliseconds(2));
    cpu.pc=0x2870;pce::step(bus,cpu,forever,pce::ExecutionPolicy::native_only);
    require(!wall.complete() && wall.calls().empty() && wall.stop_reason()=="wall-limit","wall bound not applied at call entry");
    require(wall.jsonl(metadata()).find("wall-limit")!=std::string::npos,"wall-limit incomplete serialization");
    cpu.mpr[0]=0xFF;cpu.pc=0;
    pce::BusTrace unreadable({1,8});unreadable.attach(bus,cpu);
    pce::step(bus,cpu,forever,pce::ExecutionPolicy::native_only);
    const auto missing=unreadable.jsonl(metadata());
    require(missing.find("\"source\":null")!=std::string::npos &&
        missing.find("\"stop\":\"source-mismatch\",\"complete\":false")!=std::string::npos,
        "unobservable source accepted fabricated identity/completion");
}
int probe(int argc,char**argv) {
    if(argc!=11)throw pce::Fault("probe requires profile policy ROM output revision sourceSHA binarySHA fixtureSHA observed|disabled");
    const std::string profile=argv[2],tier=argv[3];const bool observed=std::string(argv[10])=="observed";
    const auto fixture=bus_fixture(profile);
    std::ifstream input(argv[4],std::ios::binary);std::vector<std::uint8_t> rom((std::istreambuf_iterator<char>(input)),{});
    pce::Bus bus;pce::Cpu cpu;bus.configure_hucard(rom);bus.power_on_cpu(cpu);
    for(unsigned i=0;i<fixture.primer;++i)require(pce::step(bus,cpu,forever,pce::ExecutionPolicy::interpreter_only)==pce::Exit::executed,"fixture primer");
    const auto policy=tier=="native"?pce::ExecutionPolicy::native_only:pce::ExecutionPolicy::interpreter_only;
    pce::BusTrace trace({fixture.instructions.size(),1000});if(observed)trace.attach(bus,cpu);
    const auto native=cpu.native_steps,interpreted=cpu.interpreter_steps;
    for(const auto& ins:fixture.instructions) {
        require(cpu.pc==ins.pc,"fixture source entry PC");
        require(pce::step(bus,cpu,forever,policy)==pce::Exit::executed,"fixture measured execution");
    }
    if(observed)trace.write(argv[5],{tier=="native"?"toolkit-native":"toolkit-interpreter",argv[6],argv[7],argv[8],argv[9],"authored-bus-"+profile,std::nullopt});
    std::cout<<"{\"checkpoint_sha256\":\""<<pce::checkpoint_hash(pce::encode_checkpoint(bus,cpu))
        <<"\",\"ticks\":"<<cpu.ticks<<",\"native\":"<<cpu.native_steps-native<<",\"interpreted\":"<<cpu.interpreter_steps-interpreted
        <<",\"events\":"<<trace.events().size()<<",\"calls\":"<<trace.calls().size()<<"}\n";
    return 0;
}
int source_identities() {
    pce::Bus bus;pce::Cpu cpu;initialize(bus,cpu);
    for(unsigned op=0;op<256;++op) {
        cpu=pce::Cpu{};cpu.mpr.fill(0xF8);cpu.pc=0x2870;
        for(unsigned i=0;i<7;++i)(*bus.bytes)[0x1F0870+i]=static_cast<std::uint8_t>(i?i*17:op);
        pce::BusTrace trace({1,8});trace.attach(bus,cpu);
        // Native misses observe source candidates without executing arbitrary
        // opcodes. EA is the one compiled source and remains a genuine NOP.
        pce::step(bus,cpu,forever,pce::ExecutionPolicy::native_only);
        const auto& source=trace.calls()[0].source;
        std::cout<<"{\"opcode\":"<<op<<",\"pc\":"<<source.pc<<",\"length\":"<<source.size
            <<",\"sha256\":\""<<source.sha256<<"\"}\n";
    }
    return 0;
}
}
int main(int argc,char**argv) {
    try {
        if(argc>1 && std::string(argv[1])=="--probe")return probe(argc,argv);
        if(argc==2 && std::string(argv[1])=="--source-identities")return source_identities();
        scalar_and_parity();block();negative_and_sources();fixed_and_irq();zero_retirement_and_limits();
        std::cout<<checks<<" authored bus-observer checks passed\n";return 0;
    }catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
}
