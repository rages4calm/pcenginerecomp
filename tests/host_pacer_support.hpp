#pragma once
#include "pce/host_pacer.hpp"
#include <array>
#include <cstdint>
#include <limits>
#include <stdexcept>

namespace host_pacer_fixture {
// Independent retained pre-fix policy; this model owns no guest state.
struct Legacy {
    std::uint64_t tick=0,wall=0;
    pce::PaceDecision plan(std::uint64_t at,std::uint64_t now) {
        const auto delta=at-tick;
        const auto target=wall+(delta/21477273)*1000000000+(delta%21477273)*1000000000/21477273;
        if(now>target && now-target>250000000) {tick=at;wall=now;return {};}
        return {target>now ? std::min<std::uint64_t>(target-now,100000000):0,0,pce::PaceReset::none};
    }
};
struct Queue {
    unsigned rate;
    std::uint64_t now=0,fraction=0,pending=0,peak=0,submitted=0,accepted=0,dropped=0,overflow_clears=0,pause_clears=0,resume_clears=0;
    void advance(std::uint64_t at) {
        const auto duration=at-now;now=at;
        const auto parts=(duration%1000000000)*rate+fraction;
        const auto frames=(duration/1000000000)*rate+parts/1000000000;fraction=parts%1000000000;
        const auto consumed=std::min(pending,frames);pending-=consumed;accepted+=consumed;
    }
    void put(std::uint64_t frames) {
        if(pending+frames>4410) {dropped+=pending;pending=0;++overflow_clears;}
        pending+=frames;submitted+=frames;peak=std::max(peak,pending);
    }
    void pause() {dropped+=pending;pending=0;++pause_clears;}
    void resume() {dropped+=pending;pending=0;++resume_clears;}
};
struct Result {
    Queue queue;
    std::uint64_t ticks=0,wall=0,hash=1469598103934665603ull,late_rebases=0;
};
template<class Pacer> Result route(unsigned rate,unsigned stall_ms) {
    Pacer pacer;
    if constexpr(requires {pacer.reset();}) (void)pacer.plan(0,0);
    Result result{Queue{rate}};std::uint64_t produced=0;
    for(unsigned frame=1;frame<=180;++frame) {
        result.ticks+=357954;
        result.wall+=1000000; // One millisecond of main-thread production.
        if(frame==30)result.wall+=std::uint64_t(stall_ms)*1000000;
        result.queue.advance(result.wall);
        const auto total=result.ticks*rate/21477273;
        for(auto i=produced;i<total;++i) {
            const auto signed_sample=std::int16_t(int((i*31)%60001)-30000);
            result.hash=(result.hash^std::uint16_t(signed_sample))*1099511628211ull;
        }
        result.queue.put(total-produced);produced=total;
        const auto decision=pacer.plan(result.ticks,result.wall);
        if(decision.reset==pce::PaceReset::late)++result.late_rebases;
        result.wall+=decision.wait_ns;result.queue.advance(result.wall);
    }
    return result;
}
inline unsigned run() {
    unsigned checks=0;
    const auto require=[&](bool good,const char* message) {if(!good)throw std::runtime_error(message);++checks;};
    for(unsigned rate:{44100u,48000u}) {
        const auto steady=route<pce::HostPacer>(rate,0);
        require(!steady.late_rebases && !steady.queue.overflow_clears,"Steady producer drifted or cleared audio");
        for(unsigned stall:{50u,100u,150u,249u,251u}) {
            auto fixed=route<pce::HostPacer>(rate,stall);const auto old=route<Legacy>(rate,stall);
            require(fixed.ticks==steady.ticks && fixed.queue.submitted==steady.queue.submitted && fixed.hash==steady.hash,
                    "Host pacing modified guest ticks, PCM count or signed PCM bytes");
            require(fixed.queue.submitted==old.queue.submitted && fixed.hash==old.hash,
                    "Old/new route generated different PCM");
            require(fixed.late_rebases==1 && fixed.queue.overflow_clears==0 && fixed.queue.dropped==0,
                    "Late host catch-up burst overflowed bounded audio input");
            require(fixed.queue.peak<=1600,"Rebased producer queued more than two ordinary frame blocks");
            if(stall>=150)require(old.queue.overflow_clears>0 && old.queue.dropped>0,
                                  "Legacy catch-up overflow regression was not exercised");
            require(fixed.queue.accepted+fixed.queue.pending+fixed.queue.dropped==fixed.queue.submitted,
                    "Active fake device accounting did not conserve");
            const auto tail=fixed.queue.pending;fixed.queue.pause();
            require(fixed.queue.pause_clears==1 && fixed.queue.dropped==tail && fixed.queue.overflow_clears==0,
                    "Planned pause tail was confused with active overflow");
            fixed.queue.resume();
            require(fixed.queue.pause_clears==1 && fixed.queue.resume_clears==1 && fixed.queue.dropped==tail,
                    "Resume clear changed the planned-pause loss history");
            pce::HostPacer resumed;resumed.reset();
            require(resumed.plan(fixed.ticks,fixed.wall).reset==pce::PaceReset::initial,
                    "Resume retained old host time debt");
        }
    }
    pce::HostPacer pacer;
    require(pacer.plan(0,0).reset==pce::PaceReset::initial,"Missing initial pacing anchor");
    for(unsigned n=1;n<=10000;++n) {
        const auto ticks=std::uint64_t(n)*357954;
        const auto target=(ticks/21477273)*1000000000+(ticks%21477273)*1000000000/21477273;
        const auto decision=pacer.plan(ticks,target-1);
        require(decision.reset==pce::PaceReset::none && decision.wait_ns==1,
                "Pre-wait one-nanosecond margin rebased or accumulated drift");
    }
    // Real sleeps can overshoot. A fast following frame must absorb jitter
    // in its remaining wait, rather than shifting the anchor on every wakeup.
    pce::HostPacer jittered;(void)jittered.plan(0,0);std::uint64_t wall=0;
    constexpr std::array<std::uint64_t,4> oversleep{0,1,50000,750000};
    for(unsigned n=1;n<=1000;++n) {
        wall+=2000000;
        const auto ticks=std::uint64_t(n)*357954;
        const auto target=(ticks/21477273)*1000000000+(ticks%21477273)*1000000000/21477273;
        const auto decision=jittered.plan(ticks,wall);
        require(decision.reset==pce::PaceReset::none && wall+decision.wait_ns==target,
                "Normal work and sleep overshoot accumulated pacing drift");
        wall+=decision.wait_ns+oversleep[n%oversleep.size()];
        require(wall==target+oversleep[n%oversleep.size()],"Jitter accumulated across absolute frame deadlines");
    }
    require(pacer.plan(1,200000000000).reset==pce::PaceReset::guest_backwards,"Guest clock rollback not rebased");
    require(pacer.plan(2,1).reset==pce::PaceReset::wall_backwards,"Wall clock rollback not rebased");
    require(pacer.plan(3,2,true).reset==pce::PaceReset::paused,"Paused pacing did not rebase");
    pacer.reset();(void)pacer.plan(0,0);
    require(pacer.plan(std::numeric_limits<std::uint64_t>::max(),1).reset==pce::PaceReset::guest_jump,
            "Impossible guest jump did not rebase before multiplication");
    pacer.reset();(void)pacer.plan(0,std::numeric_limits<std::uint64_t>::max()-10);
    require(pacer.plan(1,std::numeric_limits<std::uint64_t>::max()-9).reset==pce::PaceReset::target_overflow,
            "Absolute host deadline wrapped instead of rebasing");
    pacer.reset();(void)pacer.plan(0,0);
    require(pacer.plan(21477273,1).wait_ns==100000000,"Host sleep is not bounded to100ms");
    return checks;
}
} // namespace host_pacer_fixture
