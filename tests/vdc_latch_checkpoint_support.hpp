#pragma once
// Authored direct-device schedules. No emulator instruction count is implied.
#include <array>
#include <cstdint>
#include <ostream>
#include <stdexcept>
#include <string>
#include <vector>

namespace vdc_latch_checkpoint {
inline constexpr std::uint64_t line_ticks=1365,frame_ticks=262*line_ticks;
enum class Edge { cr_hds, mwr_vsw, mwr_vsync, burst_frame };
struct Case {std::string id;Edge edge;int delta;unsigned queue;std::uint64_t write_ticks,latch_ticks;};
inline std::vector<Case> cases() {
    std::vector<Case> out;
    for(auto edge:{Edge::cr_hds,Edge::mwr_vsw,Edge::mwr_vsync,Edge::burst_frame}) {
        // Stable div4 geometry: HDS at24dots; RCR/vertical compare at273dots.
        // Natural VSW precedes the separately forced VSync at line259 clock0.
        const auto latch=edge==Edge::cr_hds?2*frame_ticks+64*line_ticks+96:
            edge==Edge::mwr_vsw?2*frame_ticks+258*line_ticks+1092:
            edge==Edge::mwr_vsync?2*frame_ticks+259*line_ticks:3*frame_ticks;
        const char* name=edge==Edge::cr_hds?"cr-hds":edge==Edge::mwr_vsw?"mwr-vsw":edge==Edge::mwr_vsync?"mwr-vsync":"burst-frame";
        for(int delta:{-3,0,3})for(unsigned queue:{1u,2u,3u})
            out.push_back({std::string(name)+(delta<0?"-before":delta==0?"-at":"-after")+(queue==1?"-read":queue==2?"-write":"-both"),
                edge,delta,queue,static_cast<std::uint64_t>(static_cast<std::int64_t>(latch)+delta),latch});
    }
    return out;
}
inline Case selected(const std::string& id) {for(const auto& c:cases())if(c.id==id)return c;throw std::runtime_error("unknown VDC latch checkpoint case");}
inline constexpr std::array<std::uint64_t,19> offsets{0,3,6,9,12,15,18,21,24,27,30,48,96,192,1365,2730,4095,frame_ticks,frame_ticks+24000};
inline bool mwr(Edge e){return e==Edge::mwr_vsw||e==Edge::mwr_vsync;}
inline unsigned old_cr(Edge e){return e==Edge::burst_frame?0:128;}
inline unsigned new_cr(Edge e){return e==Edge::burst_frame?128:192;}
inline unsigned write_reg(Edge e){return mwr(e)?9:5;}
inline unsigned write_value(Edge e){return mwr(e)?0x11:new_cr(e);}
inline std::vector<std::uint8_t> rom(){std::vector<std::uint8_t> out(262144,0xEA);out[0x1FFE]=0;out[0x1FFF]=0xE0;return out;}
inline void seed_vram(auto* memory) {
    for(unsigned i=0;i<32768;++i)memory[i]=0;
    for(unsigned i=0;i<4096;++i)memory[i]=0x100;
    for(unsigned y=0;y<8;++y)memory[0x100*16+y]=0xFF;
    memory[0x18FF]=0x1234;memory[0x1900]=0x5678;
}
// fields: ticks,hclock,VCEline,VDCline,Hstate,Vstate,CR,MWR,latchedCR,
// latchedMWR,burst,readPending,writePending,delay,carry,MARR,MAWR,readBuffer,
// VRAM1800,BGstart,BGend,Hsyncstart,first16 rendered line indices.
using State=std::array<std::uint64_t,38>;
inline void state_json(std::ostream& out,const State& row){out<<'[';for(unsigned i=0;i<row.size();++i)out<<(i?",":"")<<row[i];out<<']';}
inline void require(bool ok,const char* text){if(!ok)throw std::runtime_error(text);}
inline void expected(const Case& c,const State& row,bool original_gear=false) {
    require(row[0]>=c.write_ticks,"latch observation precedes write");
    require(row[6]==(mwr(c.edge)?old_cr(c.edge):new_cr(c.edge)),"authored CR register differs");
    require(row[7]==(mwr(c.edge)?0x11:0),"authored MWR register differs");
    // Burst skips output consumption. The original retains a backdrop line
    // sentinel, whereas this renderer leaves its unused index storage zero.
    // Both must refresh to the authored tile before ordinary active output.
    const auto offset=row[0]-c.write_ticks;
    const std::uint64_t index=c.edge!=Edge::burst_frame || offset>frame_ticks || (c.delta<0 && offset==frame_ticks)?1:original_gear?256:0;
    for(unsigned i=22;i<38;++i)require(row[i]==index,"independent rendered/stale index literal differs");
    // A write at the exact boundary follows that boundary's already-clocked latch.
    if(row[0]==c.write_ticks) {
        if(c.edge==Edge::cr_hds)require(row[8]==128,"CR write changed current HDS latch immediately");
        if(mwr(c.edge))require(row[9]==0,"MWR write changed current vertical latch immediately");
        require(row[11]==bool(c.queue&1)&&row[12]==bool(c.queue&2),"ports did not arm declared pending queues");
    }
    if(c.edge==Edge::cr_hds && row[0]>=c.latch_ticks && row[0]<c.latch_ticks+line_ticks)
        require(row[8]==(c.delta<0?192:128),"before/at/after CR HDS latch boundary differs");
    if(c.edge==Edge::mwr_vsw && row[0]>=c.latch_ticks && row[0]<2*frame_ticks+259*line_ticks)
        require(row[9]==(c.delta<0?0x11:0),"before/at/after natural VSW MWR latch boundary differs");
    if(c.edge==Edge::mwr_vsync && row[0]>=c.latch_ticks && row[0]<c.latch_ticks+frame_ticks-273)
        require(row[9]==(c.delta<0?0x11:0),"before/at/after forced VSync MWR latch boundary differs");
    if(c.edge==Edge::burst_frame && row[0]>=c.latch_ticks && row[0]<c.latch_ticks+frame_ticks)
        require(row[10]==(c.delta<0?0:1),"frame-only burst admission boundary differs");
    if(row[0]>=c.write_ticks+4095) {
        require(row[11]==0&&row[12]==0,"pending queues failed to complete");
        require(row[15]==((c.queue&1)?0x1901:0x1900),"read queue pointer endpoint differs");
        require(row[16]==((c.queue&2)?0x1801:0x1800),"write queue pointer endpoint differs");
        require(row[17]==((c.queue&1)?0x5678:0x1234),"read queue data endpoint differs");
        require(row[18]==((c.queue&2)?0xABCD:0),"write queue VRAM endpoint differs");
    }
}
} // namespace vdc_latch_checkpoint
