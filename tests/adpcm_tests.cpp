#include "pce/adpcm.hpp"
#include "pce/runtime.hpp"
#include <algorithm>
#include <iostream>
#include <limits>
#include <tuple>

static void require(bool value,const char* why){if(!value)throw std::runtime_error(why);}
static pce::Adpcm fresh(){pce::Adpcm a;a.enabled=true;return a;}
// Literal, independently tabulated next-slot latencies for all 36 phases.
static constexpr unsigned read_delay[]={27,26,25,24,23,22,21,20,19,18,17,16,15,14,13,12,11,10,9,8,7,6,5,4,3,2,1,1,1,1,1,1,1,1,1,28};
static constexpr unsigned write_delay[]={9,8,7,6,5,4,3,2,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,19,18,17,16,15,14,13,12,11,10};

static unsigned ports(){
    unsigned checks=0;
    for(unsigned phase=0;phase<36;++phase)for(unsigned value=0;value<256;++value){
        auto a=fresh();a.advance_to(phase);a.write_address=0xFFFF;
        a.write(10,value);const auto end=phase+write_delay[phase];
        require(a.read(12)==4 && a.write_deadline==end && !a.ram[0xFFFF],"ADPCM delayed write busy/deadline expectation");
        a.advance_to(end-1);require(a.read(12)==4 && !a.ram[0xFFFF],"ADPCM RAM write completed before slot");
        a.advance_to(end);require(a.ram[0xFFFF]==value && !a.write_deadline && a.write_address==0 && a.length==1 && a.half_irq && a.end_irq,
                "ADPCM delayed write data/address wrap/length/IRQ expectation");++checks;
        a=fresh();a.advance_to(phase);a.read_latch=value^0xA5;a.read_address=0xFFFF;a.length=1;a.ram[0xFFFF]=value;
        require(a.read(10)==(value^0xA5) && a.read_deadline==phase+read_delay[phase] && a.read(12)==128,"ADPCM read did not return old latch and set busy");
        a.advance_to(phase+read_delay[phase]-1);require(a.read_latch==(value^0xA5) && a.length==1,"ADPCM read completed before slot");
        a.advance_to(phase+read_delay[phase]);require(a.read_latch==value && a.read_address==0 && !a.read_deadline && !a.length && a.half_irq && !a.end_irq,
                "ADPCM read data/address wrap/length/half expectation");
        a.read(10);a.advance_to(a.read_deadline);require(a.end_irq && !a.half_irq,"ADPCM empty read did not latch end and clear half");++checks;
    }
    for(unsigned old=0;old<16;++old)for(unsigned next=0;next<32;++next)for(unsigned address:{0U,1U,0x8000U,0xFFFFU}){
        auto a=fresh();a.control=old;a.address=address;a.read_address=0x1234;a.write_address=0x5678;a.length=0x9999;
        a.write(13,next);
        const unsigned expected_read=(next&8)&&!(old&8)?(address-((next&4)?0:1))&65535:0x1234;
        const unsigned expected_write=(next&2)&&!(old&2)?(address-((next&1)?0:1))&65535:0x5678;
        require(a.read_address==expected_read && a.write_address==expected_write && a.control==next && a.length==((next&16)?address:0x9999),
                "ADPCM control rising-edge address latch/length hold expectation");++checks;
    }
    for(unsigned value=0;value<256;++value){
        auto a=fresh();a.write(8,value);a.write(9,value^0xA5);a.write(14,value);
        require(a.address==value+256*(value^0xA5) && a.read(14)==value && a.read(9)==0 && a.sample_period()==
                (21477273ULL*65536*(16-(value&15))+16050)/32100,"ADPCM address/rate widths or selected reference clock");
        a.write(12,value);require(a.read(12)==0,"read-only ADPCM status write changed state");++checks;
    }
    return checks;
}

