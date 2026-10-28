#pragma once
#include <array>
#include <cstdint>

namespace pce {
using StereoSample=std::array<std::int16_t,2>;

// Optional presentation state, independent of guest device state and clocks.
// Inputs are PSG channel sums BEFORE half gain, so odd sums retain .5 precision.
class PsgPresentationFilter {
public:
    StereoSample process(std::array<std::int32_t,2> pre_half_sums);
    void reset();
private:
    friend struct AudioCheckpointAccess;
    std::array<float,2> previous_input_{},previous_output_{};
};

class AdpcmPresentationFilter {
public:
    // Unsigned 12-bit held decoder output; target_gain is finite and in [0,1].
    std::int16_t process(std::uint16_t decoded_unsigned12,float target_gain=1.0f);
    void reset();
private:
    friend struct AudioCheckpointAccess;
    float previous_input_=0,previous_output_=0,lowpass_=0,gain_=1;
};

struct AudioResampleOutput {
    std::array<StereoSample,2> samples{};
    unsigned count=0;
};

// Causal, fixed-memory 44,100 -> 48,000 polyphase FIR. At 44,100 the exact
// input is passed through without filtering or latency. No implicit tail is
// generated. A reset discards FIR history; presentation pauses should not reset.
class StereoResampler {
public:
    static constexpr unsigned input_rate=44100,taps=64,phases=160;
    static constexpr unsigned latency_source_frames=31;
    explicit StereoResampler(unsigned output_rate=44100);
    AudioResampleOutput push(StereoSample input);
    void reset();
    unsigned output_rate() const {return output_rate_;}
    unsigned latency() const {return output_rate_==input_rate ? 0:latency_source_frames;}
    std::uint64_t input_frames() const {return input_frames_;}
    std::uint64_t output_frames() const {return output_frames_;}
private:
    friend struct AudioCheckpointAccess;
    unsigned output_rate_,write_=0,remainder_=0;
    std::uint64_t input_frames_=0,output_frames_=0;
    std::array<StereoSample,taps> history_{};
};
} // namespace pce
