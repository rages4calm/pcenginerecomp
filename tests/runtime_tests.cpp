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
    return std::tuple{s.a,s.x,s.y,s.sp,s.p,s.pc,s.mpr,s.mpr_latch,s.ticks,s.cycles,s.clock_divisor};
}
static void initialize(pce::Bus& bus) {
    bus.kind[0x80]=pce::BankKind::ram;
    bus.kind[0x81]=pce::BankKind::ram;
    bus.kind[0xF8]=pce::BankKind::ram;
    bus.kind[0xFF]=pce::BankKind::io;
    for(auto [pa,value]:program) (*bus.bytes)[pa]=value;
}

static std::uint16_t fixture_pc(unsigned opcode) {
    for(auto [pc,op]:cases) if(op==opcode) return pc;
    throw std::runtime_error("missing instruction fixture");
}

static pce::Exit execute(pce::Bus& bus, pce::Cpu& s, bool native) {
    constexpr auto forever=std::numeric_limits<std::uint64_t>::max();
    return native ? pce::generated_step(bus,s,forever) : pce::interpret_step(bus,s,forever);
}

#include "data_tests.hpp"
#include "rmw_tests.hpp"
#include "bit_test_tests.hpp"
#include "mpr_tests.hpp"
#include "speed_tests.hpp"

static unsigned bit_stack_expectations(pce::Bus& bus) {
    unsigned checks=0;
    // Independent expected-value matrices, not emitter/interpreter agreement.
    // Every incoming status byte and both states of every selected bit.
    for(unsigned op=0x07; op<=0xF7; op+=0x10) {
        for(unsigned flags=0; flags<256; ++flags) {
            for(unsigned value: {0x00U,0xFFU,0x55U,0xAAU}) {
                for(bool native: {false,true}) {
                    pce::Cpu s; s.pc=fixture_pc(op); s.p=static_cast<std::uint8_t>(flags);
                    s.a=0x93; s.x=0xE1; s.y=0x68; s.sp=0;
                    s.clock_divisor=flags&1 ? 12 : 3;
                    auto expected=s;
                    expected.pc+=2; expected.p &= ~pce::T;
                    expected.cycles=7; expected.ticks=7*s.clock_divisor;
                    const unsigned bit=(op >> 4) & 7;
                    const auto wanted=static_cast<std::uint8_t>(op<0x80 ? value & ~(1U << bit) : value | (1U << bit));
                    (*bus.bytes)[0x1F0020]=static_cast<std::uint8_t>(value);
                    (*bus.bytes)[0x1F001F]=0x19; (*bus.bytes)[0x1F0021]=0xA6;
                    const auto generation=bus.generation[0xF8];
                    require(execute(bus,s,native)==pce::Exit::executed,"bit instruction did not execute");
                    require(state(s)==state(expected),"bit flags/registers/PC/cycles mismatch");
                    require((*bus.bytes)[0x1F0020]==wanted,"RMB/SMB bit result mismatch");
                    require((*bus.bytes)[0x1F001F]==0x19 && (*bus.bytes)[0x1F0021]==0xA6,"bit instruction touched adjacent zero-page bytes");
                    require(bus.generation[0xF8]==generation+(wanted!=value),"bit write generation mismatch");
                    ++checks;
                }
            }
        }
    }
    // All possible saved/pulled bytes at both wrap boundaries, with flags
    // deliberately including T and arbitrary incoming B values.
    for(unsigned op: {0x08U,0x28U,0x48U,0x68U,0x5AU,0x7AU,0xDAU,0xFAU}) {
        const bool pull=op==0x28 || op==0x68 || op==0x7A || op==0xFA;
        for(unsigned value=0; value<256; ++value) {
            for(unsigned sp: {0U,1U,254U,255U}) {
                for(unsigned flags: {0x00U,0xFFU,0x55U,0xAAU}) {
                    if(op==0x08 && flags!=0) continue; // value already sweeps every incoming P
                    for(bool native: {false,true}) {
                        pce::Cpu s; s.pc=fixture_pc(op); s.p=static_cast<std::uint8_t>(flags);
                        s.a=0x61; s.x=0x93; s.y=0xE7; s.sp=static_cast<std::uint8_t>(sp);
                        s.clock_divisor=sp&1 ? 12 : 3;
                        if(op==0x48) s.a=static_cast<std::uint8_t>(value);
                        if(op==0xDA) s.x=static_cast<std::uint8_t>(value);
                        if(op==0x5A) s.y=static_cast<std::uint8_t>(value);
                        // For PHP, sweep every incoming P independently of the
                        // four control-flag contexts used by other stack ops.
                        if(op==0x08) s.p=static_cast<std::uint8_t>(value);
                        auto expected=s;
                        const auto stack_offset=static_cast<std::uint8_t>(pull ? sp+1 : sp);
                        const auto pa=0x1F0100U+stack_offset;
                        const auto next_pa=0x1F0100U+static_cast<std::uint8_t>(stack_offset+1);
                        (*bus.bytes)[pa]=static_cast<std::uint8_t>(pull ? value : value^0xFF);
                        (*bus.bytes)[next_pa]=0x69;
                        unsigned stored=value;
                        if(op==0x08) stored=(value | 0x10) & ~0x20U;
                        expected.sp=static_cast<std::uint8_t>(pull ? sp+1 : sp-1);
                        expected.pc+=1; expected.p &= ~pce::T;
                        if(pull && op!=0x28) {
                            if(op==0x68) expected.a=static_cast<std::uint8_t>(value);
                            if(op==0xFA) expected.x=static_cast<std::uint8_t>(value);
                            if(op==0x7A) expected.y=static_cast<std::uint8_t>(value);
                            expected.p=static_cast<std::uint8_t>((flags & ~(0x80U|0x02U|0x20U)) | (value & 0x80) | (value==0 ? 0x02 : 0));
                        }
                        if(op==0x28) expected.p=static_cast<std::uint8_t>(value & ~0x10U);
                        expected.cycles=pull ? 4 : 3;
                        expected.ticks=expected.cycles*s.clock_divisor;
                        require(execute(bus,s,native)==pce::Exit::executed,"stack instruction did not execute");
                        require(state(s)==state(expected),"stack flags/registers/wrap/PC/cycles mismatch");
                        require((*bus.bytes)[pa]==(pull ? value : stored) && (*bus.bytes)[next_pa]==0x69,"stack memory footprint mismatch");
                        ++checks;
                    }
                }
            }
        }
    }
    return checks;
}

