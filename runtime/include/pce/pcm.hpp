#pragma once
#include <array>
#include <cstddef>
#include <cstdint>
#include <memory>
#include <vector>

namespace pce {
struct Bus;
class CddaStreamState;
// Guest-clock audio. The consumer drains a bounded queue; host timing never
// advances the guest. All hashes use signed samples encoded as little-endian
// two's-complement bytes, independent of the host's native byte order.
class AudioOutput {
public:
    static constexpr unsigned rate=44100, capacity=8192;
    bool enabled=false;
    std::uint64_t master_ticks=0,frames=0,discarded_frames=0;
    std::uint64_t psg_nonzero=0,adpcm_nonzero=0,cdda_nonzero=0,mixed_nonzero=0;
    std::uint64_t pcm_hash=14695981039346656037ULL;
    unsigned peak=0;
    AudioOutput();
    ~AudioOutput();
    AudioOutput(AudioOutput&&) noexcept;
    AudioOutput& operator=(AudioOutput&&) noexcept;
    void enable();
    void advance_to(Bus&,std::uint64_t ticks);
    std::vector<std::int16_t> drain();
    std::size_t queued_frames() const {return count_;}
private:
    std::array<std::array<std::int16_t,2>,capacity> queue_{};
    std::unique_ptr<CddaStreamState> cd_cache_;
    std::size_t begin_=0,count_=0;
    std::uint64_t next_tick_=487;
    unsigned remainder_=573;
    void append(std::array<std::int16_t,2>);
    // Independent digital source cursor. CD control/IRQ timestamps remain
    // authoritative for gating, but rounded sector durations do not resample
    // (and duplicate/drop) the 588 source frames in each raw audio sector.
    void observe_cd_audio(const Bus&);
    std::array<std::int16_t,2> cdda_sample(Bus&);
};
} // namespace pce
