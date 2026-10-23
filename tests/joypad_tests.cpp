#include "pce/runtime.hpp"
#include "joypad_fixture.hpp"
#include <fstream>
#include <iostream>
#include <limits>
#include <tuple>
#include <vector>

static constexpr auto forever=std::numeric_limits<std::uint64_t>::max();
static void require(bool value,const char* why) {if(!value)throw std::runtime_error(why);}
static unsigned site(unsigned op,unsigned address=0) {
    for(auto c:joypad_cases)if(c.op==op && c.address==address)return c.pc;
    throw std::runtime_error("missing authored controller instruction");
}
static auto cpu_state(const pce::Cpu& s) {
    return std::tuple{s.a,s.x,s.y,s.sp,s.p,s.pc,s.mpr,s.mpr_latch,s.cycles,s.ticks,s.clock_divisor};
}
static void initialize(pce::Bus& b,unsigned seed=0) {
    b.enable_joypad();b.kind[0xF8]=pce::BankKind::ram;
    for(unsigned i=0;i<8192;++i)(*b.bytes)[0x1F0000+i]=static_cast<std::uint8_t>(i*37+seed*17);
    for(auto [pa,value]:joypad_program)(*b.bytes)[pa]=value;
    b.generation.fill(0);
}
static void execute(pce::Bus& b,pce::Cpu& s,bool native) {
    require((native?pce::generated_step(b,s,forever):pce::interpret_step(b,s,forever))==pce::Exit::executed,
            "controller fixture instruction did not execute");
}
static void instruction(pce::Bus& b,pce::Cpu& s,bool native,unsigned op,unsigned address,unsigned value=0) {
    s.pc=static_cast<std::uint16_t>(site(op,address));s.a=static_cast<std::uint8_t>(value);execute(b,s,native);
}
static void print_cpu(const pce::Cpu& s) {
    std::cout<<"{\"pc\":"<<s.pc<<",\"a\":"<<unsigned(s.a)<<",\"x\":"<<unsigned(s.x)
        <<",\"y\":"<<unsigned(s.y)<<",\"sp\":"<<unsigned(s.sp)<<",\"p\":"<<unsigned(s.p)<<",\"mpr\":[";
    for(unsigned i=0;i<8;++i)std::cout<<(i?",":"")<<unsigned(s.mpr[i]);
    std::cout<<"]}";
}
static void print_memory(const pce::Bus& b) {
    constexpr char h[]="0123456789abcdef";
    for(unsigned n=0;n<8192;++n){const auto v=(*b.bytes)[0x1F0000+n];std::cout<<h[v>>4]<<h[v&15];}
}
static auto pad_state(const pce::Joypad& j) {
    return std::tuple{j.enabled,j.japanese,j.cd,j.multitap,j.sel,j.clr,j.extra,j.selected,j.latched,j.reads,j.writes};
}
static void print_pad(const pce::Joypad& j) {
    std::cout<<"{\"sel\":"<<(j.sel?"true":"false")<<",\"clr\":"<<(j.clr?"true":"false")
        <<",\"extra\":"<<(j.extra?"true":"false")<<",\"selected\":"<<j.selected
        <<",\"latched\":"<<unsigned(j.latched)<<'}';
}
static int probe(const char* path,const std::string& tier) {
    if(tier!="native" && tier!="interpreter")return 2;
    std::ifstream input(path);unsigned seed,a,x,y,sp,p,japanese,cd,tap,count;
    if(!(input>>seed>>a>>x>>y>>sp>>p>>japanese>>cd>>tap) || seed>255 || a>255 || x>255 || y>255 || sp>255 || p>255 || japanese>1 || cd>1 || tap>1)return 2;
    std::array<unsigned,5> types{},pressed{};
    for(auto& value:types)if(!(input>>value) || (value!=2 && value!=6))return 2;
    for(auto& value:pressed)if(!(input>>value) || value>4095)return 2;
    if(!(input>>count) || count<1 || count>256)return 2;
    std::vector<std::pair<unsigned,int>> actions;
    for(unsigned i=0;i<count;++i){unsigned pc;int value;if(!(input>>pc>>value) || pc>65535 || value < -1 || value>255)return 2;actions.emplace_back(pc,value);}
    std::string trailing;if(input>>trailing)return 2;
    pce::Bus b;initialize(b,seed);b.enable_joypad(japanese!=0,cd!=0);b.joypad.set_multitap(tap!=0);
    for(unsigned slot=0;slot<5;++slot){b.joypad.set_type(slot,types[slot]);b.joypad.set_pressed(slot,pressed[slot]);}
    pce::Cpu s;s.mpr=joypad_mpr;s.a=a;s.x=x;s.y=y;s.sp=sp;s.p=p;
    std::cout<<"{\"states\":[";
    for(unsigned i=0;i<count;++i){s.pc=static_cast<std::uint16_t>(actions[i].first);if(actions[i].second>=0)s.a=static_cast<std::uint8_t>(actions[i].second);execute(b,s,tier=="native");
        if(i)std::cout<<',';std::cout<<"{\"cpu\":";print_cpu(s);std::cout<<",\"joypad\":";print_pad(b.joypad);std::cout<<'}';}
    std::cout<<"],\"ram\":\"";print_memory(b);std::cout<<"\",\"native_steps\":"<<s.native_steps<<",\"interpreter_steps\":"<<s.interpreter_steps<<"}\n";
    return 0;
}

