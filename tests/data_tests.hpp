// Independent expected-value tests. No production addressing/ALU helpers used.
#pragma once

static unsigned data_expectations(pce::Bus& bus) {
    unsigned checks=0;
    // Every pair of bytes, C/D/T/V combination and execution tier for ADC/SBC.
    // N/Z start set, I/B start set, so unrelated flags must survive.
    for(unsigned opcode: {0x65U,0xE5U}) {
        for(unsigned left=0; left<256; ++left) for(unsigned right=0; right<256; ++right) {
            for(unsigned context=0; context<16; ++context) {
                const bool carry=context&1, decimal=context&2, transfer=(context&4) && opcode==0x65;
                const unsigned flags=0x96|(carry ? 1:0)|(decimal ? 8:0)|(context&4 ? 32:0)|(context&8 ? 64:0);
                const bool subtract=opcode==0xE5;
                int result=static_cast<int>(left)+(subtract ? -static_cast<int>(right):static_cast<int>(right))
                           +(subtract ? carry-1:carry);
                bool c=subtract ? result>=0:result>255;
                bool v=subtract ? ((left^right)&(left^result)&128):(~(left^right)&(left^result)&128);
                if(decimal) {
                    // A digit model, separate from the interpreter's complemented
                    // addition and the emitted code's byte/high-byte arithmetic.
                    int units=static_cast<int>(left%16)+(subtract ? -static_cast<int>(right%16):static_cast<int>(right%16))
                              +(subtract ? carry-1:carry);
                    const bool digit_carry=subtract ? units<0:units>=10;
                    int tens=static_cast<int>(left/16)+(subtract ? -static_cast<int>(right/16):static_cast<int>(right/16))
                             +(digit_carry ? (subtract ? -1:1):0);
                    if(digit_carry) units+=subtract ? -6:6;
                    c=subtract ? tens>=0:tens>=10;
                    if(subtract ? tens<0:tens>=10) tens+=subtract ? -6:6;
                    result=16*tens+(units&15);
                    v=context&8;
                }
                const auto value=static_cast<std::uint8_t>(result);
                const auto wanted_p=static_cast<std::uint8_t>((flags&~0xE3U)|(c ? 1:0)|(v ? 64:0)|(value&128)|(value==0 ? 2:0));
                for(bool native: {false,true}) {
                    pce::Cpu s; s.pc=fixture_pc(opcode); s.p=static_cast<std::uint8_t>(flags);
                    s.a=static_cast<std::uint8_t>(transfer ? left^0x5A:left); s.x=0x80; s.y=0x37;
                    s.clock_divisor=context&1 ? 12:3;
                    (*bus.bytes)[0x1F00FF]=static_cast<std::uint8_t>(right);
                    (*bus.bytes)[0x1F0080]=static_cast<std::uint8_t>(left);
                    auto expected=s; expected.pc+=2; expected.p=wanted_p;
                    if(!transfer) expected.a=value;
                    expected.cycles=4+decimal+(transfer ? 3:0); expected.ticks=expected.cycles*s.clock_divisor;
                    const auto generation=bus.generation[0xF8];
                    require(execute(bus,s,native)==pce::Exit::executed,"arithmetic did not execute");
                    require(state(s)==state(expected),"ADC/SBC result, flags, preservation or cycles mismatch");
                    require((*bus.bytes)[0x1F0080]==(transfer ? value:left) && (*bus.bytes)[0x1F00FF]==right,"T arithmetic footprint mismatch");
                    require(bus.generation[0xF8]==generation+(transfer && value!=left),"T arithmetic generation mismatch");
                    ++checks;
                }
            }
        }
    }
    // Logical operators and comparisons: every byte pair under four flag contexts.
    // Four contexts cover both C/V preservation and T destination selection.
    for(unsigned opcode: {0x05U,0x25U,0x45U,0xC5U,0xE4U,0xC4U}) {
        for(unsigned left=0; left<256; ++left) for(unsigned right=0; right<256; ++right) {
            for(unsigned flags: {0x00U,0xFFU,0x55U,0xAAU}) {
                const bool compare=opcode==0xC5 || opcode==0xE4 || opcode==0xC4;
                const bool transfer=!compare && (flags&32);
                const auto value=static_cast<std::uint8_t>(compare ? left-right:opcode==5 ? left|right:opcode==0x25 ? left&right:left^right);
                unsigned wanted_p=(flags&~0xA2U)|(value&128)|(value==0 ? 2:0);
                if(compare) wanted_p=(wanted_p&~1U)|(left>=right ? 1:0);
                for(bool native: {false,true}) {
                    pce::Cpu s; s.pc=fixture_pc(opcode); s.p=static_cast<std::uint8_t>(flags);
                    s.a=static_cast<std::uint8_t>(transfer ? left^0x5A:left); s.x=0x80; s.y=0x43;
                    if(opcode==0xE4) s.x=static_cast<std::uint8_t>(left);
                    if(opcode==0xC4) s.y=static_cast<std::uint8_t>(left);
                    (*bus.bytes)[0x1F00FF]=static_cast<std::uint8_t>(right);
                    (*bus.bytes)[0x1F0080]=static_cast<std::uint8_t>(left);
                    auto expected=s; expected.p=static_cast<std::uint8_t>(wanted_p); expected.pc+=2;
                    if(!compare && !transfer) expected.a=value;
                    expected.cycles=4+(transfer ? 3:0); expected.ticks=3*expected.cycles;
                    require(execute(bus,s,native)==pce::Exit::executed && state(s)==state(expected),"logic/compare result/flags mismatch");
                    require((*bus.bytes)[0x1F0080]==(transfer ? value:left),"logic/compare memory footprint mismatch");
                    ++checks;
                }
            }
        }
    }
    return checks;
}

