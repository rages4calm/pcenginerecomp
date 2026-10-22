// HuC6280 expectations, not the superficially similar 65C02 flag rules.
#pragma once
struct BitTestCase { unsigned op, kind, mode; };
inline constexpr BitTestCase bit_test_cases[]={
    {0x89,0,0},{0x24,0,1},{0x34,0,2},{0x2C,0,3},{0x3C,0,4},
    {0x04,1,1},{0x0C,1,3},{0x14,2,1},{0x1C,2,3},
    {0x83,3,1},{0xA3,3,2},{0x93,3,3},{0xB3,3,4}
};
static unsigned test_bit_expectations(pce::Bus& bus) {
    unsigned checks=0;
    for(auto test:bit_test_cases) {
        for(unsigned a=0; a<(test.kind==3 ? 1U:256U); ++a) for(unsigned byte=0; byte<256; ++byte) {
            if(test.mode==0 && byte!=0x20) continue;
            const bool full_flags=test.kind==3 || test.mode==0;
            for(unsigned f=0; f<(full_flags ? 256U:4U); ++f) {
                const unsigned flags=full_flags ? f:f==0 ? 0:f==1 ? 255:f==2 ? 0x55:0xAA;
                const unsigned mask=test.kind==3 ? 0x55:a;
                const unsigned result=test.kind==1 ? (byte|a):test.kind==2 ? (byte&(255-a)):(byte&mask);
                const unsigned wanted_p=(flags&~0xE2U)|(byte&0xC0)|(result==0 ? 2:0);
                for(bool native:{false,true}) {
                    pce::Cpu s; s.pc=fixture_pc(test.op); s.a=static_cast<std::uint8_t>(test.kind==3 ? byte^255:a);
                    s.x=static_cast<std::uint8_t>((flags&3)==0 ? 0:(flags&3)==1 ? 1:(flags&3)==2 ? 0xE0:255);
                    s.y=0x93; s.sp=0xFE; s.p=static_cast<std::uint8_t>(flags); s.clock_divisor=flags&4 ? 12:3;
                    const unsigned index=test.mode==2 || test.mode==4 ? s.x:0;
                    const auto offset=test.mode<=2 ? (255+index)%256:0x2FF+index;
                    const auto pa=0x1F0000U+offset;
                    (*bus.bytes)[pa]=static_cast<std::uint8_t>(byte);
                    (*bus.bytes)[pa-1]=0x19; (*bus.bytes)[pa+1]=0xE7;
                    auto expected=s; expected.p=static_cast<std::uint8_t>(wanted_p);
                    expected.pc+=test.kind==3 ? (test.mode<=2 ? 3:4):test.mode==0 ? 2:test.mode<=2 ? 2:3;
                    expected.cycles=test.kind==3 ? (test.mode<=2 ? 7:8):test.mode==0 ? 2:(test.mode<=2 ? 4:5)+(test.kind==1 || test.kind==2 ? 2:0);
                    expected.ticks=expected.cycles*s.clock_divisor;
                    const auto generation=bus.generation[0xF8];
                    const bool write=test.kind==1 || test.kind==2;
                    require(execute(bus,s,native)==pce::Exit::executed && state(s)==state(expected),"BIT/TSB/TRB/TST flags/registers/address/length/cycles mismatch");
                    require((*bus.bytes)[pa]==(write ? result:byte) && (*bus.bytes)[pa-1]==0x19 && (*bus.bytes)[pa+1]==0xE7,"bit-test memory footprint mismatch");
                    require(bus.generation[0xF8]==generation+(write && result!=byte),"bit-test generation mismatch");
                    ++checks;
                }
            }
        }
    }
    return checks;
}
static unsigned bit_branch_bsr_expectations(pce::Bus& bus) {
    unsigned checks=0;
    for(unsigned op=15; op<256; op+=16) for(unsigned byte=0; byte<256; ++byte) {
        for(unsigned flags=0; flags<256; ++flags) for(bool native:{false,true}) {
            pce::Cpu s; s.pc=fixture_pc(op); s.a=0x91; s.x=0xF3; s.y=0xAE; s.sp=0;
            s.p=static_cast<std::uint8_t>(flags); s.clock_divisor=flags&1 ? 12:3;
            (*bus.bytes)[0x1F00FF]=static_cast<std::uint8_t>(byte);
            const bool take=bool(byte&(1U<<((op/16)%8)))==(op>=128);
            auto expected=s; expected.pc=static_cast<std::uint16_t>(s.pc+(take ? 0:3));
            expected.p &= ~pce::T; expected.cycles=take ? 8:6; expected.ticks=expected.cycles*s.clock_divisor;
            const auto generations=bus.generation;
            require(execute(bus,s,native)==pce::Exit::executed && state(s)==state(expected) && generations==bus.generation,"BBR/BBS target/flags/PC/cycles mismatch");
            ++checks;
        }
    }
    for(unsigned sp=0; sp<256; ++sp) for(unsigned flags=0; flags<256; ++flags) for(bool native:{false,true}) {
        pce::Cpu s; s.pc=fixture_pc(0x44); s.sp=static_cast<std::uint8_t>(sp); s.p=static_cast<std::uint8_t>(flags);
        s.a=0x8F; s.x=0x73; s.y=0xA1; s.clock_divisor=flags&1 ? 12:3;
        auto expected=s; expected.p &= ~pce::T; expected.sp=static_cast<std::uint8_t>(sp-2);
        expected.cycles=8; expected.ticks=8*s.clock_divisor;
        const unsigned saved=s.pc+1;
        require(execute(bus,s,native)==pce::Exit::executed && state(s)==state(expected),"BSR stack/flags/target/cycles mismatch");
        require(bus.read(s,0x2100|sp)==(saved>>8) && bus.read(s,0x2100|((sp+255)%256))==(saved&255),"BSR return address/order/wrap mismatch");
        ++checks;
    }
    return checks;
}
static void bit_test_boundaries(pce::Bus& bus) {
    const auto forever=std::numeric_limits<std::uint64_t>::max();
    for(bool native:{false,true}) {
        pce::Cpu s; s.pc=fixture_pc(0xB3); s.x=1; s.a=0; s.p=0xFF;
        auto mask=pce::Bus::physical(s,s.pc+1); (*bus.bytes)[mask]=0xAA;
        auto before=s;
        require(pce::generated_step(bus,s,forever)==pce::Exit::miss && state(s)==state(before),"TST stale mask guard");
        (*bus.bytes)[0x1F0300]=0x80;
        require(pce::step(bus,s,forever)==pce::Exit::executed && s.p==0x9D,"TST mutated mask fallback");
        initialize(bus);
        for(auto kind:{pce::BankKind::rom,pce::BankKind::io,pce::BankKind::unmapped}) {
            s=pce::Cpu{}; s.pc=fixture_pc(0x04); bus.kind[0xF8]=kind;
            bool fault=false;
            try { execute(bus,s,native); } catch(const pce::Fault&) { fault=true; }
            require(fault && s.pc==fixture_pc(0x04) && s.cycles==0,"TSB fault retired");
            bus.kind[0xF8]=pce::BankKind::ram;
        }
    }
    // Signed branch and fetch wrap in the interpreter, across logical FFFF.
    bus.kind[0]=bus.kind[0xFF]=pce::BankKind::ram;
    pce::Cpu s; s.pc=0xFFFE; const unsigned char data[]={0x0F,0xFF,0x80};
    for(unsigned i=0;i<3;++i) (*bus.bytes)[pce::Bus::physical(s,static_cast<std::uint16_t>(s.pc+i))]=data[i];
    (*bus.bytes)[0x1F00FF]=0;
    require(pce::interpret_step(bus,s,forever)==pce::Exit::executed && s.pc==0xFF81 && s.cycles==8,"BBR signed PC/fetch wrap");
    // BSR saves the wrapped operand address, so RTS returns to logical 0001.
    s=pce::Cpu{}; s.pc=0xFFFF; s.sp=0;
    (*bus.bytes)[0x1FFF]=0x44; (*bus.bytes)[0x1FE000]=0x80;
    require(pce::interpret_step(bus,s,forever)==pce::Exit::executed && s.pc==0xFF81 && s.sp==0xFE && bus.read(s,0x2100)==0 && bus.read(s,0x21FF)==0,"BSR fetch/target/stack wrap");
    bus.kind[0]=pce::BankKind::unmapped; initialize(bus);
}
