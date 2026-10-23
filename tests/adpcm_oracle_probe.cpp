// Authored state bridge: the independent emulator supplies the initial state;
// subsequent raw decoder/clock results are produced by the toolkit itself.
#include "pce/adpcm.hpp"
#include "pce/runtime.hpp"
#include <fstream>
#include <iostream>
#include <string>

int main(int argc,char** argv) {
    try {
        if(argc!=3) throw pce::Fault("usage: pce-adpcm-probe RAM PLAN");
        pce::Adpcm a;a.enabled=true;
        std::ifstream ram(argv[1],std::ios::binary),plan(argv[2]);
        if(!ram.read(reinterpret_cast<char*>(a.ram.data()),a.ram.size()) || ram.peek()!=EOF || !plan)
            throw pce::Fault("invalid authored RAM/plan");
        unsigned rate,control,read,length,playing,pending,nibble,output,index,end,half;
        std::uint64_t phase,time;
        if(!(plan>>rate>>control>>read>>length>>playing>>pending>>nibble>>output>>index>>phase>>time>>end>>half) ||
           rate>255 || control>255 || read>65535 || length>131071 || playing>1 || pending>1 || nibble>1 ||
           output>4095 || index>48 || end>1 || half>1)
            throw pce::Fault("invalid ADPCM initial state");
        a.sample_rate=static_cast<std::uint8_t>(rate);a.control=static_cast<std::uint8_t>(control);
        a.read_address=static_cast<std::uint16_t>(read);a.length=length;a.playing=playing!=0;
        a.play_pending=pending!=0;a.nibble=nibble!=0;a.decoder_output=static_cast<std::uint16_t>(output);
        a.decoder_index=static_cast<std::uint8_t>(index);a.sample_phase=phase;a.master_ticks=time;
        a.end_irq=end!=0;a.half_irq=half!=0;
        std::string op;bool first=true;std::cout<<'[';
        while(plan>>op) {
            if(op=="w") {
                unsigned port,value;
                if(!(plan>>port>>value) || port<8 || port>14 || value>255)throw pce::Fault("invalid write");
                a.write(port,static_cast<std::uint8_t>(value));
            } else if(op=="s") {
                std::uint64_t delta;
                if(!(plan>>delta) || delta>10000000)throw pce::Fault("invalid finite advance");
                a.advance_to(a.master_ticks+delta);
                if(!first)std::cout<<',';first=false;
                std::cout<<"{\"predictor\":"<<a.decoder_output<<",\"index\":"<<unsigned(a.decoder_index)
                    <<",\"control\":"<<unsigned(a.control)<<",\"rate\":"<<unsigned(a.sample_rate)
                    <<",\"phase\":"<<a.sample_phase<<",\"period\":"<<a.sample_period()
                    <<",\"read_address\":"<<a.read_address<<",\"length\":"<<a.length
                    <<",\"playing\":"<<(a.playing?"true":"false")<<",\"pending\":"<<(a.play_pending?"true":"false")
                    <<",\"nibble\":"<<(a.nibble?"true":"false")<<",\"end\":"<<(a.end_irq?"true":"false")
                    <<",\"half\":"<<(a.half_irq?"true":"false")<<",\"pcm\":"<<a.sample_pcm()<<'}';
            } else throw pce::Fault("unknown plan command");
        }
        if(!plan.eof())throw pce::Fault("incomplete plan");
        std::cout<<"]\n";
    } catch(const std::exception& error) {std::cerr<<error.what()<<'\n';return 1;}
}
