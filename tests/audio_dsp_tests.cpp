// Authored presentation equations and analytic signal tests; no retail audio.
#include "pce/audio_dsp.hpp"
#include "pce/audio_kernel.hpp"
#include <algorithm>
#include <array>
#include <cmath>
#include <iostream>
#include <limits>
#include <numbers>
#include <stdexcept>
#include <vector>

static unsigned checks=0;
static void require(bool okay,const char* why) {++checks;if(!okay)throw std::runtime_error(why);}
static void filter_vectors() {
    pce::PsgPresentationFilter psg;
    require(psg.process({3,-3})==pce::StereoSample{1,-1},"PSG half-sample input/truncation");
    require(psg.process({6,-6})==pce::StereoSample{2,-2},"PSG fractional history was lost");
    psg.reset();
    require(psg.process({200000,-200000})==pce::StereoSample{32767,-32768},"PSG saturation");
    require(psg.process({0,0})==pce::StereoSample{-150,150},"PSG history must not store clipped samples");
    psg.reset();
    for(unsigned index=0;index<10000;++index) {
        const auto result=psg.process({10000,0});
        const double expected=5000*std::pow(static_cast<double>(0.9985f),index);
        require(std::abs(result[0]-expected)<1.1,"PSG analytic DC decay");
        require(result[1]==0,"PSG stereo history isolation");
    }
    psg.reset();require(psg.process({0,0})==pce::StereoSample{0,0},"PSG reset history");
    pce::AdpcmPresentationFilter adpcm;
    require(adpcm.process(2049)==4,"ADPCM authored first LP impulse");
    require(adpcm.process(2049)==6,"ADPCM authored held second output");
    adpcm.reset();require(adpcm.process(2049,0)==3,"ADPCM gain smoothing precedes output");
    adpcm.reset();require(adpcm.process(2047)==-4,"ADPCM negative predictor centering");
    adpcm.reset();require(adpcm.process(0)==-8192,"ADPCM minimum input");
    adpcm.reset();require(adpcm.process(4095)==8188,"ADPCM maximum input");
    adpcm.reset();
    // Evaluate an independent double-precision state equation. Binary32 state
    // roundoff is allowed a one-LSB sample envelope, not a shared float oracle.
    double previous_x=0,previous_y=0,lowpass=0,gain=1;
    for(unsigned index=0;index<20000;++index) {
        const auto input=static_cast<std::uint16_t>((index*73+1979)&4095);
        const float target=(index/1000)%2 ? 0.0f:1.0f;
        const double x=(static_cast<int>(input)-2048)*10;
        const double y=x-previous_x+static_cast<double>(0.997f)*previous_y;
        previous_x=x;previous_y=y;
        lowpass+=static_cast<double>(0.4f)*(y-lowpass);
        gain+=(target-gain)*static_cast<double>(0.003f);
        const int expected=static_cast<int>(std::clamp(lowpass*gain,-32768.0,32767.0));
        require(std::abs(adpcm.process(input,target)-expected)<=1,"ADPCM independent double equations");
    }
    const auto before=adpcm;
    for(float invalid:{-0.01f,1.01f,std::numeric_limits<float>::infinity(),
                       -std::numeric_limits<float>::infinity(),std::numeric_limits<float>::quiet_NaN()}) {
        bool rejected=false;try {adpcm.process(2048,invalid);}catch(const std::invalid_argument&){rejected=true;}
        require(rejected,"invalid ADPCM gain accepted");
    }
    bool rejected=false;try {adpcm.process(4096);}catch(const std::invalid_argument&){rejected=true;}
    require(rejected,"invalid ADPCM 12-bit input accepted");
    auto unchanged=before;
    require(adpcm.process(1234)==unchanged.process(1234),"invalid ADPCM input changed history");
    adpcm.reset();
    for(unsigned index=0;index<1000;++index)require(adpcm.process(2048)==0,"ADPCM reset centered silence");
}