// Expected connector nibbles are active low. Each literal mask position is
// exercised independently; these checks never call the emitter's data logic.
static unsigned button_expectations(pce::Bus& b) {
    unsigned checks=0;
    for(bool native:{false,true})for(unsigned divisor:{3U,12U})for(unsigned buttons:{2U,6U}) {
        initialize(b);
        for(unsigned mask=0;mask<4096;++mask) {
            b.enable_joypad(false,false);b.joypad.set_type(0,buttons);b.joypad.set_pressed(0,mask);
            pce::Cpu s;s.mpr=joypad_mpr;s.p=0xFF;s.clock_divisor=divisor;s.x=0x71;s.y=0x93;s.sp=0xE7;s.mpr_latch=0x65;
            const unsigned standard_buttons=0xBF-(mask&15);
            const unsigned directions=0xBF-((mask>>4)&15);
            const unsigned extras=0xBF-((mask>>8)&15);
            // Falling CLR selects the six-button extension. A second falling
            // edge restores the ordinary bank; repeated writes retain it.
            const unsigned controls[]={0,1,3,0,1,1,2,0};
            const unsigned values[]={buttons==6?extras:standard_buttons,buttons==6?0xB0U:directions,
                                     0xB0,standard_buttons,directions,directions,0xB0,
                                     buttons==6?extras:standard_buttons};
            for(unsigned index=0;index<8;++index) {
                instruction(b,s,native,0x8D,0x1000,controls[index]);
                const auto before_read=s;instruction(b,s,native,0xAD,0xB3FF);
                const unsigned expected_p=(before_read.p&0x5D)|(values[index]&128)|(values[index]==0?2:0);
                require(s.a==values[index] && s.p==expected_p,"controller active-low button/direction/extension nibble or flags");
            }
            require(s.cycles==80 && s.ticks==80*divisor && s.mpr_latch==0x65 && s.x==0x71 && s.y==0x93 && s.sp==0xE7,
                    "controller accesses changed fixed CPU timing or unrelated state");
            require(s.native_steps==(native?16U:0U) && s.interpreter_steps==(native?0U:16U),"controller button sweep execution tier");
            ++checks;
        }
    }
    return checks;
}

