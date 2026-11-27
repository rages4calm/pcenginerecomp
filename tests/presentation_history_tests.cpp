#include "pce/presentation_history.hpp"
#include <iostream>
#include <limits>

namespace {
unsigned checks=0;
void require(bool good,const char* message) {
    ++checks;if(!good)throw pce::Fault(message);
}
template<class F> void refuses(F operation) {
    ++checks;try{operation();}catch(const pce::Fault&){return;}
    throw pce::Fault("expected presentation refusal");
}
const pce::VideoFrame original{2,2,{1,2,3,4,5,6,7,8,9,10,11,12}};
pce::PresentationStamp stamp(std::uint64_t seq=1,std::uint64_t ticks=100) {
    return {.sequence=seq,.ticks=ticks,.scene=7,.epoch=3,.width=640,.height=480};
}
}

int main() {
    using namespace pce;
    refuses([]{PresentationHistory bad(0);});
    PresentationHistory gate(100);
    auto clone=original;
    auto decision=gate.observe(original,clone,stamp());
    require(decision.exact && !decision.interpolation && decision.reason==PresentationBreak::first_frame,
            "first exact frame enabled interpolation");
    require(&decision.frame==&clone && gate.has_previous(),"exact frame not admitted");
    const auto second=gate.observe(original,clone,stamp(2,200));
    require(second.interpolation && second.reason==PresentationBreak::none,"continuous exact pair rejected");

    // An independent literal expectation catches mismatch in each channel and
    // at both ends. No comparison implementation is used to derive expectations.
    for(unsigned channel=0;channel<12;++channel) {
        auto bad=original;bad.rgb[channel]^=0x80;
        const auto mismatch=gate.observe(original,bad,stamp(3,300));
        require(!mismatch.exact && !mismatch.interpolation && &mismatch.frame==&original &&
                mismatch.reason==PresentationBreak::pixel_mismatch && !gate.has_previous(),
                "changed reconstruction pixel escaped gate");
        const auto warmup=gate.observe(original,clone,stamp(4,400));
        require(!warmup.interpolation && warmup.reason==PresentationBreak::reset,
                "mismatch retained temporal history");
        require(gate.observe(original,clone,stamp(5,500)).interpolation,"mismatch recovery failed");
    }

    for(const auto& malformed: {
        VideoFrame{0,2,{}}, VideoFrame{2,0,{}}, VideoFrame{2,2,{1,2,3}},
        VideoFrame{1,1,{1,2,3,4}}, VideoFrame{8193,1,{}},
        VideoFrame{8192,8192,{}}, VideoFrame{std::numeric_limits<unsigned>::max(),2,{}}}) {
        const auto result=gate.observe(original,malformed,stamp(6,600));
        require(!result.exact && !result.interpolation && &result.frame==&original &&
                result.reason==PresentationBreak::invalid_reconstruction,"malformed reconstruction admitted");
        refuses([&]{(void)gate.observe(malformed,clone,stamp(7,700));});
        require(!gate.has_previous(),"malformed original retained history");
    }
    const auto missing=gate.observe(original,nullptr,stamp(8,800));
    require(&missing.frame==&original && missing.reason==PresentationBreak::missing_reconstruction,
            "missing reconstruction didn't preserve original");
    const VideoFrame reshaped{1,4,original.rgb};
    require(gate.observe(original,reshaped,stamp(9,900)).reason==PresentationBreak::pixel_mismatch,
            "equal byte count admitted changed geometry");
    for(const auto broken: {PresentationStamp{}, PresentationStamp{.sequence=1,.width=8193,.height=1},
                           PresentationStamp{.sequence=1,.width=8192,.height=8192}}) {
        refuses([&]{(void)gate.observe(original,clone,broken);});
    }

    // Each transition starts with a literal baseline and checks a single
    // independent discontinuity, followed by the next valid continuous frame.
    const auto transition=[&](PresentationStamp changed,PresentationBreak expected) {
        PresentationHistory history(100);
        (void)history.observe(original,clone,stamp());
        const auto actual=history.observe(original,clone,changed);
        require(actual.exact && !actual.interpolation && actual.reason==expected,
                "discontinuous pair enabled interpolation");
        changed.cut=false;++changed.sequence;changed.ticks+=100;
        require(history.observe(original,clone,changed).interpolation,"discontinuity recovery failed");
    };
    auto changed=stamp(2,200);changed.scene=8;transition(changed,PresentationBreak::scene_change);
    changed=stamp(2,200);changed.epoch=4;transition(changed,PresentationBreak::epoch_change);
    changed=stamp(2,200);changed.view=1;transition(changed,PresentationBreak::view_change);
    changed=stamp(2,200);changed.width=800;transition(changed,PresentationBreak::extent_change);
    changed=stamp(2,200);changed.height=600;transition(changed,PresentationBreak::extent_change);
    changed=stamp(2,200);changed.cut=true;transition(changed,PresentationBreak::cut);
    transition(stamp(3,200),PresentationBreak::sequence_gap);
    transition(stamp(1,200),PresentationBreak::sequence_gap);
    transition(stamp(2,100),PresentationBreak::clock_gap);
    transition(stamp(2,99),PresentationBreak::clock_gap);
    transition(stamp(2,201),PresentationBreak::clock_gap);

    PresentationHistory paused(100);
    (void)paused.observe(original,clone,stamp());
    for(unsigned n=0;n<5;++n)require(paused.observe(original,clone,stamp()).reason==PresentationBreak::repeated_frame,
                                  "paused redraw consumed history");
    require(paused.observe(original,clone,stamp(2,200)).interpolation,"paused redraw broke next pair");
    paused.invalidate();
    const auto restored=paused.observe(original,clone,stamp(2,200));
    require(!restored.interpolation && restored.reason==PresentationBreak::reset,
            "same-sequence checkpoint restore reused history");
    require(paused.observe(original,clone,stamp(3,300)).interpolation,"post-restore warmup failed");

    // Changed guest source geometry also breaks the pair even with fixed output.
    PresentationHistory geometry(100);
    (void)geometry.observe(original,clone,stamp());
    require(geometry.observe(reshaped,reshaped,stamp(2,200)).reason==PresentationBreak::extent_change,
            "reference geometry change allowed interpolation");
    PresentationHistory wrapping(100);
    (void)wrapping.observe(original,clone,stamp(std::numeric_limits<std::uint64_t>::max(),100));
    require(wrapping.observe(original,clone,stamp(1,200)).reason==PresentationBreak::sequence_gap,
            "wrapped sequence allowed interpolation");
    std::cout<<checks<<" authored reconstruction/continuity/fallback/reset checks passed\n";
}
