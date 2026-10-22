#include "pce/runtime.hpp"
#include "io_fixture.hpp"
#include <fstream>
#include <iostream>
#include <limits>
#include <tuple>
#include <vector>

constexpr auto forever=std::numeric_limits<std::uint64_t>::max();
static void require(bool value,const char* message) { if(!value) throw std::runtime_error(message); }
static auto cpu_state(const pce::Cpu& s) { return std::tuple{s.a,s.x,s.y,s.sp,s.p,s.pc,s.mpr,s.mpr_latch,s.cycles,s.ticks,s.clock_divisor}; }
static auto cd_state(const pce::CdControl& c) { return std::tuple{c.enabled,c.bram_unlocked,c.ack,c.interrupt_enable,c.interrupt_active,c.reset,c.reads,c.writes,c.irq2()}; }
static unsigned site(unsigned op,unsigned address) {
    for(auto c:io_cases) if(c.op==op && c.address==address) return c.pc;
    throw std::runtime_error("missing synthetic I/O site");
}
static void initialize(pce::Bus& bus,unsigned seed=0) {
    bus.enable_cd_control(); bus.kind[0xF8]=pce::BankKind::ram;
    for(unsigned i=0;i<8192;++i) (*bus.bytes)[0x1F0000+i]=static_cast<std::uint8_t>(i*37+seed*17);
    for(unsigned i=0;i<2048;++i) (*bus.bytes)[0x1EE000+i]=static_cast<std::uint8_t>(i*13+seed*7);
    for(auto [pa,v]:io_program) (*bus.bytes)[pa]=v;
    bus.generation.fill(0);
}
static void print_cd(const pce::CdControl& c) {
    std::cout << "{\"bram_unlocked\":" << (c.bram_unlocked ? "true":"false")
              << ",\"ack\":" << (c.ack ? "true":"false") << ",\"irq_enable\":" << unsigned(c.interrupt_enable)
              << ",\"irq_active\":" << unsigned(c.interrupt_active) << ",\"reset\":" << unsigned(c.reset)
              << ",\"irq2\":" << (c.irq2() ? "true":"false") << "}";
}
static void print_cpu(const pce::Cpu& s) {
    std::cout << "{\"pc\":" << s.pc << ",\"a\":" << unsigned(s.a) << ",\"x\":" << unsigned(s.x)
              << ",\"y\":" << unsigned(s.y) << ",\"sp\":" << unsigned(s.sp) << ",\"p\":" << unsigned(s.p) << ",\"mpr\":[";
    for(unsigned i=0;i<8;++i) std::cout << (i ? ",":"") << unsigned(s.mpr[i]);
    std::cout << "]}";
}
static void print_memory(const pce::Bus& bus,unsigned start,unsigned size) {
    constexpr char h[]="0123456789abcdef";
    for(unsigned i=0;i<size;++i) {auto v=(*bus.bytes)[start+i];std::cout << h[v>>4] << h[v&15];}
}
static int probe(const char* path,const std::string& tier) {
    if(tier!="native" && tier!="interpreter") return 2;
    std::ifstream in(path); unsigned seed,a,x,y,sp,p,count;
    if(!(in>>seed>>a>>x>>y>>sp>>p>>count) || seed>255 || a>255 || x>255 || y>255 || sp>255 || p>255 || count<1 || count>32) return 2;
    std::vector<std::pair<unsigned,int>> steps;
    for(unsigned i=0;i<count;++i) {unsigned pc;int value;if(!(in>>pc>>value) || pc>65535 || value < -1 || value>255) return 2;steps.emplace_back(pc,value);}
    std::string extra;if(in>>extra) return 2;
    pce::Bus bus;initialize(bus,seed);pce::Cpu s;s.mpr=io_mpr;s.a=a;s.x=x;s.y=y;s.sp=sp;s.p=p;
    std::cout << "{\"states\":[";
    for(unsigned i=0;i<count;++i) {
        s.pc=static_cast<std::uint16_t>(steps[i].first);
        if(steps[i].second>=0) s.a=static_cast<std::uint8_t>(steps[i].second);
        auto result=tier=="native" ? pce::generated_step(bus,s,forever):pce::interpret_step(bus,s,forever);
        if(result!=pce::Exit::executed) return 3;
        if(i) std::cout << ',';
        std::cout << "{\"cpu\":";print_cpu(s);std::cout << ",\"cd\":";print_cd(bus.cd);std::cout << '}';
    }
    std::cout << "],\"ram\":\"";print_memory(bus,0x1F0000,8192);std::cout << "\",\"bram\":\"";print_memory(bus,0x1EE000,2048);
    std::cout << "\",\"native_steps\":" << s.native_steps << ",\"interpreter_steps\":" << s.interpreter_steps << "}\n";
    return 0;
}

