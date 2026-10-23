#pragma once
#include "pce/video.hpp"
#include <array>
#include <cstdint>

namespace pce {
struct Vdc;
struct Vce;

// Guest-clock video output. Publication never advances the guest and host reads
// never consume a frame. A returned reference stays valid until next publication.
// Two bounded RGB buffers and a single index line; no retained frame history.
class VideoOutput {
public:
    bool enabled=false;
    void enable(const Vdc&);
    const VideoFrame& completed() const { return front_; }
    std::uint64_t sequence() const { return sequence_; }
    std::uint64_t completed_ticks() const { return completed_ticks_; }
    std::uint64_t lines_rendered() const { return lines_rendered_; }
    std::uint64_t pixels_rendered() const { return pixels_rendered_; }
    // Raster/VDC integration, not host presentation entry points.
    void register_write(const Vdc&, unsigned index, bool high);
    void latch_y(const Vdc&);
    void latch_x(const Vdc&);
    void latch_mode(const Vdc&);
    void increment_y();
    void horizontal_start(const Vdc&);
    void begin_line(const Vdc&);
    void pixel(const Vdc&, const Vce&);
    void end_line();
    void frame_boundary(const Vdc&);
private:
    VideoFrame front_, back_;
    std::array<std::uint16_t,1024> indices_{};
    std::uint64_t sequence_=0, completed_ticks_=0, lines_rendered_=0, pixels_rendered_=0;
    unsigned x_=0, row_=0, line_width_=0;
    std::uint16_t scroll_x_=0, scroll_y_=0, counter_y_=0, control_=0, mode_=0;
    bool y_pending_=false, increment_=false, burst_=true, active_=false;
    void prepare_frame(const Vdc&);
};
} // namespace pce