static unsigned playback(){
    unsigned checks=0;
    for(unsigned rate=0;rate<16;++rate)for(unsigned count:{1U,2U,3U,17U}){
        auto a=fresh();a.ram[0xFFFF]=0xA3;a.ram[0]=0x5C;a.read_address=0xFFFF;a.length=count;a.write(14,rate);a.write(13,0x60);
        const auto period=a.sample_period();const auto first=(period+65535)/65536;
        a.advance_to(first-1);require(!a.playing && a.play_pending && !a.samples,"ADPCM playback began before sample edge");
        a.advance_to(first);require(a.playing && !a.play_pending && a.samples==1 && a.nibble && a.last_nibble==10 && a.read_address==0xFFFF && a.length==count,
                "ADPCM playback first high nibble/pending transition");
        const auto last=(period*(2*count)+65535)/65536;a.advance_to(last);
        require(a.samples==2*count && !a.nibble && a.length==0 && a.read_address==((0xFFFF+count)&65535) && a.end_irq && a.half_irq && !a.playing,
                "ADPCM finite playback consumption/wrap/end/half/stop expectation");++checks;
    }
    auto a=fresh();a.ram[12]=0x6F;a.length=0;a.read_address=12;a.write(13,32);a.advance_to((a.sample_period()*2+65535)/65536);
    require(a.playing && a.samples==2 && a.length==0x1FFFF && a.last_nibble==15 && a.read_address==13,"ADPCM non-auto-stop zero length did not wrap 17 bits");++checks;
    auto whole=fresh(),parts=fresh();whole.length=parts.length=50;whole.write(13,0x60);parts.write(13,0x60);
    whole.advance_to(40000);for(unsigned t=1;t<40000;t+=37)parts.advance_to(t);parts.advance_to(40000);
    require(std::tuple{whole.samples,whole.sample_phase,whole.read_address,whole.length,whole.playing,whole.nibble}==
            std::tuple{parts.samples,parts.sample_phase,parts.read_address,parts.length,parts.playing,parts.nibble},"ADPCM playback clock partition changed state");++checks;
    a=fresh();a.ram[17]=0xA5;a.write(10,0xCC);a.read(10);a.length=0x1234;a.read_address=1;a.write_address=2;a.address=3;a.half_irq=a.end_irq=true;
    a.write(13,128);require(a.read(12)==0 && !a.read_deadline && !a.write_deadline && !a.address && !a.read_address && !a.write_address && !a.length && a.ram[17]==0xA5,
                "ADPCM soft reset did not cancel transactions/reset addresses/IRQ while retaining RAM");++checks;
    return checks;
}

