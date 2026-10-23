// Authored CPU/RAM fixture driver for a separately linked, unchanged Gear core.
// Never link this GPL-reference executable into the toolkit runtime.
#include "geargrafx_core.h"
#include "huc6280.h"
#include "memory.h"
#include <algorithm>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#ifdef GG_TESTING
#error BRK reference requires normal HuC6280 stack/vector semantics, not GG_TESTING
#endif

bool g_mcp_stdio_mode=true;
int main(int argc,char** argv){try{
    if(argc!=2)throw std::runtime_error("usage: gear-brk PLAN");
    std::ifstream input(argv[1]);if(!input)throw std::runtime_error("cannot open BRK plan");
    GeargrafxCore core;core.Init(nullptr);auto* cpu=core.GetHuC6280();auto* memory=core.GetMemory();
    cpu->SetResetValue(0);cpu->SetDebugBRK(false,0,false);
    unsigned pc,flags,sp,speed,requests,mask,steps,index=0;bool first=true;std::cout<<'[';
    while(input>>pc>>flags>>sp>>speed>>requests>>mask>>steps){
        if(pc>65535 || flags>255 || sp>255 || (speed!=3 && speed!=12) || requests>7 || mask>7 || steps<1 || steps>2 || ++index>10000)
            throw std::runtime_error("invalid bounded BRK fixture");
        // The fixture has no cartridge. Establish mapped WRAM before the
        // real CPU reset reads its vector; the empty ROM mapping is invalid.
        for(unsigned j=0;j<8;++j)memory->SetMpr(j,0xF8);
        cpu->Reset();auto* state=cpu->GetState();auto* ram=memory->GetWorkingRAM();
        std::fill_n(ram,8192,0);
        // Same authored initial program, independently installed by logical
        // WRAM offsets. These are fixture inputs, not expected output state.
        for(unsigned offset:{0x800U,0x1FFFU,0x100U})ram[offset]=0;
        for(unsigned offset:{0x801U,0U,0x101U})ram[offset]=0xA5;
        ram[0x900]=0x40;
        ram[0x1FF6]=0;ram[0x1FF7]=0x29;ram[0x1FF8]=0x20;ram[0x1FF9]=0x29;ram[0x1FFA]=0x40;ram[0x1FFB]=0x29;
        for(unsigned j=0;j<8;++j)memory->SetMpr(j,0xF8);
        state->PC->SetValue(pc);state->P->SetValue(flags);state->S->SetValue(sp);
        state->A->SetValue(0x63);state->X->SetValue(0xA7);state->Y->SetValue(0x3B);
        *state->SPEED=speed==3?1:0;*state->IDR=mask;*state->IRR=requests;
        u64 ticks=0;
        for(unsigned n=0;n<steps;++n){
            u8 opcode=0;
            if(!memory->TryPeek(state->PC->GetValue(),&opcode) || (opcode!=0 && opcode!=0x40))
                throw std::runtime_error("reference fixture left BRK/RTI source");
            ticks+=cpu->RunInstruction();
            if(!first)std::cout<<',';first=false;
            std::cout<<"{\"case\":"<<index-1<<",\"step\":"<<n+1<<",\"pc\":"<<state->PC->GetValue()
                <<",\"a\":"<<unsigned(state->A->GetValue())<<",\"x\":"<<unsigned(state->X->GetValue())
                <<",\"y\":"<<unsigned(state->Y->GetValue())<<",\"p\":"<<unsigned(state->P->GetValue())
                <<",\"sp\":"<<unsigned(state->S->GetValue())<<",\"ticks\":"<<ticks<<",\"mpr\":[";
            for(unsigned j=0;j<8;++j)std::cout<<(j?",":"")<<unsigned(memory->GetMpr(j));
            std::cout<<"],\"stack\":\"";constexpr char hex[]="0123456789abcdef";
            for(unsigned j=0;j<256;++j){const auto v=ram[0x100+j];std::cout<<hex[v>>4]<<hex[v&15];}
            std::cout<<"\"}";
        }
    }
    if(!input.eof())throw std::runtime_error("truncated BRK plan");std::cout<<"]\n";
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
