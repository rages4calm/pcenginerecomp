#include "pce/presentation_effects.hpp"
#include <iostream>
#include <limits>
#include <string_view>

namespace {
unsigned checks=0;
void require(bool good,const char* message) {
    ++checks;if(!good)throw pce::Fault(message);
}
template<class F> void refuses(F operation) {
    ++checks;try{operation();}catch(const pce::Fault&){return;}
    throw pce::Fault("expected presentation effect refusal");
}
pce::PresentationStamp stamp(std::uint64_t sequence=1,std::uint64_t ticks=100) {
    return {.sequence=sequence,.ticks=ticks,.scene=7,.epoch=3,.width=640,.height=480};
}
const pce::VideoFrame bright{1,1,{101,201,255}}, dark{1,1,{0,0,0}};
void pixels(const pce::VideoFrame& frame,std::initializer_list<std::uint8_t> expected) {
    require(frame.rgb==std::vector<std::uint8_t>(expected),"literal effect RGB differs");
}
}

int main() {
    using namespace pce;
    refuses([]{PresentationEffects effects(0);});
    PresentationEffects effects(100);

    // Disabled processing is an identity with no retained image/history.
    const auto disabled=effects.apply(bright,stamp());
    require(&disabled.frame==&bright && &disabled.admission.frame==&bright,
            "disabled effects copied/replaced source image");
    require(!effects.has_previous(),"disabled effects retained temporal state");

    // Independently calculated, channel-separated edge clamp and tie rounding.
    const VideoFrame row{3,1,{0,10,200,100,30,0,0,90,100}};
    const auto soft=effects.apply(row,stamp(),{100,0});
    pixels(soft.frame,{25,15,150,50,40,75,25,75,75});
    require(soft.admission.reason==PresentationBreak::reset && !soft.admission.interpolation,
            "first effect application retained disabled history");
    require(&soft.admission.frame==&soft.frame,"effect metadata borrowed a different image");
    const auto half=effects.apply(row,stamp(2,200),{50,0});
    pixels(half.frame,{13,13,175,75,35,38,13,83,88});
    require(half.admission.reason==PresentationBreak::reset && !half.admission.interpolation,
            "changed softness retained history");
    const auto original=row.rgb;
    for(unsigned n=0;n<5;++n) {
        const auto repeated=effects.apply(row,stamp(2,200),{50,0});
        pixels(repeated.frame,{13,13,175,75,35,38,13,83,88});
        require(repeated.admission.reason==PresentationBreak::repeated_frame &&
                !repeated.admission.interpolation,"paused effect redraw advanced history");
    }
    require(row.rgb==original,"softness modified caller-owned RGB");
    const VideoFrame two_rows{1,2,{101,201,255,0,0,0}};
    pixels(effects.apply(two_rows,stamp(3,300),{100,0}).frame,{101,201,255,0,0,0});
    for(unsigned strength:{0u,1u,50u,99u,100u}) {
        effects.invalidate();
        pixels(effects.apply(bright,stamp(),{strength,0}).frame,{101,201,255});
    }

    // Retention is floor-rounded exactly once per admitted completed frame.
    effects.invalidate();
    pixels(effects.apply(bright,stamp(),{0,95}).frame,{101,201,255});
    const auto faded=effects.apply(dark,stamp(2,200),{0,95});
    pixels(faded.frame,{95,190,242});
    require(faded.admission.interpolation && faded.admission.reason==PresentationBreak::none,
            "continuous effect pair was not admitted");
    for(unsigned n=0;n<12;++n) {
        const auto repeated=effects.apply(dark,stamp(2,200),{0,95});
        pixels(repeated.frame,{95,190,242});
        require(repeated.admission.reason==PresentationBreak::repeated_frame,
                "capture/redraw consumed persistence");
    }
    pixels(effects.apply(dark,stamp(3,300),{0,95}).frame,{90,180,229});
    effects.invalidate();
    (void)effects.apply(bright,stamp(),{0,50});
    pixels(effects.apply(dark,stamp(2,200),{0,50}).frame,{50,100,127});
    pixels(effects.apply(dark,stamp(3,300),{0,50}).frame,{25,50,63});

    // Combined effects retain the FILTERED prior image, then take a per-channel
    // maximum with the current filtered image; no blur feeds back during redraw.
    effects.invalidate();
    const VideoFrame left_light{3,1,{100,0,0,0,0,0,0,0,0}};
    const VideoFrame right_light{3,1,{0,0,0,0,0,0,100,0,0}};
    const VideoFrame all_dark{3,1,std::vector<std::uint8_t>(9,0)};
    pixels(effects.apply(left_light,stamp(),{100,50}).frame,{75,0,0,25,0,0,0,0,0});
    pixels(effects.apply(right_light,stamp(2,200),{100,50}).frame,{37,0,0,25,0,0,75,0,0});
    pixels(effects.apply(all_dark,stamp(3,300),{100,50}).frame,{18,0,0,12,0,0,37,0,0});
    const auto changed_strength=effects.apply(all_dark,stamp(4,400),{100,100});
    pixels(changed_strength.frame,{0,0,0,0,0,0,0,0,0});
    require(changed_strength.admission.reason==PresentationBreak::reset,
            "persistence setting change retained earlier trail");

    // Full retention is an explicit artistic hold, not a guessed decay model.
    effects.invalidate();
    (void)effects.apply(bright,stamp(),{0,100});
    const VideoFrame new_bright{1,1,{255,10,20}};
    pixels(effects.apply(new_bright,stamp(2,200),{0,100}).frame,{255,201,255});
    pixels(effects.apply(dark,stamp(3,300),{0,100}).frame,{255,201,255});

    // An altered source under the SAME stamp must not return cached pixels or
    // advance a fabricated frame. It resets, then warms from that new source.
    const auto changed_repeat=effects.apply(dark,stamp(3,300),{0,100});
    // It is still identical to the prior raw source, so retain the cached trail.
    pixels(changed_repeat.frame,{255,201,255});
    const VideoFrame edited{1,1,{1,2,3}};
    const auto edited_repeat=effects.apply(edited,stamp(3,300),{0,100});
    pixels(edited_repeat.frame,{1,2,3});
    require(edited_repeat.admission.reason==PresentationBreak::reset &&
            !edited_repeat.admission.interpolation,"changed repeated source reused stale trail");
    pixels(effects.apply(dark,stamp(4,400),{0,100}).frame,{1,2,3});

    // Every shared continuity break starts a fresh display history. The next
    // regular frame may retain only this new source, never the old bright one.
    const auto transition=[&](PresentationStamp changed,PresentationBreak reason) {
        PresentationEffects local(100);
        (void)local.apply(bright,stamp(),{0,100});
        const auto reset=local.apply(edited,changed,{0,100});
        pixels(reset.frame,{1,2,3});
        require(reset.admission.reason==reason && !reset.admission.interpolation,
                "discontinuity retained effect history");
        changed.cut=false;++changed.sequence;changed.ticks+=100;
        pixels(local.apply(dark,changed,{0,100}).frame,{1,2,3});
    };
    auto changed=stamp(2,200);changed.epoch=4;transition(changed,PresentationBreak::epoch_change);
    changed=stamp(2,200);changed.scene=8;transition(changed,PresentationBreak::scene_change);
    changed=stamp(2,200);changed.view=1;transition(changed,PresentationBreak::view_change);
    changed=stamp(2,200);changed.width=800;transition(changed,PresentationBreak::extent_change);
    changed=stamp(2,200);changed.height=600;transition(changed,PresentationBreak::extent_change);
    changed=stamp(2,200);changed.cut=true;transition(changed,PresentationBreak::cut);
    transition(stamp(3,200),PresentationBreak::sequence_gap);
    transition(stamp(1,200),PresentationBreak::sequence_gap);
    transition(stamp(2,100),PresentationBreak::clock_gap);
    transition(stamp(2,99),PresentationBreak::clock_gap);
    transition(stamp(2,201),PresentationBreak::clock_gap);
    transition(stamp(1,99),PresentationBreak::sequence_gap);

    effects.invalidate();
    (void)effects.apply(bright,stamp(),{0,100});
    const VideoFrame reshaped{3,1,{0,0,0,0,0,0,0,0,0}};
    const auto shape=effects.apply(reshaped,stamp(2,200),{0,100});
    pixels(shape.frame,{0,0,0,0,0,0,0,0,0});
    require(shape.admission.reason==PresentationBreak::extent_change,"source shape retained trail");
    effects.invalidate();
    const auto reset=effects.apply(dark,stamp(2,200),{0,100});
    require(reset.admission.reason==PresentationBreak::reset,"explicit invalidate did not reset");
    effects.invalidate();
    (void)effects.apply(bright,stamp(std::numeric_limits<std::uint64_t>::max(),100),{0,100});
    require(effects.apply(dark,stamp(1,200),{0,100}).admission.reason==PresentationBreak::sequence_gap,
            "sequence wrap retained trail");

    for(const auto settings:{PresentationEffectSettings{101,0},{0,101},
                             {std::numeric_limits<unsigned>::max(),0}}) {
        (void)effects.apply(bright,stamp(),{0,50});
        refuses([&]{(void)effects.apply(bright,stamp(2,200),settings);});
        require(!effects.has_previous(),"invalid settings retained history");
    }
    for(const auto& malformed:{VideoFrame{0,1,{}},VideoFrame{1,0,{}},VideoFrame{1,1,{}},
            VideoFrame{1,1,{0,1,2,3}},VideoFrame{8193,1,{}},VideoFrame{8192,2049,{}},
            VideoFrame{std::numeric_limits<unsigned>::max(),2,{}}}) {
        refuses([&]{(void)effects.apply(malformed,stamp(),{0,100});});
        require(!effects.has_previous(),"malformed image retained history");
    }
    for(const auto& malformed:{PresentationStamp{},PresentationStamp{.sequence=1,.width=0,.height=1},
            PresentationStamp{.sequence=1,.width=8193,.height=1},
            PresentationStamp{.sequence=1,.width=8192,.height=2049}}) {
        refuses([&]{(void)effects.apply(bright,malformed,{0,100});});
    }
    const VideoFrame widest{8192,1,std::vector<std::uint8_t>(8192*3,17)};
    const auto legal=effects.apply(widest,stamp(),{100,100});
    require(legal.frame.rgb==widest.rgb,"legal maximum axis rejected/changed uniform color");
    const auto& borrowed=legal.frame;
    refuses([&]{(void)effects.apply(borrowed,stamp(2,200),{100,100});});
    require(!effects.has_previous(),"borrowed-input alias retained unsafe history");

    const PresentationBreak reasons[]={PresentationBreak::none,PresentationBreak::first_frame,
        PresentationBreak::reset,PresentationBreak::missing_reconstruction,PresentationBreak::invalid_reconstruction,
        PresentationBreak::pixel_mismatch,PresentationBreak::scene_change,PresentationBreak::extent_change,
        PresentationBreak::epoch_change,PresentationBreak::sequence_gap,PresentationBreak::clock_gap,
        PresentationBreak::cut,PresentationBreak::repeated_frame,PresentationBreak::view_change};
    const char* names[]={"none","first_frame","reset","missing_reconstruction","invalid_reconstruction",
        "pixel_mismatch","scene_change","extent_change","epoch_change","sequence_gap","clock_gap",
        "cut","repeated_frame","view_change"};
    for(unsigned n=0;n<std::size(reasons);++n)
        require(std::string_view(presentation_break_name(reasons[n]))==names[n],"presentation reason label differs");
    require(std::string_view(presentation_break_name(static_cast<PresentationBreak>(999)))=="unknown",
            "invalid presentation reason label guessed");
    std::cout<<checks<<" independent host effect RGB/continuity/refusal checks passed\n";
}
