#pragma once
#include "pce/runtime.hpp"
#include <limits>
#include <optional>

namespace pce {

// The port supplies scene identity and presentation extent. Neither is inferred
// from pixels or guest addresses. Advance epoch, or invalidate the history,
// after a checkpoint load, rewind, state edit or other out-of-band change.
struct PresentationStamp {
    std::uint64_t sequence=0, ticks=0, scene=0, epoch=0;
    unsigned width=0, height=0;
    std::uint64_t view=0;
    bool cut=false;
};

enum class PresentationBreak {
    none, first_frame, reset, missing_reconstruction, invalid_reconstruction,
    pixel_mismatch, scene_change, extent_change, epoch_change,
    sequence_gap, clock_gap, cut, repeated_frame, view_change
};

struct PresentationAdmission {
    // Borrowed from the call arguments. Both input frames must outlive use of
    // this result. The original guest image is selected on reconstruction failure.
    const VideoFrame& frame;
    bool exact=false;
    bool interpolation=false;
    PresentationBreak reason=PresentationBreak::first_frame;
};

// A bounded, host-only gate, not an interpolation renderer or frame scheduler.
// The port first reconstructs the current guest image at original positions.
// Only an exact reconstruction can participate in a continuous frame pair.
// No image history is retained and no guest state or guest clock is changed.
class PresentationHistory {
    static constexpr unsigned max_axis=8192;
    static constexpr std::uint64_t max_pixels=16*1024*1024;
    std::uint64_t max_tick_gap_;
    std::optional<PresentationStamp> previous_;
    unsigned source_width_=0, source_height_=0;
    bool reset_=false;

    static bool valid_extent(unsigned width,unsigned height) {
        return width && height && width<=max_axis && height<=max_axis &&
            std::uint64_t(width)*height<=max_pixels;
    }
    static bool valid_frame(const VideoFrame& frame) {
        return valid_extent(frame.width,frame.height) &&
            frame.rgb.size()==std::uint64_t(frame.width)*frame.height*3;
    }
    void remember(const PresentationStamp& stamp,const VideoFrame& guest) {
        previous_=stamp;source_width_=guest.width;source_height_=guest.height;reset_=false;
    }
public:
    // Supply a guest-clock gap bound appropriate for the port's completed-frame
    // cadence. This is an upper bound, not a guessed fixed refresh period.
    explicit PresentationHistory(std::uint64_t max_tick_gap):max_tick_gap_(max_tick_gap) {
        if(!max_tick_gap_)throw Fault("presentation history requires a positive tick-gap bound");
    }
    void invalidate() {
        previous_.reset();source_width_=source_height_=0;reset_=true;
    }
    bool has_previous() const {return previous_.has_value();}

    PresentationAdmission observe(const VideoFrame& guest,const VideoFrame* reconstructed,
                                  const PresentationStamp& stamp) {
        if(!valid_frame(guest) || !stamp.sequence || !valid_extent(stamp.width,stamp.height)) {
            invalidate();
            throw Fault("invalid original frame or presentation stamp");
        }
        if(!reconstructed || !valid_frame(*reconstructed)) {
            const auto reason=reconstructed ? PresentationBreak::invalid_reconstruction:
                PresentationBreak::missing_reconstruction;
            invalidate();
            return {guest,false,false,reason};
        }
        if(guest.width!=reconstructed->width || guest.height!=reconstructed->height ||
           guest.rgb!=reconstructed->rgb) {
            invalidate();
            return {guest,false,false,PresentationBreak::pixel_mismatch};
        }

        auto reason=reset_ ? PresentationBreak::reset:PresentationBreak::first_frame;
        if(previous_) {
            const auto& before=*previous_;
            if(stamp.epoch!=before.epoch)reason=PresentationBreak::epoch_change;
            else if(stamp.scene!=before.scene)reason=PresentationBreak::scene_change;
            else if(stamp.view!=before.view)reason=PresentationBreak::view_change;
            else if(stamp.width!=before.width || stamp.height!=before.height ||
                    guest.width!=source_width_ || guest.height!=source_height_)
                reason=PresentationBreak::extent_change;
            else if(stamp.cut)reason=PresentationBreak::cut;
            else if(stamp.sequence==before.sequence && stamp.ticks==before.ticks)
                // An exact paused redraw doesn't consume or replace history.
                return {*reconstructed,true,false,PresentationBreak::repeated_frame};
            else if(before.sequence==std::numeric_limits<std::uint64_t>::max() ||
                    stamp.sequence!=before.sequence+1)
                reason=PresentationBreak::sequence_gap;
            else if(stamp.ticks<=before.ticks || stamp.ticks-before.ticks>max_tick_gap_)
                reason=PresentationBreak::clock_gap;
            else reason=PresentationBreak::none;
        } else if(stamp.cut)reason=PresentationBreak::cut;
        remember(stamp,guest);
        return {*reconstructed,true,reason==PresentationBreak::none,reason};
    }
    PresentationAdmission observe(const VideoFrame& guest,const VideoFrame& reconstructed,
                                  const PresentationStamp& stamp) {
        return observe(guest,&reconstructed,stamp);
    }
};
} // namespace pce
