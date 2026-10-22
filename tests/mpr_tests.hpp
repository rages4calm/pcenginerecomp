#pragma once

static std::uint16_t mpr_pc(unsigned op,unsigned mask) {
    for(auto entry:mpr_cases) if(entry.op==op && entry.mask==mask) return entry.pc;
    throw std::runtime_error("missing MPR fixture");
}
static unsigned expected_mpr_or(const std::array<std::uint8_t,8>& mapping,unsigned mask) {
    // Independent bit-column model, separate from the production byte ORs.
    unsigned result=0;
    for(unsigned bit=1; bit<256; bit*=2) {
        bool present=false;
        for(unsigned i=0;i<8;++i) if((mask&(1U<<i)) && (mapping[i]&bit)) present=true;
        if(present) result+=bit;
    }
    return result;
}
static unsigned mpr_expectations(pce::Bus& bus) {
    unsigned checks=0;
    for(unsigned mask=0;mask<256;++mask) for(unsigned value=0;value<256;++value) {
        for(unsigned flags:{0U,255U,0x55U,0xAAU}) for(unsigned op:{0x43U,0x53U}) for(bool native:{false,true}) {
            pce::Cpu s; s.pc=mpr_pc(op,mask); s.a=static_cast<std::uint8_t>(op==0x53 ? value:value^0x5A);
            s.mpr_latch=static_cast<std::uint8_t>(op==0x43 ? value:value^255);
            s.x=0x83; s.y=0x19; s.sp=0x61; s.p=static_cast<std::uint8_t>(flags);
            s.clock_divisor=value&1 ? 12:3;
            auto expected=s;
            expected.pc+=2; expected.p &= ~pce::T;
            expected.cycles=op==0x43 ? 4:5; expected.ticks=expected.cycles*s.clock_divisor;
            if(mask) {
                if(op==0x43) expected.mpr_latch=static_cast<std::uint8_t>(expected_mpr_or(s.mpr,mask));
                else {
                    expected.mpr_latch=s.a;
                    for(unsigned i=0;i<8;++i) if(mask&(1U<<i)) expected.mpr[i]=s.a;
                }
            }
            if(op==0x43) expected.a=expected.mpr_latch;
            const auto generations=bus.generation;
            require(execute(bus,s,native)==pce::Exit::executed && state(s)==state(expected),"MPR masks/values/latch/flags/cycles mismatch");
            require(bus.generation==generations,"MPR operation wrote RAM");
            ++checks;
        }
    }
    // Different mappings are interpreter contexts; code stays in work RAM.
    for(unsigned mask=0;mask<256;++mask) for(unsigned pattern=0;pattern<256;++pattern) {
        pce::Cpu s; s.pc=0x2700; s.p=static_cast<std::uint8_t>(pattern); s.a=0xDE;
        s.mpr_latch=static_cast<std::uint8_t>(pattern^0xA5);
        for(unsigned i=0;i<8;++i) if(i!=1) s.mpr[i]=static_cast<std::uint8_t>(pattern^(1U<<i));
        const auto wanted=mask ? expected_mpr_or(s.mpr,mask):s.mpr_latch;
        (*bus.bytes)[0x1F0700]=0x43; (*bus.bytes)[0x1F0701]=static_cast<std::uint8_t>(mask);
        auto expected=s; expected.pc+=2; expected.p &= ~pce::T;
        expected.a=expected.mpr_latch=static_cast<std::uint8_t>(wanted); expected.cycles=4; expected.ticks=12;
        require(execute(bus,s,false)==pce::Exit::executed && state(s)==state(expected),"TMA arbitrary mapping OR/latch mismatch");
        ++checks;
    }
    return checks;
}
static void mpr_boundaries(pce::Bus& bus) {
    constexpr auto forever=std::numeric_limits<std::uint64_t>::max();
    for(bool native:{false,true}) {
        pce::Cpu s; s.pc=mpr_pc(0x43,4); s.p=255;
        execute(bus,s,native); require(s.a==0x80 && s.mpr_latch==0x80 && s.p==0xDF,"TMA selected register or flags");
        s.pc=mpr_pc(0x53,0); s.a=0x37; execute(bus,s,native);
        require(s.mpr_latch==0x80,"TAM zero changed the MPR latch");
        s.pc=fixture_pc(0x85); execute(bus,s,native);
        s.pc=fixture_pc(0xA5); execute(bus,s,native);
        require(s.a==0x37 && s.mpr_latch==0x80,"ordinary memory traffic changed the MPR latch");
        s.pc=mpr_pc(0x43,0); execute(bus,s,native);
        require(s.a==0x80 && s.mpr_latch==0x80,"TMA zero used A or the memory bus instead of its latch");
    }
    // A TAM that changes the executing page must retire, then invalidate the
    // old native context. Fallback fetches the next opcode through the new MPR.
    pce::Cpu s; s.pc=mpr_pc(0x53,4); s.a=0x81; s.mpr_latch=0x19;
    require(execute(bus,s,true)==pce::Exit::executed && s.mpr[2]==0x81 && s.mpr_latch==0x81,"native TAM remap/latch");
    auto next=pce::Bus::physical(s,s.pc); (*bus.bytes)[next]=0xA9; (*bus.bytes)[next+1]=0x5B;
    auto before=s;
    require(pce::generated_step(bus,s,forever)==pce::Exit::miss && state(s)==state(before),"remapped native context did not yield");
    require(pce::step(bus,s,forever)==pce::Exit::executed && s.a==0x5B && s.mpr_latch==0x81 && s.interpreter_steps==1,"TAM remap fallback fetch or latch persistence");
    initialize(bus);
    s=pce::Cpu{}; s.pc=fixture_pc(0x53); s.a=0xA7; s.mpr_latch=0x19;
    const auto operand=pce::Bus::physical(s,s.pc+1); (*bus.bytes)[operand]=0;
    before=s;
    require(pce::generated_step(bus,s,forever)==pce::Exit::miss && state(s)==state(before),"TAM stale operand changed state or latch");
    require(pce::interpret_step(bus,s,forever)==pce::Exit::executed && s.mpr==before.mpr && s.mpr_latch==0x19,"TAM mutated zero operand fallback");
    initialize(bus);
    s=pce::Cpu{}; s.pc=mpr_pc(0x43,0); s.mpr_latch=0xA5; s.ticks=10; before=s;
    require(pce::generated_step(bus,s,10)==pce::Exit::budget && state(s)==state(before),"TMA budget mutated the latch");
    require(pce::interpret_step(bus,s,10)==pce::Exit::budget && state(s)==state(before),"interpreter TMA budget mutated the latch");
}
