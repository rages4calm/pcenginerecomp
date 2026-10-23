#pragma once
#include <cstdint>
#include <memory>
#include <span>

namespace pce {
struct AudioHostStats {
    std::uint64_t submitted_frames=0, dropped_frames=0, clears=0, pauses=0;
    std::uint64_t queued_frames=0, peak_queue_frames=0, queued_bytes=0;
};

// Main-thread PCM presentation only; the SDL audio thread never calls guest
// code. The bound covers pending stream input, not OS/device output latency.
class AudioHost {
public:
    static constexpr unsigned sample_rate=44100, max_queue_frames=4410;
    AudioHost();
    ~AudioHost();
    AudioHost(const AudioHost&)=delete;
    AudioHost& operator=(const AudioHost&)=delete;
    // Interleaved native-endian signed-16 stereo. Invalid shapes are refused
    // before changing statistics or queue contents. No wait for device drain.
    void submit(std::span<const std::int16_t> stereo);
    void set_paused(bool paused);
    // Refreshes queued counts from SDL, rather than estimating consumption.
    const AudioHostStats& stats() const;
private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};
} // namespace pce
