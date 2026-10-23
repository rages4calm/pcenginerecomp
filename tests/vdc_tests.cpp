#include "pce/runtime.hpp"
#include "vdc_fixture.hpp"
#include <fstream>
#include <iostream>
#include <limits>
#include <vector>

static constexpr auto forever=std::numeric_limits<std::uint64_t>::max();
static void require(bool value,const char* why) { if(!value) throw std::runtime_error(why); }
static void initialize(pce::Bus& b,unsigned seed=0) {
    b.enable_vdc(); b.kind[0xF8]=pce::BankKind::ram;
    for(unsigned i=0;i<8192;++i) (*b.bytes)[0x1F0000+i]=static_cast<std::uint8_t>(i*37+seed*17);
    for(auto [pa,v]:vdc_program) (*b.bytes)[pa]=v;
    for(unsigned i=0;i<32768;++i) (*b.vdc.vram)[i]=static_cast<std::uint16_t>(
        ((2*i*13+seed*7)&255)|((( (2*i+1)*13+seed*7)&255)<<8));
}
static std::uint16_t site(unsigned op,unsigned value) {
    for(auto c:vdc_cases) if(c.op==op && c.value==value) return c.pc;
    throw std::runtime_error("missing VDC fixture");
}
static void execute(pce::Bus& b,pce::Cpu& s,bool native) {
    require((native ? pce::generated_step(b,s,forever):pce::interpret_step(b,s,forever))==pce::Exit::executed,"VDC instruction failed");
}
static void write_word(pce::Vdc& v,unsigned r,unsigned value) {
    v.write(0,static_cast<std::uint8_t>(r));v.write(2,static_cast<std::uint8_t>(value));v.write(3,static_cast<std::uint8_t>(value>>8));
}
static unsigned instruction_expectations(pce::Bus& b) {
    unsigned count=0;
    for(bool native:{false,true}) for(unsigned divisor:{3U,12U})
    for(unsigned flags:{0U,255U,85U,170U}) for(unsigned value=0;value<256;++value) {
        for(unsigned op:{3U,19U,35U}) {
            b.vdc.reg.fill(0);b.vdc.reg[5]=0x1234;b.vdc.selected=5;
            pce::Cpu s;s.mpr=vdc_mpr;s.pc=site(op,value);s.p=flags;s.clock_divisor=divisor;
            s.a=0x73;s.x=0xE1;s.y=0x99;s.sp=0;
            const auto pc=s.pc;
            execute(b,s,native);
            require(s.pc==pc+2 && s.a==0x73 && s.x==0xE1 && s.y==0x99 && s.sp==0 && s.p==(flags&~32U),"ST registers/flags/PC");
            require(s.cycles==5 && s.ticks==5*divisor && s.native_steps==unsigned(native) && s.interpreter_steps==unsigned(!native),"ST timing/tier");
            require(b.vdc.selected==(op==3 ? value&31:5),"ST0 select mask");
            require(b.vdc.reg[5]==(op==3 ? 0x1234:op==19 ? ((0x1200|value)&0x1FFF):((0x34|(value<<8))&0x1FFF)),"ST1/ST2 byte mask");
            ++count;
        }
        for(auto address:{0xA000U,0xA001U,0xA002U,0xA003U,0xA3FCU,0xA3FDU,0xA3FEU,0xA3FFU}) {
            b.vdc.selected=5;b.vdc.reg[5]=0x1234;
            pce::Cpu s;s.mpr=vdc_mpr;s.pc=site(0x8D,address);s.a=value;s.p=flags;s.clock_divisor=divisor;
            const auto generations=b.generation;
            execute(b,s,native);
            require(s.cycles==6 && s.ticks==6*divisor && s.p==(flags&~32U),"mapped VDC write wait/flags");
            require(b.generation==generations,"VDC port dirtied executable RAM");
            const auto port=address&3;
            require(b.vdc.selected==(port==0 ? value&31:5),"mapped port mirror selector");
            require(b.vdc.reg[5]==(port<2 ? 0x1234:port==2 ? ((0x1200|value)&0x1FFF):((0x34|(value<<8))&0x1FFF)),"mapped byte/unused-port semantics");
            ++count;
            b.vdc.selected=5;b.vdc.read_buffer=0xB837;b.vdc.status=static_cast<std::uint8_t>(value&63);b.vdc.irq1=true;
            s=pce::Cpu{};s.mpr=vdc_mpr;s.pc=site(0xAD,address);s.p=flags;s.clock_divisor=divisor;
            execute(b,s,native);
            const unsigned wanted=port==0 ? value&63:port==1 ? 0:port==2 ? 0x37:0xB8;
            const unsigned expected_p=(flags&~(32U|128U|2U))|(wanted&128)|(wanted==0 ? 2:0);
            require(s.a==wanted && s.p==expected_p && s.cycles==6 && s.ticks==6*divisor,"mapped VDC read/buffer/flags/wait");
            require(port!=0 || (b.vdc.status==0 && !b.vdc.irq1),"mapped status must acknowledge IRQ");
            ++count;
        }
    }
    return count;
}
static unsigned register_expectations(pce::Vdc& v) {
    unsigned count=0;
    // Literal hardware widths, independently expected from byte-split writes.
    constexpr unsigned masks[]={0xFFFF,0xFFFF,0xFFFF,0,0,0x1FFF,0x3FF,0x3FF,0x1FF,0xFF,
        0x7F1F,0x7F7F,0xFF1F,0x1FF,0xFF,0x1F,0xFFFF,0xFFFF,0xFFFF,0xFFFF};
    for(unsigned r=0;r<32;++r) for(unsigned byte=0;byte<256;++byte) {
        v.reg.fill(0);v.write(0,static_cast<std::uint8_t>(r));
        v.write(2,static_cast<std::uint8_t>(byte));
        if(r<20) require(v.reg[r]==(byte&masks[r]),"VDC low-byte register width");
        if(r!=1 && r!=2 && r!=18 && r!=19) {
            v.write(3,static_cast<std::uint8_t>(byte^255));
            if(r<20) require(v.reg[r]==(((byte^255)*256+byte)&masks[r]),"VDC high-byte register width");
            else for(auto word:v.reg) require(word==0,"invalid selector wrote register");
        }
        ++count;
    }
    return count;
}
static unsigned vram_expectations(pce::Vdc& v) {
    unsigned count=0;
    for(unsigned mode=0;mode<4;++mode) {
        const unsigned increment[]={1,32,64,128};
        v.reg.fill(0);v.reg[5]=static_cast<std::uint16_t>(mode<<11);
        for(unsigned addr=0;addr<65536;++addr) {
            (*v.vram)[addr&32767]=0xCC77;
            v.reg[0]=static_cast<std::uint16_t>(addr);v.selected=2;
            v.write(2,0x39);
            require(v.reg[0]==addr && (addr>=32768 || (*v.vram)[addr]==0xCC77),"VWR low must only latch");
            v.write(3,0xA6);
            require(v.reg[0]==((addr+increment[mode])&65535),"MAWR increment/wrap");
            if(addr<32768) require((*v.vram)[addr]==0xA639,"VRAM word commit");
            else require((*v.vram)[addr&32767]==0xCC77,"undriven VRAM write must not mirror");
            ++count;
        }
        for(unsigned addr=0;addr<32768-increment[mode];++addr) {
            (*v.vram)[addr]=0xB837;(*v.vram)[addr+increment[mode]]=0x6E91;
            write_word(v,1,addr);
            require(v.read_buffer==0xB837 && v.reg[1]==addr+increment[mode],"MARR prefetch/increment");
            v.write(0,5);
            require(v.read(2)==0x37 && v.read(3)==0xB8 && v.reg[1]==addr+increment[mode],"all selected registers read buffer; no high advance outside VRR");
            v.write(0,2);
            require(v.read(2)==0x37 && v.read(2)==0x37,"low VRR read must not advance");
            require(v.read(3)==0xB8 && v.read_buffer==0x6E91 && v.reg[1]==addr+2*increment[mode],"high VRR returns previous buffer and prefetches next");
            ++count;
        }
    }
    return count;
}
static void boundaries(pce::Bus& b) {
    pce::Cpu s;s.mpr=vdc_mpr;
    for(unsigned flags=0;flags<64;++flags) {
        b.vdc.status=static_cast<std::uint8_t>(flags);b.vdc.irq1=true;
        require(b.read(s,0xA3FC)==flags && b.vdc.status==0 && !b.vdc.irq1,"status read flags/IRQ acknowledgement");
        require(b.read(s,0xA001)==0,"unused port must read zero");
    }
    for(unsigned r:{18U,19U}) {
        b.vdc.selected=static_cast<std::uint8_t>(r);b.vdc.reg[r]=0x1255;
        const auto writes=b.vdc.writes;
        bool failed=false;try{b.vdc.write(3,0x81);}catch(const pce::Fault&){failed=true;}
        require(failed && b.vdc.reg[r]==0x1255 && b.vdc.writes==writes,"DMA fault mutated register");
    }
    b.vdc.selected=1;b.vdc.reg[1]=0x1234;
    bool failed=false;try{b.vdc.write(3,0x80);}catch(const pce::Fault&){failed=true;}
    require(failed && b.vdc.reg[1]==0x1234,"undriven VRAM prefetch did not refuse before mutation");
    for(bool native:{false,true}) {
        s=pce::Cpu{};s.mpr=vdc_mpr;s.pc=site(3,255);
        auto writes=b.vdc.writes;
        require((native?pce::generated_step(b,s,0):pce::interpret_step(b,s,0))==pce::Exit::budget && b.vdc.writes==writes,"deadline touched VDC");
        auto pa=pce::Bus::physical(s,s.pc+1);(*b.bytes)[pa]^=1;
        require(pce::generated_step(b,s,forever)==pce::Exit::miss && b.vdc.writes==writes,"operand guard touched VDC");
        (*b.bytes)[pa]^=1;s.mpr[0]=255;
        require(pce::generated_step(b,s,forever)==pce::Exit::miss && b.vdc.writes==writes,"MPR guard touched VDC");
        b.vdc.selected=0;
        require(pce::step(b,s,forever)==pce::Exit::executed && b.vdc.selected==31 && s.interpreter_steps==1,"ST MPR-independent fallback");
        s.mpr=vdc_mpr;s.pc=site(3,255);b.vdc.enabled=false;failed=false;
        try{execute(b,s,native);}catch(const pce::Fault&){failed=true;}
        require(failed && s.pc==site(3,255),"disabled VDC accepted ST");b.vdc.enabled=true;
    }
    s=pce::Cpu{};s.mpr=vdc_mpr;
    // The first VCE address must not be mistaken for a VDC mirror.
    failed=false;try{b.write(s,0xA400,0);}catch(const pce::Fault&){failed=true;}
    require(failed,"VDC decoding escaped its 1 KiB window");
}
static void print_state(const pce::Bus& b,const pce::Cpu& s) {
    std::cout<<"{\"cpu\":{\"pc\":"<<s.pc<<",\"a\":"<<unsigned(s.a)<<",\"x\":"<<unsigned(s.x)<<",\"y\":"<<unsigned(s.y)
        <<",\"sp\":"<<unsigned(s.sp)<<",\"p\":"<<unsigned(s.p)<<",\"mpr\":[";
    for(unsigned i=0;i<8;++i) std::cout<<(i?",":"")<<unsigned(s.mpr[i]);
    std::cout<<"]},\"vdc\":{\"selected\":"<<unsigned(b.vdc.selected)<<",\"registers\":[";
    for(unsigned i=0;i<20;++i)std::cout<<(i?",":"")<<b.vdc.reg[i];
    std::cout<<"]}}";
}
static int probe(const char* path,const std::string& tier) {
    if(tier!="native" && tier!="interpreter")return 2;
    std::ifstream in(path);unsigned seed,a,x,y,sp,p,count;
    if(!(in>>seed>>a>>x>>y>>sp>>p>>count) || seed>255 || a>255 || x>255 || y>255 || sp>255 || p>255 || count<1 || count>128)return 2;
    std::vector<std::pair<unsigned,int>> steps;
    for(unsigned i=0;i<count;++i) {unsigned pc;int v;if(!(in>>pc>>v)||pc>65535||v< -1||v>255)return 2;steps.emplace_back(pc,v);}
    std::string trailing;if(in>>trailing)return 2;
    pce::Bus b;initialize(b,seed);pce::Cpu s;s.mpr=vdc_mpr;s.a=a;s.x=x;s.y=y;s.sp=sp;s.p=p;
    std::cout<<"{\"states\":[";
    for(unsigned i=0;i<count;++i) {
        s.pc=steps[i].first;if(steps[i].second>=0)s.a=steps[i].second;
        execute(b,s,tier=="native");const auto next=s.pc;
        s.pc=0x2600;for(unsigned n=0;n<16;++n)execute(b,s,tier=="native");s.pc=next;
        if(i)std::cout<<',';print_state(b,s);
    }
    constexpr char hex[]="0123456789abcdef";
    auto byte=[&](unsigned v){std::cout<<hex[(v>>4)&15]<<hex[v&15];};
    std::cout<<"],\"ram\":\"";for(unsigned i=0;i<8192;++i)byte((*b.bytes)[0x1F0000+i]);
    std::cout<<"\",\"vram\":\"";for(auto v:*b.vdc.vram){byte(v&255);byte(v>>8);}
    std::cout<<"\",\"native_steps\":"<<s.native_steps<<",\"interpreter_steps\":"<<s.interpreter_steps<<"}\n";
    return 0;
}
int main(int argc,char** argv) {
    try {
        if(argc==4 && std::string(argv[1])=="--probe")return probe(argv[2],argv[3]);
        if(argc!=1)return 2;
        pce::Bus bus;initialize(bus);
        const auto instructions=instruction_expectations(bus);
        const auto registers=register_expectations(bus.vdc);
        const auto vram=vram_expectations(bus.vdc);
        boundaries(bus);
        std::cout<<instructions<<" VDC instruction expectations; "<<registers<<" register-width cases; "<<vram
                 <<" VRAM transfer/address cases; status/guards/deadlines/faults passed\n";
        return 0;
    }catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
}
