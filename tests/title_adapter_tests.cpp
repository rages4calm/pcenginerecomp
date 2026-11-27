// Authored engine fixtures. No retail input, device clocks or guest work is
// manufactured by an adapter; the test explicitly simulates one retirement.
#include "pce/title_adapter.hpp"
#include "pce/checkpoint.hpp"
#include <algorithm>
#include <iostream>
#include <memory>
#include <stdexcept>

namespace {
unsigned checks=0;
void require(bool good,const char* why){++checks;if(!good)throw std::runtime_error(why);}
template<class F>void refuses(F f,const char* why){bool caught=false;try{f();}catch(const std::exception&){caught=true;}require(caught,why);}
struct Fixture {
    pce::Bus bus;pce::Cpu cpu;
    Fixture(){bus.kind[0x80]=pce::BankKind::rom;bus.kind[0xF8]=pce::BankKind::ram;
        (*bus.bytes)[0x100000]=0xA9;(*bus.bytes)[0x100001]=3;
        (*bus.bytes)[0x1F0010]=100;(*bus.bytes)[0x1F0020]=7;cpu.pc=0x4000;}
};
void reward(pce::TitleAdapterContext& c) {
    if(c.event().name!="earned"||c.source().pc!=0x4000||c.source().physical[0]!=0x100000||
       c.before().pc!=0x4000||c.source().length!=2||c.source().data[1]!=3)
        throw std::runtime_error("Wrong original source delivered to callback");
    const auto earned=static_cast<std::uint8_t>(c.after().a*c.setting("exp"));
    c.set_a(c.after().a,earned);
    const auto balance=c.read_ram_u16(0x1F0010);
    c.write_ram_u16(0x1F0010,balance,static_cast<std::uint16_t>(balance+earned));
    c.write_ram_u8(0x1F0020,c.read_ram(0x1F0020),static_cast<std::uint8_t>(c.read_ram(0x1F0020)+1));
    ++c.state()[0];c.state()[1]=static_cast<std::uint8_t>(c.ticks());c.state()[2]=static_cast<std::uint8_t>(c.frame());
}
pce::TitleAdapterSpec spec(void(*callback)(pce::TitleAdapterContext&)=reward) {
    return {"authored-qol",std::string(64,'a'),4,{{"protection",0,1,0},{"exp",1,8,1}},
        {{"earned",0x4000,{255,248,128,129,130,131,132,0},0,{0xA9,3}}},callback};
}
void execute(Fixture& f,pce::TitleAdapterRuntime& adapter,bool native=true,bool irq_poststate=false) {
    f.cpu.pc=0x4000;const auto pending=adapter.before(f.bus,f.cpu);
    f.cpu.a=3;f.cpu.nz(3);f.cpu.pc=0x4002;f.cpu.retire(2,native);
    if(irq_poststate){f.cpu.pc=0xE100;f.cpu.mpr.fill(0);}
    adapter.after(pending,f.bus,f.cpu);
}
void no_patch(pce::TitleAdapterContext& c){c.setting("does-not-exist");}
void bad_expected(pce::TitleAdapterContext& c){c.state()[0]=99;c.set_a(3,12);c.write_ram_u8(0x1F0020,7,9);c.write_ram_u8(0x1F0021,99,4);}
void callback_throw(pce::TitleAdapterContext& c){c.state()[0]=99;c.write_ram_u8(0x1F0020,7,9);throw std::runtime_error("authored callback refusal");}
void bad_register(pce::TitleAdapterContext& c){c.state()[0]=99;c.write_ram_u8(0x1F0020,7,9);c.set_a(4,12);}
void duplicate_register(pce::TitleAdapterContext& c){c.set_x(0,3);c.set_x(0,4);}
void alias_overlap(pce::TitleAdapterContext& c){c.write_ram_u8(0x1F0020,7,8);c.write_ram_u8(0x1F2020,7,9);}
void io_write(pce::TitleAdapterContext& c){c.write_ram_u8(0x1FE000,0,1);}
void bram_write(pce::TitleAdapterContext& c){c.write_ram_u8(0x1EE000,0,1);}
void source_write(pce::TitleAdapterContext& c){c.write_ram_u8(0x1F0000,0xA9,0xEA);}
void wide_write(pce::TitleAdapterContext& c){c.write_ram_u16(0x1FFFFF,0,1);}
void frame_timer(pce::TitleAdapterContext& c) {
    auto data=c.state();std::uint64_t expiry=0;
    for(unsigned i=0;i<8;++i)expiry|=std::uint64_t(data[i])<<(8*i);
    if(c.event().name=="hit") {
        const auto duration=static_cast<std::uint64_t>(c.setting("duration"));
        if(duration>UINT64_MAX-c.frame())throw std::runtime_error("authored timer overflow");
        expiry=c.frame()+duration;
        for(unsigned i=0;i<8;++i)data[i]=static_cast<std::uint8_t>(expiry>>(8*i));
    } else c.write_ram_u8(0x1F0030,c.read_ram(0x1F0030),c.frame()<expiry?1:0);
}
void cd_ram(pce::TitleAdapterContext& c){c.write_ram_u16(0x102010,0x201,0xC9A7);}
void self_overwritten_block(pce::TitleAdapterContext& c) {
    if(c.event().name!="block"||c.source().length!=7||c.source().data[0]!=0x73||c.before().pc!=0x4000||c.after().pc!=0x4007)
        throw std::runtime_error("Block callback did not retain original instruction source");
    c.write_ram_u8(0x1F0030,0,0x77);c.state()[0]=c.source().data[0];
}

void settings_and_pristine() {
    auto s=spec();pce::TitleAdapterRuntime empty;
    require(!empty.compiled()&&!empty.enabled()&&empty.checkpoint_state().empty(),"Plain host gained adapter state");
    refuses([&]{pce::TitleAdapterRuntime x(nullptr,"enhanced");},"Uncompiled enhanced mode accepted");
    refuses([&]{pce::TitleAdapterRuntime x(nullptr,"pristine","exp=1");},"Uncompiled settings accepted");
    for(const auto* text:{"exp=0","exp=9","exp=+2","exp=02","exp=-0","exp= 2","exp=2,","exp=2,exp=2",
                         "unknown=1","exp=9223372036854775808","exp=2=3",",exp=2"})
        refuses([&]{pce::TitleAdapterRuntime x(&s,"enhanced",text);},"Malformed/unknown/range-invalid settings accepted");
    refuses([&]{pce::TitleAdapterRuntime x(&s,"pristine","exp=2");},"Pristine mode accepted nondefault settings");
    refuses([&]{pce::TitleAdapterRuntime x(&s,"something");},"Unknown mode accepted");
    pce::TitleAdapterRuntime a(&s),b(&s,"pristine","exp=1,protection=0"),c(&s,"enhanced","protection=0,exp=3");
    require(a.canonical_settings()=="exp=1,protection=0"&&a.binding_digest()==b.binding_digest(),"Default normalization differs");
    require(c.canonical_settings()=="exp=3,protection=0"&&a.binding_digest()!=c.binding_digest(),"Settings/mode absent from binding");
    auto other=spec();other.manifest_sha256.assign(64,'b');pce::TitleAdapterRuntime d(&other);
    require(a.binding_digest()!=d.binding_digest(),"Manifest absent from binding");
    auto f=std::make_unique<Fixture>();execute(*f,a);
    require(f->cpu.a==3&&(*f->bus.bytes)[0x1F0010]==100&&(*f->bus.bytes)[0x1F0020]==7&&a.state().empty(),"Pristine mode changed guest");
    require(a.stats().matched_events==0&&a.checkpoint_state().empty(),"Pristine mode ran callback");
    auto limits=spec();limits.settings={{"signed",INT64_MIN,INT64_MAX,0}};
    pce::TitleAdapterRuntime low(&limits,"enhanced","signed=-9223372036854775808"),high(&limits,"enhanced","signed=9223372036854775807");
    require(low.canonical_settings()=="signed=-9223372036854775808"&&high.canonical_settings()=="signed=9223372036854775807","Signed64 endpoints lost");
    for(unsigned bad=0;bad<7;++bad){auto invalid=spec();
        if(bad==0)invalid.id="bad identifier";if(bad==1)invalid.events[0].data.push_back(0);
        if(bad==2)invalid.events.push_back(invalid.events.front());if(bad==3)invalid.state_bytes=4097;
        if(bad==4)invalid.settings.push_back(invalid.settings.front());if(bad==5)invalid.events[0].selector=16;
        if(bad==6)invalid.manifest_sha256="bad";
        refuses([&]{pce::TitleAdapterRuntime x(&invalid);},"Invalid spec accepted");}
    for(auto opcode:{0x0B,0x1B,0x2B,0x33,0x3B,0x4B,0x5B,0x5C,0x63,0x6B,0x7B,0x8B,0x9B,0xAB,0xBB,0xCB,0xDB,0xDC,0xE2,0xEB,0xFB,0xFC}) {
        auto invalid=spec();invalid.events[0].data={static_cast<std::uint8_t>(opcode)};
        refuses([&]{pce::TitleAdapterRuntime x(&invalid);},"Illegal opcode declaration accepted");
    }
}

void source_and_retirement() {
    const auto s=spec();
    for(unsigned mismatch=0;mismatch<12;++mismatch) {
        auto f=std::make_unique<Fixture>();pce::TitleAdapterRuntime a(&s,"enhanced","exp=3");
        if(mismatch<8)f->cpu.mpr[mismatch]^=1;
        if(mismatch==8)f->cpu.pc=0x4001;
        if(mismatch==9)f->bus.hucard_mapper_latch=1;
        if(mismatch==10)(*f->bus.bytes)[0x100001]=4;
        if(mismatch==11)f->bus.kind[0x80]=pce::BankKind::io;
        const auto pending=a.before(f->bus,f->cpu);f->cpu.retire(2,true);a.after(pending,f->bus,f->cpu);
        require(a.stats().matched_events==0&&a.state()[0]==0,"Wrong source matched title event");
    }
    auto native=std::make_unique<Fixture>(),reference=std::make_unique<Fixture>();
    pce::TitleAdapterRuntime a(&s,"enhanced","exp=3"),b(&s,"enhanced","exp=3");
    execute(*native,a);execute(*reference,b,false);
    require(native->cpu.a==9&&(*native->bus.bytes)[0x1F0010]==109&&(*native->bus.bytes)[0x1F0020]==8,"Literal earned reward mismatch");
    require(native->cpu.pc==0x4002&&native->cpu.cycles==2&&native->cpu.ticks==6&&native->cpu.native_steps==1&&native->cpu.interpreter_steps==0,"Adapter altered PC/time/tiers");
    require(reference->cpu.native_steps==0&&reference->cpu.interpreter_steps==1&&a.checkpoint_state()==b.checkpoint_state(),"Reference adapter semantics/counters differ");
    require(a.state()[0]==1&&a.state()[1]==6&&a.state()[2]==0,"Adapter guest-time/state input differs");
    require(a.stats().matched_events==1&&a.stats().transactions==1&&a.stats().ram_bytes_changed==2&&a.stats().register_writes==1,"Adapter diagnostics masquerade as guest work");
    require(a.last_audit_json().find("\"physical\":[1048576,1048577]")!=std::string::npos&&a.last_audit_json().find("\"execution\":\"enhanced\"")!=std::string::npos,"Source audit missing");
    auto irq=std::make_unique<Fixture>();pce::TitleAdapterRuntime after_irq(&s,"enhanced","exp=3");execute(*irq,after_irq,true,true);
    require(after_irq.stats().matched_events==1&&irq->cpu.pc==0xE100&&irq->cpu.mpr[2]==0&&irq->cpu.a==9,"Post-retire IRQ PC/MPR used as source");
    auto zero=std::make_unique<Fixture>();pce::TitleAdapterRuntime c(&s,"enhanced","exp=3");auto pending=c.before(zero->bus,zero->cpu);
    c.after(pending,zero->bus,zero->cpu);require(c.stats().matched_events==0,"Zero retirement ran hook");
    zero->cpu.a=3;zero->cpu.retire(2,true);c.after(pending,zero->bus,zero->cpu);
    const auto saved=c.checkpoint_state();refuses([&]{c.after(pending,zero->bus,zero->cpu);},"Repeated retirement ran hook twice");
    require(saved==c.checkpoint_state(),"Duplicate rejection mutated adapter");
    pending=c.before(zero->bus,zero->cpu);zero->cpu.native_steps=0;
    refuses([&]{c.after(pending,zero->bus,zero->cpu);},"Retirement counter regression accepted");
    pending=c.before(zero->bus,zero->cpu);zero->cpu.native_steps=2;
    refuses([&]{c.after(pending,zero->bus,zero->cpu);},"Multi-retirement callback accepted");
    zero->cpu.native_steps=UINT64_MAX;zero->cpu.interpreter_steps=1;
    refuses([&]{c.before(zero->bus,zero->cpu);},"Retirement-total overflow accepted");
}

void atomic_refusals() {
    const std::array callbacks{bad_expected,callback_throw,bad_register,duplicate_register,alias_overlap,io_write,bram_write,wide_write,no_patch};
    for(auto callback:callbacks) {
        auto f=std::make_unique<Fixture>();f->bus.work_ram_mirrors=true;
        for(unsigned bank=0xF8;bank<=0xFB;++bank)f->bus.kind[bank]=pce::BankKind::ram;
        f->bus.kind[0xF7]=pce::BankKind::ram;f->bus.kind[0xFF]=pce::BankKind::io;
        const auto s=spec(callback);pce::TitleAdapterRuntime a(&s,"enhanced","exp=3");
        auto pending=a.before(f->bus,f->cpu);f->cpu.a=3;f->cpu.retire(2,true);
        const auto machine=pce::encode_checkpoint(f->bus,f->cpu),adapter=a.checkpoint_state();
        refuses([&]{a.after(pending,f->bus,f->cpu);},"Invalid transaction did not refuse");
        require(machine==pce::encode_checkpoint(f->bus,f->cpu)&&adapter==a.checkpoint_state(),"Refused adapter partially mutated machine/state");
    }
    auto f=std::make_unique<Fixture>();auto s=spec(source_write);s.events[0].mpr[2]=248;
    f->cpu.mpr[2]=248;(*f->bus.bytes)[0x1F0000]=0xA9;(*f->bus.bytes)[0x1F0001]=3;
    pce::TitleAdapterRuntime a(&s,"enhanced");auto pending=a.before(f->bus,f->cpu);f->cpu.retire(2,true);
    const auto machine=pce::encode_checkpoint(f->bus,f->cpu);refuses([&]{a.after(pending,f->bus,f->cpu);},"Declared original source was writable");
    require(machine==pce::encode_checkpoint(f->bus,f->cpu),"Source refusal changed guest");
    auto overflow=std::make_unique<Fixture>();
    // Restore the ordinary ROM declaration for this separate transaction.
    auto normal=spec();pce::TitleAdapterRuntime generation_guard(&normal,"enhanced");
    auto event=generation_guard.before(overflow->bus,overflow->cpu);overflow->cpu.a=3;overflow->cpu.retire(2,true);
    overflow->bus.generation[0xF8]=UINT64_MAX-1;
    const auto stable=pce::encode_checkpoint(overflow->bus,overflow->cpu),opaque=generation_guard.checkpoint_state();
    refuses([&]{generation_guard.after(event,overflow->bus,overflow->cpu);},"Generation overflow accepted");
    require(stable==pce::encode_checkpoint(overflow->bus,overflow->cpu)&&opaque==generation_guard.checkpoint_state(),"Generation overflow partially committed");
}

void restored_state() {
    auto f=std::make_unique<Fixture>();const auto s=spec();pce::TitleAdapterRuntime a(&s,"enhanced","exp=3");execute(*f,a);
    const auto saved=a.checkpoint_state();require(saved.size()==60,"Opaque adapter state size differs");
    a.validate_restore(saved,1,0);a.validate_restore(saved,0,1);a.validate_restore(saved,2,3);
    require(saved[48]==1&&saved[49]==0,"Authored checkpoint last retirement differs from one");
    auto ahead=saved;ahead[48]=2;
    refuses([&]{a.validate_restore(ahead,1,0);},"Adapter last retirement ahead of guest accepted");
    refuses([&]{a.validate_restore(saved,0,0);},"Earned event accepted without guest retirement");
    refuses([&]{a.validate_restore(saved,UINT64_MAX,1);},"Overflowing guest retirement total accepted");
    a.validate_restore(saved,UINT64_MAX-1,1);
    require(saved==a.checkpoint_state(),"Guest-bound restore validation mutated adapter state");
    pce::TitleAdapterRuntime b(&s,"enhanced","exp=3");b.validate_restore(saved);b.commit_restore(saved);
    require(saved==b.checkpoint_state()&&b.stats().matched_events==1&&b.state()[0]==1,"Adapter restore changed persistent state");
    auto g=std::make_unique<Fixture>();g->cpu=f->cpu;*g->bus.bytes=*f->bus.bytes;g->bus.generation=f->bus.generation;
    execute(*f,a);execute(*g,b);
    require(a.checkpoint_state()==b.checkpoint_state()&&pce::encode_checkpoint(f->bus,f->cpu)==pce::encode_checkpoint(g->bus,g->cpu),"Resumed adapter diverged");
    require((*f->bus.bytes)[0x1F0010]==118&&a.state()[0]==2&&f->cpu.native_steps==2&&f->cpu.ticks==12,"Second earned event literal result differs");
    for(unsigned mutation=0;mutation<5;++mutation){auto broken=saved;
        if(mutation==0)broken.pop_back();if(mutation==1)broken.push_back(0);if(mutation==2)broken[0]^=1;
        if(mutation==3)broken[12]^=1;if(mutation==4)broken[24]=2;
        const auto before=b.checkpoint_state();refuses([&]{b.validate_restore(broken);},"Invalid adapter state accepted");
        require(before==b.checkpoint_state(),"State validation changed live adapter");}
    pce::TitleAdapterRuntime pristine(&s);refuses([&]{pristine.validate_restore(saved);},"Pristine mode restored enhanced state");
    pristine.validate_restore({});pristine.commit_restore({});
}
void guest_frames_and_cd_ram() {
    auto f=std::make_unique<Fixture>();f->bus.enable_continuous_video();(*f->bus.bytes)[0x100002]=0xEA;
    auto s=spec(frame_timer);s.state_bytes=8;s.settings={{"duration",1,8,3}};s.events[0].name="hit";
    s.events.push_back({"loop",0x4002,s.events[0].mpr,0,{0xEA}});
    pce::TitleAdapterRuntime timer(&s,"enhanced");execute(*f,timer);
    require(timer.state()[0]==3&&f->bus.vdc.video.sequence()==0,"Timer did not start in guest-frame units");
    for(unsigned frame=0;frame<=3;++frame) {
        unsigned waits=0;
        while(f->bus.vdc.video.sequence()<frame&&++waits<=2000)f->bus.clock_cpu(f->cpu,100);
        require(f->bus.vdc.video.sequence()==frame,"Authored guest frame fixture did not progress");
        f->cpu.pc=0x4002;const auto pending=timer.before(f->bus,f->cpu);f->cpu.pc=0x4003;f->cpu.retire(2,true);timer.after(pending,f->bus,f->cpu);
        require((*f->bus.bytes)[0x1F0030]==(frame<3?1:0),"Frame-counted protection expired at wrong guest frame");
    }
    require(f->cpu.native_steps==5&&timer.stats().matched_events==5,"Timer manufactured guest retirements");
    auto g=std::make_unique<Fixture>();g->bus.kind[0x81]=pce::BankKind::ram;
    (*g->bus.bytes)[0x102010]=1;(*g->bus.bytes)[0x102011]=2;
    auto cd=spec(cd_ram);pce::TitleAdapterRuntime c(&cd,"enhanced");execute(*g,c);
    require((*g->bus.bytes)[0x102010]==0xA7&&(*g->bus.bytes)[0x102011]==0xC9&&g->bus.generation[0x81]==2,"CD RAM word edit/generation mismatch");
}
void actual_self_overwriting_block() {
    auto f=std::make_unique<Fixture>();f->cpu.mpr[2]=248;f->cpu.x=0x11;f->cpu.a=0x22;f->cpu.y=0x33;
    const std::array<std::uint8_t,7> code{0x73,0x20,0x40,0x00,0x40,0x01,0x00};
    std::copy(code.begin(),code.end(),f->bus.bytes->begin()+0x1F0000);(*f->bus.bytes)[0x1F0020]=0xA9;
    auto s=spec(self_overwritten_block);s.events={{"block",0x4000,f->cpu.mpr,0,{code.begin(),code.end()}},
        {"replacement",0x4000,f->cpu.mpr,0,{0xA9,0x20}}};
    pce::TitleAdapterRuntime adapter(&s,"enhanced");const auto pending=adapter.before(f->bus,f->cpu);
    pce::interpret_block(f->bus,f->cpu,0x73);
    require((*f->bus.bytes)[0x1F0000]==0xA9,"Authored block did not overwrite its opcode");
    adapter.after(pending,f->bus,f->cpu);
    require(adapter.stats().matched_events==1&&adapter.state()[0]==0x73&&(*f->bus.bytes)[0x1F0030]==0x77,
            "Block hook used overwritten bytes or invoked twice");
    require(f->cpu.pc==0x4007&&f->cpu.native_steps==0&&f->cpu.interpreter_steps==1&&
            f->cpu.interpreter_block_steps==1&&f->cpu.block_bytes==1&&f->cpu.cycles==23&&f->cpu.ticks==69,
            "Block adapter changed original CPU timing/retirements");
    require(f->cpu.a==0x22&&f->cpu.x==0x11&&f->cpu.y==0x33&&f->cpu.sp==0xFF,"Block adapter changed restored registers/stack");
}
}
int main(){try{settings_and_pristine();source_and_retirement();atomic_refusals();restored_state();guest_frames_and_cd_ram();actual_self_overwriting_block();std::cout<<checks<<" authored title-adapter settings/source/transaction/state checks passed\n";return 0;}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
