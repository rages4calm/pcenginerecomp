#pragma once

#include "pce/runtime.hpp"

namespace pce {
using Sector = std::array<std::uint8_t,2048>;

// User-data sectors only. Audio, gaps and undecodable data must throw Fault.
// An attached provider is single-threaded and never modifies its source image.
class SectorProvider {
public:
    virtual ~SectorProvider() = default;
    virtual Sector read(std::uint32_t lba) = 0;
    virtual const CdToc& toc() const = 0;
};

// ISO: single-track cooked MODE1. CHD: v5 MODE1/MODE1_RAW plus audio TOC;
// CHD decoding requires an explicitly selected optional libchdr shared library.
// The actual file is SHA256-pinned, metadata bounded, and only one decoded hunk
// (at most 512 KiB) is retained. Source size/mtime changes refuse further reads.
std::shared_ptr<SectorProvider> open_sector_provider(
    const std::string& image, const std::string& libchdr="");
std::string image_sha256(const std::string& image);
} // namespace pce
