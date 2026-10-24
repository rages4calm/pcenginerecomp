#include "pce/runtime.hpp"
#include "pce/code_capture.hpp"
#include "reset_probe_support.hpp"
#include <memory>
#include <string>

#ifdef PCE_RESET_NATIVE_ONLY
static constexpr bool native_only=true;
#else
static constexpr bool native_only=false;
#endif

struct ExecutionCounts {
    unsigned cases=0,guard_checks=0,restored_source_mutations=0;
    std::uint64_t native=0,interpreted=0;
    std::vector<std::array<std::uint64_t,2>> per_case;
};

static std::vector<std::uint64_t> cpu_state(pce::Bus& bus,const pce::Cpu& c) {
    std::vector<std::uint64_t> out{c.pc,c.a,c.x,c.y,c.sp,c.p,c.clock_divisor,c.ticks};
    for(auto mpr:c.mpr)out.push_back(mpr);
    out.insert(out.end(),{c.mpr_latch,bus.io_latch,unsigned(bus.irq.timer_enabled),bus.irq.timer_reload,bus.irq.timer_counter,bus.irq.mask,bus.irq_requests()});return out;
}
static std::vector<std::uint64_t> devices(const pce::Bus& bus) {
    const auto& v=bus.vdc;const auto& cd=bus.cd;const auto& a=bus.adpcm;const auto& p=bus.psg;
    std::vector<std::uint64_t> out{v.selected,v.status,v.read_buffer};for(auto r:v.reg)out.push_back(r);
    out.insert(out.end(),{bus.vce.control,bus.vce.address,reset_probe::hash(bus.vce.palette.data(),512),bus.joypad.latched,
        cd.reset,unsigned(cd.bram_unlocked),cd.interrupt_active,cd.interrupt_enable,cd.audio.fader,cd.scsi.data,cd.scsi.signals,cd.scsi.phase,
        cd.audio.state,cd.audio.start_lba,cd.audio.stop_lba,cd.audio.current_lba,cd.audio.source_cursor.frame,
        a.control,a.dma,a.sample_rate,a.address,a.read_address,a.write_address,a.length,unsigned(a.playing),unsigned(a.end_irq),unsigned(a.half_irq),
        p.selected,p.main_volume,p.lfo_frequency,p.lfo_control});
    for(const auto& c:p.channels)out.insert(out.end(),{c.frequency,c.control,c.balance,c.wave_index,c.noise,c.dda,c.noise_lfsr,reset_probe::hash(c.waveform.data(),32)});
    out.insert(out.end(),{reset_probe::hash(bus.bytes->data()+0x1F0000,8192),reset_probe::hash(bus.bytes->data()+0x100000,65536),
        reset_probe::hash(bus.bytes->data()+0xD0000,bus.system_card==pce::SystemCardProfile::super?196608:0),reset_probe::hash(bus.bytes->data()+0x1EE000,2048),
        reset_probe::hash(v.vram->data(),32768),reset_probe::hash(v.satb.data(),256),reset_probe::hash(a.ram.data(),65536)});return out;
}
static void check_native_guards(pce::Bus& bus,const pce::Cpu& original,ExecutionCounts& counts) {
    const auto check=[&](pce::Cpu candidate,std::uint64_t deadline,pce::Exit expected) {
        const auto before=cpu_state(bus,candidate),hardware=devices(bus);
        const auto cycles=candidate.cycles,native=candidate.native_steps,interpreted=candidate.interpreter_steps;
        if(pce::generated_step(bus,candidate,deadline)!=expected || cpu_state(bus,candidate)!=before ||
           devices(bus)!=hardware || candidate.cycles!=cycles || candidate.native_steps!=native ||
           candidate.interpreter_steps!=interpreted)throw std::runtime_error("native reset guard mutated or executed guest state");
        ++counts.guard_checks;
    };
    check(original,original.ticks,pce::Exit::budget);
    auto wrong_mapping=original;wrong_mapping.mpr[7]^=0x40;
    check(wrong_mapping,100000000,pce::Exit::miss);
    const auto mutate=[&](pce::Cpu candidate,unsigned operand,std::uint8_t replacement) {
        const auto source=pce::Bus::physical(candidate,static_cast<std::uint16_t>(candidate.pc+operand));
        const auto byte=bus.peek(source);if(!byte)throw std::runtime_error("guard fixture source unreadable");
        // Mutate the same backing through another physical ROM window. Keep
        // mapped physical identity intact; restore exact bytes before capture.
        const auto alias=source+0x40000;
        bus.load(alias,&replacement,1);
        check(candidate,100000000,pce::Exit::miss);
        bus.load(alias,&*byte,1);
        if(bus.peek(source)!=byte || bus.peek(alias)!=byte)throw std::runtime_error("native guard source restoration failed");
        ++counts.restored_source_mutations;
    };
    mutate(original,0,0xFC); // Unsupported opcode was never captured here.
    auto operand=original;
    if(bus.peek(pce::Bus::physical(operand,operand.pc))==std::optional<std::uint8_t>{0x78})operand.pc+=2;
    const auto value=bus.peek(pce::Bus::physical(operand,static_cast<std::uint16_t>(operand.pc+1)));
    if(!value)throw std::runtime_error("missing authored immediate operand");
    mutate(operand,1,static_cast<std::uint8_t>(*value^1));
}
int main(int argc,char** argv) {
    try {
        if(argc<4 || (argc-4)%2)throw std::runtime_error("usage: pce-reset-probe PLAN AUTHORED_ROM AUTHORED_CUE [--capture NEW_JSON] [--execution-report NEW_JSON] [--guard-checks on]");
        const char* capture_path=nullptr;const char* report_path=nullptr;bool guards=false;
        for(int i=4;i<argc;i+=2) {
            const std::string flag=argv[i];
            if(flag=="--capture" && !capture_path)capture_path=argv[i+1];
            else if(flag=="--execution-report" && !report_path)report_path=argv[i+1];
            else if(flag=="--guard-checks" && !guards && std::string(argv[i+1])=="on")guards=true;
            else throw std::runtime_error("invalid reset-probe option");
        }
        if(guards && !native_only)throw std::runtime_error("guard checks require native-only probe");
        if(report_path && std::filesystem::exists(report_path))throw std::runtime_error("execution report exists");
        if(report_path && capture_path && std::filesystem::absolute(report_path).lexically_normal()==
           std::filesystem::absolute(capture_path).lexically_normal())throw std::runtime_error("execution report aliases capture");
        std::unique_ptr<pce::CodeCapture> capture;
        if(capture_path)capture=std::make_unique<pce::CodeCapture>(capture_path,65536);
        ExecutionCounts counts;
        std::ifstream plan(argv[1]);if(!plan)throw std::runtime_error("cannot open plan");
        const auto base=reset_probe::rom(argv[2]);std::unique_ptr<pce::Bus> bus;pce::Cpu cpu;bool first=true;std::string op;
        std::cout<<'[';
        while(plan>>op) {
            if(op=="r") {
                unsigned profile,region,vector,registers,mpr,ram;
                if(!(plan>>profile>>region>>vector>>registers>>mpr>>ram))throw std::runtime_error("truncated reset");
                reset_probe::valid(profile,region,vector,registers,mpr,ram);auto rom=base;rom[8190]=vector&255;rom[8191]=vector>>8;
                bus=std::make_unique<pce::Bus>();bus->configure_system_card(profile?pce::SystemCardProfile::super:pce::SystemCardProfile::standard,rom,ram);
                bus->enable_cd_control();bus->enable_cd_transport();bus->enable_video();bus->enable_video_timing();bus->enable_interrupts();
                bus->enable_psg();bus->enable_adpcm();bus->enable_joypad(region==0,true);
                std::array<std::uint8_t,2048> bram;bram.fill(0x5A);bus->load(0x1EE000,bram.data(),bram.size());
                bus->power_on_cpu(cpu,registers,mpr);
                ++counts.cases;counts.per_case.push_back({0,0});
                if(guards)check_native_guards(*bus,cpu,counts);
            } else {
                if(!bus)throw std::runtime_error("operation before reset");
                if(op=="s")reset_probe::record(first,"cpu",cpu_state(*bus,cpu));
                else if(op=="d")reset_probe::record(first,"devices",devices(*bus));
                else if(op=="i") {
                    unsigned count;if(!(plan>>count) || count>4096)throw std::runtime_error("invalid instruction count");
                    for(unsigned i=0;i<count;++i){
                        pce::CodeCapture::Pending pending;if(capture)pending=capture->before(*bus,cpu);
                        const auto n=cpu.native_steps,j=cpu.interpreter_steps;
#ifdef PCE_RESET_NATIVE_ONLY
                        if(pce::generated_step(*bus,cpu,100000000)!=pce::Exit::executed)throw std::runtime_error("native-only authored reset instruction missed; no interpreter fallback");
#else
                        if(pce::interpret_step(*bus,cpu,100000000)!=pce::Exit::executed)throw std::runtime_error("authored reset instruction did not execute");
#endif
                        const auto native=cpu.native_steps-n,interpreted=cpu.interpreter_steps-j;
                        if(native+interpreted!=1 || native!=(native_only?1U:0U))throw std::runtime_error("invalid reset probe retirement tier");
                        counts.native+=native;counts.interpreted+=interpreted;
                        counts.per_case.back()[0]+=native;counts.per_case.back()[1]+=interpreted;
                        if(capture)capture->after(pending,cpu);
                        reset_probe::record(first,"cpu",cpu_state(*bus,cpu));
                    }
                } else if(op=="q" || op=="p" || op=="w") {
                    unsigned bank,offset,value=0;if(!(plan>>bank>>offset) || bank>254 || offset>8191 || (op=="w" && (!(plan>>value) || value>255)))throw std::runtime_error("invalid finite memory transaction");
                    const auto old=cpu.mpr[6];cpu.mpr[6]=bank;
                    if(op=="w")bus->write(cpu,0xC000+offset,value);
                    else if(op=="q")reset_probe::record(first,"memory",{bank,offset,bus->read(cpu,0xC000+offset)});
                    else {const auto byte=bus->peek((bank<<13)|offset);if(!byte)throw std::runtime_error("unreadable source peek");reset_probe::record(first,"peek",{bank,offset,*byte});}
                    cpu.mpr[6]=old;
                } else if(op=="c" || op=="a") {
                    unsigned port,value=0;if(!(plan>>port) || port>1023 || (op=="c" && (!(plan>>value) || value>255)))throw std::runtime_error("invalid CD transaction");
                    const auto old=cpu.mpr[6];cpu.mpr[6]=255;
                    if(op=="c")bus->write(cpu,0xD800+port,value);else reset_probe::record(first,"port",{port,bus->read(cpu,0xD800+port)});
                    cpu.mpr[6]=old;
                } else throw std::runtime_error("unknown reset operation");
            }
        }
        std::cout<<"]\n";
        if(capture)capture->finish();
        if(report_path) {
            std::ostringstream report;
            report<<"{\"runtime_abi\":"<<pce::abi_version<<",\"native_only\":"<<(native_only?"true":"false")
                  <<",\"interpreter_fallback\":false,\"cases\":"<<counts.cases<<",\"native_steps\":"<<counts.native
                  <<",\"interpreter_steps\":"<<counts.interpreted<<",\"guard_checks\":"<<counts.guard_checks
                  <<",\"restored_source_mutations\":"<<counts.restored_source_mutations<<",\"per_case\":[";
            for(unsigned i=0;i<counts.per_case.size();++i){if(i)report<<',';report<<'['<<counts.per_case[i][0]<<','<<counts.per_case[i][1]<<']';}
            report<<"]}\n";
            const auto text=report.str();const auto path=std::filesystem::path(report_path);
#ifdef _WIN32
            auto* file=_wfopen(path.c_str(),L"wx");
#else
            auto* file=std::fopen(path.c_str(),"wx");
#endif
            if(!file)throw std::runtime_error("cannot exclusively create execution report");
            const bool written=std::fwrite(text.data(),1,text.size(),file)==text.size();
            const bool closed=std::fclose(file)==0;
            if(!written || !closed)throw std::runtime_error("cannot write execution report");
        }
        return 0;
    }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
