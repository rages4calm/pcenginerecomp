// Authored command supervisor; source bytes are synthetic. The original Gear
// build includes this driver only, never toolkit CPU/device implementations.
#include <filesystem>
#include <algorithm>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>
#ifndef PCE_CDDA_GAP_GEAR
#include "pce/runtime.hpp"
#include "pce/sector.hpp"
#include "pce/code_capture.hpp"
#include "cdda_gap_fixture.hpp"
#include "reset_probe_support.hpp"
struct GapAdapter {
    std::unique_ptr<pce::Bus> bus; pce::Cpu cpu;
    const std::vector<std::uint8_t>& rom;const char* cue;bool native;unsigned divisor;
    pce::CodeCapture capture;std::uint64_t calls=0,guards=0;
    GapAdapter(const std::vector<std::uint8_t>& r,const char* c,const std::string& tier,unsigned speed,const char* cap):rom(r),cue(c),native(tier=="native"),divisor(speed),capture(cap,16){}
    void reset(){bus=std::make_unique<pce::Bus>();bus->configure_system_card(pce::SystemCardProfile::super,rom);
        bus->enable_cd_transport();bus->enable_adpcm();bus->enable_video();bus->enable_interrupts();bus->enable_psg();
        bus->cd.set_sector_provider(pce::open_sector_provider(cue));for(auto [address,value]:gap_program)(*bus->bytes)[address]=value;
        cpu=pce::Cpu{};cpu.mpr=gap_mpr;cpu.clock_divisor=divisor;cpu.p=pce::I;}
    void execute(unsigned opcode,unsigned address,int value=-1){
        bool found=false;for(auto item:gap_sites)if(item.opcode==opcode&&item.address==address){cpu.pc=std::uint16_t(item.pc);found=true;break;}
        if(!found)throw std::runtime_error("Unknown authored port site");if(value>=0)cpu.a=std::uint8_t(value);
        const auto pending=capture.before(*bus,cpu);const auto status=native?pce::generated_step(*bus,cpu,UINT64_MAX):pce::interpret_step(*bus,cpu,UINT64_MAX);
        if(status!=pce::Exit::executed)throw std::runtime_error("Authored port opcode missed");capture.after(pending,cpu);++calls;
    }
    void write(unsigned address,unsigned value){execute(0x8D,address,value);}
    unsigned read(){execute(0xAD,0x1801);return cpu.a;}
    void advance(std::uint64_t ticks){while(ticks){const auto n=std::min<std::uint64_t>(ticks,4096);cpu.ticks+=n;bus->sync(cpu);ticks-=n;}}
    std::uint64_t now()const{return cpu.ticks;}
    unsigned signals()const{return bus->cd.scsi.signals;}
    unsigned phase()const{return bus->cd.scsi.phase;}
    std::vector<std::uint64_t> logical()const{const auto& a=bus->cd.audio;return {a.state,a.start_lba,a.current_lba,a.stop_lba,a.seek_start_lba,a.stop_mode,bus->cd.scsi.current_lba};}
    std::uint64_t seek()const{return bus->cd.audio.seek_deadline;}
    std::uint64_t event_deadline()const{return bus->cd.scsi.deadline;}
    unsigned event()const{return bus->cd.scsi.event;}
    void finish(){capture.finish();}
};
#else
struct GapAdapter:GearGapAdapterBase {
    unsigned divisor;std::uint64_t calls=0,guards=0;
    GapAdapter(const std::vector<std::uint8_t>& r,const char* c,const std::string&,unsigned speed,const char*):GearGapAdapterBase{nullptr,r,c},divisor(speed){}
    void reset(){GearGapAdapterBase::reset(1);core->GetAudio()->Reset(true);}
    void write(unsigned address,unsigned value){core->GetCDROM()->WriteRegister(std::uint16_t(address),std::uint8_t(value));++calls;advance(5*divisor);}
    unsigned read(){const auto value=core->GetCDROM()->ReadRegister(0x1801);++calls;advance(5*divisor);return value;}
    void advance(std::uint64_t ticks){while(ticks){const auto n=unsigned(std::min<std::uint64_t>(ticks,4096));GearGapAdapterBase::advance(n);ticks-=n;}}
    std::uint64_t now()const{return core->GetMasterClockCycles();}
    unsigned phase()const{return unsigned(*core->GetScsiController()->GetState()->PHASE);}
    std::vector<std::uint64_t> logical()const{auto* s=core->GetCDROMAudio()->GetState();return {unsigned(*s->CURRENT_STATE),*s->START_LBA,*s->CURRENT_LBA,*s->STOP_LBA,
        core->GetCDROMAudio()->*member(GapSeekStart{}),unsigned(*s->STOP_EVENT),core->GetCDROMMedia()->GetCurrentSector()};}
    std::uint64_t seek()const{const auto remaining=*core->GetCDROMAudio()->GetState()->SEEK_CYCLES;return remaining>0?now()+unsigned(remaining):0;}
    std::uint64_t event_deadline()const{const auto n=*core->GetScsiController()->GetState()->NEXT_EVENT_CYCLES;return n>0?now()+unsigned(n):0;}
    unsigned event()const{return unsigned(*core->GetScsiController()->GetState()->NEXT_EVENT);}
    void finish(){}
};
#endif

