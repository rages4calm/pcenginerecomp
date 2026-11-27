#pragma once
#include "pce/desktop.hpp"
#include "pce/runtime.hpp"
#include <algorithm>

namespace pce {
enum class PortView { four_three, sixteen_nine, twenty_one_nine, adaptive };

// Valid for the duration of the renderer call. Inspection never clocks a
// device or performs guest I/O, including when an address is unmapped.
class DesktopFrameInput {
public:
    DesktopFrameInput(const Bus& bus, PortView requested_view, DesktopExtent output={}, std::uint64_t epoch=0, std::uint64_t ticks=0)
        : guest(bus.vdc.video.completed()), sequence(bus.vdc.video.sequence()), view(requested_view),
          drawable(output), presentation_epoch(epoch), guest_ticks(ticks), bus_(bus) {}

    const VideoFrame& guest;
    const std::uint64_t sequence;
    const PortView view;
    const DesktopExtent drawable;
    // Host-only discontinuity identity. Fresh checkpoint imports advance it.
    const std::uint64_t presentation_epoch;
    const std::uint64_t guest_ticks;

    // Select a square-pixel camera width at a fixed logical height.
    unsigned camera_width(unsigned height, unsigned minimum, unsigned maximum) const {
        if(!height || !minimum || minimum>maximum)throw Fault("invalid port camera bounds");
        auto aspect=DesktopExtent{4,3};
        switch(view) {
        case PortView::four_three:break;
        case PortView::sixteen_nine:aspect={16,9};break;
        case PortView::twenty_one_nine:aspect={21,9};break;
        case PortView::adaptive:
            if(drawable.width && drawable.height)aspect=drawable;
            break;
        }
        const auto width=std::uint64_t(height)*aspect.width/aspect.height;
        return static_cast<unsigned>(std::clamp<std::uint64_t>(width,minimum,maximum));
    }

    std::optional<std::uint8_t> peek(std::uint32_t physical) const {
        return bus_.peek(physical);
    }

private:
    const Bus& bus_;
};

// Implemented by the PORT_RENDERER source of an opted-in desktop consumer.
// Return false to publish the guest frame (for example during menus or boot).
// Derive the view from the supplied state so checkpoint restore can redraw it.
bool render_desktop_frame(const DesktopFrameInput& input, VideoFrame& output);
} // namespace pce
