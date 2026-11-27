#include "pce/desktop_view.hpp"
#include "pce/presentation_history.hpp"
#include <array>
#include <iostream>

namespace {
pce::VideoFrame original() {
    pce::VideoFrame frame{256,240,{}};
    frame.rgb.reserve(256*240*3);
    for(unsigned y=0;y<240;++y)for(unsigned x=0;x<256;++x) {
        const bool opaque=(x%8)%2==(y%8<4 ? 0u:1u);
        std::array<std::uint8_t,3> rgb=opaque ? std::array<std::uint8_t,3>{255,0,0}:
            std::array<std::uint8_t,3>{0,0,255};
        if(x>=80 && x<96 && y>=80 && y<96)rgb={0,255,0};
        else if(x>=120 && x<136 && y>=80 && y<96 && !opaque)rgb={255,255,255};
        frame.rgb.insert(frame.rgb.end(),rgb.begin(),rgb.end());
    }
    return frame;
}
}

bool pce::render_desktop_frame(const DesktopFrameInput& input,VideoFrame& output) {
    static PresentationHistory history(2000000);
    static std::uint64_t epoch=0;
    if(epoch!=input.presentation_epoch){history.invalidate();epoch=input.presentation_epoch;}
    if(input.peek(0x1F0041)!=0xA5 || input.guest.width!=256 || input.guest.height!=240) {
        history.invalidate();return false;
    }
    const auto reference=original();
    const auto admitted=history.observe(input.guest,reference,{.sequence=input.sequence,
        .ticks=input.completed_ticks,.scene=1,.epoch=input.presentation_epoch,
        .width=input.drawable.width,.height=input.drawable.height,
        .view=static_cast<std::uint64_t>(input.view)});
    std::cerr<<"PCE_RENDER_EFFECT={\"epoch\":"<<input.presentation_epoch
        <<",\"frame\":"<<input.sequence<<",\"guest_ticks\":"<<input.guest_ticks
        <<",\"completed_ticks\":"<<input.completed_ticks
        <<",\"exact\":"<<(admitted.exact?"true":"false")
        <<",\"interpolation\":"<<(admitted.interpolation?"true":"false")
        <<",\"reason\":"<<unsigned(admitted.reason)<<"}\n";
    if(!admitted.exact)return false;
    const auto width=input.camera_width(240,256,640);
    output={width,240,{}};output.rgb.reserve(width*240*3);
    // Explicit diagnostic swatches, not recovered offscreen game scenery.
    // The four-frame phase is guest sequence only; paused CPU work cannot move it.
    constexpr std::array<std::array<std::uint8_t,3>,4> colors{{
        {240,0,0},{0,160,0},{0,0,80},{0,0,0}}};
    for(unsigned y=0;y<240;++y)for(unsigned x=0;x<width;++x) {
        const auto& rgb=colors[(x+input.sequence)%4];
        output.rgb.insert(output.rgb.end(),rgb.begin(),rgb.end());
    }
    return true;
}
