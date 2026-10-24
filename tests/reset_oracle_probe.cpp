#include "pce/runtime.hpp"
#include "reset_probe_support.hpp"
#include <memory>
#include <string>

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
int main(int argc,char** argv) {
    try {
        if(argc!=4)throw std::runtime_error("usage: pce-reset-probe PLAN AUTHORED_ROM AUTHORED_CUE");
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
            } else {
                if(!bus)throw std::runtime_error("operation before reset");
                if(op=="s")reset_probe::record(first,"cpu",cpu_state(*bus,cpu));
                else if(op=="d")reset_probe::record(first,"devices",devices(*bus));
                else if(op=="i") {
                    unsigned count;if(!(plan>>count) || count>4096)throw std::runtime_error("invalid instruction count");
                    for(unsigned i=0;i<count;++i){if(pce::interpret_step(*bus,cpu,100000000)!=pce::Exit::executed)throw std::runtime_error("authored reset instruction did not execute");reset_probe::record(first,"cpu",cpu_state(*bus,cpu));}
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
        std::cout<<"]\n";return 0;
    }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
