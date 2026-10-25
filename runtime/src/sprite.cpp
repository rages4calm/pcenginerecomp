#include "pce/runtime.hpp"
#include <algorithm>

namespace pce {
void Vdc::fetch_sprite_rows() {
    sprite_count=0;
    constexpr unsigned heights[]={16,32,64,64};
    constexpr unsigned pattern_masks[]={1023,1021,1017,1017};
    const bool two_bit=((sprite_mode>>2)&3)==1;
    for(unsigned index=0;index<64;++index) {
        const auto flags=satb[index*4+3];
        const unsigned height_code=(flags>>12)&3,height=heights[height_code];
        const int top=int(satb[index*4]&1023)-64;
        const int relative=int(raster.raster_line)-top;
        if(relative<0 || relative>=int(height)) continue;
        if(sprite_count==sprite_rows.size()) { sprite_overflow=true;break; }
        const bool wide=(flags&256)!=0,flip=(flags&2048)!=0;
        const auto pattern_word=satb[index*4+2];
        unsigned pattern=(pattern_word>>1)&pattern_masks[height_code];
        if(wide) pattern&=1022;
        const unsigned row=(flags&32768) ? height-1-unsigned(relative):unsigned(relative);
        const unsigned base=pattern*64+(row/16)*128+(row&15)+
            (two_bit ? (pattern_word&1)*32:0);
        const int left=int(satb[index*4+1]&1023)-32;
        const auto append=[&](int x,unsigned address) {
            SpriteRow cell;cell.x=x;cell.index=index;cell.flip=flip;
            cell.palette=(flags&15)*16;cell.front=(flags&128)!=0;
            for(unsigned plane=0;plane<(two_bit?2U:4U);++plane) {
                // The VDC address calculation wraps its 16-bit internal bus.
                const auto word=(address+plane*16)&65535;
                cell.planes[plane]=read_vram(static_cast<std::uint16_t>(word));
            }
            sprite_rows[sprite_count++]=cell;
        };
        append(left,base+(wide&&flip?64:0));
        if(wide) {
            // A wide sprite tests the cell budget between its two halves.
            if(sprite_count==sprite_rows.size()) { sprite_overflow=true;break; }
            append(left+16,base+(flip?0:64));
        }
    }
}

void Vdc::sprite_collision() {
    if(!(reg[5]&1)) return;
    const int width=int(raster.horizontal[1]);
    // At most sixteen admitted cells, with no allocation in the guest clock.
    // Collision depends on opaque sprite pixels, independently of background
    // priority, palette, and whether host presentation is enabled.
    std::array<bool,1024> occupied{};
    for(unsigned cursor=sprite_count;cursor>0;--cursor) {
        const auto& cell=sprite_rows[cursor-1];
        const auto opaque=cell.planes[0]|cell.planes[1]|cell.planes[2]|cell.planes[3];
        for(int offset=std::max(0,-cell.x);offset<16 && cell.x+offset<width;++offset) {
            const unsigned shift=cell.flip?unsigned(offset):15-unsigned(offset);
            if(!(opaque&(1U<<shift))) continue;
            const auto x=unsigned(cell.x+offset);
            if(cell.index==0 && occupied[x]) { status|=1;irq1=true;return; }
            occupied[x]=true;
        }
    }
}
} // namespace pce
