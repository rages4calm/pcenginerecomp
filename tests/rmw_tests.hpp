// Independent expected values, separate from production operation bodies.
#pragma once

struct RmwCase { unsigned op, operation, size; bool indexed; };
inline constexpr RmwCase rmw_cases[]={
    {0x0A,0,1,false},{0x06,0,2,false},{0x16,0,2,true},{0x0E,0,3,false},{0x1E,0,3,true},
    {0x2A,1,1,false},{0x26,1,2,false},{0x36,1,2,true},{0x2E,1,3,false},{0x3E,1,3,true},
    {0x4A,2,1,false},{0x46,2,2,false},{0x56,2,2,true},{0x4E,2,3,false},{0x5E,2,3,true},
    {0x6A,3,1,false},{0x66,3,2,false},{0x76,3,2,true},{0x6E,3,3,false},{0x7E,3,3,true},
    {0x1A,4,1,false},{0xE6,4,2,false},{0xF6,4,2,true},{0xEE,4,3,false},{0xFE,4,3,true},
    {0x3A,5,1,false},{0xC6,5,2,false},{0xD6,5,2,true},{0xCE,5,3,false},{0xDE,5,3,true}
};

static unsigned rmw_expectations(pce::Bus& bus) {
    unsigned checks=0;
    for(auto test: rmw_cases) for(unsigned value=0; value<256; ++value) {
        for(unsigned flags=0; flags<256; ++flags) {
            const unsigned carry=flags%2;
            unsigned result, next_carry=carry;
            switch(test.operation) {
            case 0: result=value*2; next_carry=value>=128; break;
            case 1: result=value*2+carry; next_carry=result>=256; break;
            case 2: result=value/2; next_carry=value%2; break;
            case 3: result=(value+carry*256)/2; next_carry=value%2; break;
            case 4: result=value+1; break;
            default: result=value+255; break;
            }
            result%=256;
            const unsigned wanted_p=(flags&~0xA3U)|next_carry|(result==0 ? 2:0)|(result>=128 ? 128:0);
            for(bool native: {false,true}) {
                pce::Cpu s; s.pc=fixture_pc(test.op); s.p=static_cast<std::uint8_t>(flags);
                s.a=static_cast<std::uint8_t>(test.size==1 ? value:value^0x5A);
                s.x=static_cast<std::uint8_t>((flags&3)==0 ? 0:(flags&3)==1 ? 1:(flags&3)==2 ? 0xE0:0xFF);
                s.y=0xA6; s.sp=0x73; s.clock_divisor=flags&4 ? 12:3;
                const unsigned index=test.indexed ? s.x:0;
                const unsigned offset=test.size==2 ? (255+index)%256:0x2FF+index;
                const auto pa=0x1F0000+offset;
                (*bus.bytes)[pa]=static_cast<std::uint8_t>(value);
                (*bus.bytes)[pa-1]=0x5A; (*bus.bytes)[pa+1]=0xA5;
                const auto t_dest=0x1F0000U+s.x;
                if(t_dest!=pa) (*bus.bytes)[t_dest]=0x69;
                auto expected=s;
                expected.pc+=test.size; expected.p=static_cast<std::uint8_t>(wanted_p);
                if(test.size==1) expected.a=static_cast<std::uint8_t>(result);
                expected.cycles=test.size==1 ? 2:test.size==2 ? 6:7;
                expected.ticks=expected.cycles*s.clock_divisor;
                const auto generation=bus.generation[0xF8];
                require(execute(bus,s,native)==pce::Exit::executed && state(s)==state(expected),"RMW byte/flags/registers/PC/cycles mismatch");
                require((*bus.bytes)[pa]==(test.size==1 ? value:result),"RMW memory result mismatch");
                if(t_dest!=pa) require((*bus.bytes)[t_dest]==0x69,"RMW incorrectly used a T destination");
                // The T sentinel can coincide with a neighboring byte.
                require((*bus.bytes)[pa-1]==(t_dest==pa-1 ? 0x69:0x5A) &&
                        (*bus.bytes)[pa+1]==(t_dest==pa+1 ? 0x69:0xA5),"RMW wrote neighboring memory");
                require(bus.generation[0xF8]==generation+(test.size!=1 && result!=value),"RMW generation mismatch");
                ++checks;
            }
        }
    }
    return checks;
}

static unsigned jump_expectations(pce::Bus& bus) {
    unsigned checks=0;
    for(unsigned op: {0x6CU,0x7CU}) for(unsigned flags=0; flags<256; ++flags) {
        for(unsigned index: {0U,1U,0xE0U,0xFFU}) for(unsigned target: {0U,0x20FFU,0x8000U,0xFFFFU}) {
            for(bool native: {false,true}) {
                pce::Cpu s; s.pc=fixture_pc(op); s.p=static_cast<std::uint8_t>(flags);
                s.a=0xD7; s.x=static_cast<std::uint8_t>(index); s.y=0xA5; s.sp=0x71;
                s.clock_divisor=index&1 ? 12:3;
                const unsigned pointer=0x2FF+(op==0x7C ? index:0);
                (*bus.bytes)[0x1F0000+pointer]=static_cast<std::uint8_t>(target);
                (*bus.bytes)[0x1F0000+pointer+1]=static_cast<std::uint8_t>(target>>8);
                // Wrong NMOS-style page wrapping must produce a different high byte.
                if((pointer&255)==255) (*bus.bytes)[0x1F0000+(pointer&~255U)]=static_cast<std::uint8_t>((target>>8)^0x5A);
                auto expected=s; expected.pc=static_cast<std::uint16_t>(target); expected.p &= ~pce::T;
                expected.cycles=7; expected.ticks=7*s.clock_divisor;
                const auto generations=bus.generation;
                require(execute(bus,s,native)==pce::Exit::executed && state(s)==state(expected) && bus.generation==generations,"indirect JMP target/flags/page crossing/cycles mismatch");
                ++checks;
            }
        }
    }
    return checks;
}

