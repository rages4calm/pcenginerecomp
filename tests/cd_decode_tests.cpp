// Authored exhaustive decoded-hole tests. No retail image or firmware bytes.
#include "pce/runtime.hpp"
#include "pce/code_capture.hpp"
#include "cd_decode_fixture.hpp"
#include "reset_probe_support.hpp"
#include <memory>
#include <tuple>
namespace {
std::uint64_t decode_checks=0,decode_native=0,decode_interpreted=0,decode_guards=0;
void require_decode(bool ok,const char* why){++decode_checks;if(!ok)throw std::runtime_error(why);}
auto decode_control(const pce::Bus& b){const auto& c=b.cd;return std::tuple{b.io_latch,c.enabled,c.bram_unlocked,c.ack,c.interrupt_enable,c.interrupt_active,c.reset,c.audio_enabled,c.audio.sample_latch,c.audio.sample_right,c.audio.fader,c.scsi.enabled,c.scsi.phase,c.scsi.signals,c.scsi.latch,c.scsi.data,c.scsi.event,c.scsi.deadline,c.scsi.auto_ack_deadline,c.scsi.command,c.scsi.last_command,c.scsi.response,c.scsi.response_size,c.scsi.response_index,c.scsi.command_size,c.scsi.last_command_size,c.pending_origin.valid,c.irq2()};}
auto decode_cpu(const pce::Cpu& c){return std::tuple{c.a,c.x,c.y,c.sp,c.p,c.pc,c.mpr,c.mpr_latch,c.ticks,c.cycles,c.native_steps,c.interpreter_steps,c.guard_misses,c.vdc_wait_ticks};}
void decode_pointer(pce::Bus& b,unsigned offset,unsigned alias){const auto address=(alias?0xA000:0xC000)|offset;(*b.bytes)[0x1F0010]=address&255;(*b.bytes)[0x1F0011]=address>>8;}
void decode_step(pce::Bus& b,pce::Cpu& c,bool native){const auto result=native?pce::generated_step(b,c,UINT64_MAX):pce::interpret_step(b,c,UINT64_MAX);require_decode(result==pce::Exit::executed,"Decode operation did not execute directly");}
std::unique_ptr<pce::Bus> decode_setup(unsigned profile,bool complete=false){
    auto b=std::make_unique<pce::Bus>();const auto rom=cd_decode_rom();
    if(profile==2)b->configure_hucard(rom);else b->configure_system_card(profile?pce::SystemCardProfile::super:pce::SystemCardProfile::standard,rom);
    if(complete){b->enable_video();b->enable_interrupts();if(profile!=2)b->enable_adpcm();b->enable_psg();b->enable_joypad(false,profile!=2);}
    else if(profile!=2)b->enable_cd_control();
    // Explicit authored memory seed, not a claim about formatting on reset.
    std::fill_n(b->bytes->begin()+0x1F0000,8192,0);std::fill_n(b->bytes->begin()+0x1EE000,2048,0);return b;
}
void decode_sweep(unsigned profile,unsigned divisor,unsigned alias,bool native){
    auto owned=decode_setup(profile);auto& b=*owned;pce::Cpu c;c.mpr=cd_decode_mpr;c.clock_divisor=divisor;c.p=4;b.io_latch=0x5A;
    b.cd.ack=true;b.cd.interrupt_enable=0x65;b.cd.interrupt_active=0x20;b.cd.reset=9;b.cd.audio.sample_latch=0x1234;b.cd.audio.sample_right=true;b.cd.audio.fader=0xA7;
    const auto control=decode_control(b);const auto generation=b.generation;const auto original_rom=reset_probe::hash(b.bytes->data(),0x100000),bram=reset_probe::hash(b.bytes->data()+0x1EE000,2048);
    for(unsigned offset=0x1810;offset<0x2000;++offset){
        if(profile==2 && offset<0x1C00)continue;decode_pointer(b,offset,alias);
        const auto expected_reads=b.cd.reads,expected_writes=b.cd.writes;
        for(unsigned value=0;value<256;++value){
            c.pc=cd_decode_write_pc;c.a=static_cast<std::uint8_t>(value);const auto ticks=c.ticks,cycles=c.cycles;decode_step(b,c,native);
            require_decode(c.pc==cd_decode_write_pc+2 && c.a==value && c.p==4 && c.ticks==ticks+7*divisor && c.cycles==cycles+7,"Ignored write CPU/cycle literal differs");
            require_decode(decode_control(b)==control,"Ignored write modified control or general I/O latch");
        }
        require_decode(b.cd.writes==expected_writes+(offset<0x1C00?256:0) && b.cd.reads==expected_reads,"Ignored-write diagnostic count differs");
        c.pc=cd_decode_read_pc;c.p=4;const auto ticks=c.ticks,cycles=c.cycles;decode_step(b,c,native);
        constexpr unsigned signature[]{0,0xAA,0x55,3};const unsigned value=profile==1 && offset>=0x18C0 && offset<=0x18C3?signature[offset&3]:255;
        require_decode(c.a==value && c.p==((value&128)|4|(value==0?2:0)) && c.pc==cd_decode_read_pc+2 && c.ticks==ticks+7*divisor && c.cycles==cycles+7,"Decoded pull-up/signature read literal differs");
        require_decode(decode_control(b)==control && b.generation==generation,"Read/write hole changed latch/device/generation");
        require_decode(b.cd.reads==expected_reads+(offset<0x1C00?1:0),"Hole read diagnostic count differs");
        c.p=4;
    }
    require_decode(reset_probe::hash(b.bytes->data(),0x100000)==original_rom && reset_probe::hash(b.bytes->data()+0x1EE000,2048)==bram,"Ignored writes modified ROM or BRAM");
    decode_native+=c.native_steps;decode_interpreted+=c.interpreter_steps;
}
void decode_refusals(){
    auto owned=decode_setup(0);auto& b=*owned;pce::Cpu c;c.mpr=cd_decode_mpr;
    // Disabled known ports must not become accepted merely because CD exists.
    for(unsigned offset:{0U,0x400U,0x800U,0xC00U,0x1000U,0x1400U,0x1800U,0x1801U,0x1808U,0x1809U,0x180AU,0x180BU,0x180CU,0x180DU,0x180EU,0x180FU}){
        bool fault=false;try{b.write(c,0xC000|offset,0x5A);}catch(const pce::Fault&){fault=true;}
        require_decode(fault,"Disabled known hardware write was swallowed");
    }
    for(bool cd:{false,true}){auto sandbox=std::make_unique<pce::Bus>();if(cd)sandbox->enable_cd_control();else sandbox->kind[255]=pce::BankKind::io;
        for(unsigned offset:{0x1C00U,0x1FFFU})for(bool write:{false,true}){bool fault=false;try{if(write)sandbox->write(c,0xC000|offset,1);else(void)sandbox->read(c,0xC000|offset);}catch(const pce::Fault&){fault=true;}require_decode(fault,"Unconfigured sandbox acquired an unused-window hardware profile");}}
    b.enable_interrupts();b.irq.timer_enabled=true;b.irq.timer_deadline=6;b.irq.timer_reload=0;b.irq.timer_counter=0;
    c.pc=cd_decode_write_pc;decode_pointer(b,0x1811,0);const auto cpu=decode_cpu(c);const auto control=decode_control(b);const auto generation=b.generation;const auto timer=b.irq;
    auto guarded=[&](pce::Cpu trial,std::uint64_t deadline,pce::Exit expected){const auto before=decode_cpu(trial);require_decode(pce::generated_step(b,trial,deadline)==expected,"Decode pure guard exit differs");require_decode(decode_cpu(trial)==before && decode_cpu(c)==cpu && decode_control(b)==control && b.generation==generation && b.irq.master_ticks==timer.master_ticks && b.irq.timer_deadline==timer.timer_deadline && b.irq.timer_pending==timer.timer_pending,"Decode guard advanced guest/device state");++decode_guards;};
    guarded(c,c.ticks,pce::Exit::budget);auto wrong=c;wrong.mpr[3]=1;guarded(wrong,UINT64_MAX,pce::Exit::miss);
    for(unsigned byte=0;byte<2;++byte){const auto address=pce::Bus::physical(c,c.pc+byte);const auto old=(*b.bytes)[address];(*b.bytes)[address]^=255;guarded(c,UINT64_MAX,pce::Exit::miss);(*b.bytes)[address]=old;}
}
}
int main(){try{for(bool native:{false,true})for(unsigned profile:{0U,1U,2U})for(unsigned divisor:{3U,12U})for(unsigned alias:{0U,1U})decode_sweep(profile,divisor,alias,native);decode_refusals();std::cout<<decode_checks<<" decode checks; "<<decode_native<<" native, "<<decode_interpreted<<" interpreted; "<<decode_guards<<" pure guards\n";return 0;}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
