#pragma once

static unsigned speed_expectations(pce::Bus& bus) {
    unsigned checks=0;
    // Literal transition table, independently specified in master ticks:
    // entry high -> CSH/CSL = 9/18; entry low -> CSH/CSL = 27/36.
    constexpr unsigned ticks[2][2]={{9,18},{27,36}};
    for(unsigned old=0;old<2;++old) for(unsigned target=0;target<2;++target)
        for(unsigned flags=0;flags<256;++flags) for(unsigned latch=0;latch<256;++latch) for(bool native:{false,true}) {
            pce::Cpu s; s.pc=fixture_pc(target ? 0x54:0xD4);
            s.a=static_cast<std::uint8_t>(flags^latch); s.x=static_cast<std::uint8_t>(latch+19);
            s.y=static_cast<std::uint8_t>(flags+37); s.sp=static_cast<std::uint8_t>(latch^255);
            s.p=static_cast<std::uint8_t>(flags); s.mpr_latch=static_cast<std::uint8_t>(latch);
            s.clock_divisor=old ? 12:3; s.cycles=91; s.ticks=1009;
            auto expected=s; expected.pc++; expected.p &= ~pce::T;
            expected.clock_divisor=target ? 12:3; expected.cycles+=3; expected.ticks+=ticks[old][target];
            const auto generations=bus.generation;
            require(execute(bus,s,native)==pce::Exit::executed && state(s)==state(expected),"speed flags/registers/latch/transition timing mismatch");
            require(s.native_steps==unsigned(native) && s.interpreter_steps==unsigned(!native),"speed instruction retirement counter mismatch");
            require(bus.generation==generations,"speed instruction wrote RAM");
            ++checks;
        }
    return checks;
}

static void speed_boundaries(pce::Bus& bus) {
    constexpr auto forever=std::numeric_limits<std::uint64_t>::max();
    for(bool native:{false,true}) for(unsigned divisor:{3U,12U}) {
        pce::Cpu s; s.pc=fixture_pc(0x54); s.clock_divisor=divisor; s.ticks=10; s.mpr_latch=0xA7; s.p=255;
        auto before=s;
        auto run=[&](std::uint64_t deadline) { return native ? pce::generated_step(bus,s,deadline):pce::interpret_step(bus,s,deadline); };
        require(run(10)==pce::Exit::budget && state(s)==state(before),"deadline changed speed or architectural state");
        require(run(11)==pce::Exit::executed && s.clock_divisor==12 && s.ticks==(divisor==3 ? 28U:46U),"crossing deadline truncated speed instruction");
        s.pc=fixture_pc(0xEA); before=s;
        require(run(11)==pce::Exit::budget && state(s)==state(before),"next instruction ran after crossing speed deadline");
        // Repeated speed selects, mixed transitions and following ordinary
        // instructions must use current speed without stale native constants.
        s=pce::Cpu{}; s.clock_divisor=divisor; s.p=255; s.mpr_latch=0x65;
        unsigned expected_ticks=0, expected_cycles=0, old=divisor;
        for(unsigned op:{0x54U,0x54U,0xEAU,0xD4U,0xD4U,0xEAU,0x54U,0xEAU}) {
            s.pc=fixture_pc(op);
            const unsigned next=op==0x54 ? 12:op==0xD4 ? 3:old;
            expected_ticks+=op==0xEA ? 2*old:old+old+next;
            expected_cycles+=op==0xEA ? 2:3;
            require(execute(bus,s,native)==pce::Exit::executed && s.clock_divisor==next && s.ticks==expected_ticks && s.cycles==expected_cycles && s.p==0xDF && s.mpr_latch==0x65,"mixed speed sequence accounting/preservation");
            old=next;
        }
    }
    pce::Cpu s; s.pc=fixture_pc(0x54); s.clock_divisor=12; s.mpr_latch=0x91;
    const auto pa=pce::Bus::physical(s,s.pc); (*bus.bytes)[pa]=0xD4;
    auto before=s;
    require(pce::generated_step(bus,s,forever)==pce::Exit::miss && state(s)==state(before),"mutated speed source altered state");
    require(pce::step(bus,s,forever)==pce::Exit::executed && s.clock_divisor==3 && s.ticks==27 && s.interpreter_steps==1 && s.mpr_latch==0x91,"speed mutation fallback ignored live opcode");
    initialize(bus);
    s=pce::Cpu{}; s.pc=fixture_pc(0x54); s.mpr[2]=0x81; before=s;
    require(pce::generated_step(bus,s,forever)==pce::Exit::miss && state(s)==state(before),"speed mapping guard changed state");
    // Instruction-level contract: one opcode fetch, PC wraps, no invented
    // operand fetch into the unmapped next page. Hardware dummy reads remain unmodeled.
    s=pce::Cpu{}; s.pc=0xFFFF; s.mpr[7]=0xF8; (*bus.bytes)[0x1F1FFF]=0x54;
    require(pce::interpret_step(bus,s,forever)==pce::Exit::executed && s.pc==0 && s.clock_divisor==12 && s.ticks==18,"speed PC wrap or spurious operand fetch");
    s=pce::Cpu{}; s.pc=0; before=s; bool fault=false;
    try { pce::interpret_step(bus,s,forever); } catch(const pce::Fault&) { fault=true; }
    require(fault && state(s)==state(before),"failed speed opcode fetch changed state");
    initialize(bus);
}
