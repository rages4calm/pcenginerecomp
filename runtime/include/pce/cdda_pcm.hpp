#pragma once
#include "pce/sector.hpp"

namespace pce {
// Presentation-side raw lookup only. Guest seek/sector/stop timing and gain
// belong to CdAudio/CdControl. Exactly one sector is retained per instance.
class CddaPcmCache {
    std::weak_ptr<SectorProvider> source_;
    AudioSector samples_{};
    std::uint32_t lba_=0;
    bool valid_=false;
public:
    void reset() { source_.reset();valid_=false; }
    std::array<std::int16_t,2> sample(const std::shared_ptr<SectorProvider>&,
                                    std::uint32_t lba,unsigned stereo_frame);
};
} // namespace pce