static unsigned control_expectations(pce::Bus& b) {
    unsigned checks=0;
    for(bool native:{false,true})for(bool japanese:{false,true})for(bool cd:{false,true})
    for(unsigned flags:{0U,0x55U,0xAAU,0xFFU})for(unsigned value=0;value<256;++value) {
        initialize(b);b.enable_joypad(japanese,cd);b.joypad.set_pressed(0,0xA53);
        pce::Cpu s;s.mpr=joypad_mpr;s.p=flags;
        const unsigned high=0x30+(japanese?0x40:0)+(cd?0:0x80);
        require(b.read(s,0x1000)==high,"controller reset value or region/CD pin polarity");
        const auto generation=b.generation;instruction(b,s,native,0x8D,0xB001,value);
        const unsigned low=value&2?0:((value&1)?10:12);
        require(b.joypad.sel==bool(value&1) && b.joypad.clr==bool(value&2) && b.joypad.extra==!(value&2),
                "controller SEL/CLR decode or falling-edge extension toggle");
        require(s.a==value && s.p==(flags&~32U),"controller store altered source accumulator or status");
        instruction(b,s,native,0xAD,0x1100);
        require(s.a==high+low && s.p==((flags&0x5D)|(high&128)),"controller region/CD/button load or NZ/T semantics");
        require(s.cycles==10 && s.ticks==30 && b.generation==generation,"controller port wait or memory-generation side effect");
        ++checks;
    }
    return checks;
}

static unsigned tap_expectations(pce::Bus& b) {
    unsigned checks=0;
    // Fixed masks distinguish every slot, both ordinary nibbles and extras.
    constexpr unsigned masks[]={0x111,0x222,0x444,0x888,0xFFF};
    constexpr unsigned standard[]={0x3E,0x3D,0x3B,0x37,0x30};
    for(bool native:{false,true})for(unsigned buttons:{2U,6U}) {
        initialize(b);b.enable_joypad(false,true);b.joypad.set_multitap(true);
        for(unsigned slot=0;slot<5;++slot){b.joypad.set_pressed(slot,masks[slot]);b.joypad.set_type(slot,buttons);}
        pce::Cpu s;s.mpr=joypad_mpr;
        instruction(b,s,native,0x8D,0x1000,0);
        instruction(b,s,native,0xAD,0x1000);require(s.a==0x3E && b.joypad.selected==0,"tap first slot/extra nibble");++checks;
        for(unsigned slot=1;slot<=5;++slot) {
            instruction(b,s,native,0x8D,0xB000,1);instruction(b,s,native,0xAD,0x1000);
            require(b.joypad.selected==slot && s.a==(slot==5?0x3FU:buttons==6?0x30U:standard[slot]),"tap SEL rise did not advance exactly one slot");++checks;
            instruction(b,s,native,0x8D,0x1000,1);require(b.joypad.selected==slot,"held SEL advanced the tap twice");++checks;
            instruction(b,s,native,0x8D,0x1000,0);instruction(b,s,native,0xAD,0xB000);
            require(s.a==(slot==5?0x3FU:standard[slot]),"tap button or overflow nibble");++checks;
        }
        require(b.joypad.selected==5 && b.joypad.extra,"tap overflow changed extension bank");
        for(unsigned value:{1U,0U,1U,2U,0U}) {
            instruction(b,s,native,0x8D,0x1000,value);instruction(b,s,native,0xAD,0x1000);
            require(s.a==0x3F && b.joypad.selected==5 && b.joypad.extra,"tap overflow wrapped, blanked, or toggled extension");++checks;
        }
        instruction(b,s,native,0x8D,0x1000,3);instruction(b,s,native,0xAD,0x1000);
        require(s.a==0x30 && b.joypad.selected==0,"tap CLR rise with SEL high did not reset the slot");++checks;
        instruction(b,s,native,0x8D,0x1000,0);instruction(b,s,native,0xAD,0x1000);
        require(s.a==0x3E && !b.joypad.extra,"tap reset plus CLR fall did not select ordinary bank");++checks;
        // A SEL rising edge with CLR high does not increment. CLR low->high
        // while SEL low does not reset a nonzero slot.
        instruction(b,s,native,0x8D,0x1000,1);instruction(b,s,native,0x8D,0x1000,0);
        instruction(b,s,native,0x8D,0x1000,2);require(b.joypad.selected==1,"tap CLR rise with SEL low reset the slot");++checks;
        instruction(b,s,native,0x8D,0x1000,3);require(b.joypad.selected==1,"tap SEL rise with held CLR advanced/reset the slot");++checks;
        b.joypad.set_multitap(false);require(b.joypad.selected==1,"host tap setting unexpectedly relatched state");
        instruction(b,s,native,0x8D,0x1000,0);require(b.joypad.selected==0,"single connector write failed to force slot zero");++checks;
    }
    // Each row starts with one control write from reset, then every possible
    // next control. In particular 2 -> 1 changes both lines at once: it must
    // increment the tap and toggle the extension bank in the same access.
    constexpr unsigned slots[]={0,1,0,0, 0,0,0,0, 0,1,0,0, 0,0,0,0};
    constexpr unsigned banks[]={1,1,1,1, 1,1,1,1, 1,1,0,0, 1,1,0,0};
    constexpr unsigned samples[]={0x3E,0x30,0x30,0x30, 0x3E,0x30,0x30,0x30,
                                   0x3E,0x30,0x30,0x30, 0x3E,0x30,0x30,0x30};
    for(bool native:{false,true})for(unsigned previous=0;previous<4;++previous)for(unsigned next=0;next<4;++next) {
        initialize(b);b.enable_joypad(false,true);b.joypad.set_multitap(true);
        for(unsigned slot=0;slot<5;++slot){b.joypad.set_type(slot,6);b.joypad.set_pressed(slot,0x124);}
        pce::Cpu s;s.mpr=joypad_mpr;
        instruction(b,s,native,0x8D,0x1000,previous);instruction(b,s,native,0x8D,0x1000,next);
        instruction(b,s,native,0xAD,0x1000);const unsigned index=previous*4+next;
        require(b.joypad.selected==slots[index] && b.joypad.extra==bool(banks[index]) && s.a==samples[index],
                "simultaneous/held SEL CLR transitions disagreed with the literal connector table");++checks;
    }
    return checks;
}

