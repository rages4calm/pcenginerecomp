#pragma once

#include "pce/runtime.hpp"

namespace pce {
using Sector = std::array<std::uint8_t,2048>;
// One Red Book sector: 588 interleaved stereo frames, signed 16-bit values.
// Values are host numeric samples, independent of image or host byte order.
using AudioSector = std::array<std::int16_t,1176>;

// read() accepts user data only; audio/gaps/undecodable data throw Fault.
// read_audio() returns stored AUDIO payload only. audio_playable() separately
// describes the reference playback gate, including deliberate data/gap silence.
// An attached provider is single-threaded and never modifies its source image.
class SectorProvider {
public:
    virtual ~SectorProvider() = default;
    virtual Sector read(std::uint32_t lba) = 0;
    virtual AudioSector read_audio(std::uint32_t) {
        throw Fault("Sector provider does not support raw audio sectors");
    }
    virtual bool audio_playable(std::uint32_t) const {
        throw Fault("Sector provider does not classify audio geometry");
    }
    virtual const CdToc& toc() const = 0;
};

// ISO: single-track cooked MODE1. CHD: v5 MODE1/MODE1_RAW and AUDIO;
// CUE: bounded BINARY MODE1/2048, MODE1/2352 and little-endian AUDIO files.
// CHD decoding requires an explicitly selected optional libchdr shared library.
// The actual file is SHA256-pinned, metadata bounded, and only one decoded hunk
// (at most 512 KiB) is retained. Source size/mtime changes refuse further reads.
std::shared_ptr<SectorProvider> open_sector_provider(
    const std::string& image, const std::string& libchdr="");
// CUE returns the documented complete-image digest of the exact cue plus every
// referenced file; ISO/CHD retain their raw file SHA256 identity.
std::string image_sha256(const std::string& image);
} // namespace pce
