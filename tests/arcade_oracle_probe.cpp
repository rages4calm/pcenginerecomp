// Authored device/CPU fixture; external reference runs in another executable.
#include "pce/runtime.hpp"
#include "pce/arcade_card.hpp"
#include "pce/code_capture.hpp"
#include "reset_probe_support.hpp"
#include <filesystem>
#include <memory>
#include <sstream>
#include <string>

#ifdef PCE_ARCADE_NATIVE_ONLY
constexpr bool native_only=true;
#else
constexpr bool native_only=false;
#endif
static std::vector<std::uint64_t> cpu_state(const pce::Cpu& c) {
    std::vector<std::uint64_t> out{c.pc,c.a,c.x,c.y,c.sp,c.p,c.clock_divisor,c.ticks};
    for(auto m:c.mpr)out.push_back(m);return out;
}
static std::vector<std::uint64_t> arcade_state(const pce::Bus& b) {
    std::vector<std::uint64_t> out;const auto& a=*b.arcade_card;
    for(const auto& p:a.ports)out.insert(out.end(),{p.base,p.offset,p.increment,p.control});
    out.insert(out.end(),{a.shift_register,a.shift_amount,a.rotate_amount});return out;
}
struct Counts {unsigned cases=0,guards=0,mutations=0;std::uint64_t native=0,interpreted=0;std::vector<std::array<std::uint64_t,2>> per_case;};
static void guard_checks(pce::Bus& b,const pce::Cpu& original,Counts& counts) {
    auto check=[&](pce::Cpu c,std::uint64_t deadline,pce::Exit expected) {
        const auto before=cpu_state(c),ports=arcade_state(b);const auto cycles=c.cycles;
        const auto memory=reset_probe::hash(b.arcade_card->ram->data(),0x200000);
        if(pce::generated_step(b,c,deadline)!=expected || cpu_state(c)!=before ||
           arcade_state(b)!=ports || c.cycles!=cycles || c.native_steps || c.interpreter_steps ||
           reset_probe::hash(b.arcade_card->ram->data(),0x200000)!=memory)
            throw std::runtime_error("native guard mutated arcade/CPU state");
        ++counts.guards;
    };
    check(original,0,pce::Exit::budget);
    auto wrong=original;wrong.mpr[7]=0x80;check(wrong,100000000,pce::Exit::miss);
    const auto pa=pce::Bus::physical(original,original.pc);const auto byte=b.peek(pa);
    if(!byte)throw std::runtime_error("reset source missing");
    const std::uint8_t unsupported=0xFC;b.load(pa,&unsupported,1);
    check(original,100000000,pce::Exit::miss);b.load(pa,&*byte,1);++counts.mutations;
    for(unsigned port=0;port<4;++port) {
        if(b.peek((0x40+port)<<13))throw std::runtime_error("side-effecting port exposed as source");
        wrong=original;wrong.mpr[7]=static_cast<std::uint8_t>(0x40+port);
        check(wrong,100000000,pce::Exit::miss);
    }
}
int main(int argc,char** argv) {
    try {
        if(argc<3 || (argc-3)%2)throw std::runtime_error("usage: pce-arcade PLAN AUTHORED_FIRMWARE [--capture NEWJSON] [--execution-report NEWJSON] [--guard-checks on]");
        const auto image=reset_probe::rom(argv[2]);std::ifstream plan(argv[1]);
        if(!plan)throw std::runtime_error("plan missing");
        const char* capture_path=nullptr;const char* report_path=nullptr;bool guards=false;
        for(int i=3;i<argc;i+=2){const std::string name=argv[i];
            if(name=="--capture"&&!capture_path)capture_path=argv[i+1];
            else if(name=="--execution-report"&&!report_path)report_path=argv[i+1];
            else if(name=="--guard-checks"&&!guards&&std::string(argv[i+1])=="on")guards=true;
            else throw std::runtime_error("invalid probe option");}
        if(guards&&!native_only)throw std::runtime_error("guards require native probe");
        if(report_path&&std::filesystem::exists(report_path))throw std::runtime_error("report exists");
        std::unique_ptr<pce::CodeCapture> capture;if(capture_path)capture=std::make_unique<pce::CodeCapture>(capture_path,65536);
        std::unique_ptr<pce::Bus> bus;pce::Cpu cpu;Counts counts;std::string op;bool first=true;std::cout<<'[';
        while(plan>>op) {
            if(op=="r") {
                unsigned fill;if(!(plan>>fill)||fill>255)throw std::runtime_error("RAM fill");
                bus=std::make_unique<pce::Bus>();bus->configure_system_card(pce::SystemCardProfile::super,image,fill);
                bus->configure_arcade_card_duo(fill);bus->enable_cd_transport();bus->enable_video();
                bus->enable_interrupts();bus->enable_psg();bus->enable_adpcm();bus->enable_joypad(true,true);
                bus->power_on_cpu(cpu);++counts.cases;counts.per_case.push_back({0,0});
                if(guards)guard_checks(*bus,cpu,counts);
            } else {
                if(!bus)throw std::runtime_error("operation before reset");
                if(op=="s")reset_probe::record(first,"cpu",cpu_state(cpu));
                else if(op=="a")reset_probe::record(first,"arcade",arcade_state(*bus));
                else if(op=="f") {
                    if(native_only)throw std::runtime_error("port-sourced instructions are interpreter-only");
                    cpu.mpr[7]=0x40;cpu.pc=0xE000;
                }
                else if(op=="i") {
                    unsigned count;if(!(plan>>count)||count>4096)throw std::runtime_error("instruction bound");
                    for(unsigned i=0;i<count;++i) {
                        pce::CodeCapture::Pending pending;if(capture)pending=capture->before(*bus,cpu);
#ifdef PCE_ARCADE_NATIVE_ONLY
                        if(pce::generated_step(*bus,cpu,100000000)!=pce::Exit::executed)throw std::runtime_error("native step missed; fallback forbidden");
#else
                        if(pce::interpret_step(*bus,cpu,100000000)!=pce::Exit::executed)throw std::runtime_error("interpreted step refused");
#endif
                        counts.native+=native_only;counts.interpreted+=!native_only;
                        counts.per_case.back()[native_only?0:1]++;
                        if(capture)capture->after(pending,cpu);reset_probe::record(first,"cpu",cpu_state(cpu));
                    }
                } else if(op=="k") {
                    unsigned address;if(!(plan>>address)||address>=0x200000)throw std::runtime_error("RAM offset");
                    reset_probe::record(first,"ram",{address,(*bus->arcade_card->ram)[address]});
                } else if(op=="q"||op=="w"||op=="p") {
                    unsigned bank,offset,value=0;if(!(plan>>bank>>offset)||bank>255||offset>8191||
                        (op=="w"&&(!(plan>>value)||value>255)))throw std::runtime_error("memory bound");
                    const auto old=cpu.mpr[6];cpu.mpr[6]=static_cast<std::uint8_t>(bank);
                    if(op=="w")bus->write(cpu,0xC000+offset,value);
                    else if(op=="q")reset_probe::record(first,"memory",{bank,offset,bus->read(cpu,0xC000+offset)});
                    else {const auto byte=bus->peek((bank<<13)|offset);if(!byte)throw std::runtime_error("unreadable source");
                        reset_probe::record(first,"peek",{bank,offset,*byte});}
                    cpu.mpr[6]=old;
                } else throw std::runtime_error("unknown operation");
            }
        }
        std::cout<<"]\n";if(capture)capture->finish();
        if(report_path) {
            std::ostringstream out;out<<"{\"runtime_abi\":"<<pce::abi_version<<",\"native_only\":"<<(native_only?"true":"false")
                <<",\"interpreter_fallback\":false,\"cases\":"<<counts.cases<<",\"native_steps\":"<<counts.native
                <<",\"interpreter_steps\":"<<counts.interpreted<<",\"guard_checks\":"<<counts.guards
                <<",\"restored_source_mutations\":"<<counts.mutations<<",\"per_case\":[";
            for(unsigned i=0;i<counts.per_case.size();++i){if(i)out<<',';out<<'['<<counts.per_case[i][0]<<','<<counts.per_case[i][1]<<']';}out<<"]}\n";
#ifdef _WIN32
            auto* file=_wfopen(std::filesystem::path(report_path).c_str(),L"wx");
#else
            auto* file=std::fopen(report_path,"wx");
#endif
            if(!file)throw std::runtime_error("cannot exclusively write report");const auto text=out.str();
            const auto wrote=std::fwrite(text.data(),1,text.size(),file)==text.size();const auto closed=std::fclose(file)==0;
            if(!wrote||!closed)throw std::runtime_error("report write failed");
        }
        return 0;
    }catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
}
