#pragma once
#include <cstdint>

namespace pce {
// Control/position timeline only. No PCM samples, audio decoder or host mixer.
struct CdAudio {
    unsigned state=1, stop_mode=0; // PLAYING=0, IDLE=1, PAUSED=2, STOPPED=3.
    std::uint32_t start_lba=0, current_lba=0, stop_lba=0, seek_start_lba=0;
    std::uint64_t deadline=0, seek_deadline=0, sector_deadline=0, playback_deadline=0;
    std::uint64_t sectors_played=0, commands=0;
    unsigned sector_fraction=0;
    std::uint8_t fader=0;
    std::uint64_t fade_start=0, fade_duration=0;
    void stop(bool idle=false);
    void reschedule();
};
} // namespace pce
