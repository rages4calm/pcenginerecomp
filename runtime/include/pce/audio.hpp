#pragma once
#include <array>
#include <cstdint>

namespace pce {
// Functional, write-observable PSG state. Oscillator clocks, mixing, audio
// buffers and host playback are deliberately separate and not implemented.
struct Psg {
    struct Channel {
        std::uint16_t frequency=0;
        std::uint8_t control=0, balance=0, wave_index=0, wave=0, dda=0, noise=0;
        std::array<std::uint8_t,32> waveform{};
        bool playing() const { return (control&128)!=0; }
        bool dda_mode() const { return (control&64)!=0; }
        unsigned noise_period() const { return (noise&31)==31 ? 32:((~noise)&31)*64; }
    };
    bool enabled=false;
    std::uint8_t selected=0, main_volume=0, lfo_frequency=0, lfo_control=0;
    std::array<Channel,6> channels{};
    std::uint64_t writes=0;
    void write(unsigned port, std::uint8_t value);
};
} // namespace pce
