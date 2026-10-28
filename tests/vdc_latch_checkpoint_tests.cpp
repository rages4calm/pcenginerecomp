// Host-configured direct VDC clocks and port transactions; no retired opcodes.
#include "pce/runtime.hpp"
#include "pce/checkpoint.hpp"
#include "vdc_latch_checkpoint_support.hpp"
#include "irq_trace_support.hpp"
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <memory>
#include <span>

namespace {
namespace model=vdc_latch_checkpoint;
std::uint64_t checks=0;
void check(bool ok,const char* why){++checks;model::require(ok,why);}
template<class Tag,typename Tag::type Pointer>struct Access {friend typename Tag::type member(Tag){return Pointer;}};
struct Indices{using type=std::array<std::uint16_t,1024> pce::VideoOutput::*;friend type member(Indices);};
template struct Access<Indices,&pce::VideoOutput::indices_>;
struct Machine{pce::Bus bus;pce::Cpu cpu;};
void reg(pce::Vdc& v,unsigned index,unsigned value){v.write(0,std::uint8_t(index));v.write(2,std::uint8_t(value));v.write(3,std::uint8_t(value>>8));}
std::unique_ptr<Machine> configured(const model::Case& c){
    auto m=std::make_unique<Machine>();auto& b=m->bus;
    const auto rom=model::rom();b.configure_hucard(pce::HuCardProfile::base,rom);b.enable_continuous_video();b.enable_interrupts();b.power_on_cpu(m->cpu,0,0);
    model::seed_vram(b.vdc.vram->data());b.vce.palette[1]=0x38;
    reg(b.vdc,5,model::old_cr(c.edge));reg(b.vdc,9,0);reg(b.vdc,10,0x0202);reg(b.vdc,11,0x7F1D);
    reg(b.vdc,12,0x0F02);reg(b.vdc,13,239);reg(b.vdc,14,2);reg(b.vdc,0,0x1800);reg(b.vdc,1,0x18FF);
    return m;
}
void advance(Machine& m,std::uint64_t ticks){check(ticks>=m.cpu.ticks,"clock regression");m.cpu.ticks=ticks;m.bus.sync(m.cpu);}
void ports(Machine& m,const model::Case& c){
    auto& v=m.bus.vdc;v.write(0,2);
    if(c.queue&2){v.write(2,0xCD);v.write(3,0xAB);}
    if(c.queue&1)(void)v.read(3);
    reg(v,model::write_reg(c.edge),model::write_value(c.edge));
}
model::State observe(const Machine& m){
    const auto& v=m.bus.vdc;const auto& r=v.raster;
    model::State out{m.cpu.ticks,r.hclock,r.line,r.vdc_line,r.h_state,r.v_state,v.reg[5],v.reg[9],v.sprite_control,v.sprite_mode,v.sprite_burst,
        v.pending_vram_read,v.pending_vram_write,std::uint64_t(v.vram_transfer_delay),v.vram_cpu_cycles,v.reg[1],v.reg[0],v.read_buffer,(*v.vram)[0x1800],
        std::uint64_t(v.load_bg_start_clock),std::uint64_t(v.load_bg_end_clock),std::uint64_t(v.hsync_start_clock)};
    for(unsigned i=0;i<16;++i)out[22+i]=(v.video.*member(Indices{}))[i];return out;
}
std::string hash(std::span<const std::uint8_t> bytes){return irq_trace::hash(bytes);}
void write_new(const std::filesystem::path& path,const std::vector<std::uint8_t>& bytes){
#ifdef _WIN32
    auto* file=_wfopen(path.c_str(),L"wbx");
#else
    auto* file=std::fopen(path.c_str(),"wbx");
#endif
    check(file!=nullptr,"checkpoint probe requires new private output");const bool written=std::fwrite(bytes.data(),1,bytes.size(),file)==bytes.size();
    const bool closed=std::fclose(file)==0;check(written&&closed,"checkpoint write failed");
}
std::vector<std::uint8_t> read(const std::filesystem::path& path){std::ifstream in(path,std::ios::binary);check(bool(in),"cannot open checkpoint payload");return {std::istreambuf_iterator<char>(in),std::istreambuf_iterator<char>()};}
void execute(const model::Case& c,const std::string& mode={},const std::filesystem::path& path={},const std::filesystem::path& final_path={}){
    auto a=configured(c);std::vector<std::uint8_t> saved;
    if(mode=="resume"){saved=read(path);pce::restore_checkpoint(a->bus,a->cpu,saved);}
    else{advance(*a,c.write_ticks);ports(*a,c);saved=pce::encode_checkpoint(a->bus,a->cpu);if(mode=="create")write_new(path,saved);}
    check(saved==pce::encode_checkpoint(a->bus,a->cpu),"save or fresh restore changed full machine payload");
    auto b=configured(c);pce::restore_checkpoint(b->bus,b->cpu,saved);
    check(observe(*a)==observe(*b),"restored latch/index/queue fields differ");
    check(a->cpu.native_steps==0&&a->cpu.interpreter_steps==0,"direct device fixture fabricated CPU work");
    if(!mode.empty())std::cout<<"{\"case\":\""<<c.id<<"\",\"scope\":\"host-configured direct device clocks; no opcode retirements\",\"native\":0,\"interpreted\":0,\"checkpoint_sha256\":\""<<hash(saved)<<"\",\"rows\":[";
    for(unsigned i=0;i<model::offsets.size();++i){
        const auto ticks=c.write_ticks+model::offsets[i];advance(*a,ticks);advance(*b,ticks);
        const auto actual=observe(*a);check(actual==observe(*a),"repeated observation mutated device");model::expected(c,actual);++checks;
        check(actual==observe(*b),"restored live latch/indices/queue continuation differs");
        check(a->bus.vdc.video.completed().rgb==b->bus.vdc.video.completed().rgb,"restored completed RGB differs");
        check(pce::encode_checkpoint(a->bus,a->cpu)==pce::encode_checkpoint(b->bus,b->cpu),"full CPU/bus/partial RGB/index/DMA continuation differs");
        if(!mode.empty()){std::cout<<(i?",":"");model::state_json(std::cout,actual);}
    }
    const auto final=pce::encode_checkpoint(a->bus,a->cpu);if(!final_path.empty())write_new(final_path,final);
    if(!mode.empty())std::cout<<"],\"final_payload_sha256\":\""<<hash(final)<<"\"}\n";
}
}
int main(int argc,char** argv){try{
    if(argc==5||argc==6){const std::string mode=argv[2];check(mode=="create"||mode=="resume","explicit create/resume mode required");check(std::string(argv[4])=="json","explicit JSON format required");execute(model::selected(argv[1]),mode,argv[3],argc==6?argv[5]:std::filesystem::path{});}
    else{check(argc==1,"usage: probe CASE create|resume NEW_PRIVATE_CHECKPOINT json [NEW_FINAL_PAYLOAD]");for(const auto& c:model::cases())execute(c);std::cout<<checks<<" authored VDC latch/checkpoint/queue/RGB checks; direct device clocks, zero retired opcodes\n";}
    return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
