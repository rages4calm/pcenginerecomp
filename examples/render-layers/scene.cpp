#include "pce/desktop_view.hpp"
#include "pce/port_render.hpp"
#include "pce/presentation_history.hpp"
#include <array>
#include <iostream>
#include <tuple>

namespace {
constexpr unsigned height=240;
pce::PortLayerFrame scene(unsigned width) {
    std::array<std::uint8_t,64> pixels{};
    for(unsigned y=0;y<8;++y)for(unsigned x=0;x<8;++x)
        pixels[y*8+x]=((x&1)==(y<4 ? 0u:1u)) ? 1:0;
    std::array<pce::PortMapCell,64*32> cells{};
    std::array<std::uint16_t,512> palette{};
    palette[0]=7;palette[1]=0x38;palette[256]=0x1F8;palette[257]=0x1C0;palette[273]=0x1FF;
    const int camera=-int((width-256)/2);
    auto background=pce::sample_port_tilemap({64,32,cells,pixels},{width,height,camera,0});
    std::vector<std::uint16_t> sprites(width*height);
    std::vector<std::uint8_t> front(width*height);
    for(unsigned actor=0;actor<2;++actor)for(unsigned y=80;y<96;++y)for(int world=80+40*int(actor);world<96+40*int(actor);++world) {
        const int x=world-camera;
        if(x>=0 && x<int(width)) {const auto at=y*width+unsigned(x);sprites[at]=actor ? 273:257;front[at]=actor ? 0:1;}
    }
    return pce::compose_port_layers({width,height,background,sprites,front,palette,{}});
}
}

bool pce::render_desktop_frame(const DesktopFrameInput& input,VideoFrame& output) {
    static PresentationHistory history(2000000);
    static std::uint64_t epoch=0;
    if(epoch!=input.presentation_epoch){history.invalidate();epoch=input.presentation_epoch;}
    if(input.peek(0x1F0041)!=0xA5 || input.guest.width!=256 || input.guest.height!=height)return false;
    auto reference=scene(256);
    // A deliberately changed consumer marker demonstrates fail-closed fallback
    // without pretending current RAM reconstructs historical video changes.
    if(input.peek(0x1F0042).value_or(0))reference.image.rgb[0]^=1;
    const auto admitted=history.observe(input.guest,reference.image,{.sequence=input.sequence,
        .ticks=input.guest_ticks,.scene=1,.epoch=input.presentation_epoch,.width=input.drawable.width,
        .height=input.drawable.height,.view=static_cast<std::uint64_t>(input.view)});
    static std::tuple<std::uint64_t,std::uint64_t,unsigned,unsigned,unsigned> last{};
    const auto stamp=std::tuple(input.presentation_epoch,input.sequence,input.drawable.width,input.drawable.height,unsigned(admitted.reason));
    if(stamp!=last) {
        std::cerr<<"PCE_RENDER_LAYER={\"epoch\":"<<input.presentation_epoch<<",\"frame\":"<<input.sequence
            <<",\"exact\":"<<(admitted.exact?"true":"false")<<",\"interpolation\":"<<(admitted.interpolation?"true":"false")
            <<",\"reason\":"<<unsigned(admitted.reason)<<"}\n";last=stamp;
    }
    if(!admitted.exact)return false;
    const unsigned width=input.view==PortView::four_three ? 256:input.camera_width(height,256,640);
    auto layers=scene(width);output=std::move(layers.image);
    const auto blue=std::uint8_t(16+(input.sequence%4)*4);
    for(std::size_t i=0;i<layers.sprite_visible.size();++i) {
        // Modernized light tint affects scenery, never the visible sprites.
        if(!layers.sprite_visible[i] && layers.background.rgb[i*3]==255)output.rgb[i*3+2]=blue;
        // A small presentation-only reveal window demonstrates the hidden
        // sprite underlay without changing collision, SATB or guest memory.
        const int world=int(i%width)-int((width-256)/2);
        if(world>=120 && world<124 && i/width>=80 && i/width<96 &&
           layers.behind_background.rgb[i*3]==255 && layers.behind_background.rgb[i*3+1]==255)
            for(unsigned channel=0;channel<3;++channel)output.rgb[i*3+channel]=layers.behind_background.rgb[i*3+channel];
    }
    return true;
}