static unsigned address_expectations(pce::Bus& bus) {
    unsigned checks=0;
    // Each addressing form, including X/Y-specific loads/stores. Fixed FF
    // operands deliberately cross byte/page boundaries with nonzero indices.
    for(unsigned opcode: {0xA1U,0xB1U,0xB2U,0xA5U,0xB5U,0xADU,0xBDU,0xB9U,
                         0xA6U,0xB6U,0xAEU,0xBEU,0xA4U,0xB4U,0xACU,0xBCU,
                         0x81U,0x91U,0x92U,0x85U,0x95U,0x8DU,0x9DU,0x99U,
                         0x86U,0x96U,0x8EU,0x84U,0x94U,0x8CU,0x64U,0x74U,0x9CU,0x9EU}) {
        for(unsigned index: {0U,1U,0x7FU,0xE0U,0xFFU}) for(bool native: {false,true}) {
            pce::Cpu s; s.pc=fixture_pc(opcode); s.x=static_cast<std::uint8_t>(index);
            s.y=static_cast<std::uint8_t>(index); s.a=0xA7; s.p=0xFF;
            const bool store=opcode<0xA0;
            const bool indexed_pointer=opcode==0xA1 || opcode==0x81;
            const bool indirect_y=opcode==0xB1 || opcode==0x91;
            const bool indirect=indexed_pointer || indirect_y || opcode==0xB2 || opcode==0x92;
            const bool zp=opcode==0xA5 || opcode==0xA6 || opcode==0xA4 || opcode==0x85 || opcode==0x86 || opcode==0x84 || opcode==0x64;
            const bool zpx=opcode==0xB5 || opcode==0xB4 || opcode==0x95 || opcode==0x94 || opcode==0x74;
            const bool zpy=opcode==0xB6 || opcode==0x96;
            const bool abs_index=opcode==0xBD || opcode==0xB9 || opcode==0xBE || opcode==0xBC || opcode==0x9D || opcode==0x99 || opcode==0x9E;
            unsigned target=zp ? 255:zpx || zpy ? (255+index)%256:0x2FF+(abs_index || indirect_y ? index:0);
            if(indirect) {
                const unsigned pointer=indexed_pointer ? (255+index)%256:255;
                (*bus.bytes)[0x1F0000+pointer]=255;
                (*bus.bytes)[0x1F0000+(pointer+1)%256]=0x22;
            }
            (*bus.bytes)[0x1F0000+target]=0x80;
            auto expected=s;
            expected.pc+=zp || zpx || zpy || indirect ? 2:3; expected.p &= ~pce::T;
            unsigned wanted=0x80;
            if(store) wanted=opcode==0x86 || opcode==0x96 || opcode==0x8E ? index:
                             opcode==0x84 || opcode==0x94 || opcode==0x8C ? index:
                             opcode==0x64 || opcode==0x74 || opcode==0x9C || opcode==0x9E ? 0:s.a;
            else {
                if(opcode==0xA6 || opcode==0xB6 || opcode==0xAE || opcode==0xBE) expected.x=0x80;
                else if(opcode==0xA4 || opcode==0xB4 || opcode==0xAC || opcode==0xBC) expected.y=0x80;
                else expected.a=0x80;
                expected.p=static_cast<std::uint8_t>((expected.p&~2U)|128);
            }
            expected.cycles=indirect ? 7:zp || zpx || zpy ? 4:5; expected.ticks=3*expected.cycles;
            require(execute(bus,s,native)==pce::Exit::executed && state(s)==state(expected),"load/store addressing/flags/cycles mismatch");
            require((*bus.bytes)[0x1F0000+target]==wanted,"load/store wrong memory target");
            ++checks;
        }
    }
    return checks;
}

