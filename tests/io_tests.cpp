#include "pce/runtime.hpp"
#include "pce/sector.hpp"
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
        if(c.address==0x1817 || c.address==0) continue;
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
                    loaded=255; // Decoded, unassigned standard-CD reads are pull-ups.
                    if(offset==0x1802) loaded=cd.interrupt_enable+(cd.ack ? 128:0);
                    if(offset==0x1803) {loaded=cd.interrupt_active|0x12;cd.bram_unlocked=false;}
                    if(offset==0x1804) loaded=cd.reset;
                    if(offset==0x1805 || offset==0x1806) loaded=0;
                    if(offset==0x1807) loaded=cd.bram_unlocked?128:0;
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
        require(run(forever)==pce::Exit::executed && s.a==255 && bus.cd.bram_unlocked && bus.cd.reads==cd.reads+1,
                "decoded unassigned CD read was mirrored onto BRAM status or rejected");
        cd=bus.cd;
        s.pc=site(0xAD,0x1807);before=s;
        require(run(forever)==pce::Exit::executed && s.a==128 && bus.cd.bram_unlocked && bus.cd.reads==cd.reads+1,
                "selected Gear BRAM status read did not preserve unlock state");
        cd=bus.cd;
        s.pc=site(0x8D,0x1817);before=s;const auto hole_latch=bus.io_latch;const auto hole_generation=bus.generation;
        auto expected=before;expected.pc+=3;expected.p&=static_cast<std::uint8_t>(~pce::T);expected.cycles+=5;expected.ticks+=5*expected.clock_divisor;
        ++cd.writes;
        require(run(forever)==pce::Exit::executed && cpu_state(s)==cpu_state(expected) && cd_state(bus.cd)==cd_state(cd) &&
                bus.io_latch==hole_latch && bus.generation==hole_generation,"decoded hole write changed BRAM/latch/storage or failed normal retirement");
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

static unsigned bram_readback(pce::Bus& bus) {
    unsigned checks=0;
    for(bool native:{false,true})for(unsigned speed:{3U,12U})for(unsigned alias:{0x1800U,0xB800U})for(unsigned value=0;value<256;++value){
        initialize(bus,value);pce::Cpu s;s.mpr=io_mpr;s.clock_divisor=speed;s.p=255;
        const auto generation=bus.generation;const auto original=(*bus.bytes)[0x1EE000];
        auto instruction=[&](unsigned op,unsigned address,unsigned data=0){
            s.pc=static_cast<std::uint16_t>(site(op,address));if(op==0x8D)s.a=static_cast<std::uint8_t>(data);
            const auto ticks=s.ticks,cycles=s.cycles;
            const auto exit=native?pce::generated_step(bus,s,forever):pce::interpret_step(bus,s,forever);
            require(exit==pce::Exit::executed && s.ticks==ticks+5*speed && s.cycles==cycles+5,"BRAM status sequence timing/tier expectation");
        };
        instruction(0x8D,alias+7,value);instruction(0xAD,alias+7);
        require(s.a==(value>=128?128:0) && bus.cd.bram_unlocked==(value>=128) &&
                bool(s.p&pce::N)==(value>=128) && bool(s.p&pce::Z)==(value<128),"BRAM write/read status bit-seven decode or N/Z expectation");
        instruction(0xAD,alias+3);require(s.a==0x12 && !bus.cd.bram_unlocked,"status register three did not lock BRAM");
        instruction(0xAD,alias+7);require(s.a==0 && (s.p&(pce::N|pce::Z))==pce::Z && !bus.cd.bram_unlocked,"BRAM readback did not report lock caused by register three");
        instruction(0xAD,alias+7);require(s.a==0 && !bus.cd.bram_unlocked,"repeated BRAM status read changed lock state");
        instruction(0x8D,alias+7,value^128);instruction(0xAD,alias+7);
        require(s.a==(value<128?128:0) && bus.cd.bram_unlocked==(value<128),"BRAM unlock/lock rewrite did not replace bit seven");
        instruction(0x8D,alias+3,128);instruction(0xAD,alias+7);
        require(s.a==(value<128?128:0) && bus.cd.bram_unlocked==(value<128),"register-three write changed read-only lock status");
        require(bus.cd.reads==6 && bus.cd.writes==3 && s.cycles==45 && s.ticks==45*speed &&
                s.native_steps==(native?9U:0U) && s.interpreter_steps==(native?0U:9U),"BRAM status sequence access/retirement accounting");
        require(bus.generation==generation && (*bus.bytes)[0x1EE000]==original,"BRAM status sequence changed memory or generations");++checks;
    }
    return checks;
}

