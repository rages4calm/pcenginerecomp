// Entirely authored register, memory and instruction fixtures.
#include "pce/runtime.hpp"
#include "pce/code_capture.hpp"
#include "arcade_fixture.hpp"
#include <algorithm>
#include <chrono>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <limits>
#include <tuple>

namespace {
std::uint64_t checks=0;
constexpr auto forever=std::numeric_limits<std::uint64_t>::max();
void require(bool okay,const char* message) {++checks;if(!okay)throw pce::Fault(message);}
template<class F>void refuses(F operation) {
    bool fault=false;try{operation();}catch(const pce::Fault&){fault=true;}
    require(fault,"Arcade Card operation should explicitly refuse");
}
auto port_state(const pce::ArcadePort& p) {return std::tuple{p.base,p.offset,p.increment,p.control};}
auto cpu_state(const pce::Cpu& s) {return std::tuple{s.pc,s.a,s.x,s.y,s.sp,s.p,s.mpr,
    s.cycles,s.ticks,s.native_steps,s.interpreter_steps,s.native_block_steps,
    s.interpreter_block_steps,s.block_bytes,s.mpr_latch,s.irq_sampled,s.irq_vector};}
std::uint32_t modulo(std::int64_t value,std::int64_t size) {
    return static_cast<std::uint32_t>((value%size+size)%size);
}
std::vector<std::uint8_t> firmware() {
    std::vector<std::uint8_t> rom(262144);
    rom[8190]=0;rom[8191]=0xE1;return rom;
}
std::unique_ptr<pce::Bus> configured(std::uint8_t fill=0) {
    auto result=std::make_unique<pce::Bus>();
    result->configure_system_card(pce::SystemCardProfile::super,firmware());
    result->configure_arcade_card_duo(fill);return result;
}
pce::Cpu cpu() {pce::Cpu s;s.mpr=arcade_mpr;s.pc=0xE100;return s;}
void setup() {
    auto b=configured(0xA6);
    require(bool(b->arcade_card) && b->arcade_card->ram->size()==2097152,"Duo RAM size differs");
    require(std::all_of(b->arcade_card->ram->begin(),b->arcade_card->ram->end(),[](auto x){return x==0xA6;}),
            "Duo explicit deterministic fill differs");
    for(unsigned bank=0;bank<256;++bank) {
        if(bank>=0x40 && bank<=0x43)
            require(b->kind[bank]==pce::BankKind::io && b->generation[bank]==2,"Duo window configuration differs");
    }
    for(unsigned i=0;i<32768;++i) require(!b->peek(0x80000+i),"Duo source peek treated a port as RAM");
    require(b->arcade_card->reads==0 && b->arcade_card->writes==0,"Pure peeks incremented a port");
    pce::Cpu s;b->power_on_cpu(s);
    require(s.pc==0xE100 && s.mpr==std::array<std::uint8_t,8>{},"Duo displaced reset vector");
    refuses([&]{b->configure_arcade_card_duo();});
    for(unsigned mode=0;mode<6;++mode) {
        auto invalid=std::make_unique<pce::Bus>();
        if(mode)invalid->configure_system_card(mode==1?pce::SystemCardProfile::standard:pce::SystemCardProfile::super,firmware());
        if(mode==2) {pce::Cpu c;invalid->power_on_cpu(c);}
        if(mode==3)invalid->vdc.raster.master_ticks=1;
        if(mode==4)invalid->kind[0x42]=pce::BankKind::ram;
        if(mode==5)invalid->generation[0x43]=forever;
        const auto kinds=invalid->kind;const auto generations=invalid->generation;
        refuses([&]{invalid->configure_arcade_card_duo();});
        require(!invalid->arcade_card && invalid->kind==kinds && invalid->generation==generations,
                "Failed Duo setup partly modified the bus");
    }
    auto dirty=std::make_unique<pce::Bus>();dirty->arcade_card=std::make_unique<pce::ArcadeCard>();
    refuses([&]{dirty->configure_system_card(pce::SystemCardProfile::super,firmware());});
    refuses([&]{dirty->configure_hucard(std::vector<std::uint8_t>(8192));});
    const std::array<std::uint8_t,4> bytes{1,2,3,4};
    const auto gen=b->generation;const auto before=(*b->bytes)[0x7FFFE];
    refuses([&]{b->load(0x7FFFE,bytes.data(),bytes.size());});
    refuses([&]{b->load(0x87FFE,bytes.data(),bytes.size());});
    require(b->generation==gen && (*b->bytes)[0x7FFFE]==before && b->arcade_card->writes==0,
            "Refused loader write changed data, generations or ports");
    b->load(0x80000,bytes.data(),0);
    auto ordinary=std::make_unique<pce::Bus>();ordinary->configure_system_card(pce::SystemCardProfile::super,firmware());
    require(ordinary->kind[0x40]==pce::BankKind::rom && ordinary->peek(0x80000)==0,"Disabled expansion changed base ROM map");
}
void data_ports() {
    auto owner=std::make_unique<pce::ArcadeCard>();auto& a=*owner;
    for(unsigned port=0;port<4;++port)for(unsigned control=0;control<128;++control)
    for(unsigned base:{0u,0x1FFFFFu,0xFFFFFFu,0x100000u})
    for(unsigned offset:{0u,1u,0x7FFFu,0x8000u,0xFFFFu})
    for(unsigned increment:{0u,1u,0x7FFFu,0x8000u,0xFFFFu}) {
        const auto address=modulo(std::int64_t(base)+(control&2 ? std::int64_t(offset)-(control&8?65536:0):0),2097152);
        const auto next_base=(control&1) && (control&16) ? (base+increment)%16777216:base;
        const auto next_offset=(control&1) && !(control&16) ? (offset+increment)%65536:offset;
        a.ports[port]={base,static_cast<std::uint16_t>(offset),static_cast<std::uint16_t>(increment),static_cast<std::uint8_t>(control)};
        (*a.ram)[address]=static_cast<std::uint8_t>(port+0x51);
        require(a.effective_address(port)==address,"Duo effective address differs from signed range arithmetic");
        require(a.read_data(port)==port+0x51,"Duo read used incremented address");
        require(a.ports[port].base==next_base && a.ports[port].offset==next_offset,"Duo read increment target/wrap differs");
        a.ports[port]={base,static_cast<std::uint16_t>(offset),static_cast<std::uint16_t>(increment),static_cast<std::uint8_t>(control)};
        a.write_data(port,0xA3);
        require((*a.ram)[address]==0xA3,"Duo write used incremented address");
        require(a.ports[port].base==next_base && a.ports[port].offset==next_offset,"Duo write increment target/wrap differs");
    }
    refuses([&]{a.read_data(4);});refuses([&]{a.write_data(4,0);});
    refuses([&]{a.effective_address(4);});refuses([&]{a.read_register(0x19FF);});
    refuses([&]{a.write_register(0x1C00,0);});
}
void register_bytes() {
    auto owner=std::make_unique<pce::ArcadeCard>();auto& a=*owner;
    for(unsigned p=0;p<4;++p) a.ports[p]={0xABCDEFu+p*0x111111u,0x1357,0x2468,0x54};
    for(unsigned p=0;p<4;++p)(*a.ram)[a.effective_address(p)]=static_cast<std::uint8_t>(0x90+p);
    a.shift_register=0x89ABCDEF;a.shift_amount=13;a.rotate_amount=3;
    for(unsigned offset=0;offset<256;++offset) {
        unsigned wanted=255;
        if(offset<128) {
            const auto p=(offset/16)%4,index=offset%16;
            constexpr unsigned low[]{0x57,0x13,0x68,0x24,0x54,0};
            if(index<2)wanted=0x90+p;
            else if(index<5)wanted=(a.ports[p].base>>(8*(index-2)))&255;
            else if(index<=10)wanted=low[index-5];
        } else if(offset>=224) {
            const auto index=offset-224;
            if(index<4)wanted=(0x89ABCDEFu>>(index*8))&255;
            if(index==4)wanted=13;if(index==5)wanted=3;
            if(index==28 || index==29)wanted=0;
            if(index==30)wanted=0x10;if(index==31)wanted=0x51;
        }
        require(a.read_register(static_cast<std::uint16_t>(0x1A00+offset))==wanted,"Duo register/mirror/pullup read differs");
    }
    require(a.reads==256,"Duo register data aliases counted twice");
    for(unsigned p=0;p<4;++p)for(unsigned mirror:{0u,64u})for(unsigned value=0;value<256;++value) {
        const auto prefix=0x1A00+p*16+mirror;
        a.write_register(static_cast<std::uint16_t>(prefix+9),static_cast<std::uint8_t>(value));
        require(a.read_register(static_cast<std::uint16_t>(prefix+9))==(value&127),"Duo control masked wrong bits");
        for(unsigned byte=0;byte<3;++byte) {
            a.ports[p].base=0xABCDEF;
            const unsigned divisor=1u<<(byte*8);
            const auto expected=0xABCDEFu-((0xABCDEFu/divisor)%256)*divisor+value*divisor;
            a.write_register(static_cast<std::uint16_t>(prefix+2+byte),static_cast<std::uint8_t>(value));
            require(a.ports[p].base==expected,"Duo base-byte replacement differs");
        }
    }
    for(unsigned p=0;p<4;++p)for(unsigned control=0;control<128;++control)
    for(unsigned old_offset:{0u,0x7FFFu,0x8000u,0xFFFFu})for(unsigned value=0;value<256;++value)
    for(unsigned target=0;target<3;++target) {
        a.ports[p]={2,static_cast<std::uint16_t>(old_offset),7,static_cast<std::uint8_t>(control)};
        const auto next_offset=target==0 ? (old_offset/256)*256+value:target==1 ? old_offset%256+value*256:old_offset;
        const auto triggered=((control/32)%4)==target+1;
        const auto base=triggered ? modulo(2+std::int64_t(next_offset)-(control&8?65536:0),16777216):2u;
        a.write_register(static_cast<std::uint16_t>(0x1A00+p*16+(target==2?10:5+target)),static_cast<std::uint8_t>(value));
        require(a.ports[p].offset==next_offset && a.ports[p].base==base,"Duo offset trigger timing/range differs");
        const auto snapshot=port_state(a.ports[p]);
        require(a.read_register(static_cast<std::uint16_t>(0x1A00+p*16+10))==0 && port_state(a.ports[p])==snapshot,
                "Duo trigger read changed a pointer");
    }
}
void shifter() {
    auto owner=std::make_unique<pce::ArcadeCard>();auto& a=*owner;
    for(unsigned value:{0u,1u,0x80000000u,0xFFFFFFFFu,0x12345678u,0x89ABCDEFu})
    for(unsigned raw=0;raw<256;++raw)for(unsigned rotate=0;rotate<2;++rotate) {
        const auto amount=raw%16;const int distance=amount<8?int(amount):int(amount)-16;
        std::uint32_t wanted=0;
        for(int bit=0;bit<32;++bit)if(value&(std::uint32_t(1)<<bit)) {
            const auto destination=bit+distance;
            if(rotate)wanted|=std::uint32_t(1)<<((destination+32)%32);
            else if(destination>=0 && destination<32)wanted|=std::uint32_t(1)<<destination;
        }
        a.shift_register=value;
        a.write_register(static_cast<std::uint16_t>(0x1AE4+rotate),static_cast<std::uint8_t>(raw));
        require(a.shift_register==wanted,"Duo shift/rotate differs from independent bit positions");
        require(a.read_register(static_cast<std::uint16_t>(0x1AE4+rotate))==amount,"Duo shift amount mask/readback differs");
    }
    for(unsigned byte=0;byte<4;++byte)for(unsigned value=0;value<256;++value) {
        a.shift_register=0x89ABCDEF;
        const std::uint64_t divisor=std::uint64_t(1)<<(byte*8);
        const auto expected=0x89ABCDEFu-((0x89ABCDEFu/divisor)%256)*divisor+value*divisor;
        a.write_register(static_cast<std::uint16_t>(0x1AE0+byte),static_cast<std::uint8_t>(value));
        require(a.shift_register==expected,"Duo shift register byte replacement differs");
    }
    const auto words=a.shift_register;const auto ports=a.ports;
    const auto shift=a.shift_amount,rotate=a.rotate_amount;
    for(unsigned offset=0;offset<256;++offset) {
        const auto index=offset%16;
        const bool unused=offset<128 ? index>=11:offset<224 || offset>=230;
        if(unused)for(unsigned value=0;value<256;++value)
            a.write_register(static_cast<std::uint16_t>(0x1A00+offset),static_cast<std::uint8_t>(value));
    }
    require(a.shift_register==words && a.shift_amount==shift && a.rotate_amount==rotate,"Reserved writes changed shifter state");
    for(unsigned i=0;i<4;++i)require(port_state(a.ports[i])==port_state(ports[i]),"Reserved writes changed port state");
}
void bus_decode() {
    auto b=configured();auto& a=*b->arcade_card;auto s=cpu();b->io_latch=0xD4;
    for(unsigned p=0;p<4;++p) {
        a.ports[p].base=p*32;
        for(unsigned offset=0;offset<8192;++offset) {
            const auto logical=static_cast<std::uint16_t>((p+2)*8192+offset);
            b->write(s,logical,static_cast<std::uint8_t>(offset));
            require((*a.ram)[p*32]==static_cast<std::uint8_t>(offset),"Duo window offset did not select its port");
            require(b->read(s,logical)==static_cast<std::uint8_t>(offset),"Duo window offset read an addressable RAM alias");
        }
    }
    require(a.reads==32768 && a.writes==32768 && s.cycles==0 && s.ticks==0,
            "Duo data-window access added a CPU wait or counted incorrectly");
    require(b->io_latch==0xD4 && b->cd.reads==0 && b->cd.writes==0,"Duo data windows polled unrelated I/O");
    a.shift_register=0x11;
    constexpr unsigned offsets[]{0x1A7F,0x1A80,0x1ADF,0x1AE0,0x1AFF,0x1B00,0x1BFF};
    constexpr unsigned wanted[]{255,255,255,0x11,0x51,255,255};
    for(unsigned i=0;i<std::size(offsets);++i)
        require(b->read(s,static_cast<std::uint16_t>(offsets[i]))==wanted[i],"Duo upper I/O decode boundary differs");
    const auto saved=a.ports;
    for(auto offset:{0x1A7F,0x1A80,0x1ADF,0x1AFF,0x1B00,0x1BFF})b->write(s,static_cast<std::uint16_t>(offset),0xFF);
    require(a.shift_register==0x11 && b->io_latch==0xD4,"Duo unused I/O writes changed device or bus latch");
    for(unsigned i=0;i<4;++i)require(port_state(a.ports[i])==port_state(saved[i]),"Duo unused I/O writes changed port configuration");
    const auto reads=a.reads,writes=a.writes;
    refuses([&]{b->read(s,0x1C00);});refuses([&]{b->write(s,0x1C00,0);});
    require(a.reads==reads && a.writes==writes,"Duo intercepted outside the CD upper half");
    auto ordinary=std::make_unique<pce::Bus>();ordinary->configure_system_card(pce::SystemCardProfile::super,firmware());
    ordinary->enable_cd_control();
    require(ordinary->read(s,0x1BFF)==255,"Disabled expansion changed pull-ups");
    refuses([&]{ordinary->write(s,0x1BFF,0);});
    require(!ordinary->arcade_card,"Disabled expansion silently enabled itself");
}
pce::Exit execute(pce::Bus& b,pce::Cpu& s,bool native,std::uint64_t deadline=forever) {
    return native?pce::generated_step(b,s,deadline):pce::interpret_step(b,s,deadline);
}
template<std::size_t N>void operation(pce::Bus& b,pce::Cpu& s,unsigned pc,const std::array<std::uint8_t,N>& bytes) {
    b.load(pce::Bus::physical(s,static_cast<std::uint16_t>(pc)),bytes.data(),N);s.pc=static_cast<std::uint16_t>(pc);
}
void execution() {
    for(bool native:{false,true})for(unsigned divisor:{3u,12u}) {
        auto b=configured();auto& a=*b->arcade_card;auto s=cpu();s.clock_divisor=divisor;
        b->enable_interrupts();b->io_latch=0xAD;
        for(unsigned p=0;p<4;++p) {a.ports[p].base=p*128;a.ports[p].control=0x11;a.ports[p].increment=1;}
        (*a.ram)[0]=0xA7;operation(*b,s,arcade_pc_0,arcade_op_0);
        require(execute(*b,s,native)==pce::Exit::executed && s.a==0xA7 && a.ports[0].base==1,"Translated window read failed");
        operation(*b,s,arcade_pc_1,arcade_op_1);s.a=0xB9;
        require(execute(*b,s,native)==pce::Exit::executed && (*a.ram)[128]==0xB9 && a.ports[1].base==129,"Translated window write failed");
        (*a.ram)[256]=0xC8;operation(*b,s,arcade_pc_2,arcade_op_2);
        require(execute(*b,s,native)==pce::Exit::executed && s.a==0xC8 && a.ports[2].base==257,"Translated hardware read failed");
        operation(*b,s,arcade_pc_3,arcade_op_3);s.a=0xD6;
        require(execute(*b,s,native)==pce::Exit::executed && (*a.ram)[384]==0xD6 && a.ports[3].base==385,"Translated hardware write failed");
        operation(*b,s,arcade_pc_4,arcade_op_4);
        require(execute(*b,s,native)==pce::Exit::executed && s.a==0x10,"Translated Duo detection failed");
        a.shift_register=0x12345678;operation(*b,s,arcade_pc_5,arcade_op_5);s.a=3;
        require(execute(*b,s,native)==pce::Exit::executed && a.shift_register==0x91A2B3C0,"Translated shifter write failed");
        operation(*b,s,arcade_pc_6,arcade_op_6);
        require(execute(*b,s,native)==pce::Exit::executed && s.a==0xC0,"Translated shifter read failed");
        a.ports[0]={0,0,1,0x11};(*a.ram)[0]=0x7F;(*a.ram)[1]=0;
        operation(*b,s,arcade_pc_7,arcade_op_7);
        require(execute(*b,s,native)==pce::Exit::executed && (*a.ram)[0]==0x7F && (*a.ram)[1]==0x80 && a.ports[0].base==2,
                "RMW did not perform separate incrementing read and write");
        a.ports[0]={0x1FFFF8,0,1,0x11};
        for(unsigned i=0;i<16;++i)(*b->bytes)[0x1F0000+i]=static_cast<std::uint8_t>(0x80+i);
        operation(*b,s,arcade_pc_8,arcade_op_8);
        require(execute(*b,s,native)==pce::Exit::executed,"Block copy to Arcade window failed");
        for(unsigned i=0;i<16;++i)require((*a.ram)[(0x1FFFF8+i)%2097152]==0x80+i,"Arcade block payload/wrap failed");
        a.ports[1]={0x1FFFF8,0,1,0x11};operation(*b,s,arcade_pc_9,arcade_op_9);
        require(execute(*b,s,native)==pce::Exit::executed,"Block read from Arcade window failed");
        for(unsigned i=0;i<16;++i)require(b->peek(0x1F0200+i)==0x80+i,"Arcade block read payload failed");
        require(a.ports[0].base==0x200008 && a.ports[1].base==0x200008,"Block pointers did not retain24bit base");
        require(b->io_latch==0xAD && b->cd.reads==0 && b->cd.writes==0,"Arcade accesses changed unrelated latches/counters");
        operation(*b,s,arcade_pc_0,arcade_op_0);const auto before=cpu_state(s);const auto port=port_state(a.ports[0]);
        const auto reads=a.reads,writes=a.writes;
        require(execute(*b,s,native,0)==pce::Exit::budget && cpu_state(s)==before && port_state(a.ports[0])==port && a.reads==reads && a.writes==writes,
                "Arcade deadline refusal changed state");
        if(native) {
            s.pc=0x4000;const auto state=cpu_state(s);const auto saved=a.ports;
            require(execute(*b,s,true)==pce::Exit::miss && cpu_state(s)==state && a.reads==reads && a.writes==writes,
                    "Native instruction source read an Arcade data window");
            for(unsigned i=0;i<4;++i)require(port_state(a.ports[i])==port_state(saved[i]),"Native source miss advanced a port");
        }
    }
}
void live_fetch_and_capture() {
    auto b=configured();auto& a=*b->arcade_card;auto s=cpu();s.pc=0x4000;
    a.ports[0]={0,0,1,3};(*a.ram)[0]=0xA9;(*a.ram)[1]=0x5A;
    const auto base=std::filesystem::temp_directory_path();
    const auto folder=base/("pce-arcade-capture-"+std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
    require(std::filesystem::create_directory(folder),"Capture fixture directory already exists");
    const auto path=folder/"capture.json";
    {
        pce::CodeCapture capture(path,16);
        const auto pending=capture.before(*b,s);const auto before=cpu_state(s);
        require(!pending.readable && a.reads==0 && a.ports[0].offset==0,"Capture tried to peek an Arcade instruction");
        require(execute(*b,s,true)==pce::Exit::miss && cpu_state(s)==before && a.reads==0,"Native guard touched port instruction bytes");
        require(execute(*b,s,false)==pce::Exit::executed && s.a==0x5A && s.pc==0x4002 && a.ports[0].offset==2 && a.reads==2,
                "Interpreted instruction fetch did not consume live port bytes");
        capture.after(pending,s);capture.finish();
    }
    std::ifstream file(path);const std::string text((std::istreambuf_iterator<char>(file)),{});file.close();
    require(text.find("\"unreadable_instructions\":1")!=std::string::npos &&
            text.find("\"complete\":false")!=std::string::npos && text.find("\"observations\":[]")!=std::string::npos,
            "Port-source capture fabricated a stationary instruction identity");
    std::filesystem::remove(path);std::filesystem::remove(folder);
    s=cpu();s.pc=0x3FFF;a.ports[0]={0,0,1,3};(*a.ram)[0]=0x7B;
    (*b->bytes)[0x1F1FFF]=0xA9;const auto before=cpu_state(s);const auto reads=a.reads;
    require(execute(*b,s,true)==pce::Exit::miss && cpu_state(s)==before && a.reads==reads,"Native crossing fetch read a port operand");
    require(execute(*b,s,false)==pce::Exit::executed && s.a==0x7B && s.pc==0x4001 && a.ports[0].offset==1,
            "Interpreter crossing operand did not consume live data");
}
}
int main() {
    try {setup();data_ports();register_bytes();shifter();bus_decode();execution();live_fetch_and_capture();
        std::cout<<"Arcade Card Duo: "<<checks<<" authored expectations passed\n";
    }catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
}
