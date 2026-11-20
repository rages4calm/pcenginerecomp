#pragma once
#include "pce/runtime.hpp"

namespace pce {
enum class PortView { four_three, sixteen_nine };

// Valid for the duration of the renderer call. Inspection never clocks a
// device or performs guest I/O, including when an address is unmapped.
class DesktopFrameInput {
public:
    DesktopFrameInput(const Bus& bus, PortView requested_view)
        : guest(bus.vdc.video.completed()), sequence(bus.vdc.video.sequence()), view(requested_view), bus_(bus) {}

    const VideoFrame& guest;
    const std::uint64_t sequence;
    const PortView view;

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
