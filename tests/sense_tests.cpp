#include "pce/runtime.hpp"
#include "pce/sector.hpp"
#include "scsi_fixture.hpp"
#include <algorithm>
#include <array>
#include <iostream>
#include <limits>
#include <tuple>

namespace {
constexpr auto forever=std::numeric_limits<std::uint64_t>::max();
constexpr std::uint64_t first_load=3507953;
using Reply=std::array<std::uint8_t,18>;
constexpr Reply empty{0x70,0,0,0,0,0,0,0x0A,0,0,0,0,0,0,0,0,0,0};
constexpr Reply end_volume{0x70,0,5,0,0,0,0,0x0A,0,0,0,0,0x25,0,0,0,0,0};
constexpr Reply not_data{0x70,0,3,0,0,0,0,0x0A,0,0,0,0,0x1D,0,0,0,0,0};
constexpr Reply unavailable{0x70,0,5,0,0,0,0,0x0A,0,0,0,0,0,0,0,0,0,0};
constexpr Reply invalid_data{0x70,0,3,0,0,0,0,0x0A,0,0,0,0,0x11,5,0,0,0,0};
constexpr Reply no_disc{0x70,0,2,0,0,0,0,0x0A,0,0,0,0,0x0B,0,0,0,0,0};
unsigned checks=0;
void require(bool yes,const char* reason) {if(!yes)throw std::runtime_error(reason);++checks;}
unsigned site(unsigned op,unsigned address=0) {
    for(const auto& row:scsi_cases)if(row.op==op && row.address==address)return row.pc;
    throw std::runtime_error("Missing authored SCSI operation");
}
std::uint8_t pattern(unsigned lba,unsigned byte) {return static_cast<std::uint8_t>(lba*17+byte*29+0x53);}
class Provider final:public pce::SectorProvider {
public:
    pce::CdToc table;
    unsigned calls=0;
    int failure=-1;
    pce::SectorReadReason reason=pce::SectorReadReason::unrecoverable_data;
    bool fatal=false,wrong_lba=false;
    explicit Provider(bool audio=false) {
        table.track_count=audio?2:1;table.tracks[0]={0,4};table.leadout_lba=16;
        if(audio)table.tracks[1]={8,0};
    }
    const pce::CdToc& toc() const override {return table;}
    pce::Sector read(std::uint32_t lba) override {
        ++calls;
        if(static_cast<int>(lba)==failure) {
            if(fatal)throw pce::Fault("Authored source-integrity failure");
            throw pce::SectorReadError(reason,lba+unsigned(wrong_lba),"Authored recoverable sector failure");
        }
        if(table.track_count==2 && lba>=8)
            throw pce::SectorReadError(pce::SectorReadReason::wrong_data_track,lba,"Authored audio payload");
        pce::Sector result{};for(unsigned i=0;i<result.size();++i)result[i]=pattern(lba,i);return result;
    }
};
void initialize(pce::Bus& bus,pce::Cpu& cpu,unsigned speed) {
    bus=pce::Bus{};bus.kind[0xF8]=pce::BankKind::ram;bus.enable_cd_transport();bus.enable_interrupts();
    for(auto [at,value]:scsi_program)(*bus.bytes)[at]=value;
    cpu=pce::Cpu{};cpu.mpr=scsi_mpr;cpu.clock_divisor=speed;cpu.p=pce::I;
}
void advance(pce::Bus& bus,pce::Cpu& cpu,std::uint64_t ticks) {cpu.ticks+=ticks;bus.sync(cpu);}
void step(pce::Bus& bus,pce::Cpu& cpu,bool native,unsigned op,unsigned address=0,int value=-1) {
    cpu.pc=static_cast<std::uint16_t>(site(op,address));if(value>=0)cpu.a=static_cast<std::uint8_t>(value);
    require((native?pce::generated_step(bus,cpu,forever):pce::interpret_step(bus,cpu,forever))==pce::Exit::executed,
            "Sense fixture operation failed in selected execution tier");
}
unsigned read(pce::Bus& bus,pce::Cpu& cpu,bool native,unsigned address) {step(bus,cpu,native,0xAD,address);return cpu.a;}
void write(pce::Bus& bus,pce::Cpu& cpu,bool native,unsigned address,unsigned value) {step(bus,cpu,native,0x8D,address,static_cast<int>(value));}
void ack(pce::Bus& bus,pce::Cpu& cpu,bool native) {write(bus,cpu,native,0x1802,0xE0);write(bus,cpu,native,0x1802,0x60);}
template<std::size_t N>
void command(pce::Bus& bus,pce::Cpu& cpu,bool native,const std::array<std::uint8_t,N>& bytes) {
    write(bus,cpu,native,0x1800,0);advance(bus,cpu,75000);
    for(unsigned i=0;i<N;++i) {
        require(read(bus,cpu,native,0x1800)==0xD0,"Command byte requested in wrong phase");
        write(bus,cpu,native,0x1801,bytes[i]);ack(bus,cpu,native);
        if(i+1<N)advance(bus,cpu,3000);
    }
}
void sense_command(pce::Bus& bus,pce::Cpu& cpu,bool native,unsigned allocation) {
    command(bus,cpu,native,std::array<std::uint8_t,6>{3,static_cast<std::uint8_t>(allocation^0xA5),0x13,0xE7,
            static_cast<std::uint8_t>(allocation),static_cast<std::uint8_t>(allocation^0x5A)});
    require(bus.cd.scsi.response_size==18 && bus.cd.pending_sense.key==0 && bus.cd.pending_sense.asc==0 &&
            bus.cd.pending_sense.ascq==0 && bus.cd.pending_sense.fru==0 && !bus.cd.pending_sense.failed_lba,
            "Sense must snapshot18 and consume pending context before DATA IN acknowledgement");
}
void finish(pce::Bus& bus,pce::Cpu& cpu,bool native,unsigned status) {
    require(read(bus,cpu,native,0x1800)==0xD8 && read(bus,cpu,native,0x1801)==status,"Status response mismatch");
    const auto acknowledged=bus.cd.data_bytes_acked;
    require(read(bus,cpu,native,0x1808)==status && !bus.cd.ack && !bus.cd.scsi.auto_ack_deadline &&
            bus.cd.data_bytes_acked==acknowledged,"STATUS was consumed as DATA IN by auto-ACK port");
    ack(bus,cpu,native);advance(bus,cpu,1500);
    require(read(bus,cpu,native,0x1800)==0xF8 && read(bus,cpu,native,0x1801)==status,
            "Existing Gear-compatible message DB semantics changed");
    ack(bus,cpu,native);advance(bus,cpu,1500);
    require(read(bus,cpu,native,0x1800)==0 && !bus.cd.irq2(),"Completion did not free bus and release data/status IRQs");
}
void reply(pce::Bus& bus,pce::Cpu& cpu,bool native,bool automatic,const Reply& expected) {
    const auto before=bus.cd.data_bytes_acked;
    for(unsigned i=0;i<18;++i) {
        require(read(bus,cpu,native,0x1800)==0xC8,"Sense DATA IN byte missing REQ");
        require(read(bus,cpu,native,automatic?0x1808:0x1801)==expected[i],"Sense response byte differs from literal NEC payload");
        if(automatic)advance(bus,cpu,21);else ack(bus,cpu,native);
        advance(bus,cpu,i==17?3000:900);
    }
    require(bus.cd.data_bytes_acked==before+18,"Sense byte accounting differs from exact fixed response length");
    finish(bus,cpu,native,0);
}
void read_command(pce::Bus& bus,pce::Cpu& cpu,bool native,unsigned lba,unsigned count) {
    command(bus,cpu,native,std::array<std::uint8_t,6>{8,static_cast<std::uint8_t>(lba>>16),
        static_cast<std::uint8_t>(lba>>8),static_cast<std::uint8_t>(lba),static_cast<std::uint8_t>(count),0});
}
void fail_end(pce::Bus& bus,pce::Cpu& cpu,bool native) {
    read_command(bus,cpu,native,16,1);finish(bus,cpu,native,2);
    require(bus.cd.pending_sense.key==5 && bus.cd.pending_sense.asc==0x25 && bus.cd.pending_sense.failed_lba==16,
            "Invalid READ did not retain actual failed LBA in host-only sense context");
}
void allocation_and_lifetime(pce::Bus& bus) {
    for(bool native:{false,true})for(unsigned speed:{3U,12U}) {
        pce::Cpu cpu;initialize(bus,cpu,speed);
        for(unsigned allocation=0;allocation<256;++allocation) {
            sense_command(bus,cpu,native,allocation);reply(bus,cpu,native,allocation&1,empty);
        }
        require(bus.cd.sense_commands==256 && bus.cd.sense_errors==0,"All256 allocation fields did not remain fixed18-byte commands");
        require(native?(cpu.native_steps>0 && cpu.interpreter_steps==0):(cpu.interpreter_steps>0 && cpu.native_steps==0),
                "Sense allocation matrix used another execution tier");
        auto provider=std::make_shared<Provider>();bus.cd.set_sector_provider(provider);
        fail_end(bus,cpu,native);
        command(bus,cpu,native,std::array<std::uint8_t,6>{0,0,0,0,0,0});advance(bus,cpu,450000);finish(bus,cpu,native,0);
        require(bus.cd.pending_sense.asc==0x25,"Successful TUR cleared a pending failure");
        write(bus,cpu,native,0x1804,2);write(bus,cpu,native,0x1804,0);
        require(bus.cd.pending_sense.asc==0x25 && bus.cd.sense_errors==1,"Warm bus reset cleared pending sense or lifetime counters");
        sense_command(bus,cpu,native,0);reply(bus,cpu,native,true,end_volume);
        sense_command(bus,cpu,native,255);reply(bus,cpu,native,false,empty);
        fail_end(bus,cpu,native);sense_command(bus,cpu,native,18);
        require(read(bus,cpu,native,0x1801)==0x70,"Aborted sense did not retain its buffered snapshot");
        write(bus,cpu,native,0x1800,0);advance(bus,cpu,900000);
        sense_command(bus,cpu,native,1);reply(bus,cpu,native,false,empty);
        // Cold construction clears lifetime counters and pending state.
        initialize(bus,cpu,speed);
        require(bus.cd.sense_commands==0 && bus.cd.sense_errors==0 && !bus.cd.pending_sense.key,
                "Cold CD setup retained old pending sense or counters");
        command(bus,cpu,native,std::array<std::uint8_t,10>{0xDE,0,0,0,0,0,0,0,0,0});finish(bus,cpu,native,2);
        sense_command(bus,cpu,native,0);reply(bus,cpu,native,true,no_disc);
    }
}
void read_errors_and_recovery(pce::Bus& bus) {
    const std::array reasons{pce::SectorReadReason::out_of_range,pce::SectorReadReason::wrong_data_track,
                            pce::SectorReadReason::unrecoverable_data,pce::SectorReadReason::media_data_error};
    const std::array expected{end_volume,not_data,unavailable,invalid_data};
    for(bool native:{false,true})for(unsigned speed:{3U,12U})for(unsigned category=0;category<reasons.size();++category) {
        pce::Cpu cpu;initialize(bus,cpu,speed);auto provider=std::make_shared<Provider>();
        provider->failure=0;provider->reason=reasons[category];bus.cd.set_sector_provider(provider);
        read_command(bus,cpu,native,0,1);advance(bus,cpu,first_load);finish(bus,cpu,native,2);
        require(provider->calls==1 && bus.cd.read_errors==1 && bus.cd.sectors_read==0 &&
                !bus.cd.scsi.load_deadline && !bus.cd.scsi.load_remaining && !bus.cd.scsi.read_active,
                "Failed READ leaked data, retained work or fabricated successful sectors");
        require(bus.cd.pending_sense.failed_lba==0,"Failed LBA0 was lost from host diagnostic context");
        sense_command(bus,cpu,native,0);reply(bus,cpu,native,category&1,expected[category]);
        provider->failure=-1;read_command(bus,cpu,native,0,1);advance(bus,cpu,first_load);
        for(unsigned i=0;i<2048;++i) {
            require(read(bus,cpu,native,0x1801)==pattern(0,i),"Successful retry returned corrupted or stale payload");ack(bus,cpu,native);
        }
        advance(bus,cpu,3000);finish(bus,cpu,native,0);
        require(bus.cd.sectors_read==1 && bus.cd.read_errors==1 && bus.cd.sense_errors==1,
                "Retry changed past error accounting or failed to read a real sector");
    }
    for(bool native:{false,true})for(unsigned speed:{3U,12U}) {
        pce::Cpu cpu;initialize(bus,cpu,speed);auto provider=std::make_shared<Provider>(true);bus.cd.set_sector_provider(provider);
        read_command(bus,cpu,native,8,1);finish(bus,cpu,native,2);
        require(provider->calls==0 && !bus.cd.scsi.load_deadline,"Initial audio-track READ was not rejected before provider work");
        sense_command(bus,cpu,native,18);reply(bus,cpu,native,false,not_data);
        // Cross-track errors follow the typed provider API policy. They do
        // not claim Beetle's raw-sector validator/ECC cross-track behavior.
        read_command(bus,cpu,native,7,2);advance(bus,cpu,first_load);
        for(unsigned i=0;i<2048;++i) {require(read(bus,cpu,native,0x1801)==pattern(7,i),"Cross-track first payload mismatch");ack(bus,cpu,native);}
        advance(bus,cpu,bus.cd.scsi.load_deadline-cpu.ticks);finish(bus,cpu,native,2);
        require(bus.cd.sectors_read==1 && provider->calls==2 && bus.cd.pending_sense.failed_lba==8,
                "Cross-track failure lost already completed sector or actual failure address");
        sense_command(bus,cpu,native,255);reply(bus,cpu,native,true,not_data);
    }
}
void fatal_and_guards(pce::Bus& bus) {
    for(bool native:{false,true})for(unsigned speed:{3U,12U})for(unsigned failure=0;failure<3;++failure) {
        pce::Cpu cpu;initialize(bus,cpu,speed);auto provider=std::make_shared<Provider>();bus.cd.set_sector_provider(provider);
        fail_end(bus,cpu,native);provider->failure=0;
        provider->fatal=failure==0;provider->wrong_lba=failure==1;
        if(failure==2)provider->reason=static_cast<pce::SectorReadReason>(255);
        read_command(bus,cpu,native,0,1);
        bool refused=false;try {advance(bus,cpu,first_load);}catch(const pce::Fault&){refused=true;}
        require(refused && bus.cd.sense_errors==1 && bus.cd.read_errors==1 && bus.cd.pending_sense.asc==0x25 &&
                bus.cd.pending_sense.failed_lba==16,"Fatal provider/contract error was converted into recoverable guest sense");
    }
    for(unsigned speed:{3U,12U})for(unsigned patch:{0U,1U}) {
        pce::Cpu cpu;initialize(bus,cpu,speed);auto provider=std::make_shared<Provider>();
        provider->failure=0;bus.cd.set_sector_provider(provider);read_command(bus,cpu,true,0,1);
        cpu.ticks=bus.cd.scsi.load_deadline;cpu.pc=static_cast<std::uint16_t>(site(0xEA));
        const auto pa=pce::Bus::physical(cpu,cpu.pc);if(patch==0)(*bus.bytes)[pa]^=1;else cpu.mpr[7]^=1;
        const auto before=std::tuple{cpu.ticks,cpu.cycles,cpu.pc,cpu.native_steps,cpu.interpreter_steps,bus.cd.scsi.master_ticks,
                                    bus.cd.read_errors,bus.cd.sense_errors,bus.cd.sense_commands};
        require(pce::generated_step(bus,cpu,forever)==pce::Exit::miss,"Native changed source/mapping did not refuse pending READ work");
        require(before==std::tuple{cpu.ticks,cpu.cycles,cpu.pc,cpu.native_steps,cpu.interpreter_steps,bus.cd.scsi.master_ticks,
                                  bus.cd.read_errors,bus.cd.sense_errors,bus.cd.sense_commands} && provider->calls==0 && !bus.cd.pending_sense.key,
                "Native guard miss performed provider work or changed sense state");
    }
}
} // namespace
int main() {
    try {
        pce::Bus bus;allocation_and_lifetime(bus);read_errors_and_recovery(bus);fatal_and_guards(bus);
        std::cout<<checks<<" authored NEC sense payload, lifetime, allocation, READ recovery, fatal-boundary and native-guard checks passed\n";
        return 0;
    }catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
}
