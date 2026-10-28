// Authored guest-only ADPCM source generation and native/interpreter boundaries.
#include "pce/runtime.hpp"
#include "pce/code_capture.hpp"
#include "adpcm_irq_support.hpp"
#include "reset_probe_support.hpp"
#include <memory>
#ifndef PCE_ADPCM_IRQ_CUE
#define PCE_ADPCM_IRQ_CUE ""
#endif
namespace {
using namespace adpcm_irq;
Values observe(const pce::Bus& b,const pce::Cpu& c,std::uint64_t origin){
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
std::string wram(const pce::Bus& b){return irq_trace::hash(std::span<const std::uint8_t>(b.bytes->data()+0x1F0000,8192));}
void execute(const AdpcmIrqCase& item,bool native,bool report,pce::CodeCapture* capture){
    auto owned=std::make_unique<pce::Bus>();auto& b=*owned;pce::Cpu c;
    b.configure_system_card(pce::SystemCardProfile::standard,adpcm_irq_rom(item));
    b.enable_video();b.enable_interrupts();b.enable_adpcm();b.power_on_cpu(c,0,0);
    auto step=[&]{pce::CodeCapture::Pending pending;if(capture)pending=capture->before(b,c);
        const auto result=native?pce::generated_step(b,c,UINT64_MAX):pce::interpret_step(b,c,UINT64_MAX);
        require(result==pce::Exit::executed,"ADPCM authored opcode missed; fallback forbidden");
        if(capture)capture->after(pending,c);};
    for(unsigned i=0;i<item.primer_steps;++i)step();
    const auto origin=c.ticks;literal(observe(b,c,origin),wram(b),item.initial,0);
    unsigned guards=0;
    if(native){
        const auto before=observe(b,c,origin);const auto before_ram=wram(b);const auto generations=b.generation;
        auto guard=[&](pce::Cpu trial,std::uint64_t deadline,pce::Exit wanted){
            const auto state=observe(b,trial,origin);
            require(pce::generated_step(b,trial,deadline)==wanted,"ADPCM IRQ pure guard failed");
            require(observe(b,trial,origin)==state&&observe(b,c,origin)==before&&wram(b)==before_ram&&b.generation==generations,"ADPCM IRQ guard mutated state");++guards;};
        guard(c,c.ticks,pce::Exit::budget);auto wrong=c;wrong.mpr[3]^=1;guard(wrong,UINT64_MAX,pce::Exit::miss);
        const auto at=pce::Bus::physical(c,c.pc);const auto byte=(*b.bytes)[at];(*b.bytes)[at]^=255;
        guard(c,UINT64_MAX,pce::Exit::miss);(*b.bytes)[at]=byte;
        auto target=c;target.pc=0xF843;const auto operand=pce::Bus::physical(target,target.pc+1);const auto old=(*b.bytes)[operand];
        (*b.bytes)[operand]^=1;guard(target,UINT64_MAX,pce::Exit::miss);(*b.bytes)[operand]=old;
    }
    if(report){std::cout<<"{\"case\":\""<<item.id<<"\",\"tier\":\""<<(native?"native":"interpreter")<<"\",\"origin_ticks\":"<<origin<<",\"initial\":";
        row_json(std::cout,observe(b,c,origin),wram(b),0);std::cout<<",\"rows\":[";}
    for(unsigned i=0;i<item.steps;++i){const auto entries=c.irq_entries;step();const auto vector=c.irq_entries>entries?c.irq_vector:0;
        literal(observe(b,c,origin),wram(b),item.rows[i],i+1);require(vector==item.rows[i].irq_vector,"ADPCM CPU delivery vector differs");
        if(report){if(i)std::cout<<',';row_json(std::cout,observe(b,c,origin),wram(b),vector);}}
    require(c.pc==item.end_pc,"ADPCM IRQ sentinel differs");const auto total=item.primer_steps+item.steps;
    require(c.native_steps==(native?total:0)&&c.interpreter_steps==(native?0:total)&&c.guard_misses==0,"ADPCM full execution tier/count differs");
    require(c.native_block_steps+c.interpreter_block_steps==item.block_steps,"Actual block count differs");
    if(report)std::cout<<"],\"native\":"<<c.native_steps<<",\"interpreted\":"<<c.interpreter_steps<<",\"block_steps\":"<<item.block_steps<<",\"guards\":"<<guards<<"}\n";
}
}
int main(int argc,char** argv){try{
    if(argc==1){for(const auto& item:adpcm_irq_cases)for(bool native:{false,true})execute(item,native,false,nullptr);
        std::cout<<adpcm_irq::checks<<" authored ADPCM HALF/END CPU IRQ checks; both tiers, zero fallback\n";return 0;}
    adpcm_irq::require(argc==4,"adpcm-irq CASE native|interpreter NEW_CAPTURE");
    const std::string tier=argv[2];adpcm_irq::require(tier=="native"||tier=="interpreter","Explicit tier required");
    pce::CodeCapture capture(argv[3],4096);execute(adpcm_irq_case(argv[1]),tier=="native",true,&capture);capture.finish();return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}



