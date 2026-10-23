#include "pce/adpcm.hpp"
#include <algorithm>
#include <cmath>
#include <iostream>
#include <stdexcept>
#include <tuple>

static void require(bool condition,const char* message) {
    if(!condition) throw std::runtime_error(message);
}
static std::uint64_t next_sample(const pce::Adpcm& a) {
    const auto period=a.sample_period();
    return a.master_ticks+(a.sample_phase>=period ? 1:(period-a.sample_phase+65535)/65536);
}
static auto state(const pce::Adpcm& a) {
    return std::tuple{a.playing,a.play_pending,a.nibble,a.end_irq,a.half_irq,
        a.control,a.dma,a.sample_rate,a.last_nibble,a.address,a.read_address,
        a.write_address,a.length,a.master_ticks,a.read_deadline,a.write_deadline,
        a.dma_deadline,a.sample_phase,a.samples,a.reads,a.writes,a.dma_bytes,
        a.decoder_output,a.decoder_index,a.sample_pcm()};
}

static unsigned known_sequence() {
    pce::Adpcm a;a.enabled=true;a.length=8;
    // Authored ascending nibble sequence, with independently tabulated exact
    // accumulator/index values. Starts at unsigned midscale, high nibble first.
    constexpr unsigned outputs[]={2050,2056,2066,2080,2098,2123,2168,2261,
                                  2248,2212,2157,2087,2005,1884,1673,1243};
    constexpr unsigned indices[]={0,0,0,0,2,6,12,20,19,18,17,16,18,22,28,36};
    for(unsigned byte=0;byte<8;++byte)a.ram[byte]=static_cast<std::uint8_t>(byte*0x22+1);
    require(a.decoder_output==2048 && a.decoder_index==0 && a.sample_pcm()==0,"initial decoder midpoint");
    a.write(13,0x60);
    for(unsigned i=0;i<16;++i) {
        const auto time=next_sample(a);
        const auto previous=a.sample_pcm();
        a.advance_to(time-1);require(a.sample_pcm()==previous,"PCM changed before sample event");
        a.advance_to(time);
        require(a.last_nibble==i && a.decoder_output==outputs[i] && a.decoder_index==indices[i],
                "literal ADPCM sequence mismatch");
        require(a.sample_pcm()==(static_cast<int>(outputs[i])-2048)*16,"held PCM scaling mismatch");
        require(a.samples==i+1 && a.read_address==(i+1)/2 && a.nibble==!(i&1),"PCM disturbed nibble/address clocks");
    }
    require(!a.playing && !a.length && a.end_irq && a.half_irq,"finite sample altered end/half IRQ");
    const auto held=a.sample_pcm();a.advance_to(a.master_ticks+100000);
    require(a.sample_pcm()==held && a.samples==16,"stopped digital output was not held");
    return 18;
}

static unsigned quantizer_matrix() {
    unsigned checks=0;
    // Independent arithmetic expectations use a power evaluation, rather than
    // the runtime's compile-time recurrent width calculation. Both specify the
    // mathematical quantizer. Wrap expectation uses signed modulo, not a mask.
    constexpr int index_change[]={-1,-1,-1,-1,2,4,6,8};
    for(unsigned index=0;index<49;++index)for(unsigned nibble=0;nibble<16;++nibble)
        for(unsigned initial:{0U,1U,2048U,4094U,4095U}) {
            pce::Adpcm a;a.enabled=a.playing=true;a.control=32;a.length=1;
            a.decoder_output=static_cast<std::uint16_t>(initial);
            a.decoder_index=static_cast<std::uint8_t>(index);
            a.ram[0]=static_cast<std::uint8_t>(nibble*16);
            const int width=static_cast<int>(std::floor(16*std::pow(1.1L,static_cast<int>(index))));
            int delta=width/8;
            if(nibble&1)delta+=width/4;
            if(nibble&2)delta+=width/2;
            if(nibble&4)delta+=width;
            if(nibble&8)delta=-delta;
            const int expected=(static_cast<int>(initial)+delta+4096)%4096;
            const int next_index=std::clamp(static_cast<int>(index)+index_change[nibble&7],0,48);
            a.advance_to(next_sample(a));
            require(a.decoder_output==expected && a.decoder_index==next_index,"ADPCM quantizer/wrap/index matrix");
            require(a.sample_pcm()==(expected-2048)*16,"signed full-scale PCM matrix");
            require(a.samples==1 && a.length==1 && a.read_address==0 && a.nibble &&
                    a.last_nibble==nibble && !a.end_irq && !a.half_irq && !a.reads && !a.writes,
                    "decoder changed port/length/IRQ bookkeeping");
            ++checks;
        }
    // Literal overflow vectors distinguish MSM5205 wrap from saturation. At
    // width 1552, code7 adds2910; code15 subtracts2910, modulo4096.
    for(auto [initial,nibble,expected]:{std::tuple{4095U,7U,2909U},std::tuple{0U,15U,1186U}}) {
        pce::Adpcm a;a.enabled=a.playing=true;a.control=32;a.length=1;
        a.decoder_output=static_cast<std::uint16_t>(initial);a.decoder_index=48;
        a.ram[0]=static_cast<std::uint8_t>(nibble*16);a.advance_to(next_sample(a));
        require(a.decoder_output==expected && a.decoder_index==48,"literal MSM5205 overflow wrap vector");++checks;
    }
    return checks;
}

