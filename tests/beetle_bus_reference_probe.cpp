// Authored observer wrapper around a separately compiled original GPL core.
#define main previous_beetle_probe_main
#include "beetle_cpu_probe.cpp"
#undef main
#include "bus_reference_support.hpp"
struct BusFastPage{using type=uintptr_t(HuC6280::*)[9];friend type bus_fast_page(BusFastPage);};
template<class Tag,typename Tag::type Member>struct BusFastAccess{friend typename Tag::type bus_fast_page(Tag){return Member;}};
template struct BusFastAccess<BusFastPage,&HuC6280::FastPageR>;
void bus_reference_access(unsigned logical,unsigned physical,unsigned value,bool write,bool fixed,bool direct){
    if(!bus_reference::enabled)return;
    std::array<std::uint8_t,8> mpr{};for(unsigned i=0;i<8;++i)mpr[i]=(HuCPU.*member(MPR{}))[i];
    bus_reference::access(HuCPU.Timestamp(),mpr,logical,physical,value,write,fixed,direct);
}
int main(int argc,char**argv){try{
    if(argc!=4)throw std::runtime_error("beetle-bus AUTHORED_ROM low|high|block 0|1");
    const auto fixture=bus_fixture(argv[2]);const std::string enabled=argv[3];if(enabled!="0"&&enabled!="1")throw std::runtime_error("Boolean observer choice required");
    const auto rom=std::filesystem::absolute(argv[1]);if(!std::filesystem::is_regular_file(rom)||std::filesystem::file_size(rom)!=262144)throw std::runtime_error("256KiB authored firmware required");
    private_directory=rom.parent_path().string();retro_set_environment(environment);retro_set_video_refresh(video);retro_set_audio_sample(audio);retro_set_audio_sample_batch(audio_batch);retro_set_input_poll(poll);retro_set_input_state(input);retro_init();
    const auto name=rom.string();const retro_game_info info{name.c_str(),nullptr,0,nullptr};if(!retro_load_game(&info)||PCE_IsCD)throw std::runtime_error("Original HuCard load failed");
    std::vector<bpp_t> pixels(2048*264);std::array<int32,264> line_widths{};MDFN_Rect display{};MDFN_Surface surface{pixels.data(),2048,264,2048};
    vce->SetPixelFormat(nullptr,0);vce->StartFrame(&surface,&display,line_widths.data(),false);vce->SetCDEvent(0x3FFFFFFF);HuCPU.SetEventHandler(clock_devices);HuCPU.Run(true);
    for(unsigned i=0;i<fixture.primer;++i)run_supported_instruction();
    const auto initial=pure_observe();if(initial.pc!=fixture.instructions.front().pc||initial.clock_divisor!=fixture.divisor)throw std::runtime_error("Software primer differs");
    reference_trace::write_initial(std::cout,initial);bus_reference::enabled=enabled=="1";
    for(unsigned i=0;i<fixture.instructions.size();++i){
        if(pure_observe().pc!=fixture.instructions[i].pc)throw std::runtime_error("Measured route differs");
        do{
            if(++bus_reference::calls>100)throw std::runtime_error("Finite original call bound");
            const auto entry=pure_observe();const auto source=bus_reference::candidate(fixture,entry.pc);
            // Host source inspection uses the original mapped direct pointer;
            // code must remain immutable authored ROM, not MMIO/RAM inference.
            for(unsigned n=0;n<source.bytes.size();++n){const auto address=static_cast<unsigned short>(entry.pc+n);const auto physical=(unsigned(entry.mpr[address>>13])<<13)|(address&8191);const auto pointer=(HuCPU.*bus_fast_page(BusFastPage{}))[address>>13];if(physical>=262144||!pointer||*reinterpret_cast<const std::uint8_t*>(pointer+address)!=source.bytes[n])throw std::runtime_error("Actual candidate bytes differ");}
            bus_reference::instruction_begin(bus_reference::calls,entry,source);
            if(!(entry.p&HuC6280::I_FLAG))throw std::runtime_error("Unmasked IRQ stepping unsupported");
            HuCPU.Run(true);bus_reference::retired(bus_reference::calls,pure_observe(),!HuCPU.InBlockMove());
        }while(HuCPU.InBlockMove());
    }
    bus_reference::enabled=false;bus_reference::finish(static_cast<unsigned>(fixture.instructions.size()));retro_unload_game();retro_deinit();return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
