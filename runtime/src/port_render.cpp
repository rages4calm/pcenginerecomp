#include "pce/port_render.hpp"
#include "pce/runtime.hpp"
#include <algorithm>

namespace pce {
namespace {
std::size_t extent(unsigned width,unsigned height) {
    const auto count=std::uint64_t(width)*height;
    if(!width || !height || width>8192 || height>8192 || count>16u*1024u*1024u)
        throw Fault("port rendering extent exceeds bounds");
    return static_cast<std::size_t>(count);
}
bool background_index(std::uint16_t value) {
    return value<=255 && (!value || (value&15));
}
void rgb(VideoFrame& frame,std::size_t offset,const std::array<std::uint8_t,3>& color) {
    std::copy(color.begin(),color.end(),frame.rgb.begin()+offset*3);
}
std::int64_t wrap(std::int64_t value,std::int64_t period) {
    const auto remainder=value%period;
    return remainder<0 ? remainder+period:remainder;
}
}

PortLayerFrame compose_port_layers(const PortLayerInput& input) {
    const auto count=extent(input.width,input.height);
    if((!input.background.empty() && input.background.size()!=count) ||
       (!input.sprites.empty() && input.sprites.size()!=count) ||
       (input.sprites.empty() ? !input.sprite_front.empty():input.sprite_front.size()!=count))
        throw Fault("port layer planes must match the complete extent");
    if(input.palettes.size()!=512 && input.palettes.size()!=std::size_t(input.height)*512)
        throw Fault("port palettes require one complete palette or one per row");
    if(!input.controls.empty() && input.controls.size()!=1 && input.controls.size()!=input.height)
        throw Fault("port controls require one value or one per row");
    if(input.backdrop>511)throw Fault("port backdrop palette index exceeds bounds");
    for(const auto value:input.background)
        if(!background_index(value))throw Fault("invalid port background palette index");
    for(const auto value:input.sprites)
        if(value && (value<256 || value>511 || !(value&15)))throw Fault("invalid port sprite palette index");
    for(const auto value:input.sprite_front)
        if(value>1)throw Fault("port sprite priority must be zero or one");
    for(const auto value:input.palettes)
        if(value>511)throw Fault("port palette color exceeds GRB9");
    PortLayerFrame output;
    for(auto* frame:{&output.image,&output.background,&output.behind_background}) {
        frame->width=input.width;frame->height=input.height;frame->rgb.resize(count*3);
    }
    output.sprite_visible.resize(count);
    for(std::size_t i=0;i<count;++i) {
        const auto row=i/input.width;
        const auto palette=input.palettes.subspan(input.palettes.size()==512 ? 0:row*512,512);
        const auto control=input.controls.empty() ? std::uint8_t(0):input.controls[input.controls.size()==1 ? 0:row];
        const auto bg=input.background.empty() ? 0:input.background[i];
        const auto sprite=input.sprites.empty() ? 0:input.sprites[i];
        const bool shown=sprite && (input.sprite_front[i] || !bg);
        const auto background=vce_rgb(palette[bg ? bg:input.backdrop],control);
        rgb(output.background,i,background);
        rgb(output.image,i,shown ? vce_rgb(palette[sprite],control):background);
        rgb(output.behind_background,i,sprite && !shown ? vce_rgb(palette[sprite],control):background);
        output.sprite_visible[i]=shown ? 1:0;
    }
    return output;
}

std::vector<std::uint16_t> sample_port_tilemap(const PortTilemapView& map,const PortViewport& view) {
    const auto count=extent(view.width,view.height);
    const auto cells=std::uint64_t(map.columns)*map.rows;
    if(!map.columns || !map.rows || map.columns>1024 || map.rows>1024 || cells>1024u*1024u || map.cells.size()!=cells)
        throw Fault("port tilemap shape exceeds bounds");
    if(map.pixels.empty() || map.pixels.size()%64 || map.pixels.size()/64>65536)
        throw Fault("port tile pixels require bounded complete 8x8 tiles");
    if(!view.row_scroll.empty() && view.row_scroll.size()!=view.height)
        throw Fault("port row scroll must match output height");
    if(view.address!=PortMapAddress::wrap && view.address!=PortMapAddress::clip)
        throw Fault("invalid port map address policy");
    if(!background_index(view.outside))throw Fault("invalid port outside palette index");
    if(view.clip && (view.clip->left>view.clip->right || view.clip->top>view.clip->bottom))
        throw Fault("port clip rectangle is reversed");
    for(const auto& cell:map.cells)
        if(cell.tile>=map.pixels.size()/64 || cell.palette>15)throw Fault("invalid port tile cell");
    for(const auto value:map.pixels)
        if(value>15)throw Fault("port tile color exceeds four bits");
    std::vector<std::uint16_t> output(count,view.outside);
    const auto map_width=std::int64_t(map.columns)*8,map_height=std::int64_t(map.rows)*8;
    for(unsigned y=0;y<view.height;++y) {
        const auto row=view.row_scroll.empty() ? PortRowScroll{}:view.row_scroll[y];
        for(unsigned x=0;x<view.width;++x) {
            if(view.clip && (std::int64_t(x)<view.clip->left || std::int64_t(x)>=view.clip->right ||
                            std::int64_t(y)<view.clip->top || std::int64_t(y)>=view.clip->bottom))continue;
            auto sx=std::int64_t(view.x)+row.x+x,sy=std::int64_t(view.y)+row.y+y;
            if(view.address==PortMapAddress::clip && (sx<0 || sy<0 || sx>=map_width || sy>=map_height))continue;
            sx=wrap(sx,map_width);sy=wrap(sy,map_height);
            const auto& cell=map.cells[std::size_t(sy/8)*map.columns+std::size_t(sx/8)];
            const auto tx=cell.flip_x ? 7-unsigned(sx&7):unsigned(sx&7);
            const auto ty=cell.flip_y ? 7-unsigned(sy&7):unsigned(sy&7);
            const auto color=map.pixels[std::size_t(cell.tile)*64+ty*8+tx];
            output[std::size_t(y)*view.width+x]=color ? std::uint16_t((unsigned(cell.palette)<<4)|color):0;
        }
    }
    return output;
}
} // namespace pce
