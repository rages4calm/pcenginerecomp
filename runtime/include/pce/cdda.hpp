#pragma once
#include <array>
#include <cstdint>
#include <memory>

namespace pce {
struct CdControl;
class SectorProvider;
class CddaPcmCache;
// Guest drive, source DAC and sample-latch state. Host presentation never owns
// or advances the readable DAC, even when PCM output is disabled.
struct CdAudio {
    unsigned state=1, stop_mode=0; // PLAYING=0, IDLE=1, PAUSED=2, STOPPED=3.
    std::uint32_t start_lba=0, current_lba=0, stop_lba=0, seek_start_lba=0;
    std::uint64_t deadline=0, seek_deadline=0, sector_deadline=0, playback_deadline=0;
    std::uint64_t sectors_played=0, commands=0;
    unsigned sector_fraction=0;
    std::uint8_t fader=0;
    std::uint64_t fade_start=0, fade_duration=0;
    struct Cursor {
        std::weak_ptr<SectorProvider> source;
        std::uint32_t lba=0;
        unsigned frame=0,last_state=3;
        std::uint64_t commands_seen=0,sectors_seen=0,seek_seen=0;
        bool active=false,finished=false,tail_pending=false,was_enabled=false;
        void observe(const CdControl&);
        std::array<std::int16_t,2> sample(CdControl&,CddaPcmCache&,bool& valid);
    } source_cursor;
    std::array<std::int16_t,2> sample_raw{},sample_held{};
    bool sample_valid=true,sample_right=false;
    std::uint16_t sample_latch=0;
    std::uint64_t sample_last_latch=0,sample_frames=0,sample_ticks=0,sample_clock_ticks=0;
    // Zero means the next rational source edge is beyond uint64 guest time;
    // it is an exhausted timeline, never a wrapped event at tick zero.
    std::uint64_t sample_next_tick=488;
    unsigned sample_remainder=572;
    void latch_sample(std::uint64_t ticks);
    void stop(bool idle=false);
    void reschedule();
};
} // namespace pce
