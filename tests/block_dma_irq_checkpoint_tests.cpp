// Authored host-supervised READ/ACK/DMA setup, followed by real interpreted
// block/handler/RTI instructions. No native, fresh-process or external-core proof.
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
std::uint64_t actual_steps=0,actual_blocks=0,imported_steps=0,imported_blocks=0;
std::string current;
void require(bool value,const char* why) {++checks;if(!value)throw std::runtime_error(current+": "+why);}
constexpr unsigned count=17;
unsigned source_byte(unsigned i) {return (0x42+i*29)&255;}
unsigned sector_byte(unsigned i) {return (0x61+i*13+(i>>8)*7)&255;}
struct Media final:pce::SectorProvider {
    pce::CdToc geometry;
    std::vector<unsigned> requests;
    Media() {geometry.track_count=1;geometry.tracks[0]={0,4};geometry.leadout_lba=8;geometry.image_sha256=std::string(64,'d');}
    const pce::CdToc& toc()const override{return geometry;}
    pce::Sector read(std::uint32_t lba)override {
        require(lba<8,"provider LBA outside authored geometry");requests.push_back(lba);pce::Sector result{};
        for(unsigned i=0;i<result.size();++i)result[i]=static_cast<std::uint8_t>(sector_byte(i)+lba*53);
        return result;
    }
};
struct Machine {
    pce::Bus bus;pce::Cpu cpu;
    std::shared_ptr<Media> media=std::make_shared<Media>();
    std::array<std::uint8_t,7> instruction{};
    Machine(unsigned opcode,unsigned divisor,bool masked) {
        std::vector<std::uint8_t> rom(262144,0xEA);
        const unsigned source=opcode==0xC3?0xE810:0xE800;
        const unsigned destination=opcode==0xC3?0x2210:0x2200;
        instruction={static_cast<std::uint8_t>(opcode),static_cast<std::uint8_t>(source),
            static_cast<std::uint8_t>(source>>8),static_cast<std::uint8_t>(destination),
            static_cast<std::uint8_t>(destination>>8),count,0};
        std::copy(instruction.begin(),instruction.end(),rom.begin());
        // PHA; INC witness; LDA #7; STA CPU interrupt mask; PLA; RTI.
        constexpr std::array<std::uint8_t,11> handler={0x48,0xEE,0x12,0x20,0xA9,7,0x8D,2,0x14,0x68,0x40};
        std::copy(handler.begin(),handler.end(),rom.begin()+0x1840);
        for(unsigned i=0;i<count;++i)rom[0x800+i]=static_cast<std::uint8_t>(source_byte(i));
        rom[0x1FF6]=0x40;rom[0x1FF7]=0xF8;rom[0x1FFE]=0;rom[0x1FFF]=0xE0;
        bus.configure_system_card(pce::SystemCardProfile::standard,rom);
        bus.enable_cd_transport();bus.cd.set_sector_provider(media);bus.enable_adpcm();bus.enable_interrupts();
        // Explicit unit-fixture registers, not an autonomous startup recipe.
        cpu.pc=0xE000;cpu.a=0xA7;cpu.x=0x35;cpu.y=0x69;cpu.sp=255;cpu.p=0xC9;
        cpu.clock_divisor=divisor;bus.irq.mask=masked?7:6;
    }
    void advance(std::uint64_t ticks) {cpu.ticks+=ticks;bus.sync(cpu);}
    void cd(unsigned port,unsigned value) {bus.cd.transport_write(port,static_cast<std::uint8_t>(value));}
    void ack() {const auto enabled=bus.cd.interrupt_enable;cd(2,enabled|128);cd(2,enabled);}
    std::uint64_t prepare() {
        bus.adpcm.write(8,0xFE,&bus.cd);bus.adpcm.write(9,0xFF,&bus.cd);
        bus.adpcm.write(13,3,&bus.cd);bus.adpcm.write(13,0,&bus.cd);
        cd(2,12);cd(0,0);advance(75000);
        const unsigned command[]={8,0,0,0,1,0};
        for(unsigned i=0;i<6;++i) {
            require(bus.cd.transport_read(0)==0xD0,"READ command REQ missing");
            cd(1,command[i]);ack();if(i<5)advance(3000);
        }
        require(bus.cd.scsi.load_deadline==cpu.ticks+3507953,"READ first-load deadline differs");
        advance(3507953);advance((36-cpu.ticks%36)%36);
        require(media->requests==std::vector<unsigned>{0} && bus.cd.scsi.data==sector_byte(0),"real READ payload missing");
        bus.adpcm.write(11,2,&bus.cd);advance(0);
        require(bus.adpcm.dma==2 && bus.adpcm.dma_deadline==cpu.ticks+36,"pending actual DMA capture differs");
        require(!bus.adpcm.dma_bytes && !bus.adpcm.length && !bus.adpcm.half_irq && !bus.adpcm.end_irq &&
                !bus.cd.irq2() && !cpu.irq_sampled && !cpu.irq_entries && !cpu.cycles &&
                !cpu.native_steps && !cpu.interpreter_steps,"device setup fabricated a pending IRQ or retired CPU work");
        // First write commits after36+9 master ticks, within the119-cycle
        // block at either speed, before its eventual IRQ entry's extra8cycles.
        require(45<(17+6*count)*cpu.clock_divisor,"fixture does not span the source edge");
        for(unsigned i=0;i<7;++i)require(*bus.peek(pce::Bus::physical(cpu,0xE000+i))==instruction[i],"authored block source identity differs");
        return cpu.ticks;
    }
};

