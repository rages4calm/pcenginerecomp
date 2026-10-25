#include "pce/runtime.hpp"
#include <array>
#include <iostream>
#include <stdexcept>

namespace {
std::uint64_t checks=0;
void require(bool value,const char* message) {++checks;if(!value)throw std::runtime_error(message);}
void reg(pce::Vdc& v,unsigned index,unsigned value) {
    v.write(0,static_cast<std::uint8_t>(index));
    v.write(2,static_cast<std::uint8_t>(value));
    v.write(3,static_cast<std::uint8_t>(value>>8));
}
void phase(pce::Vdc& v) {
    v.enabled=true;v.enable_raster();v.raster.h_state=0;v.raster.v_state=0;
    v.raster.hclock=0;v.raster.h_remaining=100000;
}
void delay_and_buffer() {
    constexpr unsigned reads[]={24,24,15,15},writes[]={21,18,12,12};
    for(unsigned mode=0;mode<4;++mode) {
        pce::Vdc v;phase(v);v.raster.control=static_cast<std::uint8_t>(mode);
        (*v.vram)[0x345]=0xD29E;(*v.vram)[0x346]=0x73A1;
        v.read_buffer=0x1267;reg(v,1,0x345);
        require(v.pending_vram_read && v.vram_transfer_delay==int(reads[mode]) &&
                v.reg[1]==0x345 && v.read_buffer==0x1267,"prefetch queues without early buffer/address publication");
        require(v.read(0)==0x40 && v.read(0)==0x40 && v.status==0x40,
                "status acknowledges events but retains live BUSY");
        require(v.vram_wait_required(2,false) && v.vram_wait_required(3,false) &&
                !v.vram_wait_required(0,false),"read wait predicate applies only to pending-read data ports");
        const auto before=v.reads;
        try {v.read(2);throw std::runtime_error("unsafely read pending buffer");}
        catch(const pce::Fault&){}
        require(v.reads==before && v.read_buffer==0x1267,"unsafe direct read refuses without side effects");
        v.process_cpu_vram_accesses(reads[mode]-1);
        require(v.pending_vram_read && v.vram_cpu_cycles==2 && v.read_buffer==0x1267,
                "request preserves fractional three-tick carry");
        v.process_cpu_vram_accesses(1);
        require(!v.has_pending_vram() && v.vram_cpu_cycles==0 && v.reg[1]==0x346 &&
                v.read_buffer==0xD29E && v.vram_bus_latch==0xD29E && v.status==0,
                "delay boundary completes original read and clears BUSY/carry");
        v.write(0,2);
        require(v.read(2)==0x9E && !v.has_pending_vram(),"low byte is buffered without requesting another word");
        require(v.read(3)==0xD2 && v.pending_vram_read && v.read_buffer==0xD29E && v.reg[1]==0x346,
                "high byte returns old word then queues next prefetch");
        v.process_cpu_vram_accesses(reads[mode]);
        require(v.read_buffer==0x73A1 && v.reg[1]==0x347,"later prefetch uses next live address");
        reg(v,0,0x456);reg(v,2,0xAB5C);
        require(v.pending_vram_write && v.vram_transfer_delay==int(writes[mode]) &&
                (*v.vram)[0x456]==0 && v.reg[0]==0x456,"word write remains queued until its delay");
        v.process_cpu_vram_accesses(writes[mode]-1);
        require(v.pending_vram_write && (*v.vram)[0x456]==0,"write is not published before final delay tick");
        v.process_cpu_vram_accesses(1);
        require(!v.has_pending_vram() && (*v.vram)[0x456]==0xAB5C && v.reg[0]==0x457 &&
                v.vram_bus_latch==0x73A1,"completed write increments but does not drive read bus");
    }
}
void live_order_and_predicates() {
    pce::Vdc v;phase(v);v.reg[0]=4;v.reg[1]=9;(*v.vram)[9]=0xCA7E;
    v.read_buffer=0x1234;reg(v,2,0xA519);
    for(unsigned selected=0;selected<32;++selected) {
        v.write(0,static_cast<std::uint8_t>(selected));
        require(v.vram_wait_required(2,true)==(selected<=2) &&
                v.vram_wait_required(3,true)==(selected<=2) &&
                !v.vram_wait_required(0,true),"only MAWR/MARR/VWR data writes wait for an outstanding transfer");
        require(!v.vram_wait_required(2,false),"pending writes do not block read-buffer access");
    }
    v.write(0,2);require(v.read(3)==0x12 && v.pending_vram_read && v.pending_vram_write,
                         "read may queue behind an outstanding write");
    reg(v,5,1u<<11); // Live increment is sampled when the transfer completes.
    v.process_cpu_vram_accesses(24);
    require(!v.pending_vram_read && v.pending_vram_write && v.read_buffer==0xCA7E &&
            v.reg[1]==41 && (*v.vram)[4]==0 && v.status==0x40,
            "shared delay grants the pending read before the older write using live increment");
    v.process_cpu_vram_accesses(3);
    require(!v.has_pending_vram() && (*v.vram)[4]==0xA519 && v.reg[0]==36 &&
            v.vram_bus_latch==0xCA7E,"later free group grants write and retains read bus");
    reg(v,0,0xFFFF);reg(v,2,0xFFFF);v.process_cpu_vram_accesses(21);
    require(v.reg[0]==31 && v.vram_bus_latch==0xCA7E,"undriven queued write still advances live increment with wrap");
    pce::Vdc immediate;immediate.enabled=true;(*immediate.vram)[3]=0x4A83;reg(immediate,1,3);
    require(immediate.read_buffer==0x4A83 && !immediate.has_pending_vram(),"untimed functional profile stays synchronous");
    phase(immediate);immediate.queued_cpu_accesses=false;reg(immediate,1,3);
    require(immediate.read_buffer==0x4A83 && !immediate.has_pending_vram(),"explicit immediate reference profile stays synchronous");
}
void slots() {
    for(unsigned divider:{2u,3u,4u})for(unsigned clock=0;clock<1365;++clock) {
        pce::Vdc v;phase(v);v.raster.divider=divider;v.raster.hclock=clock;
        require(v.cpu_vram_slot_available()==(((clock/divider)&1)==0),"blanking exposes even-dot slots");
        for(unsigned mode=0;mode<4;++mode) {
            v.raster.v_state=1;v.raster.vdc_line=100;v.sprite_control=128;v.sprite_mode=static_cast<std::uint16_t>(mode);
            v.load_bg_start_clock=80;v.load_bg_end_clock=800;
            bool expected=((clock/divider)&1)==0;
            if(clock>=80 && clock<800) {
                const int dot=int((clock-80)/divider)-1;
                expected=dot>=0 && (mode==0 ? (dot&1)==0:
                    mode<3 ? (dot&7)==2 || (dot&7)==3:false);
            }
            require(v.cpu_vram_slot_available()==expected,"latched background width selects the available dot slots");
        }
        v.raster.v_state=0;v.raster.h_state=3;v.hsync_start_clock=0;
        const auto future=(clock+3)%1365;
        require(v.cpu_vram_slot_available()==(((clock/divider)&1)==0 && future>=8*divider),
                "HSW withholds first eight dot clocks including elapsed-group lookahead");
        v.satb_pending=1;require(!v.cpu_vram_slot_available(),"SATB DMA excludes CPU queue");
        v.satb_pending=0;v.vram_dma_pending=1;
        require(!v.cpu_vram_slot_available(),"VRAM DMA excludes CPU queue");
    }
    for(unsigned mode=0;mode<4;++mode)for(unsigned count:{1u,8u,16u})for(unsigned clock=0;clock<1365;++clock) {
        pce::Vdc v;phase(v);v.raster.divider=3;v.raster.v_state=1;v.raster.vdc_line=100;
        v.raster.hclock=clock;v.sprite_control=64;v.sprite_count=count;
        v.sprite_mode=static_cast<std::uint16_t>(mode<<2);v.load_bg_start_clock=1365;v.load_bg_end_clock=0;
        constexpr unsigned dots[]={4,4,8,16};
        const auto elapsed=clock ? clock:1365;
        const bool expected=elapsed/3>=count*dots[mode] && ((clock/3)&1)==0;
        require(v.cpu_vram_slot_available()==expected,"sprite width and admitted cell count reserve their fetch span");
    }
}
void clock_and_dma() {
    pce::Vdc v;phase(v);v.raster.divider=3;v.raster.control=1;v.dma_enabled=true;
    v.satb_pending=4;v.reg[19]=0;(*v.vram)[255]=0xC75A;v.reg[15]=1;
    v.reg[0]=1;reg(v,2,0x942B);v.vram_transfer_delay=0;
    v.advance(12);
    require(v.satb_pending==0 && v.satb[255]==0xC75A && v.pending_vram_write &&
            (*v.vram)[1]==0 && v.raster.master_ticks==12,"CPU is blocked through final SATB dot, queue is serviced before raster");
    v.advance(3);
    require(!v.has_pending_vram() && (*v.vram)[1]==0x942B && v.raster.master_ticks==15 &&
            v.vram_bus_latch==0xC75A,"next CPU group follows completed DMA without altering its held data");
    pce::Vdc a,b;phase(a);phase(b);a.reg[1]=b.reg[1]=7;
    (*a.vram)[7]=(*b.vram)[7]=0xD038;a.write(0,1);b.write(0,1);a.write(3,0);b.write(3,0);
    a.advance(41);for(unsigned n:{1u,2u,4u,5u,3u,8u,9u,9u})b.advance(n);
    require(a.read_buffer==b.read_buffer && a.reg[1]==b.reg[1] &&
            a.pending_vram_read==b.pending_vram_read && a.raster.master_ticks==b.raster.master_ticks,
            "eventual queue result is stable under mixed host clock chunk sizes");
}
void bus_waits() {
    for(unsigned speed:{3u,12u}) {
        pce::Bus b;b.enable_video_timing();b.enable_interrupts();
        auto& v=b.vdc;v.raster.h_state=0;v.raster.v_state=0;v.raster.h_remaining=100000;
        pce::Cpu c;c.clock_divisor=speed;c.p=0;c.cycles=7;c.native_steps=2;c.interpreter_steps=3;
        v.reg[0]=4;v.reg[1]=9;(*v.vram)[9]=0xCA7E;reg(v,2,0xA519);
        b.wait_vdc(c,2,false);
        require(c.ticks==0 && c.vdc_wait_ticks==0 && v.pending_vram_write,
                "read entry with a pending write alone does not stall");
        v.write(0,2);v.read(3); // Enter with both requests: read completes first.
        b.irq.timer_enabled=true;b.irq.timer_reload=0;b.irq.timer_counter=0;b.irq.timer_deadline=9;
        b.wait_vdc(c,2,false);
        require(c.ticks==30 && c.vdc_wait_ticks==30 && !v.has_pending_vram() &&
                v.read_buffer==0xCA7E && (*v.vram)[4]==0xA519,
                "read-triggered wait drains both requests at fast three-tick cadence");
        require(c.cycles==7 && c.native_steps==2 && c.interpreter_steps==3 && !c.irq_entries,
                "VRAM wait adds elapsed ticks without logical cycles or instruction retirement");
        require(b.irq.timer_pending && b.irq.timer_deadline==3081 && b.irq.master_ticks==30 &&
                c.irq_sampled==4 && v.raster.master_ticks==30,
                "stalls advance timer and raster and sample IRQ without prematurely entering it");
    }
    for(unsigned speed:{3u,12u}) {
        pce::Bus b;b.enable_video_timing();auto& v=b.vdc;
        v.raster.h_state=0;v.raster.v_state=0;v.raster.h_remaining=100000;
        pce::Cpu c;c.clock_divisor=speed;
        reg(v,2,0x725A);v.vram_transfer_delay=3;
        require(b.read(c,0)==0 && c.ticks==speed && c.cycles==1 && c.vdc_wait_ticks==0 &&
                (*v.vram)[0]==0x725A,"mapped status read clocks its fixed cycle before observing BUSY");
    }
    for(unsigned speed:{3u,12u}) {
        pce::Bus b;b.enable_video_timing();auto& v=b.vdc;
        v.raster.h_state=0;v.raster.v_state=0;v.raster.h_remaining=100000;v.selected=2;
        pce::Cpu c;c.clock_divisor=speed;
        b.write(c,3,0x72);
        require(c.ticks==speed && c.cycles==1 && c.vdc_wait_ticks==0 && v.pending_vram_write &&
                v.vram_transfer_delay==21-int(speed),"mapped write queues before its fixed access cycle");
    }
    for(unsigned speed:{3u,12u}) {
        pce::Bus b;b.enable_video_timing();auto& v=b.vdc;
        v.raster.h_state=0;v.raster.v_state=0;v.raster.h_remaining=100000;v.selected=2;
        pce::Cpu c;c.clock_divisor=speed;
        const auto remaining=b.write_vdc(c,3,0x72);
        require(remaining==2 && c.cycles==3 && c.ticks==3*speed && c.vdc_wait_ticks==0 &&
                v.pending_vram_write && v.vram_transfer_delay==21-int(speed),
                "ST clocks two cycles before queuing and one after, leaving two base retirement cycles");
    }
    for(unsigned speed:{3u,12u}) {
        pce::Bus b;b.enable_video_timing();auto& v=b.vdc;
        v.raster.h_state=0;v.raster.v_state=0;v.raster.h_remaining=100000;
        pce::Cpu c;c.clock_divisor=speed;
        reg(v,2,0x38BC);v.vram_transfer_delay=3;
        require(b.read_block(c,0)==0 && c.cycles==2 && c.ticks==2*speed && c.vdc_wait_ticks==0,
                "block status read clocks both fixed access cycles before observing BUSY");
    }
}
void inspection_and_faults() {
    pce::Vdc v;phase(v);v.reg[5]=128;v.reg[0]=4;reg(v,2,0xCA7E);
    v.read_buffer=0x7138;v.vram_bus_latch=0xA284;
    pce::Vce palette;palette.enabled=true;
    const auto reads=v.reads,writes=v.writes;
    const auto frame=pce::render_snapshot(v,palette);
    require(frame.rgb.size()==8*3 && v.peek_vram(0x8000)==0xA284 &&
            v.pending_vram_write && !v.pending_vram_read && v.vram_transfer_delay==21 &&
            v.vram_cpu_cycles==0 && v.reg[0]==4 && v.read_buffer==0x7138 &&
            v.vram_bus_latch==0xA284 && v.reads==reads && v.writes==writes &&
            v.raster.master_ticks==0,"snapshot and retained-bus inspection do not settle or advance queued transfers");
    pce::Bus b;b.enable_video_timing();reg(b.vdc,2,0x29A6);
    // A malformed synthetic state deliberately disables the DMA engine while
    // retaining a DMA claim. Production must report starvation, never settle it.
    b.vdc.vram_dma_pending=1;
    pce::Cpu c;
    bool rejected=false;
    try {b.wait_vdc(c,2,true);}catch(const pce::Fault&){rejected=true;}
    constexpr auto maximum=8ULL*1365*263;
    require(rejected && c.ticks==maximum && c.vdc_wait_ticks==maximum && c.cycles==0 &&
            b.vdc.pending_vram_write && b.vdc.vram_dma_pending==1 && (*b.vdc.vram)[0]==0,
            "unserviceable DMA claim stops within bounded guest time without fabricating a write");
}
}
int main(){try{delay_and_buffer();live_order_and_predicates();slots();clock_and_dma();bus_waits();inspection_and_faults();
    std::cout<<checks<<" authored queued-VRAM delay, arbitration, BUSY, buffering and DMA checks passed\n";
}catch(const std::exception& e){std::cerr<<"queued VRAM check "<<checks<<": "<<e.what()<<'\n';return 1;}}
