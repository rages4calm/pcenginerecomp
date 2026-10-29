// Host-supervised authored READ/ACK/DMA device setup, followed by real guest
// CPU instructions. This is an interpreter checkpoint regression, not an
// independent emulator oracle or a fresh-process/native execution claim.
#include "pce/checkpoint.hpp"
#include "pce/sector.hpp"
#include <algorithm>
#include <array>
#include <iostream>
#include <limits>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
unsigned checks=0,cases=0;
std::uint64_t guest_steps=0,restored_prefix_steps=0;
std::string current;
void require(bool value,const char* why) {++checks;if(!value)throw std::runtime_error(current+": "+why);}
enum class Kind {mask,held,reset,cpu_mask,cd_mask,i_mask};
struct Media final:pce::SectorProvider {
    pce::CdToc geometry;
    std::vector<unsigned> requests;
    Media() {geometry.track_count=1;geometry.tracks[0]={0,4};geometry.leadout_lba=8;geometry.image_sha256=std::string(64,'e');}
    const pce::CdToc& toc()const override{return geometry;}
    pce::Sector read(std::uint32_t lba)override {
        require(lba<8,"provider address outside authored disc");requests.push_back(lba);pce::Sector result{};
        for(unsigned i=0;i<result.size();++i)result[i]=static_cast<std::uint8_t>(lba*53+i*13+(i>>8)*7+0x61);
        return result;
    }
};
struct Machine {
    pce::Bus bus;pce::Cpu cpu;std::shared_ptr<Media> media=std::make_shared<Media>();
    Machine(unsigned divisor,Kind kind) {
        std::vector<std::uint8_t> rom(262144,0xEA);
        // Sandbox entry uses Cpu's explicit IO/WRAM/ROM MPR mapping. The
        // instructions establish A, D, C and I transitions themselves.
        const std::array<std::uint8_t,9> main={0xA9,0xA7,0xF8,0x38,
            static_cast<std::uint8_t>(kind==Kind::i_mask?0xEA:0x58),0xEA,0xEA,0x80,0xFE};
        std::copy(main.begin(),main.end(),rom.begin());
        const unsigned port=kind==Kind::held?0x2011:kind==Kind::reset?0x180D:0x1802;
        const std::array<std::uint8_t,16> handler={0x48,0xAD,0x03,0x18,0x29,0x0C,
            0x8D,0x10,0x20,0xA9,static_cast<std::uint8_t>(kind==Kind::reset?128:0),
            0x8D,static_cast<std::uint8_t>(port),static_cast<std::uint8_t>(port>>8),0x68,0x40};
        std::copy(handler.begin(),handler.end(),rom.begin()+0x1840);
        rom[0x1FF6]=0x40;rom[0x1FF7]=0xF8;rom[0x1FFE]=0;rom[0x1FFF]=0xE0;
        bus.configure_system_card(pce::SystemCardProfile::standard,rom);
        bus.enable_cd_transport();bus.cd.set_sector_provider(media);bus.enable_adpcm();bus.enable_interrupts();
        cpu.pc=0xE000;cpu.clock_divisor=divisor;
    }
    void advance(std::uint64_t ticks) {cpu.ticks+=ticks;bus.sync(cpu);}
    void cd(unsigned port,unsigned value) {bus.cd.transport_write(port,static_cast<std::uint8_t>(value));}
    void ack() {const auto enable=bus.cd.interrupt_enable;cd(2,enable|128);cd(2,enable);}
    std::uint64_t prepare(Kind kind) {
        // These are explicit device transactions, not counted guest opcodes.
        bus.adpcm.write(8,0xFE,&bus.cd);bus.adpcm.write(9,0xFF,&bus.cd);
        bus.adpcm.write(13,3,&bus.cd);bus.adpcm.write(13,0,&bus.cd);
        cd(2,kind==Kind::cd_mask?0:4);bus.write(cpu,0x1402,kind==Kind::cpu_mask?5:4);
        cd(0,0);advance(75000);
        const unsigned command[]={8,0,0,0,1,0};
        for(unsigned i=0;i<6;++i) {
            require(bus.cd.transport_read(0)==0xD0,"READ command REQ missing");
            cd(1,command[i]);ack();if(i<5)advance(3000);
        }
        require(bus.cd.scsi.load_deadline==cpu.ticks+3507953,"first READ load deadline differs");
        advance(3507953);advance((36-cpu.ticks%36)%36);
        require(media->requests==std::vector<unsigned>{0} && bus.cd.scsi.data==0x61,"READ provider/data identity differs");
        bus.adpcm.write(11,2,&bus.cd);advance(0);const auto base=cpu.ticks;
        require(bus.adpcm.dma_deadline==base+36,"DMA capture did not arm");advance(45);
        require(bus.adpcm.dma_bytes==1 && bus.adpcm.ram[0xFFFE]==0x61 && bus.adpcm.write_address==0xFFFF &&
                bus.adpcm.length==1 && bus.adpcm.half_irq && bus.adpcm.end_irq,"first real DMA commit/IRQ differs");
        require((bus.cd.interrupt_active&12)==12 && bus.cd.irq2()==(kind!=Kind::cd_mask),"device enable versus active source differs");
        require(!cpu.irq_sampled && !cpu.irq_entries && !cpu.native_steps && !cpu.interpreter_steps && !cpu.cycles,
                "device setup fabricated CPU sampling, delivery or guest work");
        return cpu.ticks;
    }
    unsigned ram(unsigned address)const{return *bus.peek(0x1F0000+(address&8191));}
};
bool masked(Kind kind) {return kind==Kind::cpu_mask||kind==Kind::cd_mask||kind==Kind::i_mask;}
void expect(const Machine& m,Kind kind,unsigned step,std::uint64_t origin) {
    const auto& c=m.cpu;const bool inactive=masked(kind);
    const unsigned pcs[]={0,0xE002,0xE003,0xE004,0xE005,0xF840,0xF841,0xF844,0xF846,0xF849,0xF84B,0xF84E,0xF84F,0xE006,0xE007};
    const unsigned cycles[]={0,2,4,6,8,18,21,26,28,33,35,40,44,51,53};
    const unsigned flags[]={0,0x84,0x8C,0x8D,0x89,0x85,0x85,0x05,0x05,0x05,0x07,0x07,0x85,0x89,0x89};
    unsigned pc=pcs[step],p=flags[step],sp=step<5||step>=13?255:step==5||step==12?252:251;
    unsigned entries=step>=5?1:0,rti=step>=13?1:0,elapsed=cycles[step];
    if(kind==Kind::reset && (step==10||step==11))p=0x85;
    if(inactive) {
        pc=step<=6?0xE000+(step<2?2:step+1):0xE007;
        p=step<=3?flags[step]:kind==Kind::i_mask?0x8D:0x89;
        sp=255;entries=rti=0;elapsed=step<=6?step*2:12+(step-6)*4;
    } else if(kind==Kind::held && step==14) {pc=0xF840;p=0x85;sp=252;entries=2;elapsed+=8;}
    require(c.pc==pc && c.sp==sp && c.p==p,"literal PC/SP/P differs");
    require(c.cycles==elapsed && c.ticks==origin+elapsed*c.clock_divisor,"literal instruction/entry clocks differ");
    require(c.irq_entries==entries && m.bus.irq.entries==entries && c.rti_steps==rti,"actual delivery/RTI totals differ");
    require(c.irq_vector==(entries?0xFFF6:0) && !c.irq_sampled,"vector or completed-boundary sample differs");
    require(c.native_steps==0 && c.interpreter_steps==step && !c.native_block_steps && !c.interpreter_block_steps,
            "actual guest work differs from executed opcodes");
    require(c.mpr==std::array<std::uint8_t,8>{255,248,128,129,130,131,132,0},"logical/source MPR mapping changed");
    require(c.x==0 && c.y==0,"handler damaged X/Y");
    if(inactive||step<=6||step>=12)require(c.a==0xA7,"handler failed to preserve A");
    if(!inactive && step==7)require((c.a&12)==12 && !(c.a&128),"guest $1803 status differs");
    if(!inactive && (step==8||step==9))require(c.a==12,"guest status bit witness differs");
    if(!inactive && (step==10||step==11))require(c.a==(kind==Kind::reset?128:0),"handler control value differs");
    if(entries) {
        require(m.ram(0x21FF)==0xE0 && m.ram(0x21FE)==(entries==2?7:6) && m.ram(0x21FD)==0x89,
                "literal descending IRQ return PC/status stack differs");
        if(step>=6)require(m.ram(0x21FC)==0xA7,"handler PHA stack did not preserve A");
    } else require(!m.ram(0x21FF)&&!m.ram(0x21FE)&&!m.ram(0x21FD),"masked CPU wrote IRQ stack");
    require(m.ram(0x2010)==(!inactive&&step>=9?12:0),"guest status witness RAM differs");
    if(kind==Kind::reset && step>=11) {
        require(m.bus.adpcm.control==128 && !(m.bus.cd.interrupt_active&12) && !m.bus.cd.irq2(),"reset did not acknowledge source");
    } else {
        require((m.bus.cd.interrupt_active&12)==12 && m.bus.adpcm.half_irq && m.bus.adpcm.end_irq,
                "status read/device mask consumed active ADPCM source");
        const bool enabled=kind!=Kind::cd_mask && !(kind==Kind::mask&&step>=11);
        require(m.bus.cd.interrupt_enable==(enabled?4:0) && m.bus.cd.irq2()==enabled,"device mask versus source retention differs");
    }
    require(m.bus.irq.mask==(kind==Kind::cpu_mask?5:4),"CPU mask changed with device enable");
    // Between capture and automatic ACK release, continuous DMA remains armed
    // even though there is no next capture deadline yet.
    require(m.bus.adpcm.dma==2 && m.bus.adpcm.dma_bytes>=1 && m.bus.cd.scsi.read_active &&
            m.bus.cd.scsi.response_index<m.bus.cd.scsi.response_size,
            "CPU handler/checkpoint stopped active DMA");
}
void step(Machine& m,Kind kind,unsigned count,std::uint64_t origin) {
    require(pce::interpret_step(m.bus,m.cpu,std::numeric_limits<std::uint64_t>::max())==pce::Exit::executed,
            "authored guest opcode did not execute");++guest_steps;expect(m,kind,count,origin);
}
std::unique_ptr<Machine> fork(const Machine& source,Kind kind) {
    const auto saved=pce::encode_checkpoint(source.bus,source.cpu);
    require(saved==pce::encode_checkpoint(source.bus,source.cpu),"save advanced CPU/device state");
    auto result=std::make_unique<Machine>(source.cpu.clock_divisor,kind);const auto* provider=result->media.get();
    pce::restore_checkpoint(result->bus,result->cpu,saved);restored_prefix_steps+=result->cpu.interpreter_steps;
    require(result->media->requests.empty() && result->bus.cd.provider.get()==provider && provider!=source.media.get(),
            "restore reused/requested source provider");
    require(saved==pce::encode_checkpoint(result->bus,result->cpu),"natural CPU boundary did not round-trip canonically");
    for(unsigned mutation=0;mutation<2;++mutation) {
        auto bad=saved;if(mutation)bad[8]=2;else bad.pop_back();bool rejected=false;
        try{pce::restore_checkpoint(result->bus,result->cpu,bad);}catch(const std::exception&){rejected=true;}
        require(rejected && saved==pce::encode_checkpoint(result->bus,result->cpu),"invalid restore mutated live IRQ/stack/DMA state");
    }
    return result;
}
void run(unsigned divisor,Kind kind,unsigned cut) {
    current="div"+std::to_string(divisor)+"-kind"+std::to_string(static_cast<unsigned>(kind))+"-cut"+std::to_string(cut);++cases;
    auto source=std::make_unique<Machine>(divisor,kind);const auto origin=source->prepare(kind);
    for(unsigned i=1;i<=cut;++i)step(*source,kind,i,origin);
    auto destination=fork(*source,kind);expect(*destination,kind,cut,origin);
    const auto imported=destination->cpu.interpreter_steps;
    for(unsigned i=cut+1;i<=14;++i) {
        step(*source,kind,i,origin);step(*destination,kind,i,origin);
        require(pce::encode_checkpoint(source->bus,source->cpu)==pce::encode_checkpoint(destination->bus,destination->cpu),
                "post-cut full CPU/stack/device continuation diverged");
    }
    require(destination->cpu.interpreter_steps-imported==14-cut,"imported work was counted as new suffix work");
    require(source->media->requests==std::vector<unsigned>{0} && destination->media->requests.empty(),"buffered suffix unexpectedly fetched media");
}
}
int main() {try {
    for(unsigned divisor:{3u,12u}) {
        for(unsigned cut:{3u,4u,5u,11u,13u})run(divisor,Kind::mask,cut);
        run(divisor,Kind::held,13);run(divisor,Kind::reset,11);
        for(auto kind:{Kind::cpu_mask,Kind::cd_mask,Kind::i_mask})run(divisor,kind,5);
    }
    std::cout<<cases<<" READ-fed DMA CPU IRQ checkpoint cases; "<<checks<<" checks; "<<guest_steps
             <<" actual interpreted opcodes, 0 native; "<<restored_prefix_steps<<" imported prefix opcodes; "
             <<"host-supervised device setup, no retail/fresh-process/original-core claim\n";return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
