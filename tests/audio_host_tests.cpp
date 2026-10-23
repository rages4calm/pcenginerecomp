// Uses SDL's real dummy audio backend, never the owner's output device.
#include "pce/audio_host.hpp"
#include <SDL3/SDL.h>
#include <array>
#include <iostream>
#include <stdexcept>
#include <string>
#include <tuple>
#include <vector>

static unsigned checks=0;
static void require(bool okay,const char* why) {++checks;if(!okay)throw std::runtime_error(why);}
static auto accounting(const pce::AudioHostStats& s) {
    return std::tuple{s.submitted_frames,s.dropped_frames,s.clears,s.pauses,s.peak_queue_frames};
}
int main() {try {
    require(SDL_WasInit(SDL_INIT_AUDIO)==0,"audio test inherited an initialized output device");
    require(SDL_SetHintWithPriority(SDL_HINT_AUDIO_DRIVER,"pce-no-such-audio-driver",SDL_HINT_OVERRIDE),"set invalid test driver");
    bool refused=false;
    try{pce::AudioHost invalid;}catch(const std::runtime_error& error){refused=!std::string(error.what()).empty();}
    require(refused && SDL_WasInit(SDL_INIT_AUDIO)==0,"constructor concealed SDL failure or leaked subsystem reference");
    require(SDL_SetHintWithPriority(SDL_HINT_AUDIO_DRIVER,"dummy",SDL_HINT_OVERRIDE),"select dummy audio backend");
    {
        pce::AudioHost host;
        require(std::string(SDL_GetCurrentAudioDriver())=="dummy","test opened a physical audio driver");
        require(host.stats().queued_bytes==0 && host.stats().submitted_frames==0,"initial audio queue/accounting");
        const std::array<std::int16_t,3> odd{1,2,3};
        const auto before=accounting(host.stats());
        refused=false;try{host.submit(odd);}catch(const std::invalid_argument&){refused=true;}
        require(refused && accounting(host.stats())==before,"odd submission changed accounting");
        std::vector<std::int16_t> oversized((pce::AudioHost::max_queue_frames+1)*2);
        refused=false;try{host.submit(oversized);}catch(const std::length_error&){refused=true;}
        require(refused && accounting(host.stats())==before,"oversized submission changed accounting");
        host.submit({});require(accounting(host.stats())==before,"empty submission changed accounting");
        std::vector<std::int16_t> block(pce::AudioHost::max_queue_frames*2);
        for(unsigned i=0;i<block.size();++i)block[i]=static_cast<std::int16_t>((i*31)%16384-8192);
        for(unsigned i=0;i<64;++i) {
            host.submit(block);const auto& s=host.stats();
            require(s.queued_bytes<=pce::AudioHost::max_queue_frames*4,"SDL pending input exceeded byte bound");
            require(s.queued_frames==s.queued_bytes/4 && s.peak_queue_frames<=pce::AudioHost::max_queue_frames,
                    "SDL byte/frame accounting or high-water bound");
        }
        require(host.stats().submitted_frames==64*pce::AudioHost::max_queue_frames,"submitted frame count");
        require(host.stats().clears>0 && host.stats().dropped_frames>0,"unthrottled producer did not discard stale queue");
        host.set_paused(true);const auto paused=host.stats();
        require(paused.queued_bytes==0 && paused.queued_frames==0 && paused.pauses==1,"pause failed to empty actual SDL queue");
        const std::array<std::int16_t,4> small{120,-120,240,-240};
        host.submit(small);const auto& dropped=host.stats();
        require(dropped.queued_bytes==0 && dropped.submitted_frames==paused.submitted_frames+2 &&
                dropped.dropped_frames==paused.dropped_frames+2,"paused submission leaked or was not counted dropped");
        const auto clears=dropped.clears;host.set_paused(true);
        require(host.stats().pauses==1 && host.stats().clears==clears,"idempotent pause changed counters");
        host.set_paused(false);
        require(host.stats().queued_bytes==0 && host.stats().clears==clears+1,"resume retained stale audio");
        host.submit(small);
        require(host.stats().submitted_frames==paused.submitted_frames+4,"resume did not accept new PCM");
        {
            pce::AudioHost second;second.submit(small);
            require(second.stats().submitted_frames==2,"concurrent audio host initialization");
        }
        require(SDL_WasInit(SDL_INIT_AUDIO)!=0,"second host teardown shut down first host");
        host.submit(small);
    }
    require(SDL_WasInit(SDL_INIT_AUDIO)==0,"audio stream destruction leaked its subsystem reference");
    require(SDL_InitSubSystem(SDL_INIT_AUDIO),"initialize external audio reference");
    {
        pce::AudioHost host;host.set_paused(true);
    }
    require(SDL_WasInit(SDL_INIT_AUDIO)!=0,"host teardown removed external SDL audio reference");
    SDL_QuitSubSystem(SDL_INIT_AUDIO);
    require(SDL_WasInit(SDL_INIT_AUDIO)==0,"external audio reference cleanup");
    std::cout<<checks<<" SDL dummy audio queue/bounds/refusal/pause/resume/cleanup checks passed\n";
    return 0;
}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}}