static void bit_stack_boundaries(pce::Bus& bus) {
    constexpr auto forever=std::numeric_limits<std::uint64_t>::max();
    // An irrelevant-page RAM alias still changes the conservative MPR key:
    // native must yield, and fallback must observe the shared physical byte.
    pce::Cpu s; s.pc=fixture_pc(0x87); s.mpr[3]=0xF8;
    (*bus.bytes)[0x1F0020]=0;
    auto before=s;
    require(pce::generated_step(bus,s,forever)==pce::Exit::miss && state(s)==state(before),"alias mapping guard mutated CPU");
    require(pce::step(bus,s,forever)==pce::Exit::executed && bus.read(s,0x6020)==1 && s.interpreter_steps==1,"RMB/SMB alias fallback failed");
    // Remapping MPR1 must redirect the actual stack, never hardcode bank F8.
    s=pce::Cpu{}; s.pc=fixture_pc(0x48); s.mpr[1]=0x81; s.sp=0; s.a=0xB7;
    (*bus.bytes)[0x102100]=0; (*bus.bytes)[0x1F0100]=0x5D;
    require(pce::step(bus,s,forever)==pce::Exit::executed && s.sp==0xFF && (*bus.bytes)[0x102100]==0xB7 && (*bus.bytes)[0x1F0100]==0x5D,"stack remap fallback failed");
    // A modified bit operand is rejected before any write, then interpreted
    // using its current target rather than the stale emitted immediate.
    s=pce::Cpu{}; s.pc=fixture_pc(0x07);
    const auto operand=pce::Bus::physical(s,static_cast<std::uint16_t>(s.pc+1));
    (*bus.bytes)[operand]=0x21; (*bus.bytes)[0x1F0020]=0xFF; (*bus.bytes)[0x1F0021]=0xFF;
    before=s; const auto generation=bus.generation;
    require(pce::generated_step(bus,s,forever)==pce::Exit::miss && state(s)==state(before) && bus.generation==generation,"bit operand guard allowed stale write");
    require(pce::step(bus,s,forever)==pce::Exit::executed && (*bus.bytes)[0x1F0021]==0xFE && (*bus.bytes)[0x1F0020]==0xFF,"bit operand fallback used stale address");
    initialize(bus);
    // PLP can set T; the next ordinary instruction consumes/clears it.
    for(bool native: {false,true}) {
        s=pce::Cpu{}; s.pc=fixture_pc(0x28); s.sp=0xFF;
        (*bus.bytes)[0x1F0100]=0x20;
        require(execute(bus,s,native)==pce::Exit::executed && s.p==0x20 && s.sp==0,"PLP must restore T and clear live B");
        s.pc=fixture_pc(0x08);
        require(execute(bus,s,native)==pce::Exit::executed && (*bus.bytes)[0x1F0100]==0x10 && s.p==0 && s.sp==0xFF,"PHP saved a stale T flag");
        s.pc=fixture_pc(0x28); (*bus.bytes)[0x1F0100]=0x20;
        execute(bus,s,native); s.pc=fixture_pc(0xEA); execute(bus,s,native);
        require(s.p==0,"ordinary successor did not clear PLP-restored T");
    }
    // Device/unmapped stack or zero-page accesses are explicit fatal faults;
    // no instruction retires and there is no fabricated I/O success.
    for(auto kind: {pce::BankKind::io,pce::BankKind::unmapped}) {
        bus.kind[0xF8]=kind;
        for(unsigned op: {0x07U,0x87U,0x08U,0x28U,0x48U,0x68U,0x5AU,0x7AU,0xDAU,0xFAU}) {
            for(bool native: {false,true}) {
                s=pce::Cpu{}; s.pc=fixture_pc(op); bool fault=false;
                try { execute(bus,s,native); } catch(const pce::Fault&) { fault=true; }
                require(fault && s.cycles==0 && s.native_steps==0 && s.interpreter_steps==0 && s.pc==fixture_pc(op),"invalid stack/ZP mapping retired an instruction");
            }
        }
    }
    bus.kind[0xF8]=pce::BankKind::rom;
    for(bool native: {false,true}) {
        s=pce::Cpu{}; s.pc=fixture_pc(0x68); s.sp=0xFF; (*bus.bytes)[0x1F0100]=0x80;
        require(execute(bus,s,native)==pce::Exit::executed && s.a==0x80 && s.sp==0,"stack ROM reads must remain valid");
        for(unsigned op: {0x48U,0x08U,0x07U,0x87U}) {
            s=pce::Cpu{}; s.pc=fixture_pc(op); bool fault=false;
            try { execute(bus,s,native); } catch(const pce::Fault&) { fault=true; }
            require(fault && s.cycles==0,"stack/bit ROM write protection failed");
        }
    }
    bus.kind[0xF8]=pce::BankKind::ram;
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
                x.mpr_latch=static_cast<std::uint8_t>(random());
                x.clock_divisor=variant&1 ? 3 : 12;
                y=x;
                for(unsigned offset=0; offset<8192; ++offset) (*a.bytes)[0x1F0000+offset]=static_cast<std::uint8_t>(random());
                if((op&31)==1 || (op&31)==17 || (op&31)==18) {
                    const unsigned pointer=(op&31)==1 ? (0xFF+x.x)&255:0xFF;
                    (*a.bytes)[0x1F0000+pointer]=0xFF;
                    (*a.bytes)[0x1F0000+((pointer+1)&255)]=0x22;
                }
                *b.bytes=*a.bytes; b.generation=a.generation;
                if(op==3 || op==0x13 || op==0x23) { a.enable_vdc(); b.enable_vdc(); }
                require(pce::generated_step(a,x,forever)==pce::Exit::executed,"native step failed");
                require(pce::interpret_step(b,y,forever)==pce::Exit::executed,"interpreter step failed");
                if(state(x)!=state(y) || *a.bytes!=*b.bytes || a.generation!=b.generation) {
                    std::cerr << "opcode " << unsigned(op) << " variant " << variant << '\n';
                    throw std::runtime_error("native/interpreter state or memory mismatch");
                }
                require(x.native_steps==1 && x.interpreter_steps==0 && y.native_steps==0 && y.interpreter_steps==1,"tier counters incorrect");
                ++comparisons;
                a.vdc.enabled=false; b.vdc.enabled=false;
            }
        }
        const auto expected_checks=bit_stack_expectations(a);
        bit_stack_boundaries(a);
        const auto arithmetic_checks=data_expectations(a);
        const auto address_checks=address_expectations(a);
        data_boundaries(a);
        const auto rmw_checks=rmw_expectations(a);
        const auto jump_checks=jump_expectations(a);
        rmw_jump_boundaries(a);
        const auto test_checks=test_bit_expectations(a);
        const auto branch_checks=bit_branch_bsr_expectations(a);
        bit_test_boundaries(a);
        const auto mpr_checks=mpr_expectations(a);
        mpr_boundaries(a);
        const auto speed_checks=speed_expectations(a);
        speed_boundaries(a);
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
        const std::uint8_t unsupported[]={0x0B}; a.load(0x1F0000,unsupported,1); original=s;
        require(pce::interpret_step(a,s,forever)==pce::Exit::unsupported && state(s)==state(original),"unsupported is an explicit non-mutating exit");
        s.pc=0; bool fault=false;
        try { (void)a.read(s,0); } catch(const pce::Fault&) { fault=true; }
        require(fault && !a.peek(0x1FE000).has_value(),"unimplemented MMIO must trap; peeks must not read devices");
        a.kind[0x80]=pce::BankKind::rom; s=pce::Cpu{}; fault=false;
        try { a.write(s,0x4000,1); } catch(const pce::Fault&) { fault=true; }
        require(fault,"ROM write protection");
        std::cout << comparisons << " synthetic native/interpreter comparisons, " << cases.size()
                  << " opcodes; " << expected_checks << " independent bit/stack expectations; "
                  << arithmetic_checks << " arithmetic/logic expectations; " << address_checks << " addressing expectations; "
                  << rmw_checks << " RMW expectations; " << jump_checks << " indirect JMP expectations; "
                  << test_checks << " bit-test expectations; " << branch_checks << " bit-branch/BSR expectations; "
                  << mpr_checks << " MPR expectations; "
                  << speed_checks << " speed expectations; "
                  << "stack/zero-page/flags/invalidation/deadline/MMIO checks passed\n";
        return 0;
    } catch(const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
