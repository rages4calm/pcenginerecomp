#pragma once
#include <array>
#include <cstdint>

namespace pce {
struct CdControl;
// CD ADPCM RAM, port transactions, playback clocks and MSM5205 digital decode.
// Host mixing, resampling, the analog filter and the 10-bit DAC are separate.
struct Adpcm {
    bool enabled=false, playing=false, play_pending=false, nibble=false;
    bool end_irq=false, half_irq=false;
    std::array<std::uint8_t,65536> ram{};
    std::uint8_t control=0,dma=0,sample_rate=15,read_latch=0,write_latch=0,last_nibble=0;
    std::uint16_t address=0,read_address=0,write_address=0;
    std::uint32_t length=0;
    std::uint64_t master_ticks=0,read_deadline=0,write_deadline=0,dma_deadline=0;
    std::uint64_t sample_phase=0,samples=0,reads=0,writes=0,dma_bytes=0;
    // Unsigned 12-bit accumulator (wraps, never saturates) and 0..48 adaptive
    // index. Soft reset and actual pending-play start initialize both; stop
    // holds their values. No port/IRQ/length/sample-clock state depends on them.
    std::uint16_t decoder_output=2048;
    std::uint8_t decoder_index=0;
    // Raw held digital PCM, signed full scale. Caller applies playback/reset
    // gating and mixer gain; no DAC truncation, analog filter or fader here.
    std::int16_t sample_pcm() const {
        return static_cast<std::int16_t>((static_cast<int>(decoder_output)-2048)*16);
    }
    std::uint8_t read(unsigned port);
    void write(unsigned port,std::uint8_t value,CdControl* source=nullptr);
    // When supplied, the CD transport is advanced here at shared event times.
    // Callers must not advance that source to the end time first.
    void advance_to(std::uint64_t ticks,CdControl* source=nullptr);
    std::uint64_t sample_period() const;
private:
    void flags();
    void consume_sample();
    void update_irq(CdControl*);
};
} // namespace pce
