#include "pce/input_script.hpp"
#include "pce/runtime.hpp"
#include <fstream>
#include <limits>
#include <sstream>

namespace pce {
namespace {
std::uint64_t number(const std::string& text) {
    unsigned base=10,index=0;
    if(text.size()>2 && text[0]=='0' && (text[1]=='x' || text[1]=='X')){base=16;index=2;}
    if(index==text.size())throw Fault("input script requires an unsigned integer");
    std::uint64_t value=0;
    for(;index<text.size();++index){
        const auto ch=text[index];
        const unsigned digit=ch>='0' && ch<='9'?unsigned(ch-'0'):
            ch>='a' && ch<='f'?unsigned(ch-'a'+10):ch>='A' && ch<='F'?unsigned(ch-'A'+10):16;
        if(digit>=base)throw Fault("invalid unsigned integer in input script");
        if(value>(std::numeric_limits<std::uint64_t>::max()-digit)/base)throw Fault("input script integer overflow");
        value=value*base+digit;
    }
    return value;
}
}
std::vector<InputEvent> read_input_script(const std::string& path) {
    std::ifstream file(path,std::ios::binary);
    if(!file)throw Fault("cannot open input script");
    std::string contents;
    char ch;
    while(file.get(ch)){
        if(contents.size()==16384)throw Fault("input script exceeds 16 KiB");
        const auto byte=static_cast<unsigned char>(ch);
        if((byte<32 && ch!='\t' && ch!='\n' && ch!='\r') || byte>126)throw Fault("input script must contain ASCII text");
        contents.push_back(ch);
    }
    if(!file.eof())throw Fault("cannot read input script");
    std::istringstream lines(contents);
    std::string line;
    bool header=false;
    std::vector<InputEvent> events;
    while(std::getline(lines,line)){
        std::istringstream fields(line);
        std::vector<std::string> tokens;
        std::string token;
        while(fields>>token){
            if(tokens.empty() && token[0]=='#')break;
            tokens.push_back(token);
            if(tokens.size()>6)throw Fault("extra fields in input script");
        }
        if(tokens.empty())continue;
        if(!header){
            if(tokens.size()!=2 || tokens[0]!="PCE_INPUT" || tokens[1]!="1")throw Fault("input script requires PCE_INPUT 1 header");
            header=true;continue;
        }
        if(tokens.size()!=6)throw Fault("input event requires a tick and five button masks");
        if(events.size()==256)throw Fault("input script exceeds 256 events");
        InputEvent event;event.ticks=number(tokens[0]);
        if(!events.empty() && event.ticks<=events.back().ticks)throw Fault("input script ticks must increase strictly");
        for(unsigned n=0;n<5;++n){
            const auto mask=number(tokens[n+1]);
            if(mask>0xFFF)throw Fault("input script button mask exceeds 12 bits");
            event.buttons[n]=static_cast<std::uint16_t>(mask);
        }
        events.push_back(event);
    }
    if(!header)throw Fault("input script requires PCE_INPUT 1 header");
    return events;
}
} // namespace pce
