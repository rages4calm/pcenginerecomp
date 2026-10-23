#include "pce/audio.hpp"
#include "pce/runtime.hpp"
#include <iostream>
#include <tuple>

static void require(bool value,const char* why){if(!value)throw std::runtime_error(why);}
static auto state(const pce::Psg::Channel& c){return std::tuple{c.frequency,c.control,c.balance,c.wave_index,c.wave,c.dda,c.noise,c.waveform};}

static unsigned register_matrix(){
    unsigned checks=0;
    for(unsigned selected=0;selected<8;++selected)for(unsigned value=0;value<256;++value){
        pce::Psg p;p.enabled=true;p.write(0,selected|0xF8);
        require(p.selected==selected,"PSG channel select is not low three bits");
        p.write(1,value);p.write(8,value^0xA5);p.write(9,value&127);
        require(p.main_volume==value && p.lfo_frequency==(value^0xA5) && p.lfo_control==(value&127),"PSG globals were gated by channel selection");
        for(unsigned port=2;port<=7;++port){
            auto before=p.channels;p.write(port,value);
            for(unsigned n=0;n<6;++n)if(n!=selected || (port==7 && selected<4))
                require(state(p.channels[n])==state(before[n]),"PSG channel/noise write affected an unselected or absent channel");
        }
        if(selected<6){
            auto& c=p.channels[selected];
            require(c.frequency==((value&15)*256+value) && c.control==value && c.balance==value &&
                    c.wave==(value&31) && c.playing()==bool(value&128) && c.dda_mode()==bool(value&64),"PSG frequency width/control/balance/data expectation");
            require(c.noise==(selected<4?0:value),"PSG noise must exist only on channels four/five");
            if(selected>=4)require(c.noise_period()==((value&31)==31?32:(31-(value&31))*64),"PSG noise divider expectation");
        }
        require(p.writes==10,"PSG write accounting did not count accepted/ignored register accesses");++checks;
    }
    for(unsigned high=0;high<16;++high)for(unsigned port=10;port<16;++port){
        pce::Psg p;p.selected=3;p.main_volume=0xAB;p.lfo_frequency=0x13;p.lfo_control=0x7F;
        p.channels[3].control=0x91;p.channels[3].waveform[4]=27;const auto before=state(p.channels[3]);
        p.write(high*16+port,0xFF);
        require(p.selected==3 && p.main_volume==0xAB && p.lfo_frequency==0x13 && p.lfo_control==0x7F && state(p.channels[3])==before && p.writes==1,
                "unused PSG port acquired register effects");++checks;
    }
    return checks;
}

static unsigned waveform_matrix(){
    unsigned checks=0;
    for(unsigned selected=0;selected<6;++selected)for(unsigned control=0;control<256;++control){
        pce::Psg p;p.write(0,selected);p.write(4,control);auto& c=p.channels[selected];
        for(unsigned n=0;n<83;++n){
            p.write(6,static_cast<std::uint8_t>(n*37+19));const auto value=(n*37+19)&31;
            if(control&64){
                require(c.dda==value && c.wave_index==0 && c.waveform==std::array<std::uint8_t,32>{},"DDA write changed waveform RAM/address or retained upper sample bits");
            }else if(control&128){
                require(c.wave_index==0 && c.waveform[0]==value,"enabled waveform write advanced address or missed current sample");
                for(unsigned i=1;i<32;++i)require(c.waveform[i]==0,"enabled wave write changed another sample");
            }else{
                require(c.wave_index==(n+1)%32 && c.waveform[n%32]==value,"disabled waveform upload address wrap/sample width");
            }
            ++checks;
        }
        if(!(control&192))for(unsigned cell=0;cell<32;++cell){
            const unsigned latest=cell+(cell<=18?64:32);
            require(c.waveform[cell]==((latest*37+19)&31),"waveform upload did not retain independently expected last value per cell");++checks;
        }
    }
    // Address reset is a write-side Gear profile. No elapsed oscillator clocks
    // are used to derive these expectations.
    for(unsigned old:{0U,64U,128U,192U})for(unsigned next=0;next<256;++next)for(unsigned address=0;address<32;++address){
        pce::Psg p;p.channels[0].control=old;p.channels[0].wave_index=address;p.channels[0].dda=23;
        p.write(4,next);
        require(p.channels[0].wave_index==(((old|next)&64)?0:address) && p.channels[0].control==next && p.channels[0].dda==23,
                "DDA address-reset transition/control write changed wrong state");++checks;
    }
    for(unsigned select=0;select<8;++select)for(unsigned value=0;value<256;++value){
        pce::Psg p;p.selected=select;p.channels[0].wave_index=19;p.channels[1].wave_index=7;p.channels[1].waveform[0]=29;p.channels[1].dda=11;
        p.write(9,value);
        require(p.lfo_control==value && p.channels[0].wave_index==19 &&
                p.channels[1].wave_index==((value&128)?0:7) && p.channels[1].dda==((value&128)?29:11),"LFO trigger source index/DDA/global gating expectation");++checks;
    }
    return checks;
}

static unsigned bus_checks(){
    unsigned checks=0;
    pce::Bus b;b.kind[255]=pce::BankKind::io;b.psg.enabled=true;b.enable_interrupts();
    pce::Cpu s;s.mpr={255,248,128,129,255,131,132,0};
    for(unsigned alias:{0x0800U,0x0BF0U,0x8800U})for(unsigned value=0;value<256;++value){
        b.write(s,alias,4);b.write(s,alias+3,value);b.write(s,alias+2,value^0xA5);
        const auto writes=b.psg.writes;
        require(b.psg.selected==4 && b.psg.channels[4].frequency==((value&15)*256+(value^0xA5)),"PSG bus alias/frequency routing");
        for(unsigned port=0;port<16;++port)require(b.read(s,alias+port)==(value^0xA5),"PSG read did not return general I/O latch");
        require(b.psg.writes==writes && !s.cycles && !s.ticks,"PSG read changed channel state or added fixed wait");
        b.write(s,0x1400,value);require(b.read(s,alias+2)==value,"PSG undriven read did not share IRQ latch");
        require(b.read_block(s,alias+2)==0,"block read must suppress PSG data polling");++checks;
    }
    pce::Bus strict;strict.kind[255]=pce::BankKind::io;bool fault=false;
    try{strict.write(s,0x0800,1);}catch(const pce::Fault&){fault=true;}
    require(fault,"strict bus silently enabled PSG writes");++checks;
    return checks;
}

int main(){try{const auto r=register_matrix(),w=waveform_matrix(),b=bus_checks();
    std::cout<<r<<" independently expected PSG register groups, "<<w<<" waveform/DDA/LFO cases and "<<b<<" bus/latch groups passed; functional state only, no audio synthesis\n";return 0;
}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}}
