#pragma once
#include <algorithm>
#include <cstdint>
#include <limits>

namespace pce {
enum class PaceReset { none, initial, paused, guest_backwards, wall_backwards, guest_jump, target_overflow, late };
struct PaceDecision {
    std::uint64_t wait_ns=0, lateness_ns=0;
    PaceReset reset=PaceReset::none;
};

// Host presentation policy only. The caller supplies the completed guest tick
// and a monotonic wall clock. No guest state, PCM, audio queue or clock is edited.
class HostPacer {
    bool anchored_=false;
    std::uint64_t anchor_tick_=0,anchor_ns_=0,last_tick_=0,last_ns_=0;
    PaceDecision rebase(std::uint64_t ticks,std::uint64_t now,PaceReset reason,std::uint64_t late=0) {
        anchored_=true;anchor_tick_=last_tick_=ticks;anchor_ns_=last_ns_=now;
        return {0,late,reason};
    }
public:
    static constexpr std::uint64_t master_clock=21477273,second_ns=1000000000,max_wait_ns=second_ns/10;
    void reset() {anchored_=false;}
    PaceDecision plan(std::uint64_t ticks,std::uint64_t now,bool paused=false) {
        if(!anchored_)return rebase(ticks,now,PaceReset::initial);
        if(paused)return rebase(ticks,now,PaceReset::paused);
        if(ticks<last_tick_)return rebase(ticks,now,PaceReset::guest_backwards);
        if(now<last_ns_)return rebase(ticks,now,PaceReset::wall_backwards);
        last_tick_=ticks;last_ns_=now;
        const auto delta=ticks-anchor_tick_;
        if(delta/master_clock>3600)return rebase(ticks,now,PaceReset::guest_jump);
        const auto elapsed=(delta/master_clock)*second_ns+(delta%master_clock)*second_ns/master_clock;
        if(elapsed>std::numeric_limits<std::uint64_t>::max()-anchor_ns_)
            return rebase(ticks,now,PaceReset::target_overflow);
        const auto target=anchor_ns_+elapsed;
        // Missing a completed-frame deadline is host time that cannot be
        // recovered by bursting old PCM into a bounded real-time audio stream.
        if(now>target)return rebase(ticks,now,PaceReset::late,now-target);
        return {std::min(target-now,max_wait_ns),0,PaceReset::none};
    }
};
} // namespace pce