namespace {
void require(bool ok,const char* why){if(!ok)throw std::runtime_error(why);}
void wait_command(GapAdapter& a){for(unsigned i=0;i<20000;++i){if(a.phase()==3&&(a.signals()&64))return;a.advance(1000);}throw std::runtime_error("Command request timed out");}
void start(GapAdapter& a,unsigned op,unsigned mode,unsigned lba){
    a.write(0x1800,0);wait_command(a);
    const unsigned bytes[]={op,mode,0,lba>>16,(lba>>8)&255,lba&255,0,0,0,0};
    const unsigned read_bytes[]={8,0,0,0,1,0};
    const auto* command_bytes=op==8?read_bytes:bytes;const unsigned count=op==8?6:10;
    for(unsigned index=0;index<count;++index){const auto byte=command_bytes[index];wait_command(a);a.write(0x1801,byte);a.write(0x1802,128);a.advance(1);a.write(0x1802,0);a.advance(1);}
}
std::pair<unsigned,unsigned> drain(GapAdapter& a){unsigned status=999,message=999;
    for(unsigned i=0;i<20000;++i){
        if(!(a.signals()&128)){require(status<=255&&message<=255,"Missing command completion");return {status,message};}
        if(!(a.signals()&64)){a.advance(1000);continue;}
        require(a.signals()&8,"Wrong reply direction");const bool data=!(a.signals()&16);const auto value=a.read();
        if(data)require(value==0,"Authored READ payload differs");
        else if(a.signals()&32)message=value;else status=value;
        a.write(0x1802,128);a.advance(1);a.write(0x1802,0);a.advance(1);
    }throw std::runtime_error("Reply timed out");
}
void command(GapAdapter& a,unsigned op,unsigned mode,unsigned lba){start(a,op,mode,lba);const auto reply=drain(a);require(reply.first==0&&reply.second==0,"Setup command did not succeed");}
void array(std::ostream& o,const std::vector<std::uint64_t>& values){o<<'[';for(unsigned i=0;i<values.size();++i)o<<(i?",":"")<<values[i];o<<']';}
void observe(std::ostream& o,const GapAdapter& a){o<<"{\"ticks\":"<<a.now()<<",\"phase\":"<<a.phase()<<",\"signals\":"<<a.signals()<<",\"logical\":";array(o,a.logical());o<<",\"seek_deadline\":"<<a.seek()<<",\"event\":"<<a.event()<<",\"event_deadline\":"<<a.event_deadline()<<'}';}
}
int main(int argc,char** argv){try{
    require(argc==8,"cdda-gap CASES ROM CUE TIER DIVISOR NEW_CAPTURE NEW_REPORT");
    const std::string tier=argv[4];
#ifdef PCE_CDDA_GAP_GEAR
    require(tier=="gear","Original Gear tier required");
#else
    require(tier=="native"||tier=="interpreter","Explicit execution tier required");
#endif
    const unsigned speed=std::stoul(argv[5]);require(speed==3||speed==12,"Explicit CPU divisor required");
    require(!std::filesystem::exists(argv[7]),"New report required");
    const auto rom=reset_probe::rom(argv[2]);GapAdapter a(rom,argv[3],tier,speed,argv[6]);
    std::ifstream plan(argv[1]);require(bool(plan),"Missing authored plan");std::string id,state,kind;unsigned mode,target,cases=0;bool comma=false;
    std::cout<<'[';
    while(plan>>id>>state>>mode>>target>>kind){a.reset();command(a,8,0,0);
        if(state=="playing")command(a,0xD8,1,10);
        else if(state=="paused")command(a,0xD8,0,10);
        else if(state=="stopped"){command(a,0xD8,0,10);command(a,0xD9,0,0);}
        else if(state=="seeking"){start(a,0xD8,1,10);require(a.phase()==8&&a.seek()>a.now()+100000,"Pending seek setup missing");}
        else require(state=="idle","Unknown setup state");
        if(comma)std::cout<<',';comma=true;
        std::cout<<"{\"case\":\""<<id<<"\",\"kind\":\""<<kind<<"\",\"before\":";observe(std::cout,a);
        const auto before=a.logical();const auto seek=a.seek();start(a,0xD8,mode,target);
        std::cout<<",\"after\":";observe(std::cout,a);
        if(kind=="gap")require(before==a.logical()&&seek==a.seek(),"Ignored D8 mutated audio/head or seek deadline");
        unsigned status=999,message=999;
        if(a.phase()==7){const auto reply=drain(a);status=reply.first;message=reply.second;}
        else if(kind=="program"||seek){const auto reply=drain(a);status=reply.first;message=reply.second;}
        else a.advance(400000);
        std::cout<<",\"settled\":";observe(std::cout,a);std::cout<<",\"status\":"<<status<<",\"message\":"<<message<<'}';++cases;
    }
    require(plan.eof(),"Malformed authored case row");std::cout<<"]\n";a.finish();
    std::ofstream report(argv[7]);require(bool(report),"Report creation failed");report<<"{\"schema\":1,\"tier\":\""<<tier<<"\",\"divisor\":"<<speed<<",\"cases\":"<<cases<<",\"port_calls\":"<<a.calls<<"}\n";
    return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