static unsigned decoded_holes(pce::Bus& bus) {
    unsigned checks=0;initialize(bus);pce::Cpu s;s.mpr=io_mpr;
    for(bool unlocked:{false,true})for(unsigned page=0;page<8;++page){
        s.mpr=io_mpr;s.mpr[page]=255;bus.cd.bram_unlocked=unlocked;bus.io_latch=0xA5;
        for(unsigned offset=0x1810;offset<0x1C00;++offset){
            const auto reads=bus.cd.reads;const auto generation=bus.generation;
            require(bus.read(s,static_cast<std::uint16_t>((page<<13)|(offset&8191)))==255 &&
                    bus.cd.reads==reads+1 && bus.cd.bram_unlocked==unlocked && bus.io_latch==0xA5 &&
                    bus.generation==generation && !s.cycles && !s.ticks,
                    "decoded CD pull-up read changed latch/gate/storage/clocks or did not translate its MPR");++checks;
        }
    }
    s.mpr=io_mpr;
    // Disabled ADPCM/fader ports cannot inherit hole semantics. This bare
    // functional-CD sandbox has no ordinary System Card/HuCard expansion map.
    for(unsigned address:{0x1809U,0x180AU,0x180BU,0x180CU,0x180DU,0x180EU,0x180FU,0x17FFU,0x1C07U}){
        const auto before=cpu_state(s);const auto cd=cd_state(bus.cd);bool fault=false;
        try{bus.read(s,static_cast<std::uint16_t>(address));}catch(const pce::Fault&){fault=true;}
        require(fault && cpu_state(s)==before && cd_state(bus.cd)==cd,"known unsupported or out-of-window port silently became a CD pull-up read");++checks;
    }
    // Decoded unassigned writes do not alias real ports or drive the I/O latch.
    for(unsigned address:{0x1817U,0x18C0U,0x18C5U,0x1907U,0x1BFFU}){
        const auto before=cpu_state(s);auto expected=bus.cd;++expected.writes;const auto latch=bus.io_latch;const auto generation=bus.generation;
        bus.write(s,static_cast<std::uint16_t>(address),0x80);
        require(cpu_state(s)==before && cd_state(bus.cd)==cd_state(expected) && bus.io_latch==latch && bus.generation==generation,
                "decoded CD hole write changed gate/registers/latch/storage/clocks");++checks;
    }
    return checks;
}

static unsigned sample_latch_instructions() {
    unsigned checks=0;
    for(bool native:{false,true})for(unsigned speed:{3u,12u})for(unsigned alias:{0x1800u,0xB800u})
        for(unsigned tick:{699u,700u,1399u,1400u}) {
            pce::Bus bus;initialize(bus);pce::Cpu cpu;cpu.mpr=io_mpr;cpu.clock_divisor=speed;
            // Prime the first accepted capture for second-write boundary cases.
            if(tick>=1399) {cpu.ticks=700;bus.write(cpu,static_cast<std::uint16_t>(alias+5),0x87);}
            cpu.ticks=tick;cpu.a=0xFF;cpu.pc=site(0x8D,alias+5);
            const auto before_ticks=cpu.ticks;
            const auto result=native ? pce::generated_step(bus,cpu,forever):pce::interpret_step(bus,cpu,forever);
            require(result==pce::Exit::executed && cpu.ticks==before_ticks+5*speed && cpu.cycles==5,
                    "latch store changed CPU instruction timing");
            const unsigned expected=tick<700 || tick==1400 ? 0x12:0x10;
            require(bus.read(cpu,static_cast<std::uint16_t>(alias+3))==expected,
                    "native/interpreted latch admission or right-first status differs");
            for(unsigned port:{5u,6u}) {
                cpu.pc=site(0xAD,alias+port);cpu.a=0xFF;cpu.p=pce::I;
                const auto out=native ? pce::generated_step(bus,cpu,forever):pce::interpret_step(bus,cpu,forever);
                require(out==pce::Exit::executed && cpu.a==0 && (cpu.p&pce::Z) && !(cpu.p&pce::N),
                        "latch load bytes/flags/tier incorrect");
            }
            require(cpu.native_steps==(native?3u:0u) && cpu.interpreter_steps==(native?0u:3u),
                    "latch operations used wrong execution tier");
            ++checks;
        }
    return checks;
}