static void resampler_vectors() {
    for(unsigned rate:{0u,1u,22050u,44099u,44101u,47999u,48001u,96000u}) {
        bool rejected=false;try {pce::StereoResampler resampler(rate);}
        catch(const std::invalid_argument&){rejected=true;}
        require(rejected,"unsupported output rate accepted");
    }
    pce::StereoResampler direct;
    require(direct.output_rate()==44100 && direct.latency()==0,"44.1 kHz passthrough contract");
    for(unsigned index=0;index<1000;++index) {
        const pce::StereoSample sample{static_cast<std::int16_t>(index*67),static_cast<std::int16_t>(-int(index)*33)};
        const auto output=direct.push(sample);
        require(output.count==1 && output.samples[0]==sample,"passthrough must be sample exact");
    }
    direct.reset();require(direct.input_frames()==0 && direct.output_frames()==0,"passthrough reset counters");
    pce::StereoResampler rational(48000);
    require(rational.latency()==31,"FIR declared source delay");
    for(unsigned index=1;index<=10000;++index) {
        const auto before=rational.output_frames();
        const auto output=rational.push({0,0});
        require(output.count>=1 && output.count<=2,"rational per-input count bound");
        require(rational.input_frames()==index && rational.output_frames()==std::uint64_t{index}*160/147,
                "rational floor count every input");
        require(output.count==rational.output_frames()-before,"rational returned count");
        for(unsigned sample=0;sample<output.count;++sample)
            require(output.samples[sample]==pce::StereoSample{0,0},"FIR zero state silence");
    }
    rational.reset();
    for(unsigned index=0;index<1000;++index) {
        const auto output=rational.push({32767,-32768});
        if(index>=64)for(unsigned sample=0;sample<output.count;++sample)
            require(output.samples[sample]==pce::StereoSample{32767,-32768},"all-phase exact Q30 DC unity");
    }
    // This authored two-tap input produces exactly -4.5 and +4.5 in phase0:
    // 3474*(-22702) + 297135*(-15996) = -4831838208 = -4.5*2^30.
    rational.reset();pce::AudioResampleOutput last;
    for(unsigned index=0;index<147;++index) {
        const int value=index==146 ? -22702:index==142 ? -15996:0;
        last=rational.push({static_cast<std::int16_t>(value),static_cast<std::int16_t>(-value)});
    }
    require(last.samples[last.count-1]==pce::StereoSample{-5,5},"signed Q30 nearest ties away");
    rational.reset();
    for(unsigned index=0;index<147;++index) {
        const unsigned tap=146-index;
        const int value=tap<64 ? (pce::audio_detail::kernel[0][tap]>=0 ? 30000:-30000):0;
        last=rational.push({static_cast<std::int16_t>(value),static_cast<std::int16_t>(-value)});
    }
    require(last.samples[last.count-1]==pce::StereoSample{32767,-32768},"FIR overshoot saturates both signs");
    // Exact known impulse shape is independently reconstructed from real sinc
    // and window equations, including each phase's normalization.
    rational.reset();unsigned output_index=0,peak_index=0;int peak=0;
    for(unsigned input_index=0;input_index<147;++input_index) {
        const auto output=rational.push(input_index==64 ? pce::StereoSample{30000,0}:pce::StereoSample{});
        for(unsigned frame=0;frame<output.count;++frame,++output_index) {
            const unsigned phase=(input_index+1)*160-(output_index+1)*147;
            const double center=31+phase/160.0;
            double sum=0,tap_value=0;
            for(unsigned tap=0;tap<64;++tap) {
                const double distance=tap-center;
                const double window=.42+.5*std::cos(std::numbers::pi*distance/32)
                                       +.08*std::cos(2*std::numbers::pi*distance/32);
                const double z=2*(20000.0/44100)*distance;
                const double sinc=z==0 ? 1:std::sin(std::numbers::pi*z)/(std::numbers::pi*z);
                const double value=2*(20000.0/44100)*sinc*window;
                sum+=value;
                if(input_index>=64 && tap==input_index-64)tap_value=value;
            }
            const double expected=30000*tap_value/sum;
            require(std::abs(output.samples[frame][0]-expected)<=.51,"independent real impulse interpolation");
            require(output.samples[frame][1]==0,"FIR stereo isolation");
            if(std::abs(int(output.samples[frame][0]))>peak) {
                peak=std::abs(int(output.samples[frame][0]));peak_index=output_index;
            }
        }
    }
    const double impulse_source_time=(peak_index+1)*147/160.0-1-31;
    require(std::abs(impulse_source_time-64)<.5,"FIR measured impulse group delay");
    // Chunk partitions are only caller scheduling: interleave pauses and make
    // copies at irregular boundaries, then compare every output and counter.
    pce::StereoResampler whole(48000),partitioned(48000);
    std::vector<pce::StereoSample> input,expected,actual;
    for(unsigned index=0;index<4097;++index)
        input.push_back({static_cast<std::int16_t>((index*173+921)&65535),
                         static_cast<std::int16_t>((index*113+1871)&65535)});
    for(auto sample:input) {
        const auto output=whole.push(sample);
        for(unsigned index=0;index<output.count;++index)expected.push_back(output.samples[index]);
    }
    for(unsigned offset=0,chunk=1;offset<input.size();chunk=chunk*7%137+1) {
        const unsigned end=std::min<unsigned>(input.size(),offset+chunk);
        for(;offset<end;++offset) {
            const auto output=partitioned.push(input[offset]);
            for(unsigned index=0;index<output.count;++index)actual.push_back(output.samples[index]);
        }
        // No implicit output, clock advancement, drain or flush at a boundary.
        auto copy=partitioned;partitioned=copy;
    }
    require(actual==expected && partitioned.output_frames()==whole.output_frames(),"chunk/pause independence");
    partitioned.reset();require(partitioned.push({0,0}).samples[0]==pce::StereoSample{0,0},"FIR reset zero history");
    for(const auto& phase:pce::audio_detail::kernel) {
        std::int64_t sum=0,absolute=0;
        for(auto coefficient:phase) {sum+=coefficient;absolute+=std::abs(std::int64_t{coefficient});}
        require(sum==(std::int64_t{1}<<30),"checked-in coefficient phase exact unity");
        require(absolute<4*(std::int64_t{1}<<30),"coefficient int64 accumulation bound");
    }
}

