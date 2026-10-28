// Separate full original Geargrafx core, public state observers and held-key APIs.
// The template friend shim calls its existing hardware scheduler unchanged.
#include "geargrafx_core.h"
#include "huc6280.h"
#include "huc6270.h"
#include "huc6260.h"
#include "input.h"
#include "media.h"
#include "memory.h"
#include "scsi_controller.h"
#include "state_route_input_support.hpp"
#include <memory>

bool g_mcp_stdio_mode=true;
struct InputClockTag {using type=bool(GeargrafxCore::*)(u32);friend type input_clock(InputClockTag);};
template<class Tag,typename Tag::type Member>struct InputClockAccess {
    friend typename Tag::type input_clock(Tag){return Member;}
};
template struct InputClockAccess<InputClockTag,&GeargrafxCore::ClockHardware<true,false,false>>;
static void clock_cpu(void* context,u32 ticks) {
    auto* core=static_cast<GeargrafxCore*>(context);(core->*input_clock(InputClockTag{}))(ticks);
}
int main(int argc,char** argv) {
    try {
        if(argc!=3)throw std::runtime_error("usage: gear-input PLAN CODE");
        const auto plan=input_probe::plan(argv[1]);const auto code=input_probe::code(argv[2]);
        auto core=std::make_unique<GeargrafxCore>();core->Init(nullptr);
        core->GetMedia()->SetConsoleType(GG_CONSOLE_PCE);core->GetMedia()->ForceBackupRAM(false);
        core->GetHuC6280()->SetResetValue(0);core->GetMemory()->SetResetValues(0,0,0,0);
        core->GetHuC6260()->SetResetValue(0);core->GetHuC6270_1()->SetSafeDefaults(false);
        core->GetScsiController()->SetResetValue(0);std::vector<u8> rom(262144,0xEA);rom[8190]=0;rom[8191]=0xE0;
        if(!core->LoadHuCardFromBuffer(rom.data(),rom.size(),"authored-input.pce"))throw std::runtime_error("authored load failed");
        auto* cpu=core->GetHuC6280();auto* memory=core->GetMemory();auto* state=cpu->GetState();
        for(unsigned i=0;i<8;++i)memory->SetMpr(i,input_probe::mpr[i]);
        std::copy(code.begin(),code.end(),memory->GetWorkingRAM()+0x800);
        state->PC->SetValue(0x2800);state->A->SetValue(0);state->P->SetValue(4);*state->SPEED=plan.divisor==3;
        cpu->SetHardwareClock(clock_cpu,core.get());bool first=true;unsigned held=0,calls=0;
        std::cout<<'[';
        for(unsigned index=0;index<plan.count;++index) {
            if(plan.held.contains(index)) {
                held=plan.held.at(index);
                for(unsigned bit=0;bit<12;++bit) {
                    const auto key=static_cast<GG_Keys>(1<<bit);
                    if(held&(1<<bit))core->GetInput()->KeyPressed(GG_CONTROLLER_1,key);
                    else core->GetInput()->KeyReleased(GG_CONTROLLER_1,key);
                }
            }
            unsigned accepted=0;for(unsigned bit=0;bit<12;++bit)
                if(core->GetInput()->IsKeyPressed(GG_CONTROLLER_1,static_cast<GG_Keys>(1<<bit)))accepted|=1<<bit;
            std::array<unsigned,8> mapping;for(unsigned i=0;i<8;++i)mapping[i]=memory->GetMpr(i);
            auto row=input_probe::identity(index,state->PC->GetValue(),mapping,[&](unsigned pc){u8 value;
                if(!memory->TryPeek(pc,memory->GetMpr(pc>>13),&value))throw std::runtime_error("source peek");return value;});
            row.insert(row.end(),{state->A->GetValue(),state->P->GetValue(),core->GetMasterClockCycles(),core->GetInput()->GetIORegister(),accepted});
            const auto ticks=cpu->RunInstruction();++calls;const auto clocked=cpu->GetClockedMasterCycles();
            if(ticks>clocked)clock_cpu(core.get(),ticks-clocked);
            row.insert(row.end(),{state->PC->GetValue(),state->A->GetValue(),state->P->GetValue(),core->GetMasterClockCycles(),core->GetInput()->GetIORegister(),memory->GetWorkingRAM()[0x400]});
            reset_probe::record(first,"instruction",row);
        }
        std::vector<std::uint64_t> ram;for(unsigned i=0;i<64;++i)ram.push_back(memory->GetWorkingRAM()[0x400+i]);
        reset_probe::record(first,"ram",ram);reset_probe::record(first,"gear_cpu_calls",{calls});std::cout<<"]\n";return 0;
    }catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
}
