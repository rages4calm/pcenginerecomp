// Authored ideal digital PSG and presentation equations; no emulator recordings.
#include "pce/runtime.hpp"
#include "pce/audio_dsp.hpp"
#include "pce/checkpoint_audio.hpp"
#include "pce/checkpoint_archive.hpp"
#include "psg_pipeline_fixture.hpp"
#include <algorithm>
#include <array>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
namespace fixture=psg_pipeline_fixture;
std::uint64_t checks=0;
void require(bool value,const char* message) {++checks;if(!value)throw std::runtime_error(message);}
std::uint64_t edge(unsigned frame) {return (std::uint64_t{frame}*21477273+44099)/44100;}
int data(unsigned frame,unsigned channel) {
    if(frame<4)return 31;
    if(frame<8)return 0;
    if(frame<40)return (frame*11+channel*7)%32;
    return channel%2 ? 16:15;
}
void decimal_gain_matrix() {
    for(bool centered:{false,true}) for(unsigned channel=0;channel<6;++channel) {
        pce::Psg p;p.enabled=p.synthesis_enabled=true;p.centered_dac=centered;
        auto& c=p.channels[channel];
        for(unsigned main=0;main<16;++main)for(unsigned pan=0;pan<16;++pan)
        for(unsigned volume=0;volume<32;++volume) {
            p.main_volume=static_cast<std::uint8_t>((main<<4)|(15-main));
            c.balance=static_cast<std::uint8_t>((pan<<4)|(15-pan));
            c.control=static_cast<std::uint8_t>(192|volume);
            const unsigned loss_left=std::min(31u,93-fixture::balance[main]-fixture::balance[pan]-volume);
            const unsigned loss_right=std::min(31u,93-fixture::balance[15-main]-fixture::balance[15-pan]-volume);
            for(unsigned dac=0;dac<32;++dac) {
                c.dda=static_cast<std::uint8_t>(dac);
                const int level=int(dac*2)-(centered ? 31:0);
                const std::array<std::int32_t,2> expected{level*int(fixture::gain[loss_left]),level*int(fixture::gain[loss_right])};
                require(p.sample_sum()==expected,"decimal-derived 32 DAC/32 volume/16x16 stereo balance source mismatch");
            }
        }
    }
}
void filter_domain_vectors() {
    pce::PsgPresentationFilter filter;
    for(unsigned i=0;i<fixture::edge_sums.size();++i)
        require(filter.process(fixture::edge_sums[i])==fixture::edge_filtered[i],
                "binary32 HPF lost odd half, unclipped sum or unclipped history");
    filter.reset();unsigned mark=0;
    for(unsigned frame=0;frame<=fixture::decay_frames.back();++frame) {
        const auto actual=filter.process({10571,-10571});
        if(frame==fixture::decay_frames[mark]) {
            require(actual==fixture::decay_filtered[mark],"binary32 HPF exact long DC decay mismatch");
            if(++mark==fixture::decay_frames.size())break;
        }
    }
}
void source_mode_edges() {
    // Independent hand-derived waveform/DDA timeline, ordinary period six.
    pce::Psg p;p.enabled=p.synthesis_enabled=true;p.main_volume=255;
    auto& c=p.channels[0];c.balance=255;c.frequency=6;c.control=159;
    for(unsigned i=0;i<32;++i)c.waveform[i]=static_cast<std::uint8_t>(i);
    p.write(4,223);p.write(4,159);
    pce::PsgPresentationFilter filter;
    const auto observe=[&](std::uint64_t tick,int expected) {
        p.advance_to(tick);
        if(p.held_sum()!=std::array<std::int32_t,2>{expected,expected})
            throw std::runtime_error("wave/DDA held source edge mismatch at "+std::to_string(tick)+
                ": got "+std::to_string(p.held_sum()[0])+", expected "+std::to_string(expected));
        ++checks;
        return filter.process(p.held_sum());
    };
    require(observe(5,-10571)==pce::StereoSample{-5285,-5285},"immediate DDA-falling waveform HPF boundary");
    require(observe(6,-10571)==pce::StereoSample{-5277,-5277},"second waveform HPF boundary");
    require(observe(35,-10571)==pce::StereoSample{-5269,-5269},"held waveform HPF boundary");
    observe(36,-9889);p.write(6,31);observe(41,10571);observe(42,10571);
    p.write(4,223);p.write(6,0);observe(47,10571);observe(48,-10571);
    p.write(4,159);observe(48,-10571);

    // Literal sequence from the polynomial, independently retained in the
    // fixture: these samples observe the new LFSR after each exact edge.
    p=pce::Psg{};p.enabled=p.synthesis_enabled=true;p.main_volume=255;
    p.selected=4;auto& n=p.channels[4];n.control=159;n.balance=255;n.noise=159;
    constexpr std::array<unsigned,24> seeds{131072,196608,229376,245760,253952,258048,
        129024,64512,32256,16128,8064,4032,133088,197616,229880,246012,254078,
        127039,194591,228367,245255,253699,257921,260032};
    filter.reset();
    for(unsigned i=0;i<seeds.size();++i) {
        p.advance_to(i ? i*192:6);
        require(n.noise_lfsr==seeds[i],"pipeline noise polynomial edge mismatch");
        require(p.held_sum()[0]==((seeds[i]&1) ? 10571:-10571),"pipeline noise post-shift source mismatch");
        require(filter.process(p.held_sum())==fixture::noise_filtered[i],"noise edge source-to-binary32-filter mismatch");
    }
    p=pce::Psg{};p.enabled=p.synthesis_enabled=true;p.main_volume=255;
    auto& dest=p.channels[0];dest.control=159;dest.balance=255;dest.frequency=20;dest.wave_remaining=1;
    for(unsigned i=0;i<32;++i)dest.waveform[i]=static_cast<std::uint8_t>(i);
    auto& src=p.channels[1];src.control=159;src.frequency=2;src.wave_remaining=1;src.waveform.fill(16);
    src.waveform[1]=17;src.waveform[2]=15;p.lfo_frequency=3;p.lfo_control=1;
    filter.reset();
    p.advance_to(6);require(dest.wave_remaining==21 && p.held_sum()[0]==-9889,"LFO source-first destination/source domain");
    require(filter.process({p.held_sum()[0],0})==fixture::lfo_filtered[0],"LFO first source-to-filter boundary");
    p.advance_to(42);require(dest.wave_remaining==15 && p.held_sum()[0]==-9889,"LFO divided source edge");
    require(filter.process({p.held_sum()[0],0})==fixture::lfo_filtered[1],"LFO second source-to-filter boundary");
    p.advance_to(132);require(dest.wave_index==2 && p.held_sum()[0]==-9207,"LFO next destination edge");
    require(filter.process({p.held_sum()[0],0})==fixture::lfo_filtered[2],"LFO changed source-to-filter boundary");
}
void setup_dda(pce::Bus& bus,bool centered,pce::AudioProfile profile,unsigned rate) {
    bus.enable_audio_output(profile,rate,pce::AudioTiming::gear);
    bus.psg.centered_dac=centered;bus.psg.write(1,255);
    for(unsigned ch=0;ch<6;++ch) {
        bus.psg.write(0,static_cast<std::uint8_t>(ch));bus.psg.write(4,223);
        bus.psg.write(5,ch%2 ? 245:255);
    }
}
template<class Expected> void run_pipeline(bool centered,pce::AudioProfile profile,unsigned rate,const Expected& expected) {
    auto bus=std::make_unique<pce::Bus>();setup_dda(*bus,centered,profile,rate);
    std::vector<std::int16_t> actual;
    pce::PsgPresentationFilter independent_filter;
    const auto& sums=centered ? fixture::source_1:fixture::source_0;
    const auto& filtered=centered ? fixture::filtered_1:fixture::filtered_0;
    for(unsigned frame=0;frame<256;++frame) {
        bus->pcm.advance_to(*bus,edge(frame+1)-7);
        for(unsigned ch=0;ch<6;++ch) {
            bus->psg.write(0,static_cast<std::uint8_t>(ch));
            bus->psg.write(6,static_cast<std::uint8_t>(data(frame,ch)));
        }
        bus->pcm.advance_to(*bus,edge(frame+1));
        require(bus->psg.held_sum()==sums[frame],"real PSG source sum differs from authored signal");
        require(independent_filter.process(bus->psg.held_sum())==filtered[frame],"real source to exact binary32 HPF domain mismatch");
        if(frame==0 || frame==1 || frame%17==0) {
            auto part=bus->pcm.drain();actual.insert(actual.end(),part.begin(),part.end());
            require(bus->pcm.drain().empty(),"draining already empty output manufactured PCM");
        }
    }
    auto final=bus->pcm.drain();actual.insert(actual.end(),final.begin(),final.end());
    require(actual.size()==expected.size()*2,"full pipeline rational output frame count");
    for(unsigned frame=0;frame<expected.size();++frame)
        require(actual[frame*2]==expected[frame][0] && actual[frame*2+1]==expected[frame][1],
                "full PSG source/HPF/mix/FIR signal differs from authored equations");
    require(bus->pcm.discarded_frames==0,"finite pipeline fixture unexpectedly overflowed");
}
std::vector<std::uint8_t> encode(const pce::Bus& bus) {
    pce::checkpoint::Writer out;pce::checkpoint::write_audio(out,bus);return std::move(out.data);
}
void decode(const std::vector<std::uint8_t>& bytes,pce::Bus& bus) {
    pce::checkpoint::Reader in(bytes);pce::checkpoint::read_audio(in,bus);in.finish();
}
void setup_continuation(pce::Bus& bus,unsigned mode) {
    if(mode)bus.enable_audio_output(mode==1 ? pce::AudioProfile::raw:pce::AudioProfile::filtered,mode==3 ? 48000:44100);
    else {bus.enable_psg();bus.psg.synthesis_enabled=true;}
    bus.psg.write(1,255);
    for(unsigned ch=0;ch<6;++ch) {
        bus.psg.write(0,static_cast<std::uint8_t>(ch));bus.psg.write(5,static_cast<std::uint8_t>(255-ch*17));
        for(unsigned i=0;i<32;++i)bus.psg.write(6,static_cast<std::uint8_t>((i*11+ch*3)&31));
        bus.psg.write(2,static_cast<std::uint8_t>(ch+7));bus.psg.write(4,159);
    }
    bus.psg.write(8,3);bus.psg.write(9,2);bus.psg.write(0,4);bus.psg.write(7,159);
    bus.psg.write(0,5);bus.psg.write(7,150);
}
void advance(pce::Bus& bus,std::uint64_t tick) {
    bus.pcm.advance_to(bus,tick);bus.psg.advance_to(tick);
}
void continuation(unsigned mode,unsigned pause) {
    auto first=std::make_unique<pce::Bus>();setup_continuation(*first,mode);advance(*first,pause);
    const auto before=encode(*first);
    require(first->psg.master_remainder==pause%6,"checkpoint fixture lost partial PSG divider");
    require(first->psg.channels[0].wave_remaining && first->psg.channels[1].wave_remaining &&
            first->psg.channels[4].noise_remaining,"checkpoint does not exercise live wave/LFO/noise phases");
    require(encode(*first)==before,"paused checkpoint inspection changed state");
    auto resumed=std::make_unique<pce::Bus>();setup_continuation(*resumed,mode);decode(before,*resumed);
    require(encode(*resumed)==before,"fresh audio machine did not retain complete checkpoint payload");
    for(auto delta:{0u,1u,5u,487u,489u,12001u,100001u,7000001u}) {
        const auto tick=std::uint64_t{pause}+delta;advance(*first,tick);advance(*resumed,tick);
        require(encode(*first)==encode(*resumed),"restored source/queue/DSP payload diverged");
        require(first->pcm.drain()==resumed->pcm.drain(),"restored PCM drain diverged");
        require(encode(*first)==encode(*resumed),"draining changed restored payload differently");
    }
}
void write_file(const std::filesystem::path& path,const std::vector<std::uint8_t>& bytes) {
    std::ofstream output(path,std::ios::binary);if(!output)throw std::runtime_error("cannot write private checkpoint fixture");
    output.write(reinterpret_cast<const char*>(bytes.data()),static_cast<std::streamsize>(bytes.size()));
    if(!output)throw std::runtime_error("checkpoint fixture write failed");
}
std::vector<std::uint8_t> read_file(const std::filesystem::path& path) {
    std::ifstream input(path,std::ios::binary);if(!input)throw std::runtime_error("cannot read private checkpoint fixture");
    return {std::istreambuf_iterator<char>(input),std::istreambuf_iterator<char>()};
}
// A bounded public test-only entrypoint permits two actual processes. These
// authored files contain no media, firmware, saves or generated guest program.
void fresh_process(const std::string& operation,const std::filesystem::path& directory) {
    require(std::filesystem::is_directory(directory),"existing private fixture directory required");
    if(operation=="--checkpoint-write")
        require(std::filesystem::is_empty(directory),"checkpoint fixture directory must be empty; preserve prior files");
    for(unsigned mode=0;mode<4;++mode)for(unsigned pause:{489u,977u,1001u}) {
        const auto stem=std::to_string(mode)+"-"+std::to_string(pause);
        auto bus=std::make_unique<pce::Bus>();setup_continuation(*bus,mode);
        if(operation=="--checkpoint-write") {
            advance(*bus,pause);write_file(directory/(stem+".checkpoint"),encode(*bus));
        } else decode(read_file(directory/(stem+".checkpoint")),*bus);
        advance(*bus,std::uint64_t{pause}+200003);
        const auto endpoint=encode(*bus);
        if(operation=="--checkpoint-write")write_file(directory/(stem+".expected"),endpoint);
        else require(endpoint==read_file(directory/(stem+".expected")),"fresh-process full source/PCM/DSP checkpoint continuation mismatch");
    }
}
}
int main(int argc,char** argv) {try {
    if(argc==3) {
        const std::string operation=argv[1];
        if(operation!="--checkpoint-write" && operation!="--checkpoint-resume")throw std::runtime_error("invalid fixture operation");
        fresh_process(operation,argv[2]);
    } else if(argc==1) {
        decimal_gain_matrix();filter_domain_vectors();source_mode_edges();
        for(bool centered:{false,true}) {
            run_pipeline(centered,pce::AudioProfile::raw,44100,centered ? fixture::raw44100_1:fixture::raw44100_0);
            run_pipeline(centered,pce::AudioProfile::filtered,44100,centered ? fixture::filtered44100_1:fixture::filtered44100_0);
            run_pipeline(centered,pce::AudioProfile::filtered,48000,centered ? fixture::filtered48000_1:fixture::filtered48000_0);
        }
        for(unsigned mode=0;mode<4;++mode)for(unsigned pause:{489u,977u,1001u,1002u,1003u,1004u,1006u})continuation(mode,pause);
    } else throw std::runtime_error("usage: pce-psg-pipeline-tests [--checkpoint-write|--checkpoint-resume PRIVATE_DIRECTORY]");
    std::cout<<checks<<" authored PSG source/HPF/PCM/continuation checks passed; zero guest retirements\n";return 0;
}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}}
