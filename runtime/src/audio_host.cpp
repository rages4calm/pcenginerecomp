#include "pce/audio_host.hpp"
#include <SDL3/SDL.h>
#include <algorithm>
#include <limits>
#include <stdexcept>
#include <string>

namespace pce {
namespace {
constexpr unsigned FRAME_BYTES=2*sizeof(std::int16_t);
void checked(bool good,const char* operation) {
    if(!good) throw std::runtime_error(std::string(operation)+": "+SDL_GetError());
}
void room(std::uint64_t value,std::uint64_t extra) {
    if(extra>std::numeric_limits<std::uint64_t>::max()-value)
        throw std::overflow_error("Audio host statistics overflow");
}
struct StreamLock {
    SDL_AudioStream* stream;
    explicit StreamLock(SDL_AudioStream* value):stream(value) {
        checked(SDL_LockAudioStream(stream),"lock SDL audio stream");
    }
    ~StreamLock() { SDL_UnlockAudioStream(stream); }
};
}
struct AudioHost::Impl {
    SDL_AudioStream* stream=nullptr;
    bool initialized=false, paused=false;
    AudioHostStats counters;
    ~Impl() {
        // The convenience stream owns its logical device; destruction closes
        // it and releases pending PCM without affecting other SDL hosts.
        if(stream) SDL_DestroyAudioStream(stream);
        if(initialized) SDL_QuitSubSystem(SDL_INIT_AUDIO);
    }
    unsigned queued() {
        const int bytes=SDL_GetAudioStreamQueued(stream);
        checked(bytes>=0,"query SDL audio queue");
        counters.queued_bytes=static_cast<unsigned>(bytes);
        counters.queued_frames=static_cast<unsigned>(bytes)/FRAME_BYTES;
        counters.peak_queue_frames=std::max(counters.peak_queue_frames,counters.queued_frames);
        return static_cast<unsigned>(bytes);
    }
    void clear() {
        const auto frames=queued()/FRAME_BYTES;
        room(counters.dropped_frames,frames);room(counters.clears,1);
        checked(SDL_ClearAudioStream(stream),"clear SDL audio queue");
        counters.dropped_frames+=frames;++counters.clears;
        queued();
    }
};
AudioHost::AudioHost():impl_(std::make_unique<Impl>()) {
    checked(SDL_InitSubSystem(SDL_INIT_AUDIO),"initialize SDL audio");
    impl_->initialized=true;
    const SDL_AudioSpec spec{SDL_AUDIO_S16,2,static_cast<int>(sample_rate)};
    impl_->stream=SDL_OpenAudioDeviceStream(SDL_AUDIO_DEVICE_DEFAULT_PLAYBACK,&spec,nullptr,nullptr);
    checked(impl_->stream!=nullptr,"open SDL audio output");
    checked(SDL_ResumeAudioStreamDevice(impl_->stream),"resume SDL audio output");
}
AudioHost::~AudioHost()=default;
void AudioHost::submit(std::span<const std::int16_t> stereo) {
    if(stereo.size()%2) throw std::invalid_argument("Audio submission requires complete stereo frames");
    if(stereo.size()/2>max_queue_frames) throw std::length_error("Audio submission exceeds bounded queue");
    const auto frames=stereo.size()/2;
    room(impl_->counters.submitted_frames,frames);
    StreamLock lock(impl_->stream);
    if(impl_->paused) {
        room(impl_->counters.dropped_frames,frames);
        impl_->counters.submitted_frames+=frames;
        impl_->counters.dropped_frames+=frames;
        impl_->queued();return;
    }
    const auto bytes=static_cast<unsigned>(stereo.size()*sizeof(std::int16_t));
    if(impl_->queued()+bytes>max_queue_frames*FRAME_BYTES) impl_->clear();
    if(bytes) checked(SDL_PutAudioStreamData(impl_->stream,stereo.data(),static_cast<int>(bytes)),"queue SDL audio PCM");
    impl_->counters.submitted_frames+=frames;
    impl_->queued();
}
void AudioHost::set_paused(bool paused) {
    if(paused==impl_->paused) return;
    if(paused) {
        room(impl_->counters.pauses,1);
        checked(SDL_PauseAudioStreamDevice(impl_->stream),"pause SDL audio output");
        impl_->paused=true;++impl_->counters.pauses;
        StreamLock lock(impl_->stream);
        impl_->clear();
    } else {
        {
            StreamLock lock(impl_->stream);
            impl_->clear();
        }
        checked(SDL_ResumeAudioStreamDevice(impl_->stream),"resume SDL audio output");
        impl_->paused=false;
    }
}
const AudioHostStats& AudioHost::stats() const {
    StreamLock lock(impl_->stream);impl_->queued();return impl_->counters;
}
} // namespace pce