static unsigned bus_expectations(pce::Bus& b) {
    unsigned checks=0;
    initialize(b);b.enable_joypad(false,true);b.joypad.set_pressed(0,0xF5);
    pce::Cpu s;s.mpr=joypad_mpr;s.mpr_latch=0xA9;
    const auto generation=b.generation;
    for(unsigned page=0;page<8;++page)for(unsigned offset=0;offset<1024;++offset) {
        auto mapping=s.mpr;s.mpr[page]=0xFF;
        const auto address=static_cast<std::uint16_t>((page<<13)|0x1000|offset);
        b.write(s,address,0);require(b.read(s,address)==0x3A,"controller 1 KiB mirror or physical MPR decode");
        b.write(s,address,1);require(b.read(s,address)==0x30,"controller direction nibble through mirror/MPR");
        s.mpr=mapping;++checks;
    }
    require(b.generation==generation && s.mpr_latch==0xA9 && s.cycles==0 && s.ticks==0,"direct controller bus traffic changed executable memory or CPU clocks/latch");
    const auto before=pad_state(b.joypad);
    for(unsigned offset=0;offset<1024;++offset)require(!b.peek(0x1FF000+offset),"source peek exposed controller data as code");
    require(pad_state(b.joypad)==before,"source peek sampled controller or changed edge state");++checks;
    // A hardware offset in an ordinary mapped RAM bank is still ordinary RAM.
    s.mpr[0]=0xF8;b.write(s,0x1000,0x42);
    require(b.read(s,0x1000)==0x42 && pad_state(b.joypad)==before,"logical controller address bypassed the MPR hardware bank");++checks;
    for(bool native:{false,true})for(unsigned op:{0x0CU,0x1CU})for(unsigned mask=0;mask<256;++mask) {
        initialize(b);b.enable_joypad(false,false);s=pce::Cpu{};s.mpr=joypad_mpr;s.p=0xAD;
        b.write(s,0x1000,0);const auto reads=b.joypad.reads,writes=b.joypad.writes;
        instruction(b,s,native,op,0xB3FF,mask);
        const unsigned written=op==0x0C?0xBF|mask:0xBF&(~mask&255);
        const unsigned expected_p=(0xAD&0x1D)|0x80|(written==0?2:0);
        require(b.joypad.sel==bool(written&1) && b.joypad.clr==bool(written&2) && b.joypad.latched==(written&2?0xB0:0xBF),
                "controller RMW used output-control readback instead of sampled input");
        require(b.joypad.reads==reads+1 && b.joypad.writes==writes+1 && s.p==expected_p && s.cycles==7 && s.ticks==21,
                "controller RMW read/write count, flags or cycles");++checks;
    }
    for(bool native:{false,true}) {
        initialize(b);s=pce::Cpu{};s.mpr=joypad_mpr;s.pc=site(0x8D,0x1000);s.a=0;
        auto cpu=cpu_state(s);auto pad=pad_state(b.joypad);
        const auto run=[&](std::uint64_t deadline){return native?pce::generated_step(b,s,deadline):pce::interpret_step(b,s,deadline);};
        require(run(0)==pce::Exit::budget && cpu_state(s)==cpu && pad_state(b.joypad)==pad,"deadline changed controller output/edge state");++checks;
        for(auto [op,address]:std::array<std::pair<unsigned,unsigned>,2>{{{0xAD,0x1400},{0x8D,0x0FFF}}}) {
            s.pc=site(op,address);cpu=cpu_state(s);pad=pad_state(b.joypad);bool fault=false;
            try{run(forever);}catch(const pce::Fault&){fault=true;}
            require(fault && cpu_state(s)==cpu && pad_state(b.joypad)==pad,"adjacent unsupported hardware access was mirrored or retired");++checks;
        }
    }
    initialize(b);s=pce::Cpu{};s.mpr=joypad_mpr;s.pc=site(0x8D,0x1000);s.a=0;
    (*b.bytes)[pce::Bus::physical(s,s.pc)+1]=1;auto cpu=cpu_state(s);auto pad=pad_state(b.joypad);
    require(pce::generated_step(b,s,forever)==pce::Exit::miss && cpu_state(s)==cpu && pad_state(b.joypad)==pad,"stale native controller operand changed state before guarding");
    require(pce::step(b,s,forever)==pce::Exit::executed && !b.joypad.sel && !b.joypad.clr && b.joypad.writes==1,"stale controller operand fallback failed through the true mirror");++checks;
    initialize(b);s=pce::Cpu{};s.mpr=joypad_mpr;s.pc=site(0xAD,0x1000);s.mpr[0]=0xF8;cpu=cpu_state(s);pad=pad_state(b.joypad);
    require(pce::generated_step(b,s,forever)==pce::Exit::miss && cpu_state(s)==cpu && pad_state(b.joypad)==pad,"mapping guard sampled controller through the original MPR context");++checks;
    pce::Bus disabled;disabled.kind[0xFF]=pce::BankKind::io;s=pce::Cpu{};s.mpr=joypad_mpr;
    for(bool write:{false,true}){bool fault=false;try{if(write)disabled.write(s,0x1000,0);else disabled.read(s,0x1000);}catch(const pce::Fault&){fault=true;}
        require(fault && !disabled.joypad.enabled,"strict sandbox silently enabled controller hardware");++checks;}
    return checks;
}