static unsigned reset_and_hold() {
    pce::Adpcm a;a.enabled=true;a.length=2;a.ram[0]=0x7f;a.write(13,32);
    a.advance_to(next_sample(a));
    require(a.decoder_output==2078 && a.decoder_index==8 && a.nibble,"first nibble restart setup");
    a.write(13,0);const auto held=a.sample_pcm();a.advance_to(a.master_ticks+10000);
    require(a.sample_pcm()==held && a.samples==1,"stop altered held decoder");
    a.write(13,32);
    require(a.sample_pcm()==held && a.play_pending,"request reset decoder before playback event");
    a.advance_to(next_sample(a));
    // Restart resets predictor/index, while the existing nibble/address phase
    // remains authoritative: low F is consumed, not a duplicated high 7.
    require(a.decoder_output==2018 && a.decoder_index==8 && !a.nibble &&
            a.last_nibble==15 && a.read_address==1 && a.samples==2,"restart decoder/nibble semantics");
    const auto phase=a.sample_phase;
    a.write(13,128);
    require(a.decoder_output==2048 && a.decoder_index==0 && a.sample_pcm()==0 &&
            !a.nibble && !a.read_address && a.sample_phase==phase && a.samples==2 && a.ram[0]==0x7f,
            "soft reset decoder or existing clock/RAM semantics");
    a.advance_to(a.master_ticks+10000);
    require(a.sample_pcm()==0 && a.samples==2,"held reset decoded more samples");
    // Full signed conversion endpoints, with no signed shift or host clipping.
    a.decoder_output=0;require(a.sample_pcm()==-32768,"negative PCM endpoint");
    a.decoder_output=4095;require(a.sample_pcm()==32752,"positive PCM endpoint");
    return 8;
}

static unsigned control_decode_isolation() {
    for(unsigned control=0;control<256;++control) {
        pce::Adpcm a;a.enabled=a.playing=true;a.control=32;
        a.address=17;a.length=19;a.decoder_output=1234;a.decoder_index=37;
        a.write(13,static_cast<std::uint8_t>(control));
        require(a.decoder_output==((control&128)?2048:1234) &&
                a.decoder_index==((control&128)?0:37),"control write decoder reset isolation");
        require(a.samples==0 && a.master_ticks==0,"control write decoded an unscheduled sample");
    }
    return 256;
}

static unsigned partitioning() {
    for(unsigned rate=0;rate<16;++rate) {
        pce::Adpcm whole,parts;whole.enabled=parts.enabled=true;
        for(unsigned address=0;address<65536;++address)
            whole.ram[address]=parts.ram[address]=static_cast<std::uint8_t>(address*73^(address>>3));
        whole.length=parts.length=2000;whole.read_address=parts.read_address=0xff00;
        whole.write(14,rate);parts.write(14,rate);whole.write(13,0x60);parts.write(13,0x60);
        whole.advance_to(1200000);
        for(unsigned t=1;t<1200000;t+=7919)parts.advance_to(t);
        parts.advance_to(1200000);
        require(state(whole)==state(parts),"ADPCM PCM depends on advance partition");
        require(whole.ram==parts.ram,"decoder mutated sample RAM");
    }
    return 16;
}

int main() {
    try {
        const auto count=known_sequence()+quantizer_matrix()+reset_and_hold()+control_decode_isolation()+partitioning();
        std::cout<<"ADPCM PCM: "<<count<<" independent expectation groups passed\n";
    }catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
}
