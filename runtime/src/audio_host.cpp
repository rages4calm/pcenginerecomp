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
    void formats() {
        SDL_AudioSpec input{},output{},device{};int frames=0;
        checked(SDL_GetAudioStreamFormat(stream,&input,&output),"query SDL audio stream formats");
        checked(SDL_GetAudioDeviceFormat(SDL_GetAudioStreamDevice(stream),&device,&frames),"query SDL audio device format");
        if(input.freq<=0 || input.channels<=0 || output.freq<=0 || output.channels<=0 ||
           device.freq<=0 || device.channels<=0 || frames<0)throw std::runtime_error("Invalid SDL audio format");
        counters.input_rate=static_cast<unsigned>(input.freq);counters.input_channels=static_cast<unsigned>(input.channels);
        counters.input_format=static_cast<unsigned>(input.format);
        counters.stream_output_rate=static_cast<unsigned>(output.freq);counters.stream_output_channels=static_cast<unsigned>(output.channels);
        counters.stream_output_format=static_cast<unsigned>(output.format);
        counters.device_rate=static_cast<unsigned>(device.freq);counters.device_channels=static_cast<unsigned>(device.channels);
        counters.device_format=static_cast<unsigned>(device.format);counters.device_sample_frames=static_cast<unsigned>(frames);
    }
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
AudioHost::AudioHost(unsigned input_rate):impl_(std::make_unique<Impl>()) {
    if(input_rate!=44100 && input_rate!=48000)throw std::invalid_argument("Audio input rate requires 44100 or 48000");
    checked(SDL_InitSubSystem(SDL_INIT_AUDIO),"initialize SDL audio");
    impl_->initialized=true;
    const SDL_AudioSpec spec{SDL_AUDIO_S16,2,static_cast<int>(input_rate)};
    impl_->stream=SDL_OpenAudioDeviceStream(SDL_AUDIO_DEVICE_DEFAULT_PLAYBACK,&spec,nullptr,nullptr);
    checked(impl_->stream!=nullptr,"open SDL audio output");
    impl_->formats();
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
    {StreamLock lock(impl_->stream);impl_->queued();}
    // Do not hold a stream lock while querying a device: SDL's device thread
    // may itself request the stream. Each format query owns its own lock.
    impl_->formats();return impl_->counters;
}
} // namespace pce
