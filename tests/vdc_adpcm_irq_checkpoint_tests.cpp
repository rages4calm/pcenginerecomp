// Authored, host-supervised register/READ setup; actual interpreted VDC access,
// IRQ acknowledgement and RTI. No native, fresh-process or original-core proof.
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
unsigned sector_byte(unsigned i) {return (0x61+i*13+(i>>8)*7)&255;}
unsigned source_word(unsigned i) {return i==0?0xA65C:i==4095?0x5AA5:(0x3217+i*79)&65535;}
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
    bool block,mask_cd;
    unsigned control,length;
    std::vector<std::uint8_t> instruction;
    std::array<std::uint8_t,8192> bank_source{};
    Machine(bool tai,unsigned divisor,unsigned vce,bool masked):block(tai),mask_cd(masked),control(vce),length(tai?7:3) {
        std::vector<std::uint8_t> rom(262144,0xEA);
        instruction=tai?std::vector<std::uint8_t>{0xF3,2,0,0,0x22,2,0}:
                        std::vector<std::uint8_t>{0xAD,3,0};
        std::copy(instruction.begin(),instruction.end(),rom.begin());
        // IRQ1: PHA; LDA VDC status; STA witness; INC witness; optional CD mask;
        // PLA; RTI. Clearing the VDC source must leave ADPCM flags intact.
        std::vector<std::uint8_t> first={0x48,0xAD,0,0,0x8D,0x10,0x20,0xEE,0x11,0x20};
        if(mask_cd)first.insert(first.end(),{0xA9,0,0x8D,2,0x18});
        first.insert(first.end(),{0x68,0x40});
        std::copy(first.begin(),first.end(),rom.begin()+0x1800);
        // IRQ2: PHA; INC witness; LDA #7; STA CPU mask; PLA; RTI.
        constexpr std::array<std::uint8_t,11> second={0x48,0xEE,0x12,0x20,0xA9,7,0x8D,2,0x14,0x68,0x40};
        std::copy(second.begin(),second.end(),rom.begin()+0x1880);
        rom[0x1FF8]=0;rom[0x1FF9]=0xF8;rom[0x1FF6]=0x80;rom[0x1FF7]=0xF8;
        rom[0x1FFE]=0;rom[0x1FFF]=0xE0;
        std::copy_n(rom.begin(),bank_source.size(),bank_source.begin());
        bus.configure_system_card(pce::SystemCardProfile::standard,rom);
        bus.enable_video();bus.enable_cd_transport();bus.cd.set_sector_provider(media);bus.enable_adpcm();bus.enable_interrupts();
        // Explicit unit-fixture registers, not autonomous startup.
        cpu.pc=0xE000;cpu.a=0xA7;cpu.x=0x35;cpu.y=0x69;cpu.sp=255;cpu.p=0xC9;
        cpu.clock_divisor=divisor;bus.irq.mask=4;
    }
    void advance(std::uint64_t ticks) {cpu.ticks+=ticks;bus.sync(cpu);}
    void reg(unsigned index,unsigned value) {bus.vdc.write(0,static_cast<std::uint8_t>(index));bus.vdc.write(2,static_cast<std::uint8_t>(value));bus.vdc.write(3,static_cast<std::uint8_t>(value>>8));}
    void cd(unsigned port,unsigned value) {bus.cd.transport_write(port,static_cast<std::uint8_t>(value));}
    void ack() {cd(2,140);cd(2,12);}
    std::uint64_t prepare() {
        bus.vdc.write_vce_control(static_cast<std::uint8_t>(control));bus.vce.write(0,static_cast<std::uint8_t>(control));
        reg(5,0);reg(10,0x7F1F);reg(11,0x7F7F);reg(15,0);
        for(unsigned i=0;i<4096;++i)(*bus.vdc.vram)[i]=static_cast<std::uint16_t>(source_word(i));
        reg(1,4095);bus.vdc.write(0,2);advance(400000);
        require(!bus.vdc.has_pending_vram() && bus.vdc.read_buffer==0x5AA5,"initial authored prefetch did not complete");
        bus.adpcm.write(8,0xFE,&bus.cd);bus.adpcm.write(9,0xFF,&bus.cd);
        bus.adpcm.write(13,3,&bus.cd);bus.adpcm.write(13,0,&bus.cd);
        cd(2,12);cd(0,0);advance(75000);
        const unsigned command[]={8,0,0,0,1,0};
        for(unsigned i=0;i<6;++i) {
            require(bus.cd.transport_read(0)==0xD0,"READ command REQ missing");
            cd(1,command[i]);ack();if(i<5)advance(3000);
        }
        require(bus.cd.scsi.load_deadline==cpu.ticks+3507953,"READ first-load deadline differs");
        advance(3507953-1024);
        bus.adpcm.write(11,2,&bus.cd);advance(0);
        require(bus.cd.scsi.load_deadline==cpu.ticks+1024 && media->requests.empty(),"READ was not still seeking before target");
        // Real register writes launch 4096 words of blank VRAM DMA and a read.
        // No source flag, DMA countdown or queue entry is injected.
        reg(15,2);reg(16,0);reg(17,0x2000);reg(18,4095);reg(1,0);bus.vdc.write(0,2);
        require(bus.vdc.vram_dma_pending==16384 && bus.vdc.pending_vram_read && bus.vdc.read_buffer==0x5AA5,
                "real VDC register sequence did not arm DMA/prefetch");
        require(!bus.vdc.irq1 && !(bus.vdc.status&63) && !bus.adpcm.half_irq && !bus.adpcm.end_irq &&
                !bus.cd.irq2() && !cpu.irq_sampled && !(cpu.p&pce::I) && !cpu.irq_entries &&
                !cpu.cycles && !cpu.native_steps && !cpu.interpreter_steps && !bus.adpcm.length && !bus.adpcm.dma_bytes,
                "setup fabricated a source edge or retired CPU work");
        require((block?16u:1u)*cpu.clock_divisor<1024,"READ could arrive before initial queued wait");
        for(unsigned i=0;i<instruction.size();++i)require(*bus.peek(pce::Bus::physical(cpu,0xE000+i))==instruction[i],"authored target source identity differs");
        return cpu.ticks;
    }
};
struct Stage {unsigned pc,cycles,flags,sp,a,entries,rtis;};
std::vector<Stage> stages(const Machine& m) {
    const unsigned a=m.block?0xA7:0xA6;
    const unsigned base=m.block?41:14;
    std::vector<Stage> s={{0xE000,0,0xC9,255,0xA7,0,0},{0xF800,base,0xC5,252,a,1,0}};
    auto add=[&](unsigned pc,unsigned cycles,unsigned flags,unsigned sp,unsigned value,unsigned entries=1,unsigned rtis=0) {
        s.push_back({pc,s.back().cycles+cycles,flags,sp,value,entries,rtis});
    };
    add(0xF801,3,0xC5,251,a);
    add(0xF804,6,0x45,251,0); // Status A is independently constrained below.
    add(0xF807,5,0x45,251,0);
    add(0xF80A,7,0x45,251,0);
    if(m.mask_cd) {add(0xF80C,2,0x47,251,0);add(0xF80F,5,0x47,251,0);}
    add(m.mask_cd?0xF810:0xF80B,4,0xC5,252,a);
    add(0xE000+m.length,7,0xC9,255,a,1,1);
    if(m.mask_cd) {
        add(0xE001+m.length,2,0xC9,255,a,1,1);add(0xE002+m.length,2,0xC9,255,a,1,1);
    } else {
        add(0xF880,10,0xC5,252,a,2,1); // NOP plus 8-cycle IRQ2 entry.
        add(0xF881,3,0xC5,251,a,2,1);add(0xF884,7,0x45,251,a,2,1);
        add(0xF886,2,0x45,251,7,2,1);add(0xF889,5,0x45,251,7,2,1);
        add(0xF88A,4,0xC5,252,a,2,1);add(0xE001+m.length,7,0xC9,255,a,2,2);
        add(0xE002+m.length,2,0xC9,255,a,2,2);
    }
    return s;
}
void expect(const Machine& m,unsigned step,std::uint64_t origin) {
    const auto& c=m.cpu;const auto expected=stages(m)[step];
    const auto wram=m.bus.bytes->begin()+0x1F0000;
    const unsigned status=step>=4?wram[0x10]:c.a;
    const bool status_a=step>=3 && step<=5;
    require(c.pc==expected.pc && c.sp==expected.sp && c.p==expected.flags,"literal completed PC/SP/P differs");
    require(c.a==(status_a?status:expected.a) && c.x==0x35 && c.y==0x69,"target or handler clobbered registers");
    if(step>=3)require((status&63)==16 && !(status&0x80),"status read did not acknowledge VRAM completion alone");
    require(c.cycles==expected.cycles && c.ticks==origin+c.cycles*c.clock_divisor+c.vdc_wait_ticks,"literal instruction clocks plus dynamic wait relation differs");
    if(step)require(c.vdc_wait_ticks>30000 && c.vdc_wait_ticks<8ULL*1365*263 && !(c.vdc_wait_ticks%3),"queued wait outside finite timing bounds");
    require(c.irq_entries==expected.entries && m.bus.irq.entries==expected.entries && c.rti_steps==expected.rtis &&
            c.irq_vector==(expected.entries==2?0xFFF6:expected.entries?0xFFF8:0) && !c.irq_sampled,"priority/RTI/pending IRQ2 handoff differs");
    require(c.native_steps==0 && !c.native_block_steps && c.interpreter_steps==step &&
            c.interpreter_block_steps==unsigned(m.block&&step>0) && c.block_bytes==(m.block&&step?2:0),"extra target/handler retirement or imported work");
    require(c.mpr==std::array<std::uint8_t,8>{255,248,128,129,130,131,132,0},"full logical/source MPR mapping changed");
    require(std::equal(m.bank_source.begin(),m.bank_source.end(),m.bus.bytes->begin()),"authored target/handler/vector source bank changed");
    require(m.bus.vdc.raster.divider==(m.control==0?4:m.control==1?3:2),"wrong VCE divider in queued-access recipe");
    std::array<std::uint8_t,8192> memory{};
    if(step) {
        memory[0x1FF]=0xE0;memory[0x1FE]=static_cast<std::uint8_t>(m.length+unsigned(expected.entries==2));memory[0x1FD]=0xC9;
        if(step>=2)memory[0x1FC]=m.block?0xA7:0xA6;
        if(m.block){memory[0x200]=0x5C;memory[0x201]=0xA6;}
        if(step>=4)memory[0x10]=static_cast<std::uint8_t>(status);
        if(step>=5)memory[0x11]=1;
        if(!m.mask_cd && step>=10)memory[0x12]=1;
    }
    require(std::equal(memory.begin(),memory.end(),wram),"independent entire WRAM/stack/read-byte/witness image differs");
    require(m.bus.irq.mask==(!m.mask_cd&&step>=12?7:4),"wrong guest CPU mask");
    require(m.bus.cd.interrupt_enable==(m.mask_cd&&step>=7?0:12) && m.bus.adpcm.dma==2,"wrong CD enable or DMA mode");
    if(!step)return;
    require(!m.bus.vdc.vram_dma_pending && m.bus.vdc.dma_words==4096,"real blank VRAM DMA did not finish during the access");
    std::array<std::uint16_t,32768> vram{};
    for(unsigned i=0;i<vram.size();++i) {
        const auto value=i<4096?source_word(i):i>=0x2000&&i<0x3000?source_word(i-0x2000):0;
        vram[i]=static_cast<std::uint16_t>(value);
    }
    require(*m.bus.vdc.vram==vram,"independent full VRAM DMA pattern differs");
    require(m.bus.vdc.irq1==(step<3) && (m.bus.vdc.status&63)==(step<3?16:0),"VDC status ACK did not clear IRQ1 independently");
    require(m.bus.adpcm.half_irq && m.bus.adpcm.end_irq && (m.bus.cd.interrupt_active&12)==12 &&
            m.bus.cd.irq2()==!(m.mask_cd&&step>=7),"ADPCM flags were lost or source-mask edge differs");
    require(m.bus.irq_requests()==(step<3?3:m.mask_cd&&step>=7?0:1),"IRQ1/IRQ2 aggregate level differs before or after device acknowledgement");
    require(m.bus.adpcm.length>0 && m.bus.adpcm.length<2048 && m.bus.adpcm.dma_bytes>=m.bus.adpcm.length &&
            m.bus.adpcm.write_address==((0xFFFE + m.bus.adpcm.length)&65535),"READ-fed DMA pointer/count relation differs");
    std::array<std::uint8_t,65536> ram{};
    for(unsigned i=0;i<m.bus.adpcm.length;++i)ram[(0xFFFE + i)&65535]=static_cast<std::uint8_t>(sector_byte(i));
    require(m.bus.adpcm.ram==ram,"independent full committed ADPCM RAM prefix differs");
}
void step(Machine& m,unsigned ordinal,std::uint64_t origin) {
    const auto blocks=m.cpu.interpreter_block_steps;
    const auto wait=m.cpu.vdc_wait_ticks;
    require(pce::interpret_step(m.bus,m.cpu,std::numeric_limits<std::uint64_t>::max())==pce::Exit::executed,"authored guest instruction did not execute");
    if(ordinal>1)require(m.cpu.vdc_wait_ticks==wait,"status acknowledgement or handler unexpectedly performed a queued data wait");
    ++actual_steps;actual_blocks+=m.cpu.interpreter_block_steps-blocks;expect(m,ordinal,origin);
}
std::unique_ptr<Machine> fork(const Machine& source) {
    const auto saved=pce::encode_checkpoint(source.bus,source.cpu);
    require(saved==pce::encode_checkpoint(source.bus,source.cpu),"save changed pending real device state");
    auto result=std::make_unique<Machine>(source.block,source.cpu.clock_divisor,source.control,source.mask_cd);
    const auto* provider=result->media.get();pce::restore_checkpoint(result->bus,result->cpu,saved);
    imported_steps+=result->cpu.interpreter_steps;imported_blocks+=result->cpu.interpreter_block_steps;
    require(result->media->requests.empty() && result->bus.cd.provider.get()==provider && provider!=source.media.get(),"restore fetched media or retained source provider");
    require(saved==pce::encode_checkpoint(result->bus,result->cpu),"whole natural-boundary checkpoint round-trip differs");
    for(unsigned mutation=0;mutation<2;++mutation) {
        auto bad=saved;if(mutation)bad[8]=2;else bad.pop_back();bool rejected=false;
        try{pce::restore_checkpoint(result->bus,result->cpu,bad);}catch(const std::exception&){rejected=true;}
        require(rejected && saved==pce::encode_checkpoint(result->bus,result->cpu),"invalid restore changed live pending device state");
    }
    return result;
}
void run(bool tai,unsigned divisor,unsigned control,bool masked,unsigned cut) {
    current=std::string(tai?"TAI2":"LDAhigh")+"-div"+std::to_string(divisor)+"-vce"+std::to_string(control)+"-maskCD"+std::to_string(masked)+"-cut"+std::to_string(cut);++cases;
    auto source=std::make_unique<Machine>(tai,divisor,control,masked);const auto origin=source->prepare();expect(*source,0,origin);
    for(unsigned n=1;n<=cut;++n)step(*source,n,origin);
    auto destination=fork(*source);expect(*destination,cut,origin);
    const auto prefix=destination->cpu.interpreter_steps;const unsigned last=static_cast<unsigned>(stages(*source).size()-1);
    for(unsigned n=cut+1;n<=last;++n) {
        step(*source,n,origin);step(*destination,n,origin);
        require(pce::encode_checkpoint(source->bus,source->cpu)==pce::encode_checkpoint(destination->bus,destination->cpu),"complete post-cut continuation diverged");
    }
    require(destination->cpu.interpreter_steps-prefix==last-cut,"imported prefix counted as new suffix work");
    require(source->media->requests==std::vector<unsigned>{0} &&
            destination->media->requests==(cut?std::vector<unsigned>{}:std::vector<unsigned>{0}),"restored buffered/pending READ fetched incorrect sectors");
}
}
int main() {try {
    for(unsigned divisor:{3u,12u})for(unsigned control:{0u,1u,2u})for(bool tai:{false,true})for(bool masked:{false,true})for(unsigned cut:{0u,1u})
        run(tai,divisor,control,masked,cut);
    std::cout<<cases<<" READ-fed ADPCM/queued VDC IRQ checkpoint cases; "<<checks<<" checks; "<<actual_steps
             <<" actual interpreted opcodes, 0 native; "<<actual_blocks<<" actual block retirements; "
             <<imported_steps<<" imported prefix opcodes/"<<imported_blocks<<" blocks; "
             <<"host-supervised setup, natural whole-instruction cuts, bounded dynamic timing, no retail/fresh-process/original-core claim\n";return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
