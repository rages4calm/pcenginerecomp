#include "pce/runtime.hpp"
#include "pce/cartridge.hpp"
#include "pce/code_capture.hpp"
#include "reset_probe_support.hpp"
#include <filesystem>
#include <memory>
#include <sstream>
#include <string>

#ifdef PCE_HUCARD_NATIVE_ONLY
static constexpr bool native_only=true;
#else
static constexpr bool native_only=false;
#endif
static std::vector<std::uint8_t> read_rom(const char* path) {
    std::ifstream file(path,std::ios::binary);if(!file)throw std::runtime_error("cannot open authored decoded HuCard");
    std::vector<std::uint8_t> rom((std::istreambuf_iterator<char>(file)),{});
    if(rom.empty() || rom.size()%8192 || rom.size()>0x280000)throw std::runtime_error("authored HuCard size");
    return rom;
}
static std::vector<std::uint64_t> cpu_state(const pce::Bus& bus,const pce::Cpu& c) {
    std::vector<std::uint64_t> out{c.pc,c.a,c.x,c.y,c.sp,c.p,c.clock_divisor,c.ticks};
    for(auto mpr:c.mpr)out.push_back(mpr);
    out.insert(out.end(),{c.mpr_latch,bus.io_latch,unsigned(bus.irq.timer_enabled),bus.irq.timer_reload,bus.irq.timer_counter,bus.irq.mask,bus.irq_requests()});return out;
}
static std::vector<std::uint64_t> devices(const pce::Bus& bus) {
    const auto& v=bus.vdc;const auto& p=bus.psg;
    std::vector<std::uint64_t> out{v.selected,v.status,v.read_buffer};for(auto reg:v.reg)out.push_back(reg);
    out.insert(out.end(),{bus.vce.control,bus.vce.address,reset_probe::hash(bus.vce.palette.data(),512),bus.joypad.latched,
        p.selected,p.main_volume,p.lfo_frequency,p.lfo_control});
    for(const auto& c:p.channels)out.insert(out.end(),{c.frequency,c.control,c.balance,c.wave_index,c.noise,c.dda,c.noise_lfsr,reset_probe::hash(c.waveform.data(),32)});
    out.insert(out.end(),{reset_probe::hash(bus.bytes->data()+0x1F0000,8192),reset_probe::hash(v.vram->data(),32768),reset_probe::hash(v.satb.data(),256)});
    return out;
}
struct Counts {unsigned cases=0,guards=0,mutations=0;std::uint64_t native=0,interpreted=0;std::vector<std::array<std::uint64_t,2>> per_case;};
static void guard_checks(pce::Bus& bus,const pce::Cpu& original,Counts& counts) {
    auto check=[&](pce::Cpu cpu,std::uint64_t deadline,pce::Exit expected){
        const auto before=cpu_state(bus,cpu),hardware=devices(bus);
        const auto cycles=cpu.cycles,native=cpu.native_steps,interpreted=cpu.interpreter_steps;
        if(pce::generated_step(bus,cpu,deadline)!=expected || cpu_state(bus,cpu)!=before || devices(bus)!=hardware ||
           cpu.cycles!=cycles || cpu.native_steps!=native || cpu.interpreter_steps!=interpreted)
            throw std::runtime_error("native HuCard guard mutated/executed state");
        ++counts.guards;
    };
    check(original,original.ticks,pce::Exit::budget);
    auto wrong=original;wrong.mpr[7]=0x80;check(wrong,100000000,pce::Exit::miss);
    const auto pa=pce::Bus::physical(original,original.pc);const auto byte=bus.peek(pa);
    if(!byte)throw std::runtime_error("guard source absent");
    const std::uint8_t unsupported=0xFC;bus.load(pa,&unsupported,1);
    check(original,100000000,pce::Exit::miss);bus.load(pa,&*byte,1);
    if(bus.peek(pa)!=byte)throw std::runtime_error("authored source restoration failed");
    ++counts.mutations;
}
int main(int argc,char** argv) {
    try {
        if(argc<4 || (argc-4)%2)throw std::runtime_error("usage: pce-hucard-probe PLAN DECODED_ROM sf2|populous [--capture NEWJSON] [--execution-report NEWJSON] [--guard-checks on]");
        const char* capture_path=nullptr;const char* report_path=nullptr;bool guards=false;
        for(int i=4;i<argc;i+=2) {
            const std::string flag=argv[i];
            if(flag=="--capture" && !capture_path)capture_path=argv[i+1];
            else if(flag=="--execution-report" && !report_path)report_path=argv[i+1];
            else if(flag=="--guard-checks" && !guards && std::string(argv[i+1])=="on")guards=true;
            else throw std::runtime_error("invalid HuCard probe option");
        }
        if(guards && !native_only)throw std::runtime_error("guards require native-only probe");
        if(report_path && (std::filesystem::exists(report_path) || std::filesystem::is_symlink(report_path)))throw std::runtime_error("execution report exists");
        if(report_path && capture_path && std::filesystem::absolute(report_path).lexically_normal()==std::filesystem::absolute(capture_path).lexically_normal())throw std::runtime_error("capture/report alias");
        std::unique_ptr<pce::CodeCapture> capture;if(capture_path)capture=std::make_unique<pce::CodeCapture>(capture_path,65536);
        const std::string selected=argv[3];
        if(selected!="sf2" && selected!="populous")throw std::runtime_error("explicit mapper profile required");
        const auto profile=selected=="sf2"?pce::HuCardProfile::sf2:pce::HuCardProfile::populous;
        const auto image=read_rom(argv[2]);std::ifstream plan(argv[1]);if(!plan)throw std::runtime_error("cannot open plan");
        std::unique_ptr<pce::Bus> bus;pce::Cpu cpu;Counts counts;bool first=true;std::string op;std::cout<<'[';
        while(plan>>op) {
            if(op=="r") {
                unsigned region,registers,mpr,ram;
                if(!(plan>>region>>registers>>mpr>>ram) || region>1 || registers>255 || mpr>255 || ram>255)throw std::runtime_error("invalid authored reset");
                bus=std::make_unique<pce::Bus>();bus->configure_hucard(profile,image,static_cast<std::uint8_t>(ram));
                bus->enable_video();bus->enable_video_timing();bus->enable_interrupts();bus->enable_psg();bus->enable_joypad(region==0,false);
                bus->power_on_cpu(cpu,static_cast<std::uint8_t>(registers),static_cast<std::uint8_t>(mpr));
                ++counts.cases;counts.per_case.push_back({0,0});if(guards)guard_checks(*bus,cpu,counts);
            } else {
                if(!bus)throw std::runtime_error("operation before reset");
                if(op=="s")reset_probe::record(first,"cpu",cpu_state(*bus,cpu));
                else if(op=="d")reset_probe::record(first,"devices",devices(*bus));
                else if(op=="i") {
                    unsigned count;if(!(plan>>count) || count>4096)throw std::runtime_error("instruction count");
                    for(unsigned i=0;i<count;++i) {
                        pce::CodeCapture::Pending pending;if(capture)pending=capture->before(*bus,cpu);
                        const auto n=cpu.native_steps,j=cpu.interpreter_steps;
#ifdef PCE_HUCARD_NATIVE_ONLY
                        if(pce::generated_step(*bus,cpu,100000000)!=pce::Exit::executed)throw std::runtime_error("native-only HuCard step missed; no interpreter fallback");
#else
                        if(pce::interpret_step(*bus,cpu,100000000)!=pce::Exit::executed)throw std::runtime_error("authored HuCard step refused");
#endif
                        const auto native=cpu.native_steps-n,interpreted=cpu.interpreter_steps-j;
                        if(native+interpreted!=1 || native!=(native_only?1U:0U))throw std::runtime_error("retirement tier differs");
                        counts.native+=native;counts.interpreted+=interpreted;counts.per_case.back()[0]+=native;counts.per_case.back()[1]+=interpreted;
                        if(capture)capture->after(pending,cpu);reset_probe::record(first,"cpu",cpu_state(*bus,cpu));
                    }
                } else if(op=="q" || op=="p" || op=="w") {
                    unsigned bank,offset,value=0;
                    if(!(plan>>bank>>offset) || bank>255 || offset>8191 || (op=="w" && (!(plan>>value) || value>255)))throw std::runtime_error("finite memory transaction");
                    const auto old=cpu.mpr[6];cpu.mpr[6]=static_cast<std::uint8_t>(bank);
                    if(op=="w")bus->write(cpu,static_cast<std::uint16_t>(0xC000+offset),static_cast<std::uint8_t>(value));
                    else if(op=="q")reset_probe::record(first,"memory",{bank,offset,bus->read(cpu,static_cast<std::uint16_t>(0xC000+offset))});
                    else {const auto byte=bus->peek((bank<<13)|offset);if(!byte)throw std::runtime_error("unreadable source peek");reset_probe::record(first,"peek",{bank,offset,*byte});}
                    cpu.mpr[6]=old;
                } else throw std::runtime_error("unknown authored operation");
            }
        }
        std::cout<<"]\n";if(capture)capture->finish();
        if(report_path) {
            std::ostringstream report;report<<"{\"runtime_abi\":"<<pce::abi_version<<",\"native_only\":"<<(native_only?"true":"false")
                <<",\"interpreter_fallback\":false,\"cases\":"<<counts.cases<<",\"native_steps\":"<<counts.native
                <<",\"interpreter_steps\":"<<counts.interpreted<<",\"guard_checks\":"<<counts.guards<<",\"restored_source_mutations\":"<<counts.mutations<<",\"per_case\":[";
            for(unsigned i=0;i<counts.per_case.size();++i){if(i)report<<',';report<<'['<<counts.per_case[i][0]<<','<<counts.per_case[i][1]<<']';}report<<"]}\n";
#ifdef _WIN32
            auto* file=_wfopen(std::filesystem::path(report_path).c_str(),L"wx");
#else
            auto* file=std::fopen(report_path,"wx");
#endif
            if(!file)throw std::runtime_error("cannot exclusively create execution report");
            const auto text=report.str();const bool wrote=std::fwrite(text.data(),1,text.size(),file)==text.size();const bool closed=std::fclose(file)==0;
            if(!wrote || !closed)throw std::runtime_error("execution report write failed");
        }
        return 0;
    }catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
}