class LatchSamples final:public pce::SectorProvider {
    pce::CdToc geometry_;std::int16_t left_,right_;
public:
    LatchSamples(std::int16_t left,std::int16_t right):left_(left),right_(right) {
        geometry_.track_count=1;geometry_.leadout_lba=2;geometry_.tracks[0]={0,0};
    }
    const pce::CdToc& toc() const override {return geometry_;}
    pce::Sector read(std::uint32_t) override {throw pce::Fault("unexpected authored data read");}
    bool audio_playable(std::uint32_t lba) const override {return lba<2;}
    pce::AudioSector read_audio(std::uint32_t) override {
        pce::AudioSector out{};for(unsigned i=0;i<588;++i){out[i*2]=left_;out[i*2+1]=right_;}return out;
    }
};
static unsigned signed_sample_instructions() {
    unsigned checks=0;
    for(bool native:{false,true})for(unsigned speed:{3u,12u})for(unsigned alias:{0x1800u,0xB800u})
        for(const auto values:{std::pair<std::int16_t,std::int16_t>{0x1234,-12345},{32767,-32768}}) {
            pce::Bus bus;initialize(bus);bus.enable_cd_transport();bus.cd.audio_enabled=true;
            bus.cd.set_sector_provider(std::make_shared<LatchSamples>(values.first,values.second));
            auto& a=bus.cd.audio;a.state=0;a.stop_lba=1;a.sector_deadline=286363;a.sector_fraction=48;a.reschedule();
            pce::Cpu cpu;cpu.mpr=io_mpr;cpu.clock_divisor=speed;
            for(unsigned channel=0;channel<2;++channel) {
                cpu.ticks=700*(channel+1);cpu.pc=site(0x8D,alias+5);cpu.a=255;
                const auto result=native?pce::generated_step(bus,cpu,forever):pce::interpret_step(bus,cpu,forever);
                require(result==pce::Exit::executed,"authored signed latch capture failed");
                const auto bits=static_cast<std::uint16_t>(channel==0?values.second:values.first);
                for(unsigned byte=0;byte<2;++byte) {
                    cpu.pc=site(0xAD,alias+5+byte);cpu.p=pce::I;
                    const auto out=native?pce::generated_step(bus,cpu,forever):pce::interpret_step(bus,cpu,forever);
                    const unsigned expected=(bits>>(byte*8))&255;
                    require(out==pce::Exit::executed && cpu.a==expected &&
                            bool(cpu.p&pce::N)==bool(expected&128) && bool(cpu.p&pce::Z)==(expected==0),
                            "signed latch byte split or native/interpreter LDA flags differ");
                }
            }
            require(!bus.pcm.enabled && !bus.pcm.frames && cpu.native_steps==(native?6u:0u) &&
                    cpu.interpreter_steps==(native?0u:6u),"latch instructions enabled PCM or changed execution tier");
            ++checks;
        }
    return checks;
}

int main(int argc,char** argv) {
    try {
        if(argc==4 && std::string(argv[1])=="--probe") return probe(argv[2],argv[3]);
        if(argc!=1) return 2;
        pce::Bus bus;initialize(bus);const auto checks=instruction_tests(bus);boundaries(bus);const auto readback=bram_readback(bus),holes=decoded_holes(bus),latches=sample_latch_instructions()+signed_sample_instructions();
        std::cout << checks << " independently expected native/interpreter CD-control/BRAM instruction cases, " << readback << " BRAM status sequences, " << holes << " decoded CD register groups and " << latches << " latch instruction sequences; extent/lock/aliases/RMW/guard/deadline/fault checks passed\n";
        return 0;
    } catch(const std::exception& e) {std::cerr << e.what() << '\n';return 1;}
}
