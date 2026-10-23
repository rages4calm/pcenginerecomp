#include "pce/input_script.hpp"
#include "pce/runtime.hpp"
#include <chrono>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <limits>
#include <string>

static void require(bool value,const char* why){if(!value)throw std::runtime_error(why);}
struct Fixture {
    std::filesystem::path path=std::filesystem::temp_directory_path()/
        ("pce-authored-input-"+std::to_string(std::chrono::steady_clock::now().time_since_epoch().count())+".txt");
    ~Fixture(){std::error_code error;std::filesystem::remove(path,error);}
    std::vector<pce::InputEvent> read(const std::string& text){
        {std::ofstream out(path,std::ios::binary|std::ios::trunc);out.write(text.data(),static_cast<std::streamsize>(text.size()));require(bool(out),"cannot create owned synthetic input script");}
        return pce::read_input_script(path.string());
    }
    void reject(const std::string& text){bool fault=false;try{read(text);}catch(const pce::Fault&){fault=true;}require(fault,"malformed input script was accepted");}
};

int main(){try{
    Fixture f;unsigned checks=0;
    auto events=f.read("# authored fixture\r\n\tPCE_INPUT 1\r\n\r\n0 0x8 0 0 0 0\r\n# release\r\n00120 0 1 0xFFF 0X800 4095\r\n18446744073709551615 0 0 0 0 0");
    require(events.size()==3 && events[0].ticks==0 && events[0].buttons==std::array<std::uint16_t,5>{8,0,0,0,0} &&
            events[1].ticks==120 && events[1].buttons==std::array<std::uint16_t,5>{0,1,4095,2048,4095} &&
            events[2].ticks==std::numeric_limits<std::uint64_t>::max(),"input script decimal/hex/CRLF/comment/button-order expectation");++checks;
    require(f.read("PCE_INPUT 1\n").empty(),"header-only input schedule should have no events");++checks;
    for(unsigned group=0;group<16;++group){
        std::string script="PCE_INPUT 1\n";
        for(unsigned n=0;n<256;++n)script+=std::to_string(n)+" "+std::to_string(group*256+n)+" 0 0 0 0\n";
        events=f.read(script);require(events.size()==256,"bounded all-mask script changed event count");
        for(unsigned n=0;n<256;++n){
            require(events[n].buttons[0]==group*256+n && events[n].ticks==n,"valid 12-bit input mask changed value");++checks;
        }
    }
    for(const std::string& text:{"","# only comments\n","PCE_INPUT 2\n","PCE_INPUT 01\n","PCE_INPUT 1 extra\n",
            "PCE_INPUT 1\n0 0 0 0 0\n","PCE_INPUT 1\n0 0 0 0 0 0 0\n","PCE_INPUT 1\n0 0 0 0 0 0 # inline\n",
            "PCE_INPUT 1\n-1 0 0 0 0 0\n","PCE_INPUT 1\n+1 0 0 0 0 0\n","PCE_INPUT 1\n0x 0 0 0 0 0\n",
            "PCE_INPUT 1\n0xG 0 0 0 0 0\n","PCE_INPUT 1\n1e3 0 0 0 0 0\n","PCE_INPUT 1\n18446744073709551616 0 0 0 0 0\n",
            "PCE_INPUT 1\n0x10000000000000000 0 0 0 0 0\n","PCE_INPUT 1\n0 -1 0 0 0 0\n","PCE_INPUT 1\n0 +1 0 0 0 0\n",
            "PCE_INPUT 1\n0 4096 0 0 0 0\n","PCE_INPUT 1\n0 0x1000 0 0 0 0\n","PCE_INPUT 1\n0 0 0 0 0 18446744073709551616\n",
            "PCE_INPUT 1\n0 0 0 0 0 0\n0 0 0 0 0 0\n","PCE_INPUT 1\n2 0 0 0 0 0\n1 0 0 0 0 0\n","PCE_INPUT 1\nPCE_INPUT 1\n"}){
        f.reject(text);++checks;
    }
    for(unsigned byte:{0U,1U,8U,11U,12U,31U,127U,128U,255U}){
        f.reject(std::string("PCE_INPUT 1\n# ")+static_cast<char>(byte));++checks;
    }
    std::string maximum="PCE_INPUT 1\n";
    for(unsigned n=0;n<256;++n)maximum+=std::to_string(n)+" 0 0 0 0 0\n";
    require(f.read(maximum).size()==256,"bounded 256-event input script rejected");++checks;
    f.reject(maximum+"256 0 0 0 0 0\n");++checks;
    auto padded=std::string("PCE_INPUT 1\n#")+std::string(16384-13,'x');
    require(padded.size()==16384 && f.read(padded).empty(),"exactly 16 KiB input script rejected");++checks;
    f.reject(padded+'x');++checks;
    bool missing=false;try{pce::read_input_script(f.path.string()+".missing");}catch(const pce::Fault&){missing=true;}
    require(missing,"missing input script was accepted");++checks;
    // Parsing snapshots has no authority to advance clocks or relatch a pad.
    pce::Joypad pad;pad.enabled=true;pad.write(0);const auto latch=pad.latched;
    events=f.read("PCE_INPUT 1\n0 8 0 0 0 0\n12 0 0 0 0 0\n");pad.set_pressed(0,events[0].buttons[0]);
    require(pad.latched==latch && pad.pads[0].pressed==8,"host input script snapshot implicitly resampled guest joypad output");++checks;
    std::cout<<checks<<" independently expected input-script syntax, bounds, integer and snapshot checks passed\n";return 0;
}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}}