static void authored_data(pce::CdControl& cd,unsigned size){
    cd=pce::CdControl{};
    cd.enabled=true;cd.scsi.enabled=true;cd.scsi.phase=4;cd.scsi.signals=0xC8;
    cd.scsi.response_size=size;cd.scsi.response_index=1;
    for(unsigned n=0;n<size;++n)cd.scsi.response[n]=static_cast<std::uint8_t>(n*37+19);
    cd.scsi.data=cd.scsi.response[0];
}
static unsigned dma(){
    unsigned checks=0;
    for(unsigned mode:{1U,2U,3U}){
        auto a=fresh();pce::CdControl cd;authored_data(cd,4);a.write_address=0xFFFE;
        a.write(11,mode,&cd);a.advance_to(10000,&cd);
        const auto count=4U;
        require(a.dma_bytes==count && a.write_address==((0xFFFE + count)&65535) && a.length==count && cd.data_bytes_acked==count,
                "ADPCM DMA bytes/address/length/transport ACK expectation");
        for(unsigned n=0;n<count;++n)require(a.ram[(0xFFFE + n)&65535]==static_cast<std::uint8_t>(n*37+19),"ADPCM DMA RAM payload differs from authored response");
        require((a.dma&1)==0 && (a.dma&2)==(mode&2),"ADPCM DMA completion must clear bit zero and retain bit one");++checks;
    }
    auto a=fresh();pce::CdControl cd;cd.enabled=cd.scsi.enabled=true;
    a.write(11,0xFD,&cd);require(a.read(11)==0xFC,"ADPCM one-shot DMA armed without buffered data");++checks;
    a=fresh();authored_data(cd,4);a.write(11,2,&cd);a.advance_to(10,&cd);a.write(11,0,&cd);
    a.advance_to(100,&cd);require(!a.dma_bytes && a.dma_deadline==126,"ADPCM disabled DMA did not preserve paused delay");
    a.write(11,2,&cd);a.advance_to(125,&cd);require(!a.dma_bytes,"ADPCM resumed DMA completed before remaining delay");
    a.advance_to(126,&cd);require(a.dma_bytes==1,"ADPCM resumed DMA did not complete after remaining delay");++checks;
    for(unsigned mode:{1U,2U,3U}){
        auto whole=fresh(),parts=fresh();pce::CdControl whole_cd,parts_cd;authored_data(whole_cd,2048);authored_data(parts_cd,2048);
        whole.write_address=parts.write_address=0xFC00;whole.write(11,mode,&whole_cd);parts.write(11,mode,&parts_cd);
        whole.advance_to(200000,&whole_cd);
        for(unsigned t=13;t<200000;t+=13)parts.advance_to(t,&parts_cd);parts.advance_to(200000,&parts_cd);
        require(whole.dma_bytes==2048 && parts.dma_bytes==2048 && whole_cd.data_bytes_acked==2048 && parts_cd.data_bytes_acked==2048 &&
                whole.length==2048 && whole.write_address==0x400 && !whole.write_deadline && !whole.dma_deadline,
                "full-sector ADPCM DMA did not drain exactly 2048 bytes through ACK and wrap RAM");
        for(unsigned n=0;n<2048;++n)require(whole.ram[(0xFC00+n)&65535]==static_cast<std::uint8_t>(n*37+19),"full-sector ADPCM DMA authored payload mismatch");
        require(whole.ram==parts.ram && std::tuple{whole.master_ticks,whole.dma,whole.length,whole.read_deadline,whole.write_deadline,whole.dma_deadline}==
                std::tuple{parts.master_ticks,parts.dma,parts.length,parts.read_deadline,parts.write_deadline,parts.dma_deadline} &&
                std::tuple{whole_cd.scsi.phase,whole_cd.scsi.signals,whole_cd.scsi.response_index,whole_cd.scsi.deadline,whole_cd.scsi.auto_ack_deadline}==
                std::tuple{parts_cd.scsi.phase,parts_cd.scsi.signals,parts_cd.scsi.response_index,parts_cd.scsi.deadline,parts_cd.scsi.auto_ack_deadline},
                "ADPCM/CD DMA partitioning changed payload, handshake, flags or pending events");++checks;
    }
    a=fresh();authored_data(cd,4);a.write_deadline=100;a.write_latch=0x55;a.write(11,2,&cd);
    a.advance_to(99,&cd);require(!a.dma_bytes && !cd.data_bytes_acked && a.write_deadline==100,"ADPCM DMA consumed a response while CPU write latch remained busy");
    a.advance_to(100,&cd);require(a.ram[0]==0x55 && a.dma_bytes==1 && cd.data_bytes_acked==1 && a.write_latch==19 && a.write_deadline==117,
                "ADPCM DMA did not retry after pending CPU write committed");
    a.advance_to(116,&cd);require(a.ram[1]==0 && cd.ack,"DMA write committed before its slot or cleared ACK early");
    a.advance_to(117,&cd);require(a.ram[1]==19 && a.write_address==2,"delayed DMA RAM commit data/address expectation");
    a.advance_to(121,&cd);require(!cd.ack && cd.scsi.response_index==2,"DMA auto-ACK did not release at 21 master ticks and preload next response");++checks;
    a=fresh();bool fault=false;try{a.write(11,2);}catch(const pce::Fault&){fault=true;}require(fault,"ADPCM DMA without a source silently succeeded");++checks;
    return checks;
}

static unsigned bus_checks(){
    unsigned checks=0;pce::Bus b;b.enable_cd_transport();b.adpcm.enabled=true;pce::Cpu s;
    require(b.read(s,0x180C)==0,"idle ADPCM status was fabricated busy/playing");
    for(unsigned value=0;value<256;++value){
        b.write(s,0x1808,value);b.write(s,0x1809,value^0xA5);b.write(s,0x180E,value);
        require(b.adpcm.address==value+256*(value^0xA5) && b.read(s,0x180E)==value,"CD routing did not preserve ADPCM address/rate");++checks;
    }
    b.write(s,0x180A,0xA6);require(b.read(s,0x180C)==4,"ADPCM routed write did not set busy");
    s.ticks=9;b.sync(s);require(b.adpcm.ram[0]==0xA6 && b.read(s,0x180C)==1 && b.cd.interrupt_active==12,"ADPCM shared clock did not commit RAM and CD IRQ flags");++checks;
    return checks;
}
int main(){try{const auto p=ports(),a=playback(),d=dma(),b=bus_checks();
    std::cout<<p<<" independent ADPCM port/slot/control groups, "<<a<<" playback/length groups, "<<d<<" DMA groups and "<<b<<" bus groups passed; no PCM synthesis\n";return 0;
}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}}