static void rmw_jump_boundaries(pce::Bus& bus) {
    const auto forever=std::numeric_limits<std::uint64_t>::max();
    // Extra native sites keep literal boundary operands source guarded. Map
    // explicit sandbox banks without altering the expected MPR dispatch key.
    bus.kind[0]=bus.kind[0xFF]=pce::BankKind::ram;
    for(auto edge: edges) for(unsigned index: {0U,1U,0x21U,0xFFU}) for(bool native: {false,true}) {
        initialize(bus); bus.kind[0xFF]=pce::BankKind::ram;
        pce::Cpu s; s.pc=edge.pc; s.x=static_cast<std::uint8_t>(index); s.p=0xFF; s.a=0x91;
        const bool jump=edge.op==0x6C || edge.op==0x7C;
        const auto address=static_cast<std::uint16_t>(edge.word+(edge.op==0x6C ? 0:index));
        const auto high_address=static_cast<std::uint16_t>(address+1);
        (*bus.bytes)[pce::Bus::physical(s,address)]=jump ? 0xAB:0x81;
        if(jump) (*bus.bytes)[pce::Bus::physical(s,high_address)]=0xE3;
        require(execute(bus,s,native)==pce::Exit::executed,"native address/MMU boundary failed");
        if(jump) require(s.pc==0xE3AB && s.p==0xDF && s.cycles==7,"JMP MMU/FFFF/index wrap mismatch");
        else {
            const unsigned wanted=edge.op==0x1E ? 2:edge.op==0x7E ? 0xC0:edge.op==0xDE ? 0x80:0x82;
            require(bus.read(s,address)==wanted && s.a==0x91 && !(s.p&pce::T) && s.cycles==7,"indexed RMW FFFF wrap mismatch");
        }
    }
    bus.kind[0]=pce::BankKind::unmapped; initialize(bus);
    for(bool native: {false,true}) {
        // Pointer bytes remain live data: changing them changes the target
        // without regenerating the instruction or weakening its source guard.
        pce::Cpu s; s.pc=fixture_pc(0x6C);
        (*bus.bytes)[0x1F02FF]=0x34; (*bus.bytes)[0x1F0300]=0x12;
        execute(bus,s,native); require(s.pc==0x1234,"first dynamic JMP pointer");
        s.pc=fixture_pc(0x6C); (*bus.bytes)[0x1F0300]=0xAB;
        execute(bus,s,native); require(s.pc==0xAB34,"native JMP folded mutable pointer data");
        // Source operand mutation must miss before touching memory or flags.
        s=pce::Cpu{}; s.pc=fixture_pc(0x16); s.x=1; s.p=0xFF;
        auto operand=pce::Bus::physical(s,s.pc+1); (*bus.bytes)[operand]=0x10;
        auto before=s; auto generations=bus.generation;
        require(pce::generated_step(bus,s,forever)==pce::Exit::miss && state(s)==state(before) && bus.generation==generations,"RMW stale operand guard");
        (*bus.bytes)[0x1F0011]=0x80;
        require(pce::step(bus,s,forever)==pce::Exit::executed && bus.read(s,0x2011)==0,"RMW mutated operand fallback");
        initialize(bus);
        for(auto kind: {pce::BankKind::rom,pce::BankKind::io,pce::BankKind::unmapped}) {
            s=pce::Cpu{}; s.pc=fixture_pc(0xE6); s.p=0xFF;
            bus.kind[0xF8]=kind; bool fault=false;
            try { execute(bus,s,native); } catch(const pce::Fault&) { fault=true; }
            require(fault && s.pc==fixture_pc(0xE6) && s.cycles==0,"RMW fault retired");
            bus.kind[0xF8]=pce::BankKind::ram;
        }
        // A successful low pointer read cannot fabricate a missing high byte.
        s=pce::Cpu{}; s.pc=edges[1].pc; bus.kind[0]=pce::BankKind::ram;
        (*bus.bytes)[0x1FFF]=0xAB; bool fault=false;
        try { execute(bus,s,native); }
        catch(const pce::Fault& error) { fault=std::string(error.what()).ends_with("logical 0"); }
        require(fault && s.pc==edges[1].pc && s.cycles==0,"JMP missing high pointer byte retired or failed to wrap");
        bus.kind[0]=pce::BankKind::unmapped;
    }
    initialize(bus);
}