struct Spectrum {double signal=0,image=0;};
static Spectrum spectral_probe(unsigned frequency) {
    constexpr unsigned prefix=1470,source_frames=44100+prefix;
    constexpr double amplitude=8000;
    pce::StereoResampler resampler(48000);
    double cosine=0,sine=0,image_cosine=0,image_sine=0;
    unsigned output_index=0,observations=0;
    for(unsigned input=0;input<source_frames;++input) {
        const auto source=static_cast<std::int16_t>(std::lround(amplitude*
            std::sin(2*std::numbers::pi*frequency*input/44100.0)));
        const auto output=resampler.push({source,0});
        for(unsigned frame=0;frame<output.count;++frame,++output_index) {
            if(output_index<1600)continue;
            const double phase=2*std::numbers::pi*frequency*output_index/48000.0;
            const double image_phase=2*std::numbers::pi*(44100-frequency)*output_index/48000.0;
            const double sample=output.samples[frame][0];
            cosine+=sample*std::cos(phase);sine+=sample*std::sin(phase);
            image_cosine+=sample*std::cos(image_phase);image_sine+=sample*std::sin(image_phase);
            require(output.samples[frame][1]==0,"spectral stereo isolation");
            ++observations;
        }
    }
    require(observations==48000,"spectral coherent one-second observation");
    return {2*std::hypot(cosine,sine)/(observations*amplitude),
            2*std::hypot(image_cosine,image_sine)/(observations*amplitude)};
}
static void quality_vectors() {
    double largest_passband_error=0,largest_nyquist_amplitude=0;
    for(const auto& phase:pce::audio_detail::kernel) {
        for(unsigned frequency=0;frequency<=18000;frequency+=50) {
            double real=0,imaginary=0;
            for(unsigned tap=0;tap<64;++tap) {
                const double angle=2*std::numbers::pi*frequency*tap/44100.0;
                const double coefficient=phase[tap]/1073741824.0;
                real+=coefficient*std::cos(angle);imaginary+=coefficient*std::sin(angle);
            }
            const double error=std::abs(20*std::log10(std::hypot(real,imaginary)));
            largest_passband_error=std::max(largest_passband_error,error);
            require(error<.03,"dense all-phase passband response");
        }
        double alternating=0;
        for(unsigned tap=0;tap<64;++tap)
            alternating+=(tap&1 ? -1:1)*phase[tap]/1073741824.0;
        largest_nyquist_amplitude=std::max(largest_nyquist_amplitude,std::abs(alternating));
        require(std::abs(alternating)<.0005,"all-phase source Nyquist rejection");
    }
    std::cout<<"FIR 160-phase / 50-Hz passband sweep to 18 kHz: max "<<largest_passband_error
             <<" dB; worst source Nyquist "<<20*std::log10(largest_nyquist_amplitude)<<" dB\n";
    for(unsigned frequency:{1000u,10000u,16000u,18000u,20500u,21500u,22000u}) {
        const auto spectrum=spectral_probe(frequency);
        const double signal_db=20*std::log10(spectrum.signal);
        const double image_db=20*std::log10(spectrum.image);
        std::cout<<"FIR tone "<<frequency<<" Hz: "<<signal_db<<" dB";
        if(frequency>=20500)std::cout<<"; image "<<44100-frequency<<" Hz: "<<image_db<<" dB";
        std::cout<<"\n";
        if(frequency<=18000)require(std::abs(signal_db)<.03,"FIR audible passband amplitude");
        if(frequency>=20500)require(image_db< -65,"FIR near-Nyquist interpolation image rejection");
        if(frequency==22000)require(signal_db< -60,"FIR source near-Nyquist stopband");
    }
}
int main() {
    try {filter_vectors();resampler_vectors();quality_vectors();}
    catch(const std::exception& error) {std::cerr<<error.what()<<" after "<<checks<<" checks\n";return 1;}
    std::cout<<"audio DSP checks: "<<checks<<"\n";
}
