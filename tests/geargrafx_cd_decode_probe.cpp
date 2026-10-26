// Authored observer around a separately compiled, unchanged original Gear core.
// Existing authored bootstrap wiring is reused; no GPL device body is copied.
#define main prior_authored_reset_main
#include "geargrafx_reset_probe.cpp"
#undef main

template<class T,typename T::type Member>struct DecodeAccess{friend typename T::type decode_member(T){return Member;}};
struct IoBuffer{using type=u8 Memory::*;friend type decode_member(IoBuffer);};
struct MprBuffer{using type=u8 Memory::*;friend type decode_member(MprBuffer);};
struct DataLatch{using type=u8 ScsiController::*;friend type decode_member(DataLatch);};
template struct DecodeAccess<IoBuffer,&Memory::m_io_buffer>;
template struct DecodeAccess<MprBuffer,&Memory::m_mpr_buffer>;
template struct DecodeAccess<DataLatch,&ScsiController::m_data_bus_latch>;

static std::vector<std::uint64_t> decode_state(GeargrafxCore& core,unsigned profile) {
    auto* c=core.GetHuC6280()->GetState();auto* m=core.GetMemory();
    std::vector<std::uint64_t> out{c->PC->GetValue(),c->A->GetValue(),c->X->GetValue(),
        c->Y->GetValue(),c->S->GetValue(),c->P->GetValue(),*c->SPEED?3U:12U,core.GetMasterClockCycles()};
    for(unsigned page=0;page<8;++page)out.push_back(m->GetMpr(page));
    out.push_back(m->*decode_member(MprBuffer{}));out.push_back(m->*decode_member(IoBuffer{}));
    if(profile<2) {
        auto* cd=core.GetCDROM()->GetState();auto* scsi=core.GetScsiController()->GetState();
        out.insert(out.end(),{unsigned(*cd->BRAM_ENABLED),*cd->RESET,*cd->ENABLED_IRQS,*cd->ACTIVE_IRQS,
            unsigned(*scsi->PHASE),*scsi->SIGNALS,core.GetScsiController()->*decode_member(DataLatch{}),*cd->FADER});
    }
    return out;
}
static std::vector<std::uint64_t> decode_memory(GeargrafxCore& core,unsigned profile) {
    auto* m=core.GetMemory();std::vector<std::uint64_t> out{reset_probe::hash(m->GetWorkingRAM(),8192)};
    if(profile<2)out.push_back(reset_probe::hash(m->GetBackupRAM(),2048));return out;
}
static void observe_decode(bool& first,GeargrafxCore& core,unsigned profile,bool memory) {
    const auto cpu=decode_state(core,profile),ram=decode_memory(core,profile);
    if(cpu!=decode_state(core,profile) || ram!=decode_memory(core,profile))
        throw std::runtime_error("Repeated original Gear decode inspection changed state");
    reset_probe::record(first,"cpu",cpu);if(memory)reset_probe::record(first,"memory",ram);
}
int main(int argc,char**argv) {
    try {
        if(argc!=4)throw std::runtime_error("gear-cd-decode PLAN AUTHORED_ROM AUTHORED_CUE");
        const auto rom=reset_probe::rom(argv[2]);std::ifstream plan(argv[1]);
        if(!plan)throw std::runtime_error("Missing authored decode plan");
        std::unique_ptr<GeargrafxCore> core;unsigned profile=0,alias=0;bool first=true;std::string op;
        std::cout<<'[';
        while(plan>>op) {
            if(op=="r") {
                unsigned fast;
                if(!(plan>>profile>>fast>>alias) || profile>2 || fast>1 || alias>1)
                    throw std::runtime_error("Invalid authored decode configuration");
                core=std::make_unique<GeargrafxCore>();core->Init(nullptr);
                core->GetMedia()->SetConsoleType(GG_CONSOLE_PCE);
                core->GetHuC6280()->SetResetValue(0);core->GetMemory()->SetResetValues(0,0,0,0);
                core->GetHuC6260()->SetResetValue(0);core->GetHuC6270_1()->SetSafeDefaults(false);
                core->GetScsiController()->SetResetValue(0);
                if(profile<2) {
                    core->GetMedia()->SetCDROMType(profile?GG_CDROM_SUPER_CDROM:GG_CDROM_STANDARD);
                    if(!core->LoadBiosFromBuffer(rom.data(),static_cast<int>(rom.size()),true) ||
                        !core->LoadMedia(argv[3],false))throw std::runtime_error("Authored BIOS/CUE setup failed");
                } else {
                    core->GetMedia()->SetCDROMType(GG_CDROM_AUTO);core->GetMedia()->ForceBackupRAM(false);
                    if(!core->LoadHuCardFromBuffer(rom.data(),static_cast<int>(rom.size()),"authored-decode.pce"))
                        throw std::runtime_error("Authored HuCard setup failed");
                }
                if(core->GetMedia()->IsCDROMHardwareEnabled()!=(profile<2) || core->GetMedia()->IsSGX())
                    throw std::runtime_error("Original hardware profile differs");
                // Explicit synthetic zero seed. Do not mistake Gear's automatic
                // HUBM formatting for a shared hardware reset contract.
                std::fill_n(core->GetMemory()->GetBackupRAM(),2048,0);
                constexpr unsigned mapping[]{0,248,0,0,0,255,255,0};
                for(unsigned page=0;page<8;++page)core->GetMemory()->SetMpr(page,mapping[page]);
                *core->GetHuC6280()->GetState()->SPEED=fast?1:0;
                core->GetHuC6280()->SetHardwareClock(clock_cpu,core.get());
            } else {
                if(!core)throw std::runtime_error("Operation before original reset");
                if(op=="s")observe_decode(first,*core,profile,true);
                else if(op=="q" || op=="w") {
                    unsigned offset,value=0;
                    if(!(plan>>offset) || offset>8191 || (op=="w" && (!(plan>>value) || value>255)))
                        throw std::runtime_error("Invalid bounded decode operation");
                    const unsigned address=(alias?0xA000:0xC000)|offset;
                    auto* ram=core->GetMemory()->GetWorkingRAM();ram[16]=address&255;ram[17]=address>>8;
                    auto* cpu=core->GetHuC6280();cpu->GetState()->PC->SetValue(op=="q"?0xE000:0xE002);
                    if(op=="w")cpu->GetState()->A->SetValue(value);
                    const auto ticks=cpu->RunInstruction(),clocked=cpu->GetClockedMasterCycles();
                    if(ticks>clocked)clock_cpu(core.get(),ticks-clocked);
                    observe_decode(first,*core,profile,false);
                } else throw std::runtime_error("Unknown authored decode operation");
            }
        }
        std::cout<<"]\n";return 0;
    }catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
}
