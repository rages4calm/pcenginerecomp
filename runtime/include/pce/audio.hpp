#pragma once
#include <array>
#include <cstdint>

namespace pce {
// Register storage remains usable without clocks. Opt-in synthesis is an
// integer, guest-clock digital PSG profile, before resampling/analog filtering.
struct Psg {
    struct Channel {
        std::uint16_t frequency=0;
        std::uint8_t control=0, balance=0, wave_index=0, wave=0, dda=0, noise=0;
        std::array<std::uint8_t,32> waveform{};
        std::uint32_t wave_remaining=0, noise_remaining=0, noise_lfsr=1;
        bool playing() const { return (control&128)!=0; }
        bool dda_mode() const { return (control&64)!=0; }
        unsigned noise_period() const { return (noise&31)==31 ? 32:((~noise)&31)*64; }
    };
    bool enabled=false;
    bool synthesis_enabled=false;
    // Centered HuC6280A DAC by default; false selects original unipolar DAC.
    bool centered_dac=true;
    std::uint64_t clock_ticks=0;
    std::uint8_t master_remainder=0;
    std::uint8_t selected=0, main_volume=0, lfo_frequency=0, lfo_control=0;
    std::array<Channel,6> channels{};
    std::uint64_t writes=0;
    void write(unsigned port, std::uint8_t value);
    void advance_to(std::uint64_t ticks);
    std::array<std::int16_t,2> sample_pcm() const;
    // Unclipped signed channel sum before half gain, for source filtering.
    // No clocks, register state or cached sample state change on observation.
    std::array<std::int32_t,2> sample_sum() const;
};
} // namespace pce
