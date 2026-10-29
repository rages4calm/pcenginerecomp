// Authored direct-device protocol regression. Zero guest instructions retire.
// The separate reference pipeline covers actual translated/interpreted ports.
#include "pce/checkpoint.hpp"
#include "pce/sector.hpp"
#include <algorithm>
#include <array>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <vector>

namespace {
constexpr std::uint64_t first_load=3507953, sector_period=286363, retry_period=6228408;
unsigned checks=0,cases=0;
void require(bool value,const char* message) {++checks;if(!value)throw std::runtime_error(message);}
std::uint8_t pattern(unsigned lba,unsigned offset) {
    return static_cast<std::uint8_t>(lba*43+offset*19+(offset>>8)*11+0x35);
}
struct Media final:pce::SectorProvider {
    pce::CdToc geometry;
    std::vector<unsigned> reads;
    explicit Media(char identity='a') {geometry.track_count=1;geometry.tracks[0]={0,4};geometry.leadout_lba=8;geometry.image_sha256=std::string(64,identity);}
    const pce::CdToc& toc() const override {return geometry;}
    pce::Sector read(std::uint32_t lba) override {
        require(lba<8,"Unexpected provider address");reads.push_back(lba);pce::Sector out{};
        for(unsigned i=0;i<out.size();++i)out[i]=pattern(lba,i);return out;
    }
};
struct Machine {
    pce::Bus bus;pce::Cpu cpu;std::shared_ptr<Media> media;
    explicit Machine(unsigned divisor,char identity='a'):media(std::make_shared<Media>(identity)) {
        cpu.clock_divisor=divisor;bus.enable_cd_transport();bus.cd.set_sector_provider(media);
    }
    void advance(std::uint64_t n) {cpu.ticks+=n;bus.sync(cpu);}
    void write(unsigned port,unsigned value) {bus.cd.transport_write(port,static_cast<std::uint8_t>(value));}
    unsigned read(unsigned port) {return bus.cd.transport_read(port);}
    void ack() {write(2,0xE0);write(2,0x60);}
    void body(unsigned lba,unsigned count) {
        const unsigned bytes[]={8,0,0,lba,count,0};
        for(unsigned i=0;i<6;++i) {
            require(read(0)==0xD0,"Command REQ missing");write(1,bytes[i]);ack();
            if(i<5)advance(3000);
        }
        require(bus.cd.scsi.load_deadline==cpu.ticks+first_load,"First-sector absolute deadline differs");
    }
    void command(unsigned lba=0,unsigned count=2) {write(0,0);advance(75000);body(lba,count);}
    unsigned byte(bool automatic) {
        require(read(0)==0xC8,"DATA IN REQ missing");const auto value=read(automatic?8:1);
        if(automatic) {require(bus.cd.ack && bus.cd.scsi.auto_ack_deadline==cpu.ticks+21,"Automatic ACK deadline differs");advance(21);}
        else ack();
        return value;
    }
    void status() {
        require(bus.cd.scsi.deadline==cpu.ticks+3000,"Final status delay differs");
        advance(2999);require(read(0)==0x88,"Status asserted early");advance(1);
        require(read(0)==0xD8 && read(1)==0,"GOOD status differs");ack();
        advance(1499);require(read(0)==0x98,"MESSAGE asserted early");advance(1);
        require(read(0)==0xF8 && read(1)==0,"MESSAGE differs");ack();advance(1500);
        require(read(0)==0 && !bus.cd.scsi.read_active && !bus.cd.scsi.load_deadline,"Completed READ retained work");
    }
};
std::unique_ptr<Machine> roundtrip(Machine& source) {
    const auto before_reads=source.media->reads;
    const auto saved=pce::encode_checkpoint(source.bus,source.cpu);
    require(source.media->reads==before_reads,"Checkpoint save accessed media");
    require(saved==pce::encode_checkpoint(source.bus,source.cpu),"Repeated save changed state");
    auto dest=std::make_unique<Machine>(source.cpu.clock_divisor);
    const auto* bound=dest->media.get();pce::restore_checkpoint(dest->bus,dest->cpu,saved);
    require(dest->media->reads.empty(),"Checkpoint restore accessed media");
    require(dest->bus.cd.provider.get()==bound && bound!=source.media.get(),"Provider was not rebound to destination");
    require(saved==pce::encode_checkpoint(dest->bus,dest->cpu),"Canonical payload changed on restore");
    for(unsigned mutation=0;mutation<4;++mutation) {
        auto bad=saved;
        if(mutation==0)bad.pop_back();
        if(mutation==1)bad.push_back(0);
        if(mutation==2)bad[0]^=0x80;
        if(mutation==3)bad[8]=2;
        const auto unchanged=pce::encode_checkpoint(dest->bus,dest->cpu);bool refused=false;
        try {pce::restore_checkpoint(dest->bus,dest->cpu,bad);}catch(const std::exception&){refused=true;}
        require(refused && pce::encode_checkpoint(dest->bus,dest->cpu)==unchanged,"Invalid copy changed live machine");
        require(dest->media->reads.empty(),"Rejected restore accessed media");
    }
    auto foreign=std::make_unique<Machine>(source.cpu.clock_divisor,'d');
    const auto unchanged=pce::encode_checkpoint(foreign->bus,foreign->cpu);bool refused=false;
    try {pce::restore_checkpoint(foreign->bus,foreign->cpu,saved);}catch(const std::exception&){refused=true;}
    require(refused && unchanged==pce::encode_checkpoint(foreign->bus,foreign->cpu),"Provider identity rejection changed destination");
    require(foreign->media->reads.empty(),"Mismatched provider restore accessed media");
    return dest;
}
unsigned prepare(Machine& m,unsigned cut,bool automatic) {
    m.command();
    if(cut==0) {m.advance(first_load-1);require(m.media->reads.empty(),"First READ accessed media early");return 0;}
    m.advance(first_load);
    require(m.media->reads==std::vector<unsigned>{0},"First load provider association differs");
    require(m.bus.cd.scsi.load_deadline==m.cpu.ticks+sector_period,"Next-sector deadline differs");
    if(cut==1)return 0;
    if(cut==2) {for(unsigned i=0;i<17;++i)require(m.byte(automatic)==pattern(0,i),"Partial prefix differs");return 17;}
    if(cut==3) {
        require(m.read(automatic?8:1)==pattern(0,0),"Held ACK source differs");
        if(!automatic)m.write(2,0xE0);
        require(m.bus.cd.ack && m.read(0)==0x88 && m.bus.cd.data_bytes_acked==1,"Held ACK edge differs");return 1;
    }
    if(cut==4) {
        for(unsigned i=0;i<2047;++i)require(m.byte(automatic)==pattern(0,i),"Boundary prefix differs");
        const auto due=m.bus.cd.scsi.load_deadline;m.advance(due-m.cpu.ticks);
        require(m.media->reads==std::vector<unsigned>({0,1}),"Final outstanding byte prevented second buffer fill");
        require(m.read(1)==pattern(0,2047) && m.bus.cd.scsi.response_index==0,"New buffer replaced outstanding DB byte");return 2047;
    }
    if(cut==5) {
        m.advance(sector_period);
        require(m.bus.cd.read_retries==1 && m.media->reads==std::vector<unsigned>{0},"Occupied buffer performed provider read");
        require(m.bus.cd.scsi.load_deadline==m.cpu.ticks+retry_period,"Backpressure retry deadline differs");return 0;
    }
    if(cut==6) {
        (void)m.read(8);m.write(4,2);
        require(m.bus.cd.scsi.signals==0x100 && !m.bus.cd.ack && !m.bus.cd.scsi.auto_ack_deadline,"Reset retained ACK state");return 0;
    }
    for(unsigned i=0;i<17;++i)require(m.byte(automatic)==pattern(0,i),"Abort prefix differs");
    m.write(0,0);
    require(m.read(0)==0xD8 && m.bus.cd.scsi.deadline==m.cpu.ticks+900000,"Abort transition differs");return 0;
}
void continue_read(Machine& m,unsigned next,bool automatic,unsigned start=0,unsigned count=2) {
    for(unsigned index=next;index<count*2048;++index) {
        if(m.read(0)==0x88) {
            const auto due=m.bus.cd.scsi.load_deadline;
            require(due>m.cpu.ticks,"Missing pending sector load");m.advance(due-m.cpu.ticks);
        }
        require(m.byte(automatic)==pattern(start+index/2048,index%2048),"Restored READ exposed stale or reordered payload");
    }
    // The final automatic ACK falling edge starts the 3000-tick status delay.
    if(automatic) {
        require(m.bus.cd.scsi.deadline==m.cpu.ticks+3000,"Automatic final ACK scheduling differs");
    }
    m.status();
}
void matrix() {
    for(unsigned divisor:{3u,12u})for(bool automatic:{false,true})for(unsigned cut=0;cut<8;++cut) {
        ++cases;auto source=std::make_unique<Machine>(divisor);const unsigned next=prepare(*source,cut,automatic);
        const auto origin_ticks=source->cpu.ticks,origin_native=source->cpu.native_steps,origin_interpreted=source->cpu.interpreter_steps;
        const auto imported_reads=source->media->reads.size();auto resumed=roundtrip(*source);
        for(auto* m:{source.get(),resumed.get()}) {
            require(m->cpu.ticks==origin_ticks && m->cpu.native_steps==origin_native && m->cpu.interpreter_steps==origin_interpreted,
                    "Checkpoint imported counters differ");
            if(cut==0) {m->advance(1);require(m->read(1)==pattern(0,0),"First pending deadline not preserved");}
            if(cut==3) {
                if(automatic) {const auto due=m->bus.cd.scsi.auto_ack_deadline;m->advance(due-m->cpu.ticks-1);require(m->bus.cd.ack,"Automatic ACK dropped early");m->advance(1);}
                else m->write(2,0x60);
                require(!m->bus.cd.ack && m->read(1)==pattern(0,1),"Held ACK did not reveal exactly next byte");
            }
            if(cut==6 || cut==7) {
                if(cut==6) {
                    m->advance(first_load+retry_period);
                    require(!m->bus.cd.scsi.event && !m->bus.cd.scsi.load_deadline && !m->bus.cd.scsi.response_size,
                            "Reset checkpoint resurrected canceled work");
                    m->write(4,0);m->command(2,1);
                } else {
                    m->advance(900000);
                    require(m->read(0)==0xD0 && !m->bus.cd.scsi.load_deadline && !m->bus.cd.scsi.response_size,
                            "Reselection checkpoint resurrected stale response");
                    m->body(2,1);
                }
                m->advance(first_load);continue_read(*m,0,automatic,2,1);
            } else continue_read(*m,next,automatic);
            require(m->cpu.native_steps==0 && m->cpu.interpreter_steps==0,"Direct-device fixture retired guest work");
        }
        const auto expected_new=(cut==6 || cut==7)?1u:2u-static_cast<unsigned>(imported_reads);
        require(resumed->media->reads.size()==expected_new,"Restored provider fetch count includes imported prefix");
        const std::vector<unsigned> expected_addresses=(cut==6 || cut==7)?std::vector<unsigned>{2}:
            imported_reads==0?std::vector<unsigned>{0,1}:imported_reads==1?std::vector<unsigned>{1}:std::vector<unsigned>{};
        require(resumed->media->reads==expected_addresses,"Restored provider fetched stale or reordered sectors");
        require(source->media->reads.size()==imported_reads+expected_new,"Source continuation fetch count differs");
        require(pce::encode_checkpoint(source->bus,source->cpu)==pce::encode_checkpoint(resumed->bus,resumed->cpu),
                "Exact continued machine differs after independent literal assertions");
    }
}
void command_checkpoint_matrix() {
    // Command ACK is manual in both DATA IN consumption profiles. Preserve a
    // real third-byte ACK and, separately, its future fourth-byte REQ edge.
    for(unsigned divisor:{3u,12u})for(bool held:{false,true}) {
        ++cases;auto source=std::make_unique<Machine>(divisor);
        source->write(0,0);source->advance(75000);
        for(unsigned i=0;i<3;++i) {
            require(source->read(0)==0xD0,"Partial CDB REQ missing");
            source->write(1,i?0:8);source->write(2,0xE0);
            if(i<2) {source->write(2,0x60);source->advance(3000);}
        }
        if(!held)source->write(2,0x60);
        const auto& s=source->bus.cd.scsi;
        require(s.phase==3 && s.command_size==3 && s.command[0]==8 && s.command[1]==0 && s.command[2]==0,
                "Partial CDB bytes/count differ");
        require(source->read(0)==0x90 && source->bus.cd.ack==held && !s.read_active && !s.load_deadline,
                "Partial CDB unexpectedly started READ");
        require(held?(!s.event && !s.deadline):(s.event==2 && s.deadline==source->cpu.ticks+3000),
                "Partial CDB pending REQ deadline differs");
        require(source->media->reads.empty(),"Partial CDB fetched a sector");
        auto resumed=roundtrip(*source);
        for(auto* m:{source.get(),resumed.get()}) {
            if(held)m->write(2,0x60);
            require(m->bus.cd.scsi.event==2 && m->bus.cd.scsi.deadline==m->cpu.ticks+3000,
                    "Restored CDB ACK did not schedule exactly one REQ");
            m->advance(2999);require(m->read(0)==0x90,"Restored CDB REQ asserted early");
            m->advance(1);require(m->read(0)==0xD0,"Restored CDB REQ missed its exact deadline");
            const unsigned remaining[]={1,1,0}; // READ LBA1, one sector.
            for(unsigned i=0;i<3;++i) {
                require(m->read(0)==0xD0,"Remaining CDB REQ missing");m->write(1,remaining[i]);m->ack();
                if(i<2)m->advance(3000);
            }
            require(m->bus.cd.scsi.last_command_size==6 && m->bus.cd.scsi.command_size==0 &&
                    m->bus.cd.scsi.last_command==std::array<std::uint8_t,16>{8,0,0,1,1,0},
                    "Restored partial CDB assembled the wrong command");
            require(m->bus.cd.scsi.load_deadline==m->cpu.ticks+first_load && m->media->reads.empty(),
                    "Partial CDB completion loaded eagerly or at wrong time");
            m->advance(first_load-1);require(m->media->reads.empty(),"Partial CDB READ loaded early");m->advance(1);
            continue_read(*m,0,divisor==12,1,1);
            require(m->media->reads==std::vector<unsigned>{1},"Restored partial CDB fetched wrong LBA/order");
            require(m->cpu.native_steps==0 && m->cpu.interpreter_steps==0,"Partial CDB fixture retired guest instructions");
        }
        require(pce::encode_checkpoint(source->bus,source->cpu)==pce::encode_checkpoint(resumed->bus,resumed->cpu),
                "Partial CDB continuation changed exact machine state");
    }
}
void completion_checkpoint_matrix() {
    for(unsigned divisor:{3u,12u})for(bool free_pending:{false,true}) {
        ++cases;auto source=std::make_unique<Machine>(divisor);source->command(2,1);source->advance(first_load);
        for(unsigned i=0;i<2048;++i)require(source->byte(divisor==12)==pattern(2,i),"Status prefix payload differs");
        source->advance(3000);
        require(source->read(0)==0xD8 && source->read(1)==0,"Status checkpoint did not follow GOOD status");
        source->ack();
        if(free_pending) {
            source->advance(1500);require(source->read(0)==0xF8 && source->read(1)==0,"MESSAGE checkpoint byte differs");
            source->ack();
        }
        require(source->bus.cd.scsi.event==(free_pending?5u:4u) &&
                source->bus.cd.scsi.deadline==source->cpu.ticks+1500 && !source->bus.cd.scsi.read_active &&
                !source->bus.cd.scsi.load_deadline && !source->bus.cd.ack,
                "Completion checkpoint pending event differs");
        auto resumed=roundtrip(*source);
        for(auto* m:{source.get(),resumed.get()}) {
            m->advance(1499);require(m->read(0)==(free_pending?0xB8u:0x98u),"Completion edge occurred early");m->advance(1);
            if(!free_pending) {
                require(m->read(0)==0xF8 && m->read(1)==0,"Restored MESSAGE byte or edge differs");m->ack();
                require(m->bus.cd.scsi.event==5 && m->bus.cd.scsi.deadline==m->cpu.ticks+1500,
                        "Restored MESSAGE did not schedule bus release");
                m->advance(1500);
            }
            require(m->read(0)==0 && !m->bus.cd.scsi.event && !m->bus.cd.scsi.deadline &&
                    m->bus.cd.data_bytes_acked==2048 && m->bus.cd.sectors_read==1,
                    "Completion continuation retained work or changed byte/sector counts");
            require(m->cpu.native_steps==0 && m->cpu.interpreter_steps==0,"Completion fixture retired guest instructions");
        }
        require(resumed->media->reads.empty() && source->media->reads==std::vector<unsigned>{2},
                "Completion restore fetched imported sector data");
        require(pce::encode_checkpoint(source->bus,source->cpu)==pce::encode_checkpoint(resumed->bus,resumed->cpu),
                "Completion continuation changed exact machine state");
    }
}
}
int main() {try {matrix();command_checkpoint_matrix();completion_checkpoint_matrix();std::cout<<checks<<" authored CD READ checkpoint expectations across "<<cases
    <<" direct-device cases; zero guest instructions\n";return 0;}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}}
