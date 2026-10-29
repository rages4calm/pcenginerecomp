// Authored direct-device coupled CD/ADPCM continuation; zero guest retirements.
#include "pce/checkpoint.hpp"
#include "pce/sector.hpp"
#include <array>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
constexpr std::uint64_t first_load=3507953;
constexpr std::uint64_t sample_period=(21477273ULL*65536+16050)/32100;
unsigned checks=0,cases=0;
std::string current;
void require(bool value,const char* why) {++checks;if(!value)throw std::runtime_error(current+": "+why);}
unsigned pattern(unsigned lba,unsigned offset) {return (lba*53+offset*13+(offset>>8)*7+0x61)&255;}
struct Media final:pce::SectorProvider {
    pce::CdToc geometry;
    std::vector<unsigned> requests;
    explicit Media(char identity='c') {
        geometry.track_count=1;geometry.tracks[0]={0,4};geometry.leadout_lba=8;
        geometry.image_sha256=std::string(64,identity);
    }
    const pce::CdToc& toc() const override {return geometry;}
    pce::Sector read(std::uint32_t lba) override {
        require(lba<8,"unexpected sector request");requests.push_back(lba);pce::Sector result{};
        for(unsigned i=0;i<result.size();++i)result[i]=static_cast<std::uint8_t>(pattern(lba,i));return result;
    }
};
struct Machine {
    pce::Bus bus;pce::Cpu cpu;std::shared_ptr<Media> media;
    explicit Machine(unsigned divisor,char identity='c'):media(std::make_shared<Media>(identity)) {
        cpu.clock_divisor=divisor;bus.enable_cd_transport();bus.enable_adpcm();bus.cd.set_sector_provider(media);
    }
    void advance(std::uint64_t delta) {cpu.ticks+=delta;bus.sync(cpu);}
    void at(std::uint64_t ticks) {require(ticks>=cpu.ticks,"clock moved backwards");advance(ticks-cpu.ticks);}
    void cd(unsigned port,unsigned value) {bus.cd.transport_write(port,static_cast<std::uint8_t>(value));}
    void ad(unsigned port,unsigned value) {bus.adpcm.write(port,static_cast<std::uint8_t>(value),&bus.cd);}
    void address(unsigned value) {ad(8,value&255);ad(9,value>>8);}
    void length(unsigned value) {address(value);ad(13,16);ad(13,0);}
    void write_base(unsigned value) {address(value);ad(13,3);ad(13,0);}
    void read_base(unsigned value) {address(value);ad(13,12);ad(13,0);}
    void ack() {const auto enabled=bus.cd.interrupt_enable;cd(2,enabled|128);cd(2,enabled);}
    void body(unsigned lba,unsigned count) {
        const unsigned bytes[]{8,0,0,lba,count,0};
        for(unsigned i=0;i<6;++i) {
            require(bus.cd.transport_read(0)==0xd0,"command REQ missing");cd(1,bytes[i]);ack();
            if(i<5)advance(3000);
        }
        require(bus.cd.scsi.load_deadline==cpu.ticks+first_load,"first-load deadline differs");
    }
    void command(unsigned lba=0,unsigned count=1) {cd(0,0);advance(75000);body(lba,count);}
    std::uint64_t ready(unsigned mode,unsigned count=1) {
        write_base(0xfffe);cd(2,12);command(0,count);advance(first_load);
        require(media->requests==std::vector<unsigned>{0},"initial provider identity/order differs");
        advance((36-cpu.ticks%36)%36);
        require(bus.cd.scsi.signals==0xc8 && bus.cd.scsi.data==pattern(0,0),"first data byte missing");
        ad(11,mode);advance(0);
        require(bus.adpcm.dma_deadline==cpu.ticks+36,"DMA did not arm a 36-tick capture");
        return cpu.ticks;
    }
    void complete() {
        // DATA IN was consumed by DMA. STATUS and MESSAGE still need manual ACK.
        require(bus.cd.scsi.phase==7 && bus.cd.transport_read(0)==0xd8 && bus.cd.transport_read(1)==0,
                "DMA consumed status or failed to finish DATA IN");
        ack();advance(1500);
        require(bus.cd.transport_read(0)==0xf8 && bus.cd.transport_read(1)==0,"message completion differs");
        ack();advance(1500);require(bus.cd.transport_read(0)==0,"bus did not release");
    }
};
void zero_work(const Machine& m) {
    require(m.cpu.native_steps==0 && m.cpu.interpreter_steps==0 && m.cpu.irq_entries==0,
            "direct-device fixture claimed guest work or CPU IRQ delivery");
}
std::unique_ptr<Machine> fork(Machine& source) {
    const auto prior=source.media->requests;const auto bytes=pce::encode_checkpoint(source.bus,source.cpu);
    require(prior==source.media->requests,"save requested media");
    require(bytes==pce::encode_checkpoint(source.bus,source.cpu),"save changed state");
    auto result=std::make_unique<Machine>(source.cpu.clock_divisor);auto* provider=result->media.get();
    pce::restore_checkpoint(result->bus,result->cpu,bytes);
    require(result->media->requests.empty(),"restore requested media");
    require(result->bus.cd.provider.get()==provider && provider!=source.media.get(),"restore reused source provider");
    require(bytes==pce::encode_checkpoint(result->bus,result->cpu),"restore changed canonical state");
    for(unsigned mutation=0;mutation<4;++mutation) {
        auto bad=bytes;if(mutation==0)bad.pop_back();if(mutation==1)bad.push_back(0);
        if(mutation==2)bad[0]^=0x80;if(mutation==3)bad[8]=2;
        const auto before=pce::encode_checkpoint(result->bus,result->cpu);bool refused=false;
        try {pce::restore_checkpoint(result->bus,result->cpu,bad);}catch(const std::exception&){refused=true;}
        require(refused && before==pce::encode_checkpoint(result->bus,result->cpu),"invalid copy changed destination");
        require(result->media->requests.empty(),"invalid load requested media");
    }
    auto foreign=std::make_unique<Machine>(source.cpu.clock_divisor,'d');
    const auto before=pce::encode_checkpoint(foreign->bus,foreign->cpu);bool refused=false;
    try {pce::restore_checkpoint(foreign->bus,foreign->cpu,bytes);}catch(const std::exception&){refused=true;}
    require(refused && before==pce::encode_checkpoint(foreign->bus,foreign->cpu),"foreign media changed destination");
    require(foreign->media->requests.empty(),"foreign load requested media");return result;
}
void same(const Machine& a,const Machine& b) {
    zero_work(a);zero_work(b);
    require(pce::encode_checkpoint(a.bus,a.cpu)==pce::encode_checkpoint(b.bus,b.cpu),"continued canonical state differs");
}
void ram(const Machine& m,unsigned start,unsigned lba,unsigned first=0,unsigned count=2048,int leading=-1) {
    std::array<unsigned,65536> expected{};
    if(leading>=0){expected[start]=static_cast<unsigned>(leading);start=(start+1)&65535;}
    for(unsigned i=0;i<count;++i)expected[(start+i)&65535]=pattern(lba,first+i);
    for(unsigned i=0;i<expected.size();++i)require(m.bus.adpcm.ram[i]==expected[i],"RAM payload/order/untouched byte differs");
}
void finish_sector(Machine& m,unsigned mode,unsigned bytes,unsigned length,unsigned address,unsigned acked=2048) {
    m.advance(220000);
    require(m.bus.adpcm.dma_bytes==bytes && m.bus.adpcm.length==length && m.bus.adpcm.write_address==address,
            "DMA byte/length/address totals differ");
    require(!m.bus.adpcm.write_deadline && !m.bus.adpcm.dma_deadline && !m.bus.cd.ack &&
            !m.bus.cd.scsi.auto_ack_deadline,"completed transfer retained a pending beat or ACK");
    require(m.bus.adpcm.dma==(mode&2),"one-shot/continuous completion bits differ");
    require(m.bus.cd.data_bytes_acked==acked,"transfer ACK count differs");m.complete();
}
void beats() {
    for(unsigned div:{3u,12u})for(unsigned mode:{1u,2u})for(unsigned cut=0;cut<6;++cut) {
        current="beat-div"+std::to_string(div)+"-mode"+std::to_string(mode)+"-cut"+std::to_string(cut);++cases;
        auto source=std::make_unique<Machine>(div);const auto base=source->ready(mode);
        const unsigned offsets[]{35,36,44,45,56,100};
        if(cut==5){source->at(base+10);source->ad(11,0);}
        source->at(base+offsets[cut]);auto dest=fork(*source);
        for(auto* m:{source.get(),dest.get()}) {
            auto& a=m->bus.adpcm;
            if(cut==5) {
                require(a.dma_deadline==base+126 && !a.dma_bytes,"disabled DMA did not preserve 26 ticks");
                m->ad(11,mode);m->at(base+125);require(!a.dma_bytes,"paused DMA resumed early");m->at(base+126);
                require(a.dma_bytes==1 && a.write_deadline==base+127 && m->bus.cd.scsi.auto_ack_deadline==base+147,
                        "paused DMA capture/commit/ACK deadline differs");
            } else {
                if(cut==0){require(!a.dma_bytes && a.dma_deadline==base+36,"capture happened early");m->at(base+36);}
                if(cut<=1)require(a.dma_bytes==1 && a.write_latch==pattern(0,0) && a.write_deadline==base+45 &&
                    !a.ram[0xfffe] && m->bus.cd.ack && m->bus.cd.scsi.auto_ack_deadline==base+57,"captured-byte state differs");
                if(cut<=2){m->at(base+44);require(!a.ram[0xfffe] && a.write_deadline==base+45,"RAM committed before slot");m->at(base+45);}
                if(cut<=3)require(a.ram[0xfffe]==pattern(0,0) && a.write_address==0xffff && a.length==1 &&
                    a.half_irq && a.end_irq && m->bus.cd.irq2() && m->bus.cd.ack,"commit/IRQ/held ACK state differs");
                if(cut<=4){m->at(base+56);require(m->bus.cd.ack,"automatic ACK dropped early");m->at(base+57);}
                require(!m->bus.cd.ack && m->bus.cd.scsi.data==pattern(0,1) && a.dma_deadline==base+93,
                        "ACK release/next beat differs");
            }
            finish_sector(*m,mode,2048,2048,0x7fe);ram(*m,0xfffe,0);
        }
        require(source->media->requests==std::vector<unsigned>{0} && dest->media->requests.empty(),"buffered suffix fetched media");same(*source,*dest);
    }
}
void waiting() {
    for(unsigned div:{3u,12u})for(unsigned mode:{1u,2u}) {
        current="waiting-div"+std::to_string(div)+"-mode"+std::to_string(mode);++cases;
        auto source=std::make_unique<Machine>(div);source->write_base(0xfffe);source->command();
        const auto due=source->bus.cd.scsi.load_deadline;source->ad(11,mode);source->at(due-1);
        require(!source->bus.adpcm.dma_deadline && source->media->requests.empty(),"armed DMA fetched before READ");
        auto dest=fork(*source);
        for(auto* m:{source.get(),dest.get()}) {
            m->at(due);require(!m->bus.adpcm.dma_bytes && m->bus.cd.scsi.data==pattern(0,0),"READ deadline/capture ordering differs");
            if(mode==1){require(m->bus.adpcm.dma==0,"one-shot armed without buffered data");m->ad(11,1);m->advance(0);}
            require(m->bus.adpcm.dma_deadline==due+36,"READ arrival did not arm DMA");
            finish_sector(*m,mode,2048,2048,0x7fe);ram(*m,0xfffe,0);
        }
        require(source->media->requests==std::vector<unsigned>{0} && dest->media->requests==std::vector<unsigned>{0},"fresh provider initial request differs");same(*source,*dest);
    }
}
void collision() {
    for(unsigned div:{3u,12u})for(unsigned mode:{1u,2u}) {
        current="collision-div"+std::to_string(div)+"-mode"+std::to_string(mode);++cases;
        auto source=std::make_unique<Machine>(div);const auto base=source->ready(mode);
        source->at(base+35);source->ad(10,0xe7);source->at(base+44);
        require(source->bus.adpcm.write_deadline==base+45 && source->bus.adpcm.dma_deadline==base+45 &&
                !source->bus.adpcm.dma_bytes,"CPU write did not postpone DMA");auto dest=fork(*source);
        for(auto* m:{source.get(),dest.get()}) {
            m->at(base+45);auto& a=m->bus.adpcm;
            require(a.ram[0xfffe]==0xe7 && a.write_address==0xffff && a.dma_bytes==1 && a.write_latch==pattern(0,0) &&
                a.write_deadline==base+46 && m->bus.cd.scsi.auto_ack_deadline==base+66,"write/DMA tie order differs");
            m->at(base+46);require(a.ram[0xffff]==pattern(0,0) && a.write_address==0,"deferred commit/wrap differs");
            finish_sector(*m,mode,2048,2049,0x7ff);ram(*m,0xfffe,0,0,2048,0xe7);
        }
        require(dest->media->requests.empty(),"collision suffix refetched media");same(*source,*dest);
    }
}
void resets() {
    for(unsigned div:{3u,12u})for(unsigned mode:{1u,2u})for(unsigned kind=0;kind<3;++kind) {
        current="reset-div"+std::to_string(div)+"-mode"+std::to_string(mode)+"-kind"+std::to_string(kind);++cases;
        auto source=std::make_unique<Machine>(div);const auto base=source->ready(mode,kind==2?2:1);
        source->at(base+10);
        if(kind==0)source->ad(13,128);else if(kind==1)source->cd(4,2);else source->cd(0,0);
        require(source->bus.adpcm.dma_deadline==base+36,"reset discarded an already armed DMA delay");auto dest=fork(*source);
        for(auto* m:{source.get(),dest.get()}) {
            auto& a=m->bus.adpcm;m->at(base+35);require(!a.dma_bytes,"reset beat completed early");m->at(base+36);
            require(a.dma_bytes==1,"already armed beat disappeared");
            if(kind==0) {
                require(a.write_latch==pattern(0,0) && !a.write_deadline && !a.length && !a.write_address &&
                    m->bus.cd.ack && a.dma==mode,"ADPCM reset held behavior differs");
                m->at(base+57);m->ad(13,0);finish_sector(*m,mode,2048,2047,2047);ram(*m,0,0,1,2047);
            } else {
                require(a.write_latch==0 && a.write_deadline==base+45 && !m->bus.cd.ack,
                        "CD reset/reselection pending beat did not sample reset/status byte");
                m->at(base+45);require(a.write_address==0xffff && a.length==1,"captured beat was canceled before commit");
                if(kind==1) {
                    require(a.dma==(mode&2) && m->bus.cd.scsi.signals==0x100,"CD reset retained stale response");
                    m->advance(400000);require(a.dma_bytes==1,"CD reset generated repeated DMA beats");
                    m->cd(4,0);m->command(1,1);
                } else {
                    require(a.dma==mode,"STATUS buffer incorrectly cleared one-shot DMA bit");
                    m->at(base+900010);require(m->bus.cd.scsi.phase==3 && !m->bus.cd.scsi.load_deadline &&
                        !m->bus.cd.scsi.response_size && m->bus.cd.read_retries==1,"reselection retained canceled data/load");m->body(1,1);
                }
                m->advance(first_load);if(mode==1&&kind==1){m->ad(11,1);m->advance(0);}
                finish_sector(*m,mode,2049,2049,0x7ff);ram(*m,0xfffe,1,0,2048,0);
            }
        }
        require(dest->media->requests==(kind?std::vector<unsigned>{1}:std::vector<unsigned>{}),"reset suffix provider order differs");same(*source,*dest);
    }
}
void length_wrap() {
    for(unsigned div:{3u,12u})for(unsigned mode:{1u,2u}) {
        current="length-wrap-div"+std::to_string(div)+"-mode"+std::to_string(mode);++cases;
        auto source=std::make_unique<Machine>(div);source->ad(13,32);source->advance((sample_period*2+65535)/65536);source->ad(13,0);
        require(source->bus.adpcm.length==0x1ffff && source->bus.adpcm.samples==2 &&
            source->bus.adpcm.decoder_output==2052 && source->bus.adpcm.decoder_index==0,"real zero-length playback did not wrap");
        const auto base=source->ready(mode);source->at(base+45);auto dest=fork(*source);
        for(auto* m:{source.get(),dest.get()}) {
            auto& a=m->bus.adpcm;require(!a.length && !a.half_irq && !a.end_irq && !m->bus.cd.irq2(),"write length wrap asserted IRQ early");
            m->at(base+94);require(a.length==1 && a.half_irq && a.end_irq && m->bus.cd.irq2(),"post-wrap zero-length write IRQ differs");
            finish_sector(*m,mode,2048,2047,0x7fe);ram(*m,0xfffe,0);
        }
        require(dest->media->requests.empty(),"length-wrap suffix refetched media");same(*source,*dest);
    }
}
void sector_boundary() {
    for(unsigned div:{3u,12u})for(unsigned mode:{1u,2u})for(bool captured:{false,true}) {
        current="sector-boundary-div"+std::to_string(div)+"-mode"+std::to_string(mode)+"-captured"+std::to_string(captured);++cases;
        auto source=std::make_unique<Machine>(div);const auto base=source->ready(mode,2);
        const auto second_due=source->bus.cd.scsi.load_deadline;
        // Last capture at 36 + 57*2047, RAM slot six ticks later, ACK21 later.
        source->at(base+(captured?116715:120000));auto dest=fork(*source);
        for(auto* m:{source.get(),dest.get()}) {
            auto& a=m->bus.adpcm;
            require(a.dma_bytes==2048 && a.dma==(mode&2),"sector exhaustion mode/capture count differs");
            if(captured) {
                require(a.write_deadline==base+116721 && m->bus.cd.scsi.auto_ack_deadline==base+116736 &&
                        a.write_latch==pattern(0,2047) && !a.ram[0x7fd],"last captured byte cut differs");
                m->at(base+116720);require(!a.ram[0x7fd],"last-byte commit occurred early");m->at(base+116721);
                require(a.ram[0x7fd]==pattern(0,2047) && a.write_address==0x7fe && a.length==2048 &&
                        m->bus.cd.ack,"last byte did not commit while ACK held");m->at(base+120000);
            }
            require(!a.write_deadline && !a.dma_deadline && !m->bus.cd.ack && m->bus.cd.scsi.signals==0x88 &&
                    m->bus.cd.scsi.load_remaining==1 && m->bus.cd.scsi.load_deadline==second_due,
                    "inter-sector gap retained wrong pending work");
            if(mode==1){m->ad(11,1);require(a.dma==0,"one-shot rearmed without buffered next sector");}
            m->at(second_due-1);require(a.dma_bytes==2048,"DMA consumed next sector before arrival");m->at(second_due);
            require(m->bus.cd.scsi.data==pattern(1,0) && m->bus.cd.scsi.current_lba==2 &&
                    !m->bus.cd.scsi.load_remaining,"next sector data/head/counter differs");
            if(mode==1){require(!a.dma_deadline,"one-shot consumed an unarmed next sector");m->ad(11,1);m->advance(0);}
            require(a.dma_deadline==second_due+36,"next-sector DMA did not preserve capture delay");
            finish_sector(*m,mode,4096,4096,0xffe,4096);
            for(unsigned address=0;address<65536;++address) {
                const unsigned offset=(address-0xfffe)&65535;
                const auto expected=offset<4096?pattern(offset/2048,offset%2048):0;
                require(a.ram[address]==expected,"two-sector RAM payload/order/untouched byte differs");
            }
        }
        require(source->media->requests==std::vector<unsigned>({0,1}) && dest->media->requests==std::vector<unsigned>{1},
                "next-sector provider read/rebinding order differs");same(*source,*dest);
    }
}
void playback_irq() {
    for(unsigned div:{3u,12u})for(unsigned enable:{4u,8u}) {
        current="playback-div"+std::to_string(div)+"-enable"+std::to_string(enable);++cases;
        auto source=std::make_unique<Machine>(div);const auto base=source->ready(2);source->at(base+45);source->ad(11,0);
        source->length(1);source->read_base(0xfffe);source->cd(2,enable);source->ad(13,0x60);
        const auto play=source->cpu.ticks,high=play+(sample_period+65535)/65536,low=play+(sample_period*2+65535)/65536;
        source->at(high);auto dest=fork(*source);
        for(auto* m:{source.get(),dest.get()}) {
            auto& a=m->bus.adpcm;require(a.samples==1 && a.nibble && a.last_nibble==6 && a.decoder_output==2074 &&
                a.decoder_index==6 && a.length==1 && !a.end_irq && a.half_irq && m->bus.cd.irq2()==(enable==4),"high-nibble/IRQ cut differs");
            const auto status=a.read(12);require(status==8 && !a.end_irq && a.half_irq,"status read acknowledged HALF");
            m->at(low-1);require(a.samples==1 && a.length==1 && !a.end_irq,"low-nibble edge occurred early");m->at(low);
            require(a.samples==2 && !a.nibble && a.last_nibble==1 && a.decoder_output==2084 && a.decoder_index==5 &&
                !a.length && !a.playing && a.end_irq && a.half_irq && m->bus.cd.irq2(),"low-nibble END/IRQ result differs");
            m->cd(2,0);require(!m->bus.cd.irq2() && a.end_irq && a.half_irq,"source disable acknowledged flags");
            m->cd(2,enable);require(m->bus.cd.irq2(),"source reenable lost pending IRQ");
            m->ad(13,128);require(!m->bus.cd.irq2() && !a.end_irq && !a.half_irq && a.ram[0xfffe]==pattern(0,0),"reset IRQ/RAM contract differs");
        }
        require(dest->media->requests.empty(),"playback restore requested media");same(*source,*dest);
    }
}
}
int main() {try {
    beats();waiting();collision();resets();length_wrap();sector_boundary();playback_irq();
    std::cout<<checks<<" authored CD/ADPCM DMA checkpoint expectations across "<<cases
             <<" direct-device cases; zero guest instructions; IRQ line only\n";return 0;
}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}}
