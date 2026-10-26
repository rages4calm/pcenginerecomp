// Authored wrapper only; the original pinned GPL core is compiled separately.
// Reuse existing authored public-API setup/report helpers, not device bodies.
#define main previous_mapper_probe_main
#include "geargrafx_mapper_probe.cpp"
#undef main
int main(int argc,char** argv) {
    try {
        if(argc!=2)throw std::runtime_error("gear-context AUTHORED_ROM");
        const auto rom=read_rom(argv[1]);if(rom.size()!=262144)throw std::runtime_error("256KiB authored ROM required");
        bool first=true;std::cout<<'[';
        for(unsigned divisor:{3U,12U}) {
            GeargrafxCore core;core.Init(nullptr);
            core.GetMedia()->SetConsoleType(GG_CONSOLE_PCE);core.GetMedia()->SetCDROMType(GG_CDROM_AUTO);
            core.GetMedia()->ForceBackupRAM(false);core.GetHuC6280()->SetResetValue(0);
            core.GetMemory()->SetResetValues(0,0,0,0);core.GetHuC6260()->SetResetValue(0);
            core.GetHuC6270_1()->SetSafeDefaults(false);core.GetScsiController()->SetResetValue(0);
            if(!core.LoadHuCardFromBuffer(rom.data(),static_cast<int>(rom.size()),"authored-context.pce"))throw std::runtime_error("Cannot load authored firmware");
            if(core.GetMedia()->IsCDROMHardwareEnabled() || core.GetMedia()->IsSGX())throw std::runtime_error("Unexpected fixture hardware");
            auto* cpu=core.GetHuC6280();*cpu->GetState()->SPEED=divisor==3?1:0;
            cpu->SetHardwareClock(clock_cpu,&core);
            for(unsigned i=0;i<40;++i) {
                const auto ticks=cpu->RunInstruction(),clocked=cpu->GetClockedMasterCycles();
                if(ticks>clocked)clock_cpu(&core,ticks-clocked);
                // Inspect CPU/mapping fields directly. Do not call the mapper
                // helper's broader observer, which also samples an I/O port.
                auto* state=cpu->GetState();auto* memory=core.GetMemory();
                std::vector<std::uint64_t> row{state->PC->GetValue(),state->A->GetValue(),
                    state->X->GetValue(),state->Y->GetValue(),state->S->GetValue(),
                    state->P->GetValue(),*state->SPEED?3U:12U,core.GetMasterClockCycles()};
                for(unsigned page=0;page<8;++page)row.push_back(memory->GetMpr(page));
                row.push_back(memory->GetMprTMA(0));
                const auto* ram=core.GetMemory()->GetWorkingRAM();const auto pc=static_cast<unsigned>(row[0]);
                row.insert(row.end(),{ram[16],ram[17],(unsigned(core.GetMemory()->GetMpr(pc>>13))<<13)|(pc&8191)});
                reset_probe::record(first,"cpu",row);
            }
        }
        std::cout<<"]\n";return 0;
    }catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
}
