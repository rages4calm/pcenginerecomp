#include "pce/checkpoint.hpp"
#include "pce/checkpoint_archive.hpp"
#include "pce/checkpoint_audio.hpp"
#include <algorithm>
#include <type_traits>

namespace pce {
struct CheckpointAccess {
    template<class A,class T> static void video(A& ar,T& v) {
        ar(v.enabled);
        frame(ar,v.front_);frame(ar,v.back_);
        ar(v.indices_,v.sequence_,v.completed_ticks_,v.lines_rendered_,v.pixels_rendered_,
           v.x_,v.row_,v.line_width_,v.scroll_x_,v.scroll_y_,v.counter_y_,v.control_,v.mode_,
           v.y_pending_,v.increment_,v.burst_,v.active_,v.latch_x_clock_,v.latch_y_clock_,
           v.byr_lsb_write_clock_,v.bxr_written_before_latch_);
    }
    template<class A,class T> static void frame(A& ar,T& f) {
        ar(f.width,f.height);ar.vector(f.rgb,1024u*512u*3u);
    }
    static void validate_video(const VideoOutput& v,std::uint64_t ticks) {
        const auto frame=[](const VideoFrame& f) {
            if(f.width>1024 || f.height>512 || ((f.width==0)!=(f.height==0)) ||
               f.rgb.size()!=std::size_t(f.width)*f.height*3) throw Fault("checkpoint invalid video frame geometry");
        };
        frame(v.front_);frame(v.back_);
        if(v.line_width_>1024 || v.x_>v.line_width_ || v.row_>1024 || v.completed_ticks_>ticks ||
           (v.enabled && (!v.back_.width || !v.back_.height)) ||
           (v.active_ && (!v.enabled || v.row_>=v.back_.height)) ||
           v.latch_x_clock_<-1 || v.latch_x_clock_>=1365 ||
           v.latch_y_clock_<-1 || v.latch_y_clock_>=1365 ||
           v.byr_lsb_write_clock_<-1 || v.byr_lsb_write_clock_>=1365 ||
           std::any_of(v.indices_.begin(),v.indices_.end(),[](auto x){return x>=512;}))
            throw Fault("checkpoint invalid video latch state");
    }
};
namespace {
constexpr std::array<std::uint8_t,8> magic={'P','C','E','C','O','R','E',0};
constexpr std::uint32_t schema=1;
template<class A,class T> void cpu_state(A& ar,T& c) {
    ar(c.a,c.x,c.y,c.sp,c.p,c.pc,c.mpr,c.mpr_latch,c.ticks,c.cycles,c.native_steps,
       c.interpreter_steps,c.guard_misses,c.vdc_wait_ticks,c.native_block_steps,
       c.interpreter_block_steps,c.block_bytes,c.clock_divisor,c.irq_sampled,c.irq_vector,
       c.irq_entries,c.rti_steps);
}
template<class A,class T> void raster_state(A& ar,T& r) {
    ar(r.enabled,r.hsync,r.vsync,r.compare_pending,r.blank_consumed,r.control,
       r.master_ticks,r.frames,r.vblank_events,r.rcr_events,r.hclock,r.line,r.dot,
       r.vdc_line,r.raster_line,r.divider,r.total_lines,r.h_state,r.v_state,r.h_remaining,
       r.v_remaining,r.event_remaining,r.event,r.horizontal,r.vertical);
}
template<class A,class T> void vdc_state(A& ar,T& v) {
    ar(v.enabled,v.irq1,v.selected,v.status,v.reg,*v.vram,v.read_buffer,v.vram_bus_latch,
       v.queued_cpu_accesses,v.pending_vram_read,v.pending_vram_write,v.vram_transfer_delay,
       v.vram_cpu_cycles,v.load_bg_start_clock,v.load_bg_end_clock,v.hsync_start_clock,
       v.reads,v.writes,v.vram_changes);
    raster_state(ar,v.raster);CheckpointAccess::video(ar,v.video);
    ar(v.satb);
    for(auto& row:v.sprite_rows) ar(row.x,row.index,row.flip,row.palette,row.front,row.planes);
    ar(v.sprite_count,v.sprite_overflow,v.sprite_burst,v.sprite_active,v.sprite_control,
       v.sprite_mode,v.dma_enabled,v.satb_armed,v.satb_pending,v.vram_dma_pending,
       v.dma_source,v.dma_dest,v.dma_words,v.satb_words);
}
template<class A,class T> void joypad_state(A& ar,T& j) {
    ar(j.enabled,j.japanese,j.cd,j.multitap,j.sel,j.clr,j.extra,j.selected,j.latched);
    for(auto& p:j.pads) ar(p.buttons,p.pressed);
    ar(j.reads,j.writes);
}
template<class A,class T> void interrupt_state(A& ar,T& i) {
    ar(i.enabled,i.timer_enabled,i.timer_pending,i.mask,i.external,i.timer_reload,
       i.timer_counter,i.timer_frozen_phase,i.master_ticks,i.timer_deadline,i.entries,i.reads,i.writes);
}
template<class A,class T> void arcade_state(A& ar,T& card) {
    for(auto& p:card.ports) ar(p.base,p.offset,p.increment,p.control);
    ar(*card.ram,card.shift_register,card.shift_amount,card.rotate_amount,card.reads,card.writes);
}
template<class A,class E> void enumeration(A& ar,E& e,unsigned maximum) {
    std::uint32_t value=static_cast<std::uint32_t>(e);ar(value);
    if(value>maximum) throw Fault("checkpoint invalid profile enumeration");
    if constexpr(!std::is_const_v<E>) e=static_cast<E>(value);
}
template<class A,class T> void bus_state(A& ar,T& b) {
    for(auto& k:b.kind) enumeration(ar,k,4);
    ar(b.generation,*b.bytes);
    vdc_state(ar,b.vdc);
    ar(b.vce.enabled,b.vce.control,b.vce.address,b.vce.palette,b.vce.reads,b.vce.writes);
    joypad_state(ar,b.joypad);interrupt_state(ar,b.irq);
    ar(b.io_latch,b.work_ram_mirrors);
    enumeration(ar,b.system_card,2);
    ar(b.system_card_powered,b.hucard,b.hucard_powered,b.hucard_rom_bytes,b.hucard_banks);
    enumeration(ar,b.hucard_profile,3);
    ar(b.hucard_mapper_latch);ar.vector(b.hucard_mapper_rom,0x280000);
    bool present=bool(b.arcade_card);ar(present);
    if constexpr(!std::is_const_v<T>) {
        if(present)b.arcade_card=std::make_unique<ArcadeCard>();else b.arcade_card.reset();
    }
    if(present)arcade_state(ar,*b.arcade_card);
}
void require(bool condition,const char* reason) { if(!condition)throw Fault(reason); }
void validate(const Bus& b,const Cpu& c) {
    require(bool(b.bytes) && bool(b.vdc.vram),"checkpoint missing memory backing");
    require(c.clock_divisor==3 || c.clock_divisor==12,"checkpoint invalid CPU speed");
    require(c.irq_sampled<=7 && (c.irq_vector==0 || c.irq_vector==0xfff6 || c.irq_vector==0xfff8 ||
            c.irq_vector==0xfffa),"checkpoint invalid sampled IRQ state");
    for(const auto k:b.kind)require(static_cast<unsigned>(k)<=4,"checkpoint invalid bank kind");
    require(static_cast<unsigned>(b.system_card)<=2 && static_cast<unsigned>(b.hucard_profile)<=3,
            "checkpoint invalid memory profile");
    require(!b.system_card_powered || b.system_card!=SystemCardProfile::none,"checkpoint powered missing System Card");
    require(!b.hucard_powered || b.hucard,"checkpoint powered missing HuCard");
    require(!b.hucard || (b.system_card==SystemCardProfile::none && b.hucard_profile!=HuCardProfile::none),
            "checkpoint incompatible memory profiles");
    if(b.hucard) {
        validate_hucard_size(b.hucard_rom_bytes,b.hucard_profile);
        require(b.hucard_banks==hucard_bank_map(b.hucard_rom_bytes,b.hucard_profile),"checkpoint invalid HuCard bank aliases");
    } else require(b.hucard_profile==HuCardProfile::none && !b.hucard_rom_bytes,"checkpoint invalid absent HuCard");
    if(b.hucard_profile==HuCardProfile::sf2) {
        require(b.hucard_mapper_latch<16 && b.hucard_mapper_rom.size()==0x280000,"checkpoint invalid SF2 mapper");
        require(std::equal(b.bytes->begin(),b.bytes->begin()+0x80000,b.hucard_mapper_rom.begin()),"checkpoint SF2 fixed ROM mismatch");
        require(std::equal(b.bytes->begin()+0x80000,b.bytes->begin()+0x100000,
                b.hucard_mapper_rom.begin()+0x80000+(b.hucard_mapper_latch&3)*0x80000),"checkpoint SF2 window mismatch");
    } else require(!b.hucard_mapper_latch && b.hucard_mapper_rom.empty(),"checkpoint unexpected mapper ROM");
    if(b.arcade_card) {
        require(b.system_card==SystemCardProfile::super && bool(b.arcade_card->ram),"checkpoint invalid Arcade Card profile");
        require(b.arcade_card->shift_amount<16 && b.arcade_card->rotate_amount<16,"checkpoint invalid Arcade Card shifter");
        for(const auto& port:b.arcade_card->ports)require(port.base<0x1000000 && port.control<128,"checkpoint invalid Arcade Card port");
    }
    const auto& v=b.vdc;const auto& r=v.raster;
    require(v.selected<32 && v.status<128 && v.sprite_count<=16,"checkpoint invalid VDC state");
    require(v.vram_transfer_delay>=0 && v.vram_transfer_delay<=24 && v.vram_cpu_cycles<3 &&
            v.satb_pending<=1024 && v.vram_dma_pending<=262144,"checkpoint invalid VDC pending access");
    require(((v.status&64)!=0)==v.has_pending_vram(),"checkpoint inconsistent VDC busy latch");
    require(v.hsync_start_clock<1365 && v.load_bg_start_clock>=-200 && v.load_bg_start_clock<=1365 &&
            v.load_bg_end_clock>=0 && v.load_bg_end_clock<=1365,"checkpoint invalid VDC fetch clocks");
    for(const auto& row:v.sprite_rows)require(row.index<64 && row.palette<=240 && !(row.palette%16) && row.x>=-32 && row.x<=1023,
                                            "checkpoint invalid sprite row");
    require(r.hclock<1365 && r.h_state<4 && r.v_state<4 && r.event<=4 &&
            (r.divider==2 || r.divider==3 || r.divider==4) && (r.total_lines==262 || r.total_lines==263) &&
            r.line<r.total_lines && r.vdc_line<r.total_lines && r.dot<=683 && r.raster_line<=1024,
            "checkpoint invalid raster phase");
    require(r.h_remaining>0 && r.h_remaining<=1024 && r.v_remaining>0 && r.v_remaining<=512 &&
            r.event_remaining>=0 && r.event_remaining<=2048,"checkpoint invalid raster countdown");
    if(r.enabled) {
        require(v.enabled && r.master_ticks==c.ticks,"checkpoint CPU/raster clock mismatch");
        for(auto h:r.horizontal)require(h>=8 && h<=1024 && !(h%8),"checkpoint invalid horizontal timing");
        require(r.vertical[0]>=2 && r.vertical[0]<=257 && r.vertical[1]>=1 && r.vertical[1]<=512 &&
                r.vertical[2]<=255 && r.vertical[3]>=1 && r.vertical[3]<=32,"checkpoint invalid vertical timing");
    }
    require(!v.video.enabled || (r.enabled && b.vce.enabled),"checkpoint incomplete video profile");
    CheckpointAccess::validate_video(v.video,c.ticks);
    require(b.vce.address<512 && std::all_of(b.vce.palette.begin(),b.vce.palette.end(),[](auto x){return x<512;}),
            "checkpoint invalid VCE state");
    require(b.joypad.selected<=5,"checkpoint invalid joypad selected port");
    for(const auto& p:b.joypad.pads)require((p.buttons==2 || p.buttons==6) && p.pressed<=0xfff,"checkpoint invalid joypad state");
    const auto& i=b.irq;
    require(i.mask<8 && i.external<8 && i.timer_reload<128 && i.timer_counter<128 &&
            i.timer_frozen_phase<=3072,"checkpoint invalid interrupt state");
    if(i.enabled)require(i.master_ticks==c.ticks,"checkpoint CPU/timer clock mismatch");
    if(i.timer_enabled)require(i.timer_deadline>i.master_ticks && i.timer_deadline-i.master_ticks<=3072,
                              "checkpoint invalid timer deadline");
    else require(!i.timer_deadline,"checkpoint stopped timer has deadline");
    if(b.pcm.enabled)require(b.pcm.master_ticks==c.ticks,"checkpoint CPU/PCM clock mismatch");
    if(b.adpcm.enabled)require(b.adpcm.master_ticks==c.ticks,"checkpoint CPU/ADPCM clock mismatch");
    if(b.cd.scsi.enabled)require(b.cd.scsi.master_ticks==c.ticks,"checkpoint CPU/CD clock mismatch");
    require(b.cd.audio.sample_clock_ticks<=c.ticks,"checkpoint CD sample clock exceeds CPU clock");
    if(b.cd.audio_enabled || b.pcm.enabled)require(b.cd.audio.sample_clock_ticks==c.ticks,
                                               "checkpoint CPU/CD source sample clock mismatch");
    checkpoint::validate_audio(b);
}
void validate_configuration(const Bus& b,const Bus& configured) {
    require(b.kind==configured.kind && b.work_ram_mirrors==configured.work_ram_mirrors &&
            b.system_card==configured.system_card && b.system_card_powered==configured.system_card_powered &&
            b.hucard==configured.hucard && b.hucard_powered==configured.hucard_powered &&
            b.hucard_rom_bytes==configured.hucard_rom_bytes && b.hucard_profile==configured.hucard_profile &&
            b.hucard_banks==configured.hucard_banks &&
            bool(b.arcade_card)==bool(configured.arcade_card),"checkpoint memory configuration mismatch");
    require(b.vdc.enabled==configured.vdc.enabled && b.vdc.raster.enabled==configured.vdc.raster.enabled &&
            b.vdc.video.enabled==configured.vdc.video.enabled && b.vdc.dma_enabled==configured.vdc.dma_enabled &&
            b.vdc.queued_cpu_accesses==configured.vdc.queued_cpu_accesses && b.vce.enabled==configured.vce.enabled &&
            b.irq.enabled==configured.irq.enabled,"checkpoint device configuration mismatch");
    require(b.joypad.enabled==configured.joypad.enabled && b.joypad.japanese==configured.joypad.japanese &&
            b.joypad.cd==configured.joypad.cd && b.joypad.multitap==configured.joypad.multitap,
            "checkpoint input configuration mismatch");
    for(unsigned n=0;n<5;++n)require(b.joypad.pads[n].buttons==configured.joypad.pads[n].buttons,
                                   "checkpoint controller type mismatch");
    require(b.hucard_mapper_rom==configured.hucard_mapper_rom,"checkpoint immutable mapper ROM mismatch");
    if(b.hucard_profile!=HuCardProfile::sf2)for(unsigned bank=0;bank<256;++bank) {
        if(b.kind[bank]!=BankKind::rom)continue;
        for(unsigned offset=0;offset<8192;++offset) {
            const auto address=bank*8192+offset;
            require((*b.bytes)[b.backing_address(address)]==(*configured.bytes)[configured.backing_address(address)],
                    "checkpoint immutable ROM mismatch");
        }
    }
    checkpoint::validate_audio_configuration(b,configured);
}
}
std::vector<std::uint8_t> encode_checkpoint(const Bus& bus,const Cpu& cpu) {
    validate(bus,cpu);
    checkpoint::Writer writer;
    writer(magic,schema);cpu_state(writer,cpu);bus_state(writer,bus);
    checkpoint::write_audio(writer,bus);
    return std::move(writer.data);
}
std::unique_ptr<MachineCheckpoint> decode_checkpoint(std::span<const std::uint8_t> bytes,const Bus& configured) {
    try {
        checkpoint::Reader reader(bytes);
        std::array<std::uint8_t,8> found{};std::uint32_t version=0;
        reader(found,version);
        require(found==magic && version==schema,"unsupported checkpoint core schema");
        auto result=std::make_unique<MachineCheckpoint>();
        result->bus.cd.provider=configured.cd.provider;
        cpu_state(reader,result->cpu);bus_state(reader,result->bus);
        checkpoint::read_audio(reader,result->bus);reader.finish();
        validate(result->bus,result->cpu);validate_configuration(result->bus,configured);
        return result;
    } catch(const checkpoint::ArchiveError& error) { throw Fault(error.what()); }
}
void restore_checkpoint(Bus& bus,Cpu& cpu,std::span<const std::uint8_t> bytes) {
    static_assert(std::is_nothrow_move_assignable_v<Bus> && std::is_nothrow_move_assignable_v<Cpu>);
    auto decoded=decode_checkpoint(bytes,bus);
    bus=std::move(decoded->bus);cpu=std::move(decoded->cpu);
}
} // namespace pce
