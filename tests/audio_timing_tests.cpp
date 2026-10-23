// Authored sample-edge and clock-latched DAC expectations, no retail inputs.
#include "pce/runtime.hpp"
#include <iostream>
#include <stdexcept>

namespace {
unsigned checks=0;
void require(bool value,const char* why) {++checks;if(!value)throw std::runtime_error(why);}
constexpr std::uint64_t master=21477273;
constexpr std::uint64_t edge(std::uint64_t n) {return (n*master+44099)/44100;}
void configure(pce::Bus& bus,pce::Cpu& cpu) {
    for(const auto [reg,value]:{std::pair{0,0},std::pair{1,255},std::pair{4,223},
                              std::pair{5,240},std::pair{6,31}})
        bus.write(cpu,static_cast<std::uint16_t>(0x800+reg),value);
}
void exact_edges() {
    pce::Bus bus;bus.enable_audio_output();
    require(bus.pcm.timing()==pce::AudioTiming::gear,"corrected timing is not default");
    bus.pcm.advance_to(bus,487);require(bus.pcm.frames==0,"sample before first ceiling edge");
    bus.pcm.advance_to(bus,488);require(bus.pcm.frames==1,"missing first ceiling edge");
    bus.pcm.advance_to(bus,974);require(bus.pcm.frames==1,"second sample one tick early");
    bus.pcm.advance_to(bus,975);require(bus.pcm.frames==2,"missing second ceiling edge");
    // First exact rational-period boundary is sample 14,700 at tick7,159,091.
    // An unconditional +1 adjustment would fail precisely here.
    for(unsigned n=3;n<=14702;++n) {
        bus.pcm.advance_to(bus,edge(n)-1);require(bus.pcm.frames==n-1,"sample edge rounded early");
        bus.pcm.advance_to(bus,edge(n));require(bus.pcm.frames==n,"sample edge rounded late");
        bus.pcm.drain();
    }
    require(edge(14700)==7159091,"independent rational-period constant");
    pce::Bus split;split.enable_audio_output();
    for(std::uint64_t t=1;t<edge(14702);t+=1937) {split.pcm.advance_to(split,t);split.pcm.drain();}
    split.pcm.advance_to(split,edge(14702));
    require(bus.pcm.pcm_hash==split.pcm.pcm_hash && bus.pcm.frames==split.pcm.frames,
            "corrected sample clock depends on host partitions");
}
void write_latches() {
    for(const auto timing:{pce::AudioTiming::gear,pce::AudioTiming::legacy}) {
        pce::Bus bus;pce::Cpu cpu;bus.enable_audio_output(pce::AudioProfile::raw,44100,timing);
        configure(bus,cpu);cpu.ticks=486;bus.write(cpu,0x806,0);
        cpu.ticks=488;bus.sync(cpu);
        const auto first=bus.pcm.drain();
        require(first==std::vector<std::int16_t>{static_cast<std::int16_t>(timing==pce::AudioTiming::gear ? 1761:-1761),0},
                "DDA write leaked through zero elapsed PSG clocks");
        cpu.ticks=975;bus.sync(cpu);
        require(bus.pcm.drain()==std::vector<std::int16_t>{-1761,0},"DDA did not refresh on positive PSG clock");
    }
    pce::Bus bus;pce::Cpu cpu;bus.enable_audio_output();configure(bus,cpu);
    cpu.ticks=488;bus.write(cpu,0x806,0); // sync-before-write samples old value at the tie.
    require(bus.pcm.drain()==std::vector<std::int16_t>{1761,0},"same-tick write changed completed sample");
    cpu.ticks=975;bus.sync(cpu);
    require(bus.pcm.drain()==std::vector<std::int16_t>{-1761,0},"same-tick write missing from next sample");
}
void decoder_edge() {
    pce::Bus bus;bus.enable_adpcm();bus.enable_audio_output();
    auto& a=bus.adpcm;a.playing=true;a.control=32;a.sample_rate=15;a.length=1;a.ram[0]=0x70;
    a.sample_phase=11866861; // Period43,848,429 -488*65,536.
    bus.pcm.advance_to(bus,487);
    require(a.samples==0 && a.decoder_output==2048 && bus.pcm.frames==0,"ADPCM advanced before authored nibble edge");
    bus.pcm.advance_to(bus,488);
    require(a.samples==1 && a.decoder_output==2078 && a.decoder_index==8,"literal MSM5205 first nibble");
    require(bus.pcm.drain()==std::vector<std::int16_t>{160,160},"PCM failed to observe simultaneous decoder edge");
    pce::Bus invalid;const auto kinds=invalid.kind;bool refused=false;
    try {invalid.enable_audio_output(pce::AudioProfile::raw,44100,static_cast<pce::AudioTiming>(99));}
    catch(const pce::Fault&){refused=true;}
    require(refused,"invalid timing enum accepted");
    require(!invalid.psg.enabled && !invalid.pcm.enabled && invalid.kind==kinds,
            "invalid timing changed device or bank state before refusal");
}
}
int main() {try {exact_edges();write_latches();decoder_edge();
    std::cout<<checks<<" authored ceiling-clock/DAC/write-tie/decoder timing checks passed\n";
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
