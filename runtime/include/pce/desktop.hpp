#pragma once
#include "pce/video.hpp"
#include "pce/shader_parameters.hpp"
#include <cstdint>
#include <memory>
#include <string>

namespace pce {
enum class DisplayMode { integer, square, four_three, sixteen_nine };
enum class DisplayFilter { nearest, linear };
enum class DisplayShader { off, sharp, crt, smooth, lcd, mono, crt_mask };

struct DesktopExtent {
    unsigned width=0, height=0;
    bool operator==(const DesktopExtent&) const=default;
};

struct DesktopOptions {
    std::string title="PC Engine Recomp — development host";
    unsigned scale=3;
    bool hidden=false;
    bool paced=true;
    DisplayMode display_mode=DisplayMode::integer;
    DisplayFilter display_filter=DisplayFilter::nearest;
    bool fullscreen=false;
    DisplayShader display_shader=DisplayShader::off;
    std::string input_profile;
    ShaderParameters shader_parameters;
};
struct DesktopSettings {
    unsigned width=256, height=240;
    bool fullscreen=false;
    DisplayMode mode=DisplayMode::integer;
    DisplayFilter filter=DisplayFilter::nearest;
    bool operator==(const DesktopSettings&) const=default;
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
    std::uint16_t buttons(unsigned slot=0) const;
    // Clear host-held keyboard state and pending two-frame taps after a
    // checkpoint restore. Live gamepad state is sampled afresh on next poll.
    void reset_input();
    bool checkpoint_input_quiescent() const;
    // Publish once per newly completed guest frame. Fresh input pulses survive
    // two such boundaries so same-poll taps span one complete guest frame.
    // Consumer renderers may supply RGB frames of up to 16 Mi pixels.
    void present(const VideoFrame&);
    // Replace the presented image without advancing input pulse lifetime.
    void redraw(const VideoFrame&);
    DesktopExtent drawable_size() const;
    void resize_window(unsigned width, unsigned height);
    // Host wall-clock confirmation, independent of guest pacing/pauses.
    void preview_display(const DesktopSettings&, unsigned timeout_ms=10000);
    void confirm_display();
    void cancel_display();
    bool display_change_pending() const;
    DesktopSettings display_settings() const;
    std::string renderer_backend() const;
    void set_shader_parameters(const ShaderParameters&);
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