std::array<std::uint8_t,8192> expected_wram(unsigned opcode,bool masked,unsigned step) {
    std::array<std::uint8_t,8192> result{};
    if(!step)return result;
    // Independent address formula; no runtime addressing/transfer helper.
    for(unsigned i=0;i<count;++i) {
        const unsigned source_index=opcode==0xC3?count-1-i:opcode==0xF3?i%2:i;
        const unsigned offset=opcode==0xC3?count-1-i:opcode==0xD3?0:opcode==0xE3?i%2:i;
        result[0x200+offset]=static_cast<std::uint8_t>(source_byte(source_index));
    }
    if(masked) {result[0x1FF]=0x69;result[0x1FE]=0xA7;result[0x1FD]=0x35;}
    else {
        result[0x1FF]=0xE0;result[0x1FE]=7;result[0x1FD]=0xC9;
        if(step>=2)result[0x1FC]=0xA7;
        if(step>=3)result[0x12]=1;
    }
    return result;
}
void expect(const Machine& m,unsigned opcode,bool masked,unsigned step,std::uint64_t origin) {
    const auto& c=m.cpu;
    constexpr unsigned pc[]={0xE000,0xF840,0xF841,0xF844,0xF846,0xF849,0xF84A,0xE007,0xE008};
    constexpr unsigned cycles[]={0,127,130,137,139,144,148,155,157};
    constexpr unsigned flags[]={0xC9,0xC5,0xC5,0x45,0x45,0x45,0xC5,0xC9,0xC9};
    const unsigned expected_pc=masked?(step==0?0xE000:step==1?0xE007:0xE008):pc[step];
    const unsigned elapsed=masked?(step==0?0:step==1?119:121):cycles[step];
    const unsigned sp=masked||!step||step>=7?255:step>=2&&step<=5?251:252;
    require(c.pc==expected_pc && c.sp==sp && c.p==(masked?0xC9:flags[step]),"literal completed PC/SP/P differs");
    require(c.a==(!masked&&(step==4||step==5)?7:0xA7) && c.x==0x35 && c.y==0x69,"block/handler failed to preserve registers");
    require(c.cycles==elapsed && c.ticks==origin+elapsed*c.clock_divisor,"literal block/entry/handler clocks differ");
    require(c.irq_entries==unsigned(!masked&&step>0) && m.bus.irq.entries==c.irq_entries &&
            c.rti_steps==unsigned(!masked&&step>=7) && c.irq_vector==(c.irq_entries?0xFFF6:0) &&
            !c.irq_sampled,"actual IRQ2 entry/RTI/sample differs");
    require(c.native_steps==0 && c.interpreter_steps==step && !c.native_block_steps &&
            c.interpreter_block_steps==unsigned(step>0) && c.block_bytes==(step?count:0),
            "block continuation/entry was counted as extra guest opcodes");
    require(c.mpr==std::array<std::uint8_t,8>{255,248,128,129,130,131,132,0},"full MPR/source mapping changed");
    const auto memory=expected_wram(opcode,masked,step);
    require(std::equal(memory.begin(),memory.end(),m.bus.bytes->begin()+0x1F0000),"independent entire WRAM/scratch/stack/witness differs");
    require(m.bus.irq.mask==(masked||step>=5?7:6),"handler changed the wrong interrupt controller mask");
    require(m.bus.cd.interrupt_enable==12 && m.bus.adpcm.dma==2,"handler changed ADPCM/CD source enables or DMA mode");
    if(step) {
        require(m.bus.adpcm.half_irq && m.bus.adpcm.end_irq && (m.bus.cd.interrupt_active&12)==12 && m.bus.cd.irq2(),"block did not span actual DMA HALF/END assertion");
        require(m.bus.adpcm.length>0 && m.bus.adpcm.length<2048 && m.bus.adpcm.dma_bytes>=m.bus.adpcm.length &&
                m.bus.adpcm.write_address==((0xFFFE + m.bus.adpcm.length)&65535),"DMA capture/commit pointer relation differs");
        std::array<std::uint8_t,65536> expected{};
        for(unsigned i=0;i<m.bus.adpcm.length;++i)expected[(0xFFFE + i)&65535]=static_cast<std::uint8_t>(sector_byte(i));
        require(m.bus.adpcm.ram==expected,"independent entire committed ADPCM RAM prefix differs");
    }
}
void step(Machine& m,unsigned opcode,bool masked,unsigned ordinal,std::uint64_t origin) {
    const auto blocks=m.cpu.interpreter_block_steps;
    require(pce::interpret_step(m.bus,m.cpu,std::numeric_limits<std::uint64_t>::max())==pce::Exit::executed,"authored guest instruction did not execute");
    ++actual_steps;actual_blocks+=m.cpu.interpreter_block_steps-blocks;expect(m,opcode,masked,ordinal,origin);
}
std::unique_ptr<Machine> fork(const Machine& source,unsigned opcode,bool masked) {
    const auto saved=pce::encode_checkpoint(source.bus,source.cpu);
    require(saved==pce::encode_checkpoint(source.bus,source.cpu),"save changed pending block/DMA state");
    auto result=std::make_unique<Machine>(opcode,source.cpu.clock_divisor,masked);const auto* provider=result->media.get();
    pce::restore_checkpoint(result->bus,result->cpu,saved);
    imported_steps+=result->cpu.interpreter_steps;imported_blocks+=result->cpu.interpreter_block_steps;
    require(result->media->requests.empty() && result->bus.cd.provider.get()==provider && provider!=source.media.get(),"restore reused/fetched through source provider");
    require(saved==pce::encode_checkpoint(result->bus,result->cpu),"complete natural-boundary checkpoint round-trip differs");
    for(unsigned mutation=0;mutation<2;++mutation) {
        auto bad=saved;if(mutation)bad[8]=2;else bad.pop_back();bool rejected=false;
        try{pce::restore_checkpoint(result->bus,result->cpu,bad);}catch(const std::exception&){rejected=true;}
        require(rejected && saved==pce::encode_checkpoint(result->bus,result->cpu),"bad restore mutated live block/IRQ/DMA state");
    }
    return result;
}
void run(unsigned opcode,unsigned divisor,bool masked,unsigned cut) {
    current="op"+std::to_string(opcode)+"-div"+std::to_string(divisor)+"-masked"+std::to_string(masked)+"-cut"+std::to_string(cut);++cases;
    auto source=std::make_unique<Machine>(opcode,divisor,masked);const auto origin=source->prepare();expect(*source,opcode,masked,0,origin);
    for(unsigned n=1;n<=cut;++n)step(*source,opcode,masked,n,origin);
    auto destination=fork(*source,opcode,masked);expect(*destination,opcode,masked,cut,origin);
    const auto prefix=destination->cpu.interpreter_steps;const unsigned last=masked?2:8;
    for(unsigned n=cut+1;n<=last;++n) {
        step(*source,opcode,masked,n,origin);step(*destination,opcode,masked,n,origin);
        require(pce::encode_checkpoint(source->bus,source->cpu)==pce::encode_checkpoint(destination->bus,destination->cpu),"whole-state post-cut continuation diverged");
    }
    require(destination->cpu.interpreter_steps-prefix==last-cut,"imported prefix counted as new suffix work");
    require(source->media->requests==std::vector<unsigned>{0} && destination->media->requests.empty(),"buffered suffix unexpectedly read media");
}
}
int main() {try {
    for(unsigned opcode:{0x73u,0xC3u,0xD3u,0xE3u,0xF3u})for(unsigned divisor:{3u,12u}) {
        for(unsigned cut:{0u,1u})run(opcode,divisor,false,cut);
        run(opcode,divisor,true,0);
    }
    std::cout<<cases<<" READ-fed block DMA IRQ checkpoint cases; "<<checks<<" checks; "<<actual_steps
             <<" actual interpreted opcodes, 0 native; "<<actual_blocks<<" actual block retirements; "
             <<imported_steps<<" imported prefix opcodes/"<<imported_blocks<<" blocks; "
             <<"host-supervised setup, natural whole-instruction cuts, no retail/fresh-process/original-core claim\n";return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
