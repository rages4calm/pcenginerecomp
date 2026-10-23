// Authored adapter for a separately compiled, unchanged Geargrafx process.
// Public VRAM/SAT pointers seed synthetic memory, never private event state.
#include "geargrafx_core.h"
#include "huc6270.h"
#include "huc6260.h"
#include "huc6280.h"
#include "memory.h"
#include <array>
#include <fstream>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>

bool g_mcp_stdio_mode=true;
// This authored bridge invokes the original scheduler at master-tick edges;
// it neither replaces Gear code nor reads or modifies private state.
struct SpriteClockTag {
    using type=bool (GeargrafxCore::*)(u32);
    friend type sprite_clock_member(SpriteClockTag);
};
template<class Tag, typename Tag::type Member> struct SpriteClockAccess {
    friend typename Tag::type sprite_clock_member(Tag) {return Member;}
};
template struct SpriteClockAccess<SpriteClockTag,&GeargrafxCore::ClockHardware<false,false,false>>;

void initialize_sprite_core(GeargrafxCore& core) {
    core.Init(nullptr);core.GetHuC6270_1()->SetSafeDefaults(false);
    core.GetHuC6280()->SetResetValue(0);
    // Init only wires the CPU. Loading a synthetic HuCard invokes the normal
    // complete media reset, with a real mapped reset vector and initialized
    // interrupt/timer state. No copyrighted program or firmware is used.
    std::array<u8,8192> card;card.fill(0xEA);card[8190]=0;card[8191]=0;
    if(!core.LoadHuCardFromBuffer(card.data(),int(card.size()),"authored-sprite.pce"))
        throw std::runtime_error("cannot load authored HuCard");
}

int main(int argc,char** argv) {
    try {
        if(argc!=2)throw std::runtime_error("usage: gear-sprite PLAN");
        if(std::string(argv[1])=="--memory") {
            GeargrafxCore core;initialize_sprite_core(core);auto* memory=core.GetMemory();
            for(unsigned i=0;i<4;++i)memory->SetMpr(i,static_cast<u8>(0xF8+i));
            unsigned checks=0;
            for(unsigned bank=0;bank<4;++bank) {
                for(unsigned offset=0;offset<8192;++offset) {
                    const auto value=static_cast<u8>((offset*37+bank*73+11)&255);
                    memory->Write(static_cast<u16>(bank*8192+offset),value);
                    for(unsigned alias=0;alias<4;++alias) {
                        if(memory->Read(static_cast<u16>(alias*8192+offset))!=value)
                            throw std::runtime_error("WRAM alias mismatch");
                        ++checks;
                    }
                }
            }
            // Execute two authored instructions through each physical alias.
            // The program and target share the ordinary 8 KiB WRAM backing.
            std::cout<<"{\"data_checks\":"<<checks<<",\"execution\":[";
            for(unsigned bank=0;bank<4;++bank) {
                memory->SetMpr(1,0xF8);memory->SetMpr(2,static_cast<u8>(0xF8+bank));
                const u8 code[]={0xA9,0xA5,0x8D,0x10,0x20};
                for(unsigned i=0;i<sizeof(code);++i)memory->Write(static_cast<u16>(0x2000+i),code[i]);
                auto* state=core.GetHuC6280()->GetState();
                state->PC->SetValue(0x4000);state->P->SetValue(4);state->A->SetValue(0);
                core.GetHuC6280()->RunInstruction();core.GetHuC6280()->RunInstruction();
                if(bank)std::cout<<',';
                std::cout<<"{\"bank\":"<<248+bank<<",\"pc\":"<<state->PC->GetValue()
                    <<",\"a\":"<<unsigned(state->A->GetValue())<<",\"stored\":"<<unsigned(memory->Read(0x2010))<<'}';
                if(state->PC->GetValue()!=0x4005 || state->A->GetValue()!=0xA5 || memory->Read(0x2010)!=0xA5)
                    throw std::runtime_error("WRAM instruction alias mismatch");
            }
            std::cout<<"]}\n";return 0;
        }
        std::ifstream plan(argv[1]);if(!plan)throw std::runtime_error("cannot open plan");
        std::unique_ptr<GeargrafxCore> core;u64 time=0;bool first=true;
        const auto advance=[&](u64 target) {
            if(!core || target<time || target-time>2000000)throw std::runtime_error("invalid finite timestamp");
            while(time<target){(core.get()->*sprite_clock_member(SpriteClockTag{}))(1);++time;}
            if(core->GetMasterClockCycles()!=time)throw std::runtime_error("core clock mismatch");
        };
        std::string op;std::cout<<'[';
        while(plan>>op) {
            if(op=="r") {
                core=std::make_unique<GeargrafxCore>();initialize_sprite_core(*core);time=0;
                // Disable the optional safe display geometry explicitly.
                core->GetHuC6270_1()->SetSafeDefaults(false);core->GetHuC6270_1()->Reset();
                core->GetHuC6260()->WriteRegister(0,0);
            } else if(op=="v" || op=="t") {
                unsigned address,value;
                if(!core || !(plan>>address>>value) || value>65535 || address>=(op=="v"?32768U:256U))
                    throw std::runtime_error("invalid authored memory seed");
                (op=="v"?core->GetHuC6270_1()->GetVRAM():core->GetHuC6270_1()->GetSAT())[address]=static_cast<u16>(value);
            } else if(op=="w") {
                u64 at;unsigned reg,value;
                if(!(plan>>at>>reg>>value) || reg>=20 || value>65535)throw std::runtime_error("invalid VDC write");
                advance(at);auto* vdc=core->GetHuC6270_1();
                vdc->WriteRegister(0,static_cast<u8>(reg));vdc->WriteRegister(2,static_cast<u8>(value));
                vdc->WriteRegister(3,static_cast<u8>(value>>8));
            } else if(op=="c") {
                u64 at;unsigned value;if(!(plan>>at>>value) || value>255)throw std::runtime_error("invalid VCE write");
                advance(at);core->GetHuC6260()->WriteRegister(0,static_cast<u8>(value));
            } else if(op=="s" || op=="d") {
                u64 at;if(!(plan>>at))throw std::runtime_error("invalid sample");advance(at);
                auto* vdc=core->GetHuC6270_1();
                const unsigned status=*vdc->GetState()->SR&63;
                const unsigned irq=(core->GetHuC6280()->ReadInterruptRegister(3)&2)!=0;
                if(op=="d" && (vdc->ReadRegister(0)&63)!=status)throw std::runtime_error("status read mismatch");
                const unsigned after=*vdc->GetState()->SR&63;
                const unsigned after_irq=(core->GetHuC6280()->ReadInterruptRegister(3)&2)!=0;
                if(!first)std::cout<<',';first=false;
                std::cout<<"{\"time\":"<<time<<",\"status\":"<<status<<",\"irq\":"<<(irq?"true":"false")
                    <<",\"after_status\":"<<after<<",\"after_irq\":"<<(after_irq?"true":"false")<<'}';
            } else throw std::runtime_error("unknown plan operation");
        }
        if(!plan.eof())throw std::runtime_error("truncated plan");std::cout<<"]\n";
    } catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
}