static unsigned instruction_tests(pce::Bus& bus) {
    unsigned checks=0;
    for(auto c:io_cases) {
        if(c.op!=0xAD && c.op!=0x8D) continue;
        if(c.address==0x1907 || c.address==0x1817 || c.address==0) continue;
        if(c.op==0xAD && (c.address==0x1807 || c.address==0xB807)) continue; // Subcode read is intentionally unsupported.
        for(unsigned v=0;v<256;++v) for(unsigned flags:{0U,255U,0x55U,0xAAU}) for(bool native:{false,true}) {
            pce::Cpu s;s.mpr=io_mpr;s.pc=c.pc;s.a=static_cast<std::uint8_t>(v);s.x=37;s.y=91;s.sp=0xFE;s.p=static_cast<std::uint8_t>(flags);s.mpr_latch=0x65;
            bus.cd=pce::CdControl{true,(v%2)==1,(v%4)>1,static_cast<std::uint8_t>(127-v%128),static_cast<std::uint8_t>(v^0xA5),static_cast<std::uint8_t>(15-v%16)};
            auto expected=s;auto cd=bus.cd;
            const unsigned offset=c.address%8192;
            const bool control=(c.address<8192 || (c.address>=0xA000 && c.address<0xC000));
            const auto pa=0x1EE000+offset;(*bus.bytes)[pa]=0x39;bus.generation.fill(0);
            unsigned byte=0x39,generation=0,loaded=0;
            if(c.op==0x8D) {
                if(control) {
                    if(offset==0x1807) cd.bram_unlocked=v>=128;
                    if(offset==0x1802) {cd.ack=v>=128 && !(cd.reset&2);cd.interrupt_enable=v%128;}
                    if(offset==0x1804) {cd.reset=v%16;if(v%4>=2) {cd.interrupt_active=static_cast<std::uint8_t>(cd.interrupt_active&0x8F);cd.ack=false;}}
                    ++cd.writes;
                } else if(cd.bram_unlocked && offset<2048) {byte=v;generation=v!=0x39;}
            } else {
                if(control) {
                    if(offset==0x1802) loaded=cd.interrupt_enable+(cd.ack ? 128:0);
                    if(offset==0x1803) {loaded=cd.interrupt_active|0x12;cd.bram_unlocked=false;}
                    if(offset==0x1804) loaded=cd.reset;
                    ++cd.reads;
                } else loaded=cd.bram_unlocked && offset<2048 ? 0x39:255;
                expected.a=static_cast<std::uint8_t>(loaded);
                expected.p=static_cast<std::uint8_t>((flags&0x7D)|(loaded>=128 ? 128:0)|(loaded==0 ? 2:0));
            }
            expected.pc+=3;expected.p &= ~pce::T;expected.cycles=5;expected.ticks=15;
            auto result=native ? pce::generated_step(bus,s,forever):pce::interpret_step(bus,s,forever);
            require(result==pce::Exit::executed && cpu_state(s)==cpu_state(expected) && cd_state(bus.cd)==cd_state(cd),"CD/BRAM instruction expected state mismatch");
            require((*bus.bytes)[pa]==byte && bus.generation[0xF7]==generation,"BRAM write/protection/generation mismatch");
            require(s.native_steps==unsigned(native) && s.interpreter_steps==unsigned(!native),"I/O tier counter mismatch");
            ++checks;
        }
    }
    return checks;
}

