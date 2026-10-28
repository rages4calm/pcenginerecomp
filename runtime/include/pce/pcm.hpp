#pragma once
#include <array>
#include <cstddef>
#include <cstdint>
#include <memory>
#include <vector>

namespace pce {
struct Bus;
class CddaStreamState;
enum class AudioProfile { raw, filtered };
// Legacy preserves the original floored sample edges and analytical PSG DAC.
// Gear uses ceiling-rational sample edges and clock-latched PSG observations.
enum class AudioTiming { gear, legacy };
struct AudioProcessingStats {
    std::uint64_t source_frames=0,raw_pcm_hash=14695981039346656037ULL,raw_mixed_nonzero=0;
    unsigned raw_peak=0,latency_source_frames=0;
};
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
    void enable(AudioProfile profile=AudioProfile::raw,unsigned output_rate=44100,
                AudioTiming timing=AudioTiming::gear);
    AudioProfile profile() const;
    AudioTiming timing() const;
    unsigned output_rate() const;
    AudioProcessingStats processing_stats() const;
    // The bus notifies presentation history of guest ADPCM reset writes,
    // including pulses that begin and end between source sample edges.
    void reset_adpcm_filter();
    void advance_to(Bus&,std::uint64_t ticks);
    std::vector<std::int16_t> drain();
    std::size_t queued_frames() const {return count_;}
private:
    friend struct AudioCheckpointAccess;
    std::array<std::array<std::int16_t,2>,capacity> queue_{};
    std::unique_ptr<CddaStreamState> cd_cache_;
    std::size_t begin_=0,count_=0;
    std::uint64_t next_tick_=487;
    unsigned remainder_=573;
    void append(std::array<std::int16_t,2>);
};
} // namespace pce