static unsigned host_expectations(pce::Bus& b) {
    unsigned checks=0;
    initialize(b);b.enable_joypad(false,true);pce::Cpu s;s.mpr=joypad_mpr;
    b.write(s,0x1000,0);require(b.read(s,0x1000)==0x3F,"released buttons are not active-high at the connector");
    auto pad=pad_state(b.joypad);b.joypad.set_pressed(0,0xFFF);
    require(pad_state(b.joypad)==pad && b.read(s,0x1000)==0x3F,"host input update resampled the latched connector before a guest write");
    b.write(s,0x1000,0);require(b.read(s,0x1000)==0x30,"repeated control write did not sample the latest host input");++checks;
    b.joypad.set_pressed(0,0);require(b.read(s,0x1000)==0x30,"host release prematurely changed sampled input");
    b.write(s,0x1000,0);require(b.read(s,0x1000)==0x3F,"write did not sample released buttons");++checks;
    b.joypad.set_type(0,6);require(b.read(s,0x1000)==0x3F,"controller type change relatched output");
    b.joypad.set_pressed(0,0xF00);b.write(s,0x1000,0);require(b.read(s,0x1000)==0x30,"controller type/extra bank did not apply on next write");++checks;
    for(unsigned slot:{5U,255U}) {
        pad=pad_state(b.joypad);bool fault=false;try{b.joypad.set_pressed(slot,0);}catch(const pce::Fault&){fault=true;}
        require(fault && pad_state(b.joypad)==pad,"out-of-range controller host slot was accepted or changed state");++checks;
        fault=false;try{b.joypad.set_type(slot,2);}catch(const pce::Fault&){fault=true;}
        require(fault && pad_state(b.joypad)==pad,"out-of-range controller type slot was accepted or changed state");++checks;
    }
    for(unsigned mask:{4096U,65535U}) {
        const auto pressed=b.joypad.pads[0].pressed;bool fault=false;try{b.joypad.set_pressed(0,mask);}catch(const pce::Fault&){fault=true;}
        require(fault && b.joypad.pads[0].pressed==pressed,"out-of-range controller button mask was truncated or accepted");++checks;
    }
    for(unsigned type:{0U,1U,3U,4U,5U,7U,255U}) {
        bool fault=false;try{b.joypad.set_type(0,type);}catch(const pce::Fault&){fault=true;}
        require(fault && b.joypad.pads[0].buttons==6,"unsupported controller type changed configuration");++checks;
    }
    b.joypad.set_multitap(true);b.write(s,0x1000,1);require(b.joypad.selected==1,"host reset setup did not select pad one");
    b.joypad.reset();require(b.joypad.enabled && !b.joypad.japanese && b.joypad.cd && b.joypad.multitap && b.joypad.sel && b.joypad.clr && !b.joypad.extra && b.joypad.selected==0 && b.joypad.latched==0x30,
            "controller reset did not restore lines/bank/slot while retaining connector configuration");
    require(b.joypad.reads==0 && b.joypad.writes==0 && b.joypad.pads[0].buttons==6,"controller reset changed pad type or retained diagnostic counts");
    for(auto p:b.joypad.pads)require(p.pressed==0,"controller reset retained held host buttons");++checks;
    return checks;
}

int main(int argc,char** argv) {
    try {
        if(argc==4 && std::string(argv[1])=="--probe")return probe(argv[2],argv[3]);
        if(argc!=1)return 2;
        pce::Bus b;const auto buttons=button_expectations(b),control=control_expectations(b),tap=tap_expectations(b),bus=bus_expectations(b),host=host_expectations(b);
        std::cout<<buttons+control+tap+bus+host<<" independently expected controller groups passed ("<<buttons<<" button masks, "<<control<<" control/pin groups, "<<tap<<" tap edges, "<<bus<<" bus/guard/RMW groups, "<<host<<" host/reset groups); both execution tiers and CPU speeds\n";
        return 0;
    }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
