#include "pce/audio_dsp.hpp"
#include "pce/audio_kernel.hpp"
#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>

namespace pce {
namespace {
static_assert(sizeof(float)==4 && std::numeric_limits<float>::is_iec559,
              "audio presentation filters require IEEE-754 binary32");
// Each state equation uses separate binary32 operations. Volatile temporaries
// prevent a compiler from contracting multiply/add into a different FMA result.
float add(float a,float b) {volatile float value=a+b;return value;}
float subtract(float a,float b) {volatile float value=a-b;return value;}
float multiply(float a,float b) {volatile float value=a*b;return value;}
std::int16_t truncate_sample(float value) {
    return static_cast<std::int16_t>(std::clamp(value,-32768.0f,32767.0f));
}
std::int16_t round_q30(std::int64_t value) {
    constexpr std::int64_t half=std::int64_t{1}<<29;
    const auto rounded=value>=0 ? (value+half)/(std::int64_t{1}<<30)
                                :-((-value+half)/(std::int64_t{1}<<30));
    return static_cast<std::int16_t>(std::clamp<std::int64_t>(rounded,-32768,32767));
}
}

StereoSample PsgPresentationFilter::process(std::array<std::int32_t,2> sums) {
    StereoSample result{};
    for(unsigned side=0;side<2;++side) {
        const float input=multiply(static_cast<float>(sums[side]),0.5f);
        const float difference=subtract(input,previous_input_[side]);
        const float feedback=multiply(0.9985f,previous_output_[side]);
        const float output=add(difference,feedback);
        previous_input_[side]=input;
        previous_output_[side]=output;
        result[side]=truncate_sample(output);
    }
    return result;
}
void PsgPresentationFilter::reset() {previous_input_={};previous_output_={};}

std::int16_t AdpcmPresentationFilter::process(std::uint16_t decoded,float target_gain) {
    if(decoded>4095 || !std::isfinite(target_gain) || target_gain<0 || target_gain>1)
        throw std::invalid_argument("ADPCM presentation requires 12-bit input and gain in [0,1]");
    const float input=multiply(static_cast<float>(static_cast<int>(decoded)-2048),10.0f);
    const float difference=subtract(input,previous_input_);
    const float feedback=multiply(0.997f,previous_output_);
    const float output=add(difference,feedback);
    previous_input_=input;
    previous_output_=output;
    lowpass_=add(lowpass_,multiply(0.4f,subtract(output,lowpass_)));
    gain_=add(gain_,multiply(subtract(target_gain,gain_),0.003f));
    return truncate_sample(multiply(lowpass_,gain_));
}
void AdpcmPresentationFilter::reset() {
    previous_input_=0;previous_output_=0;lowpass_=0;gain_=1;
}

StereoResampler::StereoResampler(unsigned output_rate):output_rate_(output_rate) {
    if(output_rate!=44100 && output_rate!=48000)
        throw std::invalid_argument("audio output rate must be 44100 or 48000");
}
void StereoResampler::reset() {
    write_=0;remainder_=0;input_frames_=0;output_frames_=0;history_={};
}
AudioResampleOutput StereoResampler::push(StereoSample input) {
    ++input_frames_;
    AudioResampleOutput output{};
    if(output_rate_==input_rate) {
        output.samples[0]=input;output.count=1;++output_frames_;return output;
    }
    history_[write_]=input;
    remainder_+=160;
    output.count=remainder_/147;
    remainder_%=147;
    // For output m (one-based) after input I, source time is m*147/160-1.
    // I*160-m*147 is the sub-sample distance from the newest source frame;
    // it is always 0..159. Subtract 31 source frames for the causal FIR delay.
    for(unsigned frame=0;frame<output.count;++frame) {
        const unsigned phase=remainder_+(output.count-1-frame)*147;
        std::array<std::int64_t,2> sums{};
        for(unsigned tap=0;tap<taps;++tap) {
            const auto& sample=history_[(write_+taps-tap)&(taps-1)];
            for(unsigned side=0;side<2;++side)
                sums[side]+=std::int64_t{sample[side]}*audio_detail::kernel[phase][tap];
        }
        for(unsigned side=0;side<2;++side)output.samples[frame][side]=round_q30(sums[side]);
    }
    write_=(write_+1)&(taps-1);
    output_frames_+=output.count;
    return output;
}
} // namespace pce
