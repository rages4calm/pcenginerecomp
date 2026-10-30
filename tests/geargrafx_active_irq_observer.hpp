#pragma once
// Authored read-only observer around separately built original Gear hardware.
// No reference device body, phase assignment or IRQ injection is included.
#include "geargrafx_core.h"
#include "huc6280.h"
#include "huc6270.h"
#include "huc6260.h"
#include "cdrom.h"
#include "adpcm.h"
#include "scsi_controller.h"
#include "audio.h"
#include <cstdint>
#include <ostream>
#include <stdexcept>
#include <vector>

namespace active_irq_gear {
template<class Tag,typename Tag::type Member>struct Access {
    friend typename Tag::type member(Tag){return Member;}
};
#define ACTIVE_IRQ_FIELD(Tag,Owner,Type,Name) \
    struct Tag{using type=Type Owner::*;friend type member(Tag);}; \
    template struct Access<Tag,&Owner::Name>;
ACTIVE_IRQ_FIELD(Extra,HuC6280,u32,m_extra_master_cycles)
ACTIVE_IRQ_FIELD(Pending,HuC6280,s32,m_irq_pending)
ACTIVE_IRQ_FIELD(Dma,HuC6270,u32,m_vram_transfer_pending)
ACTIVE_IRQ_FIELD(ReadPending,HuC6270,bool,m_pending_memory_read)
ACTIVE_IRQ_FIELD(WritePending,HuC6270,bool,m_pending_memory_write)
ACTIVE_IRQ_FIELD(Delay,HuC6270,s32,m_transfer_delay)
ACTIVE_IRQ_FIELD(Carry,HuC6270,u32,m_cpu_vram_cycles)
ACTIVE_IRQ_FIELD(Latch,HuC6270,u16,m_vram_openbus)
ACTIVE_IRQ_FIELD(Burst,HuC6270,bool,m_burst_mode)
ACTIVE_IRQ_FIELD(Control,HuC6270,u16,m_latched_cr)
ACTIVE_IRQ_FIELD(Mode,HuC6270,u16,m_latched_mwr)
ACTIVE_IRQ_FIELD(Sprites,HuC6270,s32,m_sprite_count)
ACTIVE_IRQ_FIELD(BgStart,HuC6270,s32,m_load_bg_start_clock)
ACTIVE_IRQ_FIELD(BgEnd,HuC6270,s32,m_load_bg_end_clock)
ACTIVE_IRQ_FIELD(Hsync,HuC6270,s32,m_hsync_start_clock)
ACTIVE_IRQ_FIELD(HRemaining,HuC6270,s32,m_clocks_to_next_h_state)
ACTIVE_IRQ_FIELD(Raster,HuC6270,s32,m_raster_line)
ACTIVE_IRQ_FIELD(SatPending,HuC6270,u16,m_sat_transfer_pending)
#undef ACTIVE_IRQ_FIELD
struct ClockTag{using type=bool(GeargrafxCore::*)(u32);friend type member(ClockTag);};
template struct Access<ClockTag,&GeargrafxCore::ClockHardware<true,false,false>>;

struct Kernel {
    unsigned p,mask,irr;int sample;
    unsigned status,dma,read_pending,write_pending,carry;int delay;
    unsigned read_buffer,marr,mawr,bus,divider,burst,latched_cr,latched_mwr;
    int hpos,vpos,hstate,vstate,hremaining,raster,sprite_count,bg_start,bg_end,hsync;
    unsigned sat_pending,cd_enabled,cd_active,signals,half,end,length,write_address,read_address;
    unsigned cr,mwr,rcr,selected;
};
inline Kernel kernel(GeargrafxCore&core) {
    auto*cpu=core.GetHuC6280();auto*c=cpu->GetState();auto*v=core.GetHuC6270_1();
    auto*s=v->GetState();auto*d=core.GetCDROM()->GetState();auto*a=core.GetAdpcm()->GetState();
    return {c->P->GetValue(),*c->IDR,*c->IRR,cpu->*member(Pending{}),*s->SR,
        v->*member(Dma{}),unsigned(v->*member(ReadPending{})),unsigned(v->*member(WritePending{})),
        v->*member(Carry{}),v->*member(Delay{}),*s->READ_BUFFER,s->R[1],s->R[0],v->*member(Latch{}),
        unsigned(core.GetHuC6260()->GetClockDivider()),unsigned(v->*member(Burst{})),
        v->*member(Control{}),v->*member(Mode{}),*core.GetHuC6260()->GetState()->HPOS,*s->VPOS,
        *s->H_STATE,*s->V_STATE,v->*member(HRemaining{}),v->*member(Raster{}),v->*member(Sprites{}),
        v->*member(BgStart{}),v->*member(BgEnd{}),v->*member(Hsync{}),v->*member(SatPending{}),
        *d->ENABLED_IRQS,*d->ACTIVE_IRQS,*core.GetScsiController()->GetState()->SIGNALS,
        unsigned(*a->HALF_IRQ),unsigned(*a->END_IRQ),*a->LENGTH,*a->WRITE_ADDRESS,*a->READ_ADDRESS,
        s->R[5],s->R[9],s->R[6],*s->AR};
}
inline void write_kernel(std::ostream&out,const Kernel&k) {
    out<<'{';bool first=true;
#define ACTIVE_IRQ_VALUE(Name) out<<(first?"":",")<<"\"" #Name "\":"<<k.Name;first=false;
    ACTIVE_IRQ_VALUE(p) ACTIVE_IRQ_VALUE(mask) ACTIVE_IRQ_VALUE(irr) ACTIVE_IRQ_VALUE(sample)
    ACTIVE_IRQ_VALUE(status) ACTIVE_IRQ_VALUE(dma) ACTIVE_IRQ_VALUE(read_pending)
    ACTIVE_IRQ_VALUE(write_pending) ACTIVE_IRQ_VALUE(carry) ACTIVE_IRQ_VALUE(delay)
    ACTIVE_IRQ_VALUE(read_buffer) ACTIVE_IRQ_VALUE(marr) ACTIVE_IRQ_VALUE(mawr) ACTIVE_IRQ_VALUE(bus)
    ACTIVE_IRQ_VALUE(divider) ACTIVE_IRQ_VALUE(burst) ACTIVE_IRQ_VALUE(latched_cr) ACTIVE_IRQ_VALUE(latched_mwr)
    ACTIVE_IRQ_VALUE(hpos) ACTIVE_IRQ_VALUE(vpos) ACTIVE_IRQ_VALUE(hstate) ACTIVE_IRQ_VALUE(vstate)
    ACTIVE_IRQ_VALUE(hremaining) ACTIVE_IRQ_VALUE(raster) ACTIVE_IRQ_VALUE(sprite_count)
    ACTIVE_IRQ_VALUE(bg_start) ACTIVE_IRQ_VALUE(bg_end) ACTIVE_IRQ_VALUE(hsync) ACTIVE_IRQ_VALUE(sat_pending)
    ACTIVE_IRQ_VALUE(cd_enabled) ACTIVE_IRQ_VALUE(cd_active) ACTIVE_IRQ_VALUE(signals)
    ACTIVE_IRQ_VALUE(half) ACTIVE_IRQ_VALUE(end) ACTIVE_IRQ_VALUE(length)
    ACTIVE_IRQ_VALUE(write_address) ACTIVE_IRQ_VALUE(read_address) ACTIVE_IRQ_VALUE(cr)
    ACTIVE_IRQ_VALUE(mwr) ACTIVE_IRQ_VALUE(rcr) ACTIVE_IRQ_VALUE(selected)
#undef ACTIVE_IRQ_VALUE
    out<<'}';
}
inline unsigned kinds(const Kernel&pre,const Kernel&post,int previous_sample) {
    return unsigned(pre.irr!=post.irr)|2u*unsigned(pre.read_pending!=post.read_pending||pre.write_pending!=post.write_pending)
        |4u*unsigned(pre.status!=post.status)|8u*unsigned(pre.half!=post.half||pre.end!=post.end)
        |16u*unsigned(previous_sample!=pre.sample)
        |32u*unsigned(pre.hstate!=post.hstate||pre.vstate!=post.vstate||pre.raster!=post.raster)
        |64u*unsigned(pre.cd_active!=post.cd_active||pre.signals!=post.signals);
}
using Row=std::vector<std::uint64_t>;
struct Edge{unsigned span,kinds;Kernel before,after;};
struct Context {
    GeargrafxCore*core;
    std::uint64_t calls=0,drained=0;
    bool inside=false,retain=false;unsigned last_extra=0;int last_sample=0;
    std::vector<Row>spans;std::vector<Edge>edges;
    void begin(bool selected) {
        retain=selected;spans.clear();edges.clear();last_extra=0;
        last_sample=core->GetHuC6280()->*member(Pending{});
    }
    static void clock(void*pointer,u32 n) {
        auto&self=*static_cast<Context*>(pointer);const auto before=self.core->GetMasterClockCycles();
        const auto extra=self.core->GetHuC6280()->*member(Extra{});
        const bool waiting=self.inside&&extra>self.last_extra;
        if(waiting&&(extra-self.last_extra!=3||n!=3))throw std::runtime_error("Original dynamic callback is not StallFastCycle");
        self.last_extra=extra;const auto pre=kernel(*self.core);
        (self.core->*member(ClockTag{}))(n);
        const auto after=self.core->GetMasterClockCycles();const auto post=kernel(*self.core);
        if(after!=before+n)throw std::runtime_error("Original hardware callback continuity differs");
        if(self.retain) {
            if(self.spans.size()>=1000000)throw std::runtime_error("Original selected callback bound exceeded");
            const auto index=static_cast<unsigned>(self.spans.size());
            self.spans.push_back({before,n,after,unsigned(waiting),static_cast<unsigned>(pre.sample),post.irr,
                static_cast<unsigned>(pre.hpos),static_cast<unsigned>(pre.vpos),
                static_cast<unsigned>(pre.vstate),static_cast<unsigned>(pre.hstate)});
            const auto flags=kinds(pre,post,self.last_sample);
            if(flags)self.edges.push_back({index,flags,pre,post});
        }
        self.last_sample=pre.sample;++self.calls;
        if(after-self.drained>=4096){self.core->GetAudio()->EndFrame(nullptr,nullptr);self.drained=after;}
    }
};
} // namespace active_irq_gear
