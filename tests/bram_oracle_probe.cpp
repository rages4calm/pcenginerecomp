// Authored CPU fixture. External references run as separate processes.
#include "pce/runtime.hpp"
#include "pce/code_capture.hpp"
#include "bram_probe_support.hpp"
#include <memory>
struct Adapter {
    std::unique_ptr<pce::Bus> bus;pce::Cpu state;const std::vector<std::uint8_t>& rom;pce::CodeCapture* capture;unsigned fast=0;
    void reset(unsigned selected) {fast=selected;bus=std::make_unique<pce::Bus>();bus->configure_system_card(pce::SystemCardProfile::standard,rom);
        bus->enable_cd_control();bus->power_on_cpu(state);state.clock_divisor=fast?3:12;const auto bytes=bram_probe::seed();bus->load(0x1EE000,bytes.data(),bytes.size());}
    void instructions(unsigned count) {if(!bus)throw std::runtime_error("instructions before reset");for(unsigned i=0;i<count;++i){pce::CodeCapture::Pending pending;if(capture)pending=capture->before(*bus,state);
#ifdef PCE_BRAM_NATIVE_ONLY
        if(pce::generated_step(*bus,state,100000000)!=pce::Exit::executed)throw std::runtime_error("native miss; interpreter fallback forbidden");
#else
        if(pce::interpret_step(*bus,state,100000000)!=pce::Exit::executed)throw std::runtime_error("authored interpreter refused");
#endif
        if(capture)capture->after(pending,state);}}
    std::vector<std::uint64_t> cpu()const {if(!bus)throw std::runtime_error("state before reset");std::vector<std::uint64_t> out{state.pc,state.a,state.x,state.y,state.sp,state.p,state.clock_divisor,state.ticks};for(auto m:state.mpr)out.push_back(m);return out;}
    std::vector<std::uint64_t> bram()const{return bram_probe::values(bus->bytes->data()+0x1EE000,2048);}
    std::vector<std::uint64_t> ram()const{return bram_probe::values(bus->bytes->data()+0x1F0000,16);}
    unsigned gate()const{return bus->cd.bram_unlocked;}
    void save(const std::filesystem::path& path) {const auto generations=bus->generation;const auto reads=bus->cd.reads,writes=bus->cd.writes;std::ofstream file(path,std::ios::binary);if(!file)throw std::runtime_error("raw export open");file.write(reinterpret_cast<const char*>(bus->bytes->data()+0x1EE000),2048);file.close();if(!file||generations!=bus->generation||reads!=bus->cd.reads||writes!=bus->cd.writes)throw std::runtime_error("raw export failed or touched guest devices");}
    void restore(const std::filesystem::path& path) {reset(fast);const auto before=cpu();const auto locked=gate();std::ifstream file(path,std::ios::binary|std::ios::ate);if(!file||file.tellg()!=2048)throw std::runtime_error("invalid raw restore size");std::array<std::uint8_t,2048> bytes{};file.seekg(0);file.read(reinterpret_cast<char*>(bytes.data()),2048);if(!file)throw std::runtime_error("short raw restore");bus->load(0x1EE000,bytes.data(),bytes.size());if(before!=cpu()||locked!=gate())throw std::runtime_error("raw restore mutated CPU/gate");}
};
int main(int argc,char** argv) {try {if(argc!=4&&argc!=6)throw std::runtime_error("usage: bram-probe PLAN AUTHORED_ROM NEW_EXPORT_PREFIX [--capture NEW]");const auto rom=reset_probe::rom(argv[2]);std::unique_ptr<pce::CodeCapture> capture;if(argc==6){if(std::string(argv[4])!="--capture")throw std::runtime_error("capture option");capture=std::make_unique<pce::CodeCapture>(argv[5],65536);}Adapter adapter{nullptr,{},rom,capture.get()};bram_probe::execute(adapter,argv[1],argv[3]);if(capture)capture->finish();return 0;}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
