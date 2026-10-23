// Authored settled port observations; no oscillators, PCM or CPU-tier claim.
#include "pce/runtime.hpp"
#include <fstream>
#include <iostream>
#include <string>
#include <vector>

int main(int argc,char** argv) {
    if(argc!=2)return 2;
    try {
        unsigned count;std::ifstream in(argv[1]);if(!(in>>count) || !count || count>256)return 2;
        pce::Bus bus;bus.enable_adpcm();bus.enable_psg();pce::Cpu cpu;
        std::vector<unsigned> reads;
        for(unsigned i=0;i<count;++i) {
            unsigned address;int value;if(!(in>>address>>value) || address>65535 || value < -1 || value>255)return 2;
            if(!((address>=0x800 && address<=0xBFF) || (address>=0x1808 && address<=0x180E)))return 2;
            if(value<0)reads.push_back(bus.read(cpu,static_cast<std::uint16_t>(address)));
            else bus.write(cpu,static_cast<std::uint16_t>(address),static_cast<std::uint8_t>(value));
            cpu.ticks+=120;bus.sync(cpu);
        }
        std::string tail;if(in>>tail)return 2;
        constexpr char hex[]="0123456789abcdef";
        auto output=[&](unsigned value){std::cout<<hex[(value>>4)&15]<<hex[value&15];};
        std::cout<<"{\"reads\":\"";for(auto value:reads)output(value);
        std::cout<<"\",\"ram\":\"";for(auto value:bus.adpcm.ram)output(value);
        std::cout<<"\",\"adpcm\":{\"address\":"<<bus.adpcm.address<<",\"read_address\":"<<bus.adpcm.read_address
            <<",\"write_address\":"<<bus.adpcm.write_address<<",\"length\":"<<bus.adpcm.length
            <<",\"control\":"<<unsigned(bus.adpcm.control)<<",\"dma\":"<<unsigned(bus.adpcm.dma)
            <<",\"playing\":"<<(bus.adpcm.playing?"true":"false")<<"},\"psg\":{\"selected\":"<<unsigned(bus.psg.selected)
            <<",\"main_volume\":"<<unsigned(bus.psg.main_volume)<<",\"lfo_frequency\":"<<unsigned(bus.psg.lfo_frequency)
            <<",\"lfo_control\":"<<unsigned(bus.psg.lfo_control)<<",\"channels\":[";
        for(unsigned i=0;i<6;++i) {const auto& c=bus.psg.channels[i];
            std::cout<<(i?",":"")<<"{\"frequency\":"<<c.frequency
                <<",\"balance\":"<<unsigned(c.balance)<<",\"wave_index\":"<<unsigned(c.wave_index)
                <<",\"dda_mode\":"<<unsigned(c.dda_mode())<<",\"enabled\":"<<unsigned(c.playing())
                <<",\"noise_enabled\":"<<unsigned(i>=4 && (c.noise&128))<<'}';}
        std::cout<<"]}}\n";return 0;
    }catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 2;}
}