static void data_boundaries(pce::Bus& bus) {
    const auto forever=std::numeric_limits<std::uint64_t>::max();
    // A source aliased with the T destination must be read before the write.
    for(bool native: {false,true}) {
        pce::Cpu s; s.pc=fixture_pc(0x65); s.x=0xFF; s.a=0x73; s.p=pce::T|pce::D;
        (*bus.bytes)[0x1F00FF]=0x45;
        require(execute(bus,s,native)==pce::Exit::executed && s.a==0x73 && bus.read(s,0x20FF)==0x90 && s.cycles==8,"T source/destination alias");
        // SET is consumed exactly once. PLP can also supply the entry T.
        s=pce::Cpu{}; s.pc=fixture_pc(0xF4); execute(bus,s,native);
        s.pc=fixture_pc(0x05); s.x=0x80; s.a=0x10;
        (*bus.bytes)[0x1F0080]=0x40; (*bus.bytes)[0x1F00FF]=1;
        execute(bus,s,native);
        require(s.a==0x10 && bus.read(s,0x2080)==0x41 && !(s.p&pce::T),"SET did not target memory");
        s.pc=fixture_pc(0x05); execute(bus,s,native);
        require(s.a==0x11 && bus.read(s,0x2080)==0x41,"T persisted beyond one instruction");
        s.pc=fixture_pc(0x28); s.sp=0xFF; (*bus.bytes)[0x1F0100]=pce::T;
        execute(bus,s,native); s.pc=fixture_pc(0x25); execute(bus,s,native);
        require(s.a==0x11 && bus.read(s,0x2080)==1,"PLP-restored T did not target memory");
        // Native guard before stale addressing or arithmetic, then current bytes.
        s=pce::Cpu{}; s.pc=fixture_pc(0xBD); s.x=0x81;
        const auto operand=pce::Bus::physical(s,s.pc+1);
        (*bus.bytes)[operand]=0xFF; (*bus.bytes)[operand+1]=0xFF;
        auto before=s;
        require(pce::generated_step(bus,s,forever)==pce::Exit::miss && state(s)==state(before),"stale absolute operand accepted");
        s.mpr[0]=0xF8; (*bus.bytes)[0x1F0080]=0xC3;
        require(pce::step(bus,s,forever)==pce::Exit::executed && s.a==0xC3,"16-bit absolute index wrap or MPR0 translation wrong");
        initialize(bus);
        // T write to ROM must fault; zero-page operand may still be read from ROM.
        s=pce::Cpu{}; s.pc=fixture_pc(0x65); s.x=0x80; s.p=pce::T;
        bus.kind[0xF8]=pce::BankKind::rom;
        bool fault=false;
        try { execute(bus,s,native); } catch(const pce::Fault&) { fault=true; }
        require(fault && s.cycles==0 && s.pc==fixture_pc(0x65),"T write to ROM retired");
        bus.kind[0xF8]=pce::BankKind::ram;
    }
}
