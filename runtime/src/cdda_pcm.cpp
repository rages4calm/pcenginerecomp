#include "pce/cdda_pcm.hpp"

namespace pce {
std::array<std::int16_t,2> CddaPcmCache::sample(const std::shared_ptr<SectorProvider>& source,
                                            std::uint32_t lba,unsigned stereo_frame) {
    if(!source) throw Fault("CD audio PCM requires an attached sector provider");
    if(stereo_frame>=588) throw Fault("CD audio PCM frame is outside its sector");
    if(!valid_ || source_.lock()!=source || lba_!=lba) {
        // Commit the cache only after a complete successful read. Failed
        // lookups must not expose stale samples under the new identity.
        // Non-audio geometry is explicit reference behavior: data sectors,
        // unstored gaps, and nonplayable lead-ins generate silence. Actual
        // audio read/decode faults still propagate; they are never muted.
        const auto next=source->audio_playable(lba) ? source->read_audio(lba):AudioSector{};
        samples_=next;source_=source;lba_=lba;valid_=true;
    }
    return {samples_[stereo_frame*2],samples_[stereo_frame*2+1]};
}
} // namespace pce