static void boundaries(pce::Bus& bus) {
    initialize(bus);pce::Cpu s;s.mpr=io_mpr;
    for(unsigned page=0;page<8;++page) for(unsigned v=0;v<256;++v) {
        auto alias=s;s.mpr[page]=0xFF;
        bus.write(s,static_cast<std::uint16_t>((page<<13)|0x1807),static_cast<std::uint8_t>(v));
        require(bus.cd.bram_unlocked==(v>=128),"I/O physical MPR routing/bit7 decode");s=alias;
    }
    bus.write(s,0x1807,128);
    require(!bus.peek(0x1FF803) && !bus.peek(0x1EE000) && bus.cd.bram_unlocked,"source peek touched I/O or exposed BRAM code");
    for(unsigned offset=0;offset<8192;++offset) {
        bus.write(s,static_cast<std::uint16_t>(0x8000+offset),static_cast<std::uint8_t>(offset));
        require(bus.read(s,static_cast<std::uint16_t>(0xC000+offset))==(offset<2048 ? (offset&255):255),"BRAM extent/alias/upper-hole semantics");
    }
    auto ram=std::make_unique<std::array<std::uint8_t,0x200000>>(*bus.bytes);auto generation=bus.generation;
    require(bus.read(s,0x1803)==0x12 && !bus.cd.bram_unlocked,"status read did not lock BRAM");
    for(unsigned offset=0;offset<8192;++offset) {bus.write(s,static_cast<std::uint16_t>(0x8000+offset),0x37);require(bus.read(s,static_cast<std::uint16_t>(0xC000+offset))==255,"locked BRAM read");}
    require(*bus.bytes==*ram && bus.generation==generation,"locked/hole write changed storage");
    for(bool native:{false,true}) {
        initialize(bus);s=pce::Cpu{};s.mpr=io_mpr;s.pc=site(0x8D,0x1807);s.a=0;
        auto before=s;auto cd=bus.cd;
        auto run=[&](std::uint64_t deadline) {return native ? pce::generated_step(bus,s,deadline):pce::interpret_step(bus,s,deadline);};
        require(run(0)==pce::Exit::budget && cpu_state(s)==cpu_state(before) && cd_state(bus.cd)==cd_state(cd),"deadline produced device side effects");
        s.pc=site(0xAD,0x1907);before=s;bool fault=false;
        try {run(forever);} catch(const pce::Fault&) {fault=true;}
        require(fault && cpu_state(s)==cpu_state(before) && cd_state(bus.cd)==cd_state(cd),"unsupported CD register retired or changed state");
        s.pc=site(0xAD,0x1807);fault=false;before=s;
        try {run(forever);} catch(const pce::Fault&) {fault=true;}
        require(fault && cpu_state(s)==cpu_state(before) && cd_state(bus.cd)==cd_state(cd),"subcode register returned invented BRAM readback");
        s.pc=site(0x8D,0x1817);fault=false;before=s;
        try {run(forever);} catch(const pce::Fault&) {fault=true;}
        require(fault && cpu_state(s)==cpu_state(before) && cd_state(bus.cd)==cd_state(cd),"invented 16-byte register mirror");
        s.pc=site(0xBD,0x87FF);s.x=1;
        require(run(forever)==pce::Exit::executed && s.a==255,"indexed load crossing 2 KiB BRAM boundary");
        s.pc=site(0x9D,0x87FF);s.a=0x53;generation=bus.generation;
        require(run(forever)==pce::Exit::executed && bus.generation==generation,"indexed store wrote BRAM hole");
        for(unsigned op:{0x0CU,0x1CU}) {
            bus.write(s,0x1807,128);s.pc=site(op,0x1803);s.a=128;
            require(run(forever)==pce::Exit::executed && !bus.cd.bram_unlocked,"RMW status read failed to lock BRAM");
        }
    }
    initialize(bus);s=pce::Cpu{};s.mpr=io_mpr;s.pc=site(0x8D,0x1807);s.a=255;
    (*bus.bytes)[pce::Bus::physical(s,s.pc)+1]=2;auto before=s;auto cd=bus.cd;
    require(pce::generated_step(bus,s,forever)==pce::Exit::miss && cpu_state(s)==cpu_state(before) && cd_state(bus.cd)==cd_state(cd),"stale native I/O operand caused a side effect");
    require(pce::step(bus,s,forever)==pce::Exit::executed && bus.cd.ack && bus.cd.interrupt_enable==127 && bus.cd.bram_unlocked,"mutated I/O fallback used old target");
    pce::Bus strict;strict.kind[0xFF]=pce::BankKind::io;bool fault=false;
    try {strict.write(s,0x1807,128);} catch(const pce::Fault&) {fault=true;}
    require(fault && !strict.cd.enabled,"strict sandbox silently enabled CD hardware");
}

int main(int argc,char** argv) {
    try {
        if(argc==4 && std::string(argv[1])=="--probe") return probe(argv[2],argv[3]);
        if(argc!=1) return 2;
        pce::Bus bus;initialize(bus);const auto checks=instruction_tests(bus);boundaries(bus);
        std::cout << checks << " independently expected native/interpreter CD-control/BRAM instruction cases; extent/lock/aliases/RMW/guard/deadline/fault checks passed\n";
        return 0;
    } catch(const std::exception& e) {std::cerr << e.what() << '\n';return 1;}
}
