// Authored observer/wiring around a separately compiled ORIGINAL full Beetle
// PCE core. No emulator body is extracted, rewritten or linked to pce-runtime.
#include <libretro.h>
#include <mednafen/pce/pce.h>
#include <mednafen/pce/huc.h>
#include <mednafen/pce/vce.h>
#include "reference_trace_support.hpp"
#include <cstdio>
#include <cstdarg>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>

extern VCE* vce;
namespace {
std::string private_directory;
void log_message(enum retro_log_level,const char* format,...) {
    va_list values;va_start(values,format);std::vfprintf(stderr,format,values);va_end(values);
}
bool environment(unsigned command,void* data) {
    switch(command) {
    case RETRO_ENVIRONMENT_GET_SYSTEM_DIRECTORY:
    case RETRO_ENVIRONMENT_GET_SAVE_DIRECTORY:
        *static_cast<const char**>(data)=private_directory.c_str();return true;
    case RETRO_ENVIRONMENT_GET_LOG_INTERFACE:
        static_cast<retro_log_callback*>(data)->log=log_message;return true;
    case RETRO_ENVIRONMENT_SET_PIXEL_FORMAT:return true;
    default:return false;
    }
}
void video(const void*,unsigned,unsigned,std::size_t){}
void audio(std::int16_t,std::int16_t){}
std::size_t audio_batch(const std::int16_t*,std::size_t count){return count;}
void poll(){}
std::int16_t input(unsigned,unsigned,unsigned,unsigned){return 0;}
int32 MDFN_FASTCALL clock_devices(int32 timestamp){return vce->SyncReal(timestamp);}

template<class T,typename T::type Member>struct Access{friend typename T::type member(T){return Member;}};
#define FIELD(Name,Type,Field) struct Name{using type=Type HuC6280::*;friend type member(Name);};template struct Access<Name,&HuC6280::Field>;
FIELD(PC,uint32,PC) FIELD(A,uint8,A) FIELD(X,uint8,X) FIELD(Y,uint8,Y)
FIELD(S,uint8,S) FIELD(P,uint8,P) FIELD(Speed,uint8,speed)
struct MPR{using type=uint8(HuC6280::*)[9];friend type member(MPR);};template struct Access<MPR,&HuC6280::MPR>;
#undef FIELD

reference_trace::State observe() {
    reference_trace::State out;
    out.pc=static_cast<std::uint16_t>(HuCPU.*member(PC{}));
    out.a=HuCPU.*member(A{});out.x=HuCPU.*member(X{});out.y=HuCPU.*member(Y{});
    out.sp=HuCPU.*member(S{});out.p=HuCPU.*member(P{});
    for(unsigned page=0;page<8;++page)out.mpr[page]=(HuCPU.*member(MPR{}))[page];
    out.mpr_latch=std::nullopt; // This original core has no corresponding latch.
    out.clock_divisor=(HuCPU.*member(Speed{}))?3:12;out.ticks=HuCPU.Timestamp();
    out.wram_sha256=reference_trace::hash(std::span<const std::uint8_t>(BaseRAM,8192));
    return out;
}
reference_trace::State pure_observe() {
    const auto first=observe(),second=observe();
    if(first!=second)throw std::runtime_error("Repeated full-core observation changed state");
    return first;
}
unsigned count(const char* text,unsigned maximum) {
    const std::string value=text;std::size_t used=0;const auto number=std::stoul(value,&used);
    if(used!=value.size() || number>maximum)throw std::runtime_error("Bounded integer required");
    return static_cast<unsigned>(number);
}
void dump_new(const std::filesystem::path& path) {
#ifdef _WIN32
    auto* file=_wfopen(path.c_str(),L"wx");
#else
    auto* file=std::fopen(path.c_str(),"wx");
#endif
    if(!file)throw std::runtime_error("Choose new private final WRAM dump");
    const auto written=std::fwrite(BaseRAM,1,8192,file);const auto closed=std::fclose(file);
    if(written!=8192 || closed)throw std::runtime_error("Final WRAM dump failed");
}
}
int main(int argc,char**argv) {
    try {
        std::cout<<std::unitbuf; // Retain every completed boundary on a later fault.
        if(argc!=5)throw std::runtime_error("beetle-cpu AUTHORED_ROM STEPS PRIMER_STEPS NEW_PRIVATE_WRAM");
        const auto steps=count(argv[2],99997),primer=count(argv[3],10000);
        if(!steps)throw std::runtime_error("At least one measured instruction is required");
        const auto rom=std::filesystem::absolute(argv[1]),dump=std::filesystem::absolute(argv[4]);
        if(!std::filesystem::is_regular_file(rom) || std::filesystem::file_size(rom)!=262144 ||
            std::filesystem::exists(dump))throw std::runtime_error("Require authored 256KiB ROM and new private output");
        private_directory=dump.parent_path().string();
        const std::array<std::uint8_t,3> abc{'a','b','c'};
        if(reference_trace::hash({})!="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855" ||
            reference_trace::hash(abc)!="ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")
            throw std::runtime_error("Independent SHA256 standard vectors failed");
        retro_set_environment(environment);retro_set_video_refresh(video);retro_set_audio_sample(audio);
        retro_set_audio_sample_batch(audio_batch);retro_set_input_poll(poll);retro_set_input_state(input);retro_init();
        const auto name=rom.string();const retro_game_info info{name.c_str(),nullptr,0,nullptr};
        if(!retro_load_game(&info) || PCE_IsCD)throw std::runtime_error("Full original HuCard core load failed");
        // The normal RunPartial frontend installs the same full-device clock.
        // Use its public scheduler here while the ORIGINAL CPU steps itself.
        // This pinned core's active-line renderer still writes with skip=true.
        // Supply the same bounded software surface as its real frontend, even
        // though no host window or video callback is used by this observer.
        std::vector<bpp_t> pixels(2048*264);
        std::array<int32,264> line_widths{};MDFN_Rect display{};
        MDFN_Surface surface{pixels.data(),2048,264,2048};
        vce->SetPixelFormat(nullptr,0);
        vce->StartFrame(&surface,&display,line_widths.data(),false);vce->SetCDEvent(0x3FFFFFFF);
        HuCPU.SetEventHandler(clock_devices);
        HuCPU.Run(true); // Original pending reset/vector handling, NO retirement.
        auto initial=pure_observe();
        if(initial.ticks!=0 || initial.p!=4 || initial.clock_divisor!=12)
            throw std::runtime_error("Unexpected raw original reset result");
        for(unsigned i=0;i<primer;++i) {
            const auto before=pure_observe();
            std::cerr<<"BEETLE_PRIMER "<<i+1<<" pc="<<before.pc<<" ticks="<<before.ticks<<'\n';
            do{HuCPU.Run(true);}while(HuCPU.InBlockMove());
            const auto after=pure_observe();
            if(after.ticks<=before.ticks)throw std::runtime_error("Primer failed to retire an instruction");
        }
        initial=pure_observe();reference_trace::write_initial(std::cout,initial);
        for(unsigned i=1;i<=steps;++i) {
            const auto before=pure_observe();
            do{HuCPU.Run(true);}while(HuCPU.InBlockMove());
            const auto after=pure_observe();
            if(after.ticks<=before.ticks || HuCPU.InBlockMove())throw std::runtime_error("Incomplete original step");
            reference_trace::write_instruction(std::cout,i,before,after);
        }
        reference_trace::write_final(std::cout,steps);dump_new(dump);
        std::cerr<<"BEETLE_FULL_CORE "<<steps<<" primer="<<primer<<" observer_checks="<<2*(steps+primer+1)<<'\n';
        retro_unload_game();retro_deinit();return 0;
    }catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
}
