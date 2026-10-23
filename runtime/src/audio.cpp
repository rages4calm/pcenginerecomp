#include "pce/audio.hpp"

namespace pce {
void Psg::write(unsigned port, std::uint8_t value) {
    ++writes;
    const unsigned reg=port&15;
    if(reg==0) { selected=value&7;return; }
    if(reg==1) { main_volume=value;return; }
    if(reg==8) { lfo_frequency=value;return; }
    if(reg==9) {
        if(value&128) {
            channels[1].wave_index=0;
            channels[1].dda=channels[1].waveform[0];
        }
        lfo_control=value;return;
    }
    if(selected>=channels.size()) return;
    auto& channel=channels[selected];
    switch(reg) {
    case 2: channel.frequency=static_cast<std::uint16_t>((channel.frequency&0xF00)|value);break;
    case 3: channel.frequency=static_cast<std::uint16_t>((channel.frequency&255)|((value&15)<<8));break;
    case 4:
        // Gear-reference write semantics: DDA holds the waveform address
        // reset, including the transition back to waveform mode.
        if(channel.dda_mode() || (value&64)) channel.wave_index=0;
        channel.control=value;break;
    case 5: channel.balance=value;break;
    case 6:
        channel.wave=value&31;
        if(channel.dda_mode()) channel.dda=channel.wave;
        else {
            channel.waveform[channel.wave_index]=channel.wave;
            if(!channel.playing()) channel.wave_index=(channel.wave_index+1)&31;
        }
        break;
    case 7: if(selected>=4) channel.noise=value;break;
    default: break; // Unused PSG register numbers have no register storage.
    }
}
} // namespace pce
