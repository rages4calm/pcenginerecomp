#include "pce/runtime.hpp"
#include "fixture.hpp"
#include <iostream>
#include <limits>
#include <random>
#include <tuple>

static void require(bool condition, const char* message) {
    if(!condition) throw std::runtime_error(message);
}
static auto state(const pce::Cpu& s) {
    return std::tuple{s.a,s.x,s.y,s.sp,s.p,s.pc,s.mpr,s.ticks,s.cycles,s.clock_divisor};
}
static void initialize(pce::Bus& bus) {
    bus.kind[0x80]=pce::BankKind::ram;
    bus.kind[0x81]=pce::BankKind::ram;
    bus.kind[0xF8]=pce::BankKind::ram;
    bus.kind[0xFF]=pce::BankKind::io;
    for(auto [pa,value]:program) (*bus.bytes)[pa]=value;
}
int main() {
    try {
        constexpr auto forever=std::numeric_limits<std::uint64_t>::max();
        pce::Bus a,b;
        initialize(a); initialize(b);
        std::mt19937 random(0x6280);
        unsigned comparisons=0;
        for(auto [pc,op]:cases) {
            for(unsigned variant=0; variant<64; ++variant) {
                pce::Cpu x,y;
                x.pc=pc; x.a=static_cast<std::uint8_t>(random()); x.x=static_cast<std::uint8_t>(random());
                x.y=static_cast<std::uint8_t>(random()); x.sp=static_cast<std::uint8_t>(random());
                x.p=static_cast<std::uint8_t>(variant*4 + (variant%4));
                x.clock_divisor=variant&1 ? 3 : 12;
                y=x;
                for(unsigned offset=0; offset<8192; ++offset) (*a.bytes)[0x1F0000+offset]=static_cast<std::uint8_t>(random());
                *b.bytes=*a.bytes; b.generation=a.generation;
                require(pce::generated_step(a,x,forever)==pce::Exit::executed,"native step failed");
                require(pce::interpret_step(b,y,forever)==pce::Exit::executed,"interpreter step failed");
                if(state(x)!=state(y) || *a.bytes!=*b.bytes || a.generation!=b.generation) {
                    std::cerr << "opcode " << unsigned(op) << " variant " << variant << '\n';
                    throw std::runtime_error("native/interpreter state or memory mismatch");
                }
                require(x.native_steps==1 && x.interpreter_steps==0 && y.native_steps==0 && y.interpreter_steps==1,"tier counters incorrect");
                ++comparisons;
            }
        }
        // Independent fixed expectations catch semantics both tiers could get wrong.
        pce::Cpu s; s.pc=0x2000; s.sp=0; s.p=pce::N|pce::Z|pce::T;
        const std::uint8_t jsr[]={0x20,0x34,0x12}; a.load(0x1F0000,jsr,3);
        require(pce::interpret_step(a,s,forever)==pce::Exit::executed,"JSR");
        require(s.pc==0x1234 && s.sp==0xFE && (*a.bytes)[0x1F0100]==0x20 && (*a.bytes)[0x1F01FF]==0x02,"guest stack wrap/return address");
        const std::uint8_t clear[]={0x62}; a.load(0x1F0000,clear,1); s.pc=0x2000; s.a=9;
        pce::interpret_step(a,s,forever);
        require(s.a==0 && (s.p & (pce::N|pce::Z))==(pce::N|pce::Z),"CLA must preserve flags");
        const std::uint8_t zp[]={0x85,0x20}; a.load(0x1F0000,zp,2); s.pc=0x2000; s.a=0xAB;
        pce::interpret_step(a,s,forever);
        require((*a.bytes)[0x1F0020]==0xAB,"zero page is logical $2000, not $0000");

        // Restore synthetic code before guard/fallback checks.
        initialize(a);
        s=pce::Cpu{}; s.pc=0x4000;
        auto original=s;
        require(pce::generated_step(a,s,0)==pce::Exit::budget && state(s)==state(original),"deadline side effects");
        s.mpr[2]=0x81; original=s;
        require(pce::generated_step(a,s,forever)==pce::Exit::miss && state(s)==state(original),"MPR guard");
        s=pce::Cpu{};
        // Locate LDA immediate fixture and mutate only its operand.
        for(auto [pc,op]:cases) if(op==0xA9) s.pc=pc;
        auto operand=pce::Bus::physical(s,static_cast<std::uint16_t>(s.pc+1));
        (*a.bytes)[operand]^=0x55; original=s;
        require(pce::generated_step(a,s,forever)==pce::Exit::miss && state(s)==state(original),"operand mutation guard");
        auto expected=(*a.bytes)[operand];
        require(pce::step(a,s,forever)==pce::Exit::executed && s.a==expected && s.interpreter_steps==1 && s.native_steps==0,"mutated code must execute current bytes through fallback");
        s=pce::Cpu{}; s.pc=0x2000;
        const std::uint8_t unsupported[]={0x73}; a.load(0x1F0000,unsupported,1); original=s;
        require(pce::interpret_step(a,s,forever)==pce::Exit::unsupported && state(s)==state(original),"unsupported is an explicit non-mutating exit");
        s.pc=0; bool fault=false;
        try { (void)a.read(s,0); } catch(const pce::Fault&) { fault=true; }
        require(fault && !a.peek(0x1FE000).has_value(),"unimplemented MMIO must trap; peeks must not read devices");
        a.kind[0x80]=pce::BankKind::rom; s=pce::Cpu{}; fault=false;
        try { a.write(s,0x4000,1); } catch(const pce::Fault&) { fault=true; }
        require(fault,"ROM write protection");
        std::cout << comparisons << " synthetic native/interpreter comparisons, " << cases.size()
                  << " opcodes; stack/zero-page/flags/invalidation/deadline/MMIO checks passed\n";
        return 0;
    } catch(const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
