#include "pce/runtime.hpp"
#include "pce/sector.hpp"
#include "scsi_fixture.hpp"
#include <fstream>
#include <iostream>
#include <limits>
#include <tuple>
#include <vector>

namespace {
constexpr auto forever=std::numeric_limits<std::uint64_t>::max();
constexpr std::uint64_t first_load=3507953, sector_time=286363, retry_time=6228408;
unsigned checks=0;
void require(bool condition,const char* reason) {
    if(!condition) throw std::runtime_error(reason);
    ++checks;
}
std::uint8_t pattern(unsigned lba,unsigned offset) {
    return static_cast<std::uint8_t>(lba*29+offset*17+(offset>>8)*7+0x53);
}
class AuthoredProvider final:public pce::SectorProvider {
    pce::CdToc metadata;
public:
    unsigned calls=0;
    int fail_lba=-1;
    explicit AuthoredProvider(unsigned count=24) {
        metadata.track_count=1;metadata.tracks[0]={0,4};metadata.leadout_lba=count;
    }
    const pce::CdToc& toc() const override {return metadata;}
    pce::Sector read(std::uint32_t lba) override {
        ++calls;
        if(lba>=metadata.leadout_lba || lba==static_cast<unsigned>(fail_lba))
            throw pce::Fault("authored unavailable sector");
        pce::Sector bytes{};
        for(unsigned i=0;i<bytes.size();++i)bytes[i]=pattern(lba,i);
        return bytes;
    }
};
unsigned site(unsigned opcode,unsigned address=0) {
    for(const auto& entry:scsi_cases)if(entry.op==opcode && entry.address==address)return entry.pc;
    throw std::runtime_error("missing READ instruction fixture");
}
std::shared_ptr<AuthoredProvider> initialize(pce::Bus& bus,unsigned sectors=24) {
    bus.enable_cd_transport();bus.kind[0xF8]=pce::BankKind::ram;
    for(const auto& [address,value]:scsi_program)(*bus.bytes)[address]=value;
    bus.generation.fill(0);
    auto provider=std::make_shared<AuthoredProvider>(sectors);
    bus.cd.set_sector_provider(provider);return provider;
}
void advance(pce::Bus& bus,pce::Cpu& cpu,std::uint64_t ticks) {
    cpu.ticks+=ticks;bus.sync(cpu);
}
void execute(pce::Bus& bus,pce::Cpu& cpu,bool native,unsigned opcode,unsigned address=0,int value=-1) {
    cpu.pc=static_cast<std::uint16_t>(site(opcode,address));
    if(value>=0)cpu.a=static_cast<std::uint8_t>(value);
    require((native?pce::generated_step(bus,cpu,forever):pce::interpret_step(bus,cpu,forever))==pce::Exit::executed,
            "READ fixture instruction refused execution");
}
void command(pce::Bus& bus,pce::Cpu& cpu,unsigned lba,unsigned count,unsigned high=0) {
    bus.write(cpu,0x1800,0);advance(bus,cpu,75000);
    const unsigned bytes[]={8,((lba>>16)&31)|high,(lba>>8)&255,lba&255,count,0};
    for(unsigned i=0;i<6;++i) {
        require(bus.read(cpu,0x1800)==0xD0,"READ command byte missing REQ");
        bus.write(cpu,0x1801,static_cast<std::uint8_t>(bytes[i]));
        bus.write(cpu,0x1802,0xE0);bus.write(cpu,0x1802,0x60);
        if(i<5)advance(bus,cpu,3000);
    }
}
void acknowledge(pce::Bus& bus,pce::Cpu& cpu) {
    bus.write(cpu,0x1802,0xE0);bus.write(cpu,0x1802,0x60);
}
void finish(pce::Bus& bus,pce::Cpu& cpu,unsigned status) {
    require(bus.read(cpu,0x1800)==0xD8 && bus.read(cpu,0x1801)==status,"READ status response mismatch");
    acknowledge(bus,cpu);advance(bus,cpu,1500);
    require(bus.read(cpu,0x1800)==0xF8 && bus.read(cpu,0x1801)==status,"READ message response mismatch");
    acknowledge(bus,cpu);advance(bus,cpu,1500);
    require(bus.read(cpu,0x1800)==0 && !bus.cd.irq2(),"READ completion did not release bus");
}
void stream_expected(pce::Bus& bus,pce::Cpu& cpu,bool native,bool automatic,unsigned lba) {
    for(unsigned i=0;i<2048;++i) {
        require(bus.read(cpu,0x1800)==0xC8,"sector byte REQ missing or delayed");
        execute(bus,cpu,native,0xAD,automatic?0x1808:0x1801);
        require(cpu.a==pattern(lba,i),"streamed byte differs from independently authored sector");
        if(automatic) {
            // LDA retires only 15 ticks at high speed. Complete the 21-tick
            // automatic pulse before another requested read.
            execute(bus,cpu,native,0xEA);execute(bus,cpu,native,0xEA);bus.sync(cpu);
        } else {
            execute(bus,cpu,native,0x8D,0x1802,0xE0);
            require(bus.read(cpu,0x1800)==0x88,"manual ACK rise failed to lower sector REQ");
            execute(bus,cpu,native,0x8D,0x1802,0x60);
        }
    }
}
void expected() {
    pce::Bus bus;
    for(bool native:{false,true})for(unsigned divisor:{3U,12U})for(bool automatic:{false,true}) {
        auto provider=initialize(bus);pce::Cpu cpu;cpu.mpr=scsi_mpr;cpu.clock_divisor=divisor;
        command(bus,cpu,2,1,0xE0);
        const auto start=cpu.ticks;
        require(bus.cd.scsi.phase==4 && bus.cd.scsi.load_lba==2 && bus.cd.scsi.load_remaining==1,
                "READ six-byte CDB decode/count or ignored upper LUN bits");
        require(bus.cd.scsi.load_deadline==start+first_load && provider->calls==0,
                "READ performed eager IO or scheduled the wrong deterministic first deadline");
        advance(bus,cpu,first_load-1);
        require(bus.read(cpu,0x1800)==0x88 && provider->calls==0,"first sector arrived before deadline");
        advance(bus,cpu,1);
        require(provider->calls==1 && bus.cd.sectors_read==1 && bus.cd.read_commands==1,
                "first deadline did not perform exactly one provider read");
        require(bus.cd.scsi.load_remaining==0 && bus.cd.scsi.load_deadline==0,
                "one-sector READ retained more scheduled loads");
        stream_expected(bus,cpu,native,automatic,2);
        require(bus.cd.data_bytes_acked==2048 && provider->calls==1,"READ byte/provider accounting mismatch");
        require(bus.read(cpu,0x1800)==0x88,"READ completed status before final ACK plus delay");
        const auto due=bus.cd.scsi.deadline;
        require(due>=cpu.ticks,"completion deadline already elapsed unexpectedly");
        advance(bus,cpu,due-cpu.ticks-1);require(bus.read(cpu,0x1800)==0x88,"GOOD status fired early");
        advance(bus,cpu,1);finish(bus,cpu,0);
        require(native?cpu.interpreter_steps==0:cpu.native_steps==0,"READ CPU tier accounting");
        require(native?cpu.native_steps>0:cpu.interpreter_steps>0,"READ stream never executed CPU instructions");
    }
    // Immediate full-size byte requests, duplicate ACKs, DB latching and
    // transport ownership are checked without CPU bus-phase assumptions.
    auto provider=initialize(bus);pce::Cpu cpu;cpu.mpr=scsi_mpr;
    command(bus,cpu,0,2);advance(bus,cpu,first_load);
    const auto first=bus.read(cpu,0x1801);
    require(first==pattern(0,0) && bus.read(cpu,0x1801)==first && bus.cd.data_bytes_acked==0,
            "ordinary DATA IN read consumed a byte");
    bus.write(cpu,0x1802,0xE0);bus.write(cpu,0x1802,0xE0);
    require(bus.cd.data_bytes_acked==1 && bus.read(cpu,0x1801)==first,"held ACK consumed duplicate byte");
    bus.write(cpu,0x1802,0x60);
    require(bus.read(cpu,0x1800)==0xC8 && bus.read(cpu,0x1801)==pattern(0,1) && !bus.cd.scsi.event,
            "full sector incorrectly inherited short-response 900-tick delay");
    // A slow host must not overwrite the single pending sector.
    advance(bus,cpu,sector_time);
    require(provider->calls==1 && bus.cd.read_retries==1 &&
            bus.cd.scsi.load_deadline==cpu.ticks+retry_time && bus.read(cpu,0x1801)==pattern(0,1),
            "one-sector backpressure failed to retain the unread payload");
    for(unsigned i=1;i<2047;++i) {
        require(bus.read(cpu,0x1801)==pattern(0,i),"backpressured first-sector payload mismatch");acknowledge(bus,cpu);
    }
    require(bus.read(cpu,0x1801)==pattern(0,2047),"last first-sector byte missing on DB");
    // Gear permits the second sector to fill the backing buffer while the
    // final byte from sector one is still waiting for its ACK.
    const auto next_due=bus.cd.scsi.load_deadline;advance(bus,cpu,next_due-cpu.ticks);
    require(provider->calls==2 && bus.read(cpu,0x1801)==pattern(0,2047),
            "second load overwrote final outstanding DATA IN byte");
    acknowledge(bus,cpu);
    for(unsigned i=0;i<2048;++i) {
        require(bus.read(cpu,0x1800)==0xC8 && bus.read(cpu,0x1801)==pattern(1,i),
                "second-sector boundary or payload mismatch");acknowledge(bus,cpu);
    }
    advance(bus,cpu,3000);finish(bus,cpu,0);
    require(bus.cd.data_bytes_acked==4096 && bus.cd.sectors_read==2,"two-sector accounting mismatch");

    provider=initialize(bus,300);cpu=pce::Cpu{};cpu.mpr=scsi_mpr;command(bus,cpu,3,0);
    advance(bus,cpu,first_load);
    for(unsigned sector=0;sector<256;++sector) {
        for(unsigned offset=0;offset<2048;++offset) {
            require(bus.read(cpu,0x1800)==0xC8 && bus.read(cpu,0x1801)==pattern(sector+3,offset),
                    "256-sector zero-count transfer lost a byte or truncated its count");
            acknowledge(bus,cpu);
        }
        if(sector<255) {
            require(bus.read(cpu,0x1800)==0x88 && !bus.cd.scsi.event,
                    "multi-sector READ completed before the next scheduled sector");
            advance(bus,cpu,sector_time);
        }
    }
    advance(bus,cpu,3000);finish(bus,cpu,0);
    require(provider->calls==256 && bus.cd.sectors_read==256 && bus.cd.data_bytes_acked==524288 && !bus.cd.read_retries,
            "complete 256-sector transfer accounting mismatch");

    // Zero means 256 sectors; reset cancels pending IO and retains the same
    // explicitly attached provider. No large fixture allocation is needed.
    provider=initialize(bus,300);cpu=pce::Cpu{};cpu.mpr=scsi_mpr;command(bus,cpu,3,0);
    require(bus.cd.scsi.load_remaining==256 && bus.cd.read_commands==1,"READ count zero did not decode as 256");
    bus.write(cpu,0x1804,2);advance(bus,cpu,first_load+retry_time);
    require(provider->calls==0 && !bus.cd.scsi.load_deadline && !bus.cd.scsi.read_active &&
            bus.read(cpu,0x1800)==0,"reset failed to cancel pending provider work");
    bus.write(cpu,0x1804,0);command(bus,cpu,1,1);advance(bus,cpu,first_load);
    require(provider->calls==1 && bus.read(cpu,0x1801)==pattern(1,0),"reset discarded provider attachment");
    bus.read(cpu,0x1808);bus.write(cpu,0x1804,2);advance(bus,cpu,first_load);
    require(!bus.cd.ack && !bus.cd.scsi.auto_ack_deadline && !bus.cd.scsi.load_deadline,
            "reset retained streaming or automatic ACK timers");

    provider=initialize(bus);cpu=pce::Cpu{};cpu.mpr=scsi_mpr;command(bus,cpu,24,1);
    require(provider->calls==0,"invalid initial READ accessed provider");finish(bus,cpu,2);
    provider=initialize(bus);provider->fail_lba=0;cpu=pce::Cpu{};cpu.mpr=scsi_mpr;command(bus,cpu,0,1);
    advance(bus,cpu,first_load);finish(bus,cpu,2);
    require(bus.cd.sectors_read==0 && bus.cd.data_bytes_acked==0,"failed provider fabricated successful bytes");
    provider=initialize(bus);cpu=pce::Cpu{};cpu.mpr=scsi_mpr;command(bus,cpu,23,2);advance(bus,cpu,first_load);
    for(unsigned i=0;i<2048;++i) {require(bus.read(cpu,0x1801)==pattern(23,i),"last valid sector payload mismatch");acknowledge(bus,cpu);}
    advance(bus,cpu,bus.cd.scsi.load_deadline-cpu.ticks);finish(bus,cpu,2);
    require(provider->calls==1 && bus.cd.sectors_read==1,"past-leadout READ fabricated sector");

    provider=initialize(bus);cpu=pce::Cpu{};cpu.mpr=scsi_mpr;command(bus,cpu,0,2);
    bus.write(cpu,0x1800,0);
    require(bus.read(cpu,0x1800)==0xD8 && bus.read(cpu,0x1801)==0,"READ reselection did not enter abort status");
    advance(bus,cpu,first_load+retry_time);
    require(provider->calls==0 && !bus.cd.scsi.load_deadline,"reselection failed to cancel drive loads");

    provider=initialize(bus);cpu=pce::Cpu{};cpu.mpr=scsi_mpr;command(bus,cpu,0,2);
    bus.write(cpu,0x1800,0);advance(bus,cpu,900000);
    require(bus.read(cpu,0x1800)==0xD0 && bus.cd.scsi.load_remaining==0,
            "new COMMAND retained canceled READ sector count");
    for(unsigned i=0;i<10;++i) {
        bus.write(cpu,0x1801,static_cast<std::uint8_t>(i?0:0xDE));acknowledge(bus,cpu);
        if(i<9)advance(bus,cpu,3000);
    }
    advance(bus,cpu,9000);
    for(unsigned byte:{1U,1U,0U,0U}) {
        require(bus.read(cpu,0x1800)==0xC8 && bus.read(cpu,0x1801)==byte,
                "TOC response after READ cancellation differs");
        acknowledge(bus,cpu);advance(bus,cpu,900);
    }
    advance(bus,cpu,2100);finish(bus,cpu,0);
    require(provider->calls==0,"canceled READ performed IO during subsequent TOC command");

    for(bool native:{false,true}) {
        provider=initialize(bus);cpu=pce::Cpu{};cpu.mpr=scsi_mpr;command(bus,cpu,0,1);
        cpu.ticks=bus.cd.scsi.load_deadline;cpu.pc=static_cast<std::uint16_t>(site(0xEA));
        const auto before_master=bus.cd.scsi.master_ticks;
        require((native?pce::generated_step(bus,cpu,cpu.ticks):pce::interpret_step(bus,cpu,cpu.ticks))==pce::Exit::budget &&
                provider->calls==0 && bus.cd.scsi.master_ticks==before_master,
                "CPU budget refusal performed pending sector IO");
        execute(bus,cpu,native,0xEA);
        require(provider->calls==1,"eligible CPU instruction did not synchronize pending sector IO");
    }
    provider=initialize(bus);cpu=pce::Cpu{};cpu.mpr=scsi_mpr;command(bus,cpu,0,1);
    cpu.ticks=bus.cd.scsi.load_deadline;cpu.pc=static_cast<std::uint16_t>(site(0xEA));
    const auto guarded_address=pce::Bus::physical(cpu,cpu.pc);const auto guarded_byte=(*bus.bytes)[guarded_address];
    (*bus.bytes)[guarded_address]=0;
    require(pce::generated_step(bus,cpu,forever)==pce::Exit::miss && provider->calls==0,
            "stale native code guard performed pending sector IO");
    (*bus.bytes)[guarded_address]=guarded_byte;
    execute(bus,cpu,true,0xEA);require(provider->calls==1,"restored native guard failed to synchronize sector IO");

    provider=initialize(bus);cpu=pce::Cpu{};cpu.mpr=scsi_mpr;command(bus,cpu,0,1);
    bool refused=false;try {bus.cd.set_sector_provider(std::make_shared<AuthoredProvider>());}catch(const pce::Fault&){refused=true;}
    require(refused,"provider attachment changed media during active READ");
    pce::CdControl disabled;refused=false;
    try {disabled.set_sector_provider(provider);}catch(const pce::Fault&){refused=true;}
    require(refused,"provider attachment silently enabled transport");
    bus.enable_cd_transport();cpu=pce::Cpu{};cpu.mpr=scsi_mpr;refused=false;
    try {command(bus,cpu,0,1);}catch(const pce::Fault&){refused=true;}
    require(refused,"READ without a readable provider fabricated success");

    provider=initialize(bus);refused=false;
    try {bus.cd.set_sector_provider(nullptr);}catch(const pce::Fault&){refused=true;}
    require(refused,"null sector provider accepted");
    bus.enable_cd_transport();pce::CdToc identity=provider->toc();identity.image_sha256=std::string(64,'a');
    bus.cd.set_toc(identity);refused=false;
    try {bus.cd.set_sector_provider(provider);}catch(const pce::Fault&){refused=true;}
    require(refused,"provider attachment accepted a mismatched source identity");
}
void print_cpu(const pce::Cpu& cpu) {
    std::cout<<"{\"pc\":"<<cpu.pc<<",\"a\":"<<unsigned(cpu.a)<<",\"x\":"<<unsigned(cpu.x)
        <<",\"y\":"<<unsigned(cpu.y)<<",\"sp\":"<<unsigned(cpu.sp)<<",\"p\":"<<unsigned(cpu.p)<<",\"mpr\":[";
    for(unsigned i=0;i<8;++i)std::cout<<(i?",":"")<<unsigned(cpu.mpr[i]);std::cout<<"]}";
}
void print_cd(const pce::CdControl& control) {
    const auto signals=control.scsi.signals;
    std::cout<<"{\"bram_unlocked\":"<<(control.bram_unlocked?"true":"false")<<",\"ack\":"<<(control.ack?"true":"false")
        <<",\"irq_enable\":"<<unsigned(control.interrupt_enable)<<",\"irq_active\":"<<unsigned(control.interrupt_active)
        <<",\"reset\":"<<unsigned(control.reset)<<",\"irq2\":"<<(control.irq2()?"true":"false")<<",\"phase\":"<<control.scsi.phase
        <<",\"bsy\":"<<((signals&128)?"true":"false")<<",\"req\":"<<((signals&64)?"true":"false")
        <<",\"msg\":"<<((signals&32)?"true":"false")<<",\"cd\":"<<((signals&16)?"true":"false")
        <<",\"io\":"<<((signals&8)?"true":"false")<<",\"data\":"<<unsigned(control.scsi.data)<<'}';
}
void settle(pce::Bus& bus,pce::Cpu& cpu,bool native,unsigned count) {
    const auto pc=cpu.pc;
    for(unsigned i=0;i<count;++i)execute(bus,cpu,native,0xEA);
    cpu.pc=pc;
}
int probe(const char* path,const std::string& tier) {
    if(tier!="native" && tier!="interpreter")return 2;
    std::ifstream input(path);unsigned seed,a,x,y,sp,p,count;
    if(!(input>>seed>>a>>x>>y>>sp>>p>>count) || seed>255 || a>255 || x>255 || y>255 || sp>255 || p>255 || count<1 || count>256)return 2;
    struct Action {unsigned pc;int value;unsigned nops;};std::vector<Action> actions;std::uint64_t total_nops=0;
    for(unsigned i=0;i<count;++i) {
        Action action;
        if(!(input>>action.pc>>action.value>>action.nops) || action.pc>65536 || action.value < -1 || action.value>255 ||
            action.nops>2000000 || (action.pc==65536 && action.value!=0 && action.value!=1))return 2;
        total_nops+=action.nops;if(total_nops>12000000)return 2;actions.push_back(action);
    }
    std::string trailing;if(input>>trailing)return 2;
    pce::Bus bus;initialize(bus);pce::Cpu cpu;cpu.mpr=scsi_mpr;cpu.a=a;cpu.x=x;cpu.y=y;cpu.sp=sp;cpu.p=p;
    const bool native=tier=="native";
    std::cout<<"{\"states\":[";
    for(unsigned i=0;i<count;++i) {
        const auto& action=actions[i];std::string payload;
        if(action.pc==65536) {
            settle(bus,cpu,native,action.nops);
            const auto old=std::tuple{cpu.a,cpu.x,cpu.y,cpu.sp,cpu.p,cpu.pc};
            constexpr char digits[]="0123456789abcdef";
            for(unsigned j=0;j<2048;++j) {
                require(bus.read(cpu,0x1800)==0xC8,"probe stream requested before sector ready");
                execute(bus,cpu,native,0xAD,action.value?0x1808:0x1801);const auto byte=cpu.a;
                payload+=digits[byte>>4];payload+=digits[byte&15];
                if(action.value) {execute(bus,cpu,native,0xEA);execute(bus,cpu,native,0xEA);bus.sync(cpu);}
                else {execute(bus,cpu,native,0x8D,0x1802,0xE0);execute(bus,cpu,native,0x8D,0x1802,0x60);}
            }
            std::tie(cpu.a,cpu.x,cpu.y,cpu.sp,cpu.p,cpu.pc)=old;
        } else {
            cpu.pc=static_cast<std::uint16_t>(action.pc);if(action.value>=0)cpu.a=static_cast<std::uint8_t>(action.value);
            require((native?pce::generated_step(bus,cpu,forever):pce::interpret_step(bus,cpu,forever))==pce::Exit::executed,
                    "READ probe instruction failed");settle(bus,cpu,native,action.nops);
        }
        if(i)std::cout<<',';std::cout<<"{\"cpu\":";print_cpu(cpu);std::cout<<",\"cd\":";print_cd(bus.cd);
        if(!payload.empty())std::cout<<",\"payload\":\""<<payload<<'"';std::cout<<'}';
    }
    std::cout<<"],\"native_steps\":"<<cpu.native_steps<<",\"interpreter_steps\":"<<cpu.interpreter_steps<<"}\n";return 0;
}
}
int main(int argc,char** argv) {
    try {
        if(argc==4 && std::string(argv[1])=="--probe")return probe(argv[2],argv[3]);
        if(argc!=1)return 2;
        expected();std::cout<<checks<<" independently expected READ sector/stream checks passed; authored payloads, both tiers/speeds, ACKs, backpressure, reset and failures\n";
        return 0;
    } catch(const std::exception& error) {std::cerr<<error.what()<<'\n';return 1;}
}
