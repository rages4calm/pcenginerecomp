#pragma once
#include <array>
#include <cstdint>

namespace pce {
struct CdControl;
// Functional CD ADPCM RAM, port transactions and playback consumption clocks.
// Nibbles are consumed without decoding/mixing PCM or producing host audio.
struct Adpcm {
    bool enabled=false, playing=false, play_pending=false, nibble=false;
    bool end_irq=false, half_irq=false;
    std::array<std::uint8_t,65536> ram{};
    std::uint8_t control=0,dma=0,sample_rate=15,read_latch=0,write_latch=0,last_nibble=0;
    std::uint16_t address=0,read_address=0,write_address=0;
    std::uint32_t length=0;
    std::uint64_t master_ticks=0,read_deadline=0,write_deadline=0,dma_deadline=0;
    std::uint64_t sample_phase=0,samples=0,reads=0,writes=0,dma_bytes=0;
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
