// Authored observer wrapper around a separately compiled original GPL core.
#define main previous_mapper_probe_main
#include "geargrafx_mapper_probe.cpp"
#undef main
#include "bus_reference_support.hpp"
struct BusTransferTag{using type=u32 HuC6280::*;friend type bus_transfer(BusTransferTag);};
template<class Tag,typename Tag::type Member>struct BusAccess{friend typename Tag::type bus_transfer(Tag){return Member;}};
template struct BusAccess<BusTransferTag,&HuC6280::m_transfer_state>;
static GeargrafxCore* bus_core=nullptr;
static reference_trace::State bus_state(){
    auto* s=bus_core->GetHuC6280()->GetState();auto* memory=bus_core->GetMemory();
    reference_trace::State out;
    out.pc=s->PC->GetValue();out.a=s->A->GetValue();out.x=s->X->GetValue();out.y=s->Y->GetValue();out.sp=s->S->GetValue();out.p=s->P->GetValue();
    for(unsigned i=0;i<8;++i)out.mpr[i]=memory->GetMpr(i);
    out.clock_divisor=*s->SPEED?3:12;out.ticks=bus_core->GetMasterClockCycles();
    out.wram_sha256=reference_trace::hash(std::span<const std::uint8_t>(memory->GetWorkingRAM(),8192));return out;
}
void bus_reference_access(unsigned logical,unsigned physical,unsigned value,bool write,bool fixed,bool direct){
    if(!bus_core || !bus_reference::enabled)return;
    std::array<std::uint8_t,8> mpr{};for(unsigned i=0;i<8;++i)mpr[i]=bus_core->GetMemory()->GetMpr(i);
    bus_reference::access(bus_core->GetMasterClockCycles(),mpr,logical,physical,value,write,fixed,direct);
}
int main(int argc,char**argv){try{
    if(argc!=4)throw std::runtime_error("gear-bus AUTHORED_ROM low|high|block 0|1");
    const auto fixture=bus_fixture(argv[2]);const std::string enabled=argv[3];if(enabled!="0"&&enabled!="1")throw std::runtime_error("Boolean observer choice required");
    const auto rom=read_rom(argv[1]);if(rom.size()!=262144)throw std::runtime_error("256KiB authored firmware required");
    GeargrafxCore core;bus_core=&core;core.Init(nullptr);core.GetMedia()->SetConsoleType(GG_CONSOLE_PCE);core.GetMedia()->SetCDROMType(GG_CDROM_AUTO);core.GetMedia()->ForceBackupRAM(false);
    core.GetHuC6280()->SetResetValue(0);core.GetMemory()->SetResetValues(0,0,0,0);core.GetHuC6260()->SetResetValue(0);core.GetHuC6270_1()->SetSafeDefaults(false);core.GetScsiController()->SetResetValue(0);
    if(!core.LoadHuCardFromBuffer(rom.data(),static_cast<int>(rom.size()),"authored-bus.pce"))throw std::runtime_error("Authored firmware load failed");
    auto* cpu=core.GetHuC6280();cpu->SetHardwareClock(clock_cpu,&core);
    const auto once=[&]{const auto ticks=cpu->RunInstruction(),clocked=cpu->GetClockedMasterCycles();if(ticks>clocked)clock_cpu(&core,ticks-clocked);};
    for(unsigned i=0;i<fixture.primer;++i){do{once();}while(cpu->*bus_transfer(BusTransferTag{}));}
    const auto initial=bus_state();if(initial.pc!=fixture.instructions.front().pc||initial.clock_divisor!=fixture.divisor)throw std::runtime_error("Software primer differs");
    reference_trace::write_initial(std::cout,initial);bus_reference::enabled=enabled=="1";
    for(unsigned i=0;i<fixture.instructions.size();++i){
        if(bus_state().pc!=fixture.instructions[i].pc)throw std::runtime_error("Measured route differs");
        do{
            if(++bus_reference::calls>100)throw std::runtime_error("Finite original call bound");
            const auto entry=bus_state();const auto source=bus_reference::candidate(fixture,entry.pc);
            for(unsigned n=0;n<source.bytes.size();++n){u8 actual=0;if(!core.GetMemory()->TryPeek(static_cast<u16>(entry.pc+n),&actual)||actual!=source.bytes[n])throw std::runtime_error("Actual candidate bytes differ");}
            bus_reference::instruction_begin(bus_reference::calls,entry,source);once();
            bus_reference::retired(bus_reference::calls,bus_state(),!(cpu->*bus_transfer(BusTransferTag{})));
        }while(cpu->*bus_transfer(BusTransferTag{}));
    }
    bus_reference::enabled=false;bus_reference::finish(static_cast<unsigned>(fixture.instructions.size()));bus_core=nullptr;return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
