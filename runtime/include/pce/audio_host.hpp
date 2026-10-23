#pragma once
#include <cstdint>
#include <memory>
#include <span>

namespace pce {
struct AudioHostStats {
    std::uint64_t submitted_frames=0, dropped_frames=0, clears=0, pauses=0;
    std::uint64_t queued_frames=0, peak_queue_frames=0, queued_bytes=0;
    unsigned input_rate=0,input_channels=0,input_format=0;
    unsigned stream_output_rate=0,stream_output_channels=0,stream_output_format=0;
    unsigned device_rate=0,device_channels=0,device_format=0,device_sample_frames=0;
};

// Main-thread PCM presentation only; the SDL audio thread never calls guest
// code. The bound covers selected-rate pending stream input frames, not
// OS/device latency. SDL may independently convert to the queried device spec.
class AudioHost {
public:
    static constexpr unsigned sample_rate=44100, max_queue_frames=4410;
    explicit AudioHost(unsigned input_rate=sample_rate);
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
