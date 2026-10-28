// Authored checkpoint continuations. No emulator state or retail inputs.
#include "pce/checkpoint.hpp"
#include "pce/code_capture.hpp"
#include "adpcm_irq_support.hpp"
#include <filesystem>
#include <fstream>
#include <iterator>
#include <memory>

namespace {
using adpcm_irq::require;
using adpcm_irq::Values;
std::vector<std::uint8_t> read(const std::string& path) {
    std::ifstream in(path,std::ios::binary);require(bool(in),"Cannot open checkpoint");
    return {std::istreambuf_iterator<char>(in),std::istreambuf_iterator<char>()};
}
void write(const std::string& path,const std::vector<std::uint8_t>& bytes) {
    require(!std::filesystem::exists(path),"Checkpoint destination must be new");
    std::ofstream out(path,std::ios::binary);out.write(reinterpret_cast<const char*>(bytes.data()),bytes.size());
    require(bool(out),"Cannot write checkpoint");
}
std::string hash(const std::vector<std::uint8_t>& bytes) {return irq_trace::hash(bytes);}
Values observe(const pce::Bus& b,const pce::Cpu& c,std::uint64_t origin) {
    Values row{c.pc,c.a,c.x,c.y,c.sp,c.p,c.clock_divisor,c.ticks-origin};
    for(unsigned i=0;i<8;++i)row[8+i]=c.mpr[i];
    const auto& a=b.adpcm;
    row[16]=c.mpr_latch;row[17]=c.irq_entries;row[18]=c.irq_vector;row[19]=c.rti_steps;
    row[20]=b.irq.mask;row[21]=b.irq_requests();row[22]=b.vdc.status;row[23]=b.cd.interrupt_enable;
    row[24]=b.cd.interrupt_active;row[25]=(*b.bytes)[0x1F0011];row[26]=(*b.bytes)[0x1F0012];
    row[27]=a.control;row[28]=a.address;row[29]=a.read_address;row[30]=a.write_address;row[31]=a.length;
    row[32]=a.half_irq;row[33]=a.end_irq;row[34]=a.playing;
    row[35]=(a.playing?8:0)|(a.end_irq?1:0)|(a.read_deadline?128:0)|(a.write_deadline?4:0);return row;
}
std::string wram(const pce::Bus& b) {return irq_trace::hash(std::span<const std::uint8_t>(b.bytes->data()+0x1F0000,8192));}
void setup(pce::Bus& b,pce::Cpu& c,const AdpcmIrqCase& item) {
    b.configure_system_card(pce::SystemCardProfile::standard,adpcm_irq_rom(item));
    b.enable_video();b.enable_interrupts();b.enable_adpcm();b.power_on_cpu(c,0,0);
}
void step(pce::Bus& b,pce::Cpu& c,bool native,pce::CodeCapture* capture=nullptr) {
    pce::CodeCapture::Pending pending;if(capture)pending=capture->before(b,c);
    const auto result=native?pce::generated_step(b,c,UINT64_MAX):pce::interpret_step(b,c,UINT64_MAX);
    require(result==pce::Exit::executed,"Authored checkpoint opcode missed; fallback forbidden");
    if(capture)capture->after(pending,c);
}
// Prefix executes only in the creating process. The fresh restoring process
// configures immutable inputs, imports state and captures only the new suffix.
void execute(const AdpcmIrqCase& item,bool native,bool resume,const std::string& path,const std::string& cap) {
    auto machine=std::make_unique<pce::Bus>();auto& b=*machine;pce::Cpu c;setup(b,c,item);
    std::vector<std::uint8_t> saved;
    if(resume) {saved=read(path);pce::restore_checkpoint(b,c,saved);}
    else {
        for(unsigned i=0;i<item.primer_steps;++i)step(b,c,native);
        saved=pce::encode_checkpoint(b,c);write(path,saved);
    }
    require(pce::encode_checkpoint(b,c)==saved,"Checkpoint is not a canonical exact round trip");
    const auto origin=c.ticks,prior_native=c.native_steps,prior_interpreted=c.interpreter_steps;
    require(prior_native==(native?item.primer_steps:0)&&prior_interpreted==(native?0:item.primer_steps),"Imported prefix counters differ");
    adpcm_irq::literal(observe(b,c,origin),wram(b),item.initial,0);
    pce::CodeCapture capture(cap,4096);
    if(resume)capture.set_checkpoint_origin(hash(saved),c.ticks,b.vdc.video.sequence(),c.native_steps,c.interpreter_steps);
    std::cout<<"{\"case\":\""<<item.id<<"\",\"tier\":\""<<(native?"native":"interpreter")
             <<"\",\"origin_ticks\":"<<origin<<",\"imported_native\":"<<prior_native<<",\"imported_interpreted\":"<<prior_interpreted
             <<",\"checkpoint_sha256\":\""<<hash(saved)<<"\",\"initial\":";
    adpcm_irq::row_json(std::cout,observe(b,c,origin),wram(b),0);std::cout<<",\"rows\":[";
    for(unsigned i=0;i<item.steps;++i) {
        const auto entries=c.irq_entries;step(b,c,native,&capture);const auto vector=c.irq_entries>entries?c.irq_vector:0;
        adpcm_irq::literal(observe(b,c,origin),wram(b),item.rows[i],i+1);require(vector==item.rows[i].irq_vector,"Actual checkpoint IRQ vector differs");
        if(i)std::cout<<',';adpcm_irq::row_json(std::cout,observe(b,c,origin),wram(b),vector);
    }
    capture.finish();require(c.pc==item.end_pc,"Checkpoint suffix sentinel differs");
    require(c.native_steps-prior_native==(native?item.steps:0)&&c.interpreter_steps-prior_interpreted==(native?0:item.steps)&&c.guard_misses==0,"Fresh suffix tier/count differs");
    std::cout<<"],\"window_native\":"<<c.native_steps-prior_native<<",\"window_interpreted\":"<<c.interpreter_steps-prior_interpreted
             <<",\"final_state_sha256\":\""<<hash(pce::encode_checkpoint(b,c))<<"\"}\n";
}
void reject(const AdpcmIrqCase& item,const std::string& path,bool mismatch) {
    auto machine=std::make_unique<pce::Bus>();auto& b=*machine;pce::Cpu c;setup(b,c,item);
    // Different complete live CPU state makes a partial destructive load observable.
    c.a=0x87;c.x=0x34;c.ticks=0;c.pc=0xE123;
    if(mismatch)b.psg.centered_dac=false;
    const auto before=pce::encode_checkpoint(b,c);bool rejected=false;
    try {pce::restore_checkpoint(b,c,read(path));}catch(const std::exception&){rejected=true;}
    require(rejected,"Invalid checkpoint accepted");require(before==pce::encode_checkpoint(b,c),"Rejected load changed live state");
    std::cout<<"{\"rejected\":true,\"unchanged\":true,\"before_sha256\":\""<<hash(before)<<"\"}\n";
}
}
int main(int argc,char** argv) {try {
    require(argc==6,"checkpoint create|resume|reject|profile CASE native|interpreter FILE NEW_CAPTURE");
    const std::string mode=argv[1],tier=argv[3];require(tier=="native"||tier=="interpreter","Explicit tier required");
    const auto& item=adpcm_irq_case(argv[2]);
    if(mode=="reject"||mode=="profile")reject(item,argv[4],mode=="profile");
    else {require(mode=="create"||mode=="resume","Unknown checkpoint mode");execute(item,tier=="native",mode=="resume",argv[4],argv[5]);}
    return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
