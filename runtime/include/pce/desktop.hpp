#pragma once
#include "pce/video.hpp"
#include <cstdint>
#include <memory>
#include <string>

namespace pce {
struct DesktopOptions {
    std::string title="PC Engine Recomp — development host";
    unsigned scale=3;
    bool hidden=false;
    bool paced=true;
};
struct DesktopStats {
    std::uint64_t presented=0, polls=0, pacing_resets=0;
    std::uint64_t focus_losses=0, gamepad_connections=0, resize_events=0;
    std::uint64_t keyboard_events=0, gamepad_events=0, input_pulses=0;
    std::uint64_t unmapped_key_down=0;
    std::uint32_t last_unmapped_scancode=0;
};

// Main-thread presentation/input only. No guest clock, controller latch, memory,
// persistence or simulation state is modified by this optional SDL3 adapter.
class DesktopHost {
public:
    explicit DesktopHost(const DesktopOptions& options={});
    ~DesktopHost();
    DesktopHost(const DesktopHost&)=delete;
    DesktopHost& operator=(const DesktopHost&)=delete;
    bool poll();
    bool paused() const;
    std::uint16_t buttons() const;
    // Publish once per newly completed guest frame. Fresh input pulses survive
    // two such boundaries so same-poll taps span one complete guest frame.
    void present(const VideoFrame&);
    // Call on completed guest frames. Wall time never changes guest ticks.
    void pace(std::uint64_t guest_ticks);
    void reset_pacing(); // A debugger pause must not create wall-time catch-up.
    // Actual SDL render-target RGB, including the letterbox. Redraw/read occurs
    // before present, as SDL requires. At most four million output pixels.
    VideoFrame readback();
    void capture(const std::string& new_path);
    std::uint32_t window_id() const;
    const DesktopStats& stats() const;
private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};
} // namespace pce
