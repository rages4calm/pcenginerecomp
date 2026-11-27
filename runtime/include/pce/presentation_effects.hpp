#pragma once
#include "pce/presentation_history.hpp"
#include <algorithm>

namespace pce {

struct PresentationEffectSettings {
    unsigned softness=0, persistence=0;
    bool valid() const {return softness<=100 && persistence<=100;}
    bool operator==(const PresentationEffectSettings&) const=default;
};

struct PresentationEffectResult {
    // Borrowed until the next apply()/invalidate(), or from the caller's frame
    // when disabled. This is a host effect, not guest reconstruction evidence.
    const VideoFrame& frame;
    PresentationAdmission admission;
};

inline const char* presentation_break_name(PresentationBreak reason) {
    switch(reason) {
    case PresentationBreak::none:return "none";
    case PresentationBreak::first_frame:return "first_frame";
    case PresentationBreak::reset:return "reset";
    case PresentationBreak::missing_reconstruction:return "missing_reconstruction";
    case PresentationBreak::invalid_reconstruction:return "invalid_reconstruction";
    case PresentationBreak::pixel_mismatch:return "pixel_mismatch";
    case PresentationBreak::scene_change:return "scene_change";
    case PresentationBreak::extent_change:return "extent_change";
    case PresentationBreak::epoch_change:return "epoch_change";
    case PresentationBreak::sequence_gap:return "sequence_gap";
    case PresentationBreak::clock_gap:return "clock_gap";
    case PresentationBreak::cut:return "cut";
    case PresentationBreak::repeated_frame:return "repeated_frame";
    case PresentationBreak::view_change:return "view_change";
    }
    return "unknown";
}

// Deterministic host-only RGB effects. The caller supplies completed-frame
// sequence/ticks and invalidates epochs after restore/rewind or state edits.
// This uses PresentationHistory for continuity only: comparing the supplied
// frame with itself does NOT qualify a port's original-size reconstruction.
// Ports must perform that independent gate before providing an enhanced frame.
// No guest memory, device, clock or serialized state is read or changed.
class PresentationEffects {
    PresentationHistory history_;
    std::optional<PresentationEffectSettings> settings_;
    VideoFrame source_, output_;

    static bool same_frame(const VideoFrame& left,const VideoFrame& right) {
        return left.width==right.width && left.height==right.height && left.rgb==right.rgb;
    }
    static PresentationEffectResult selected(const VideoFrame& frame,const PresentationAdmission& state) {
        return {frame,{frame,state.exact,state.interpolation,state.reason}};
    }
public:
    explicit PresentationEffects(std::uint64_t max_tick_gap):history_(max_tick_gap) {}
    PresentationEffects(const PresentationEffects&)=delete;
    PresentationEffects& operator=(const PresentationEffects&)=delete;
    PresentationEffects(PresentationEffects&&)=delete;
    PresentationEffects& operator=(PresentationEffects&&)=delete;

    void invalidate() {
        history_.invalidate();settings_.reset();source_={};output_={};
    }
    bool has_previous() const {return history_.has_previous();}

    PresentationEffectResult apply(const VideoFrame& frame,const PresentationStamp& stamp,
                                   const PresentationEffectSettings& settings={}) {
        try {
            // Borrowed results are immutable and expire at the next call. Copy
            // one to a caller-owned frame before using it as this helper's input.
            if(&frame==&output_ || &frame==&source_)
                throw Fault("presentation effect input aliases a borrowed result");
            if(!settings.valid())throw Fault("presentation effect percentage out of range");
            if(settings_ && *settings_!=settings)invalidate();
            const auto admission=[&] {
                auto observed=history_.observe(frame,frame,stamp);
                if((settings.softness || settings.persistence) &&
                   observed.reason==PresentationBreak::repeated_frame && !same_frame(frame,source_)) {
                    // Changed RGB under a repeated timestamp is not a new guest
                    // frame. Clear the trail instead of reusing stale pixels.
                    invalidate();
                    return history_.observe(frame,frame,stamp);
                }
                return observed;
            }();
            if(!settings.softness && !settings.persistence) {
                // No image allocation or retained temporal state while disabled.
                invalidate();
                return selected(frame,admission);
            }
            if(admission.reason==PresentationBreak::repeated_frame) {
                return selected(output_,admission);
            }

            VideoFrame next{frame.width,frame.height,{}};
            next.rgb.resize(frame.rgb.size());
            for(unsigned y=0;y<frame.height;++y) {
                for(unsigned x=0;x<frame.width;++x) {
                    const auto center=(std::size_t(y)*frame.width+x)*3;
                    const auto left=x ? center-3:center;
                    const auto right=x+1<frame.width ? center+3:center;
                    for(unsigned channel=0;channel<3;++channel) {
                        const unsigned value=frame.rgb[center+channel];
                        // Edge-clamped [1,2,1]/4, nearest integer with ties up;
                        // percentage mixing also rounds to nearest, ties up.
                        const unsigned blur=(frame.rgb[left+channel]+2*value+
                                             frame.rgb[right+channel]+2)/4;
                        unsigned result=(value*(100-settings.softness)+
                                         blur*settings.softness+50)/100;
                        if(settings.persistence && admission.interpolation) {
                            // One floor-rounded retention per admitted completed
                            // frame. This is an artistic effect, not an analog
                            // phosphor model or a time-based decay constant.
                            result=std::max(result,unsigned(output_.rgb[center+channel])*
                                                   settings.persistence/100);
                        }
                        next.rgb[center+channel]=static_cast<std::uint8_t>(result);
                    }
                }
            }
            source_=frame;output_=std::move(next);settings_=settings;
            return selected(output_,admission);
        } catch(...) {
            invalidate();throw;
        }
    }
};
} // namespace pce
