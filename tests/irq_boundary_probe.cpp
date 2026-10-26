// Authored actual native/interpreter instruction-boundary observer.
#include "pce/runtime.hpp"
#include "pce/code_capture.hpp"
#include "irq_boundary_fixture.hpp"
#include "irq_trace_support.hpp"
#include "reset_probe_support.hpp"
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <memory>
#include <optional>
#include <sstream>
#include <string>

namespace {
std::uint64_t checks=0;
void require(bool ok,const std::string& text){++checks;if(!ok)throw std::runtime_error(text);}
irq_trace::State observe(const pce::Bus& bus,const pce::Cpu& cpu){
    irq_trace::State out;out.pc=cpu.pc;out.a=cpu.a;out.x=cpu.x;out.y=cpu.y;out.sp=cpu.sp;out.p=cpu.p;
    out.mpr=cpu.mpr;out.mpr_latch=cpu.mpr_latch;
    out.clock_divisor=cpu.clock_divisor;out.ticks=cpu.ticks;
    out.wram_sha256=irq_trace::hash(std::span<const std::uint8_t>(bus.bytes->data()+0x1F0000,8192));return out;
}
std::array<std::uint64_t,26> values(const pce::Bus& b,const pce::Cpu& c,std::uint64_t origin){
    std::array<std::uint64_t,26> out{c.pc,c.a,c.x,c.y,c.sp,c.p,c.clock_divisor,c.ticks-origin};
    for(unsigned page=0;page<8;++page)out[8+page]=c.mpr[page];
    out[16]=c.mpr_latch;out[17]=c.irq_entries;out[18]=c.irq_vector;out[19]=c.rti_steps;
    out[20]=b.irq.timer_pending;out[21]=b.irq.mask;out[22]=b.irq.timer_enabled;
    for(unsigned i=0;i<3;++i)out[23+i]=(*b.bytes)[0x1F0010+i];return out;
}
void literal(const pce::Bus& bus,const pce::Cpu& cpu,std::uint64_t origin,const IrqLiteral& wanted,unsigned ordinal){
    const auto first=observe(bus,cpu),second=observe(bus,cpu);
    require(first==second,"Repeated IRQ observation mutated state");
    const auto actual=values(bus,cpu,origin);
    if(actual!=wanted.values){std::cerr<<"ACTUAL";for(auto v:actual)std::cerr<<' '<<v;
        std::cerr<<"\nEXPECTED";for(auto v:wanted.values)std::cerr<<' '<<v;std::cerr<<'\n';
        throw std::runtime_error("Authored IRQ literal differs at ordinal "+std::to_string(ordinal));}
    require(first.wram_sha256==wanted.wram_sha256,"Authored full WRAM/stack hash differs at ordinal "+std::to_string(ordinal));
}
void dump_new(const std::filesystem::path& path,const std::uint8_t* data){
#ifdef _WIN32
    auto* file=_wfopen(path.c_str(),L"wbx");
#else
    auto* file=std::fopen(path.c_str(),"wbx");
#endif
    require(file!=nullptr,"Choose a new private WRAM output");
    const auto written=std::fwrite(data,1,8192,file);const auto closed=std::fclose(file);
    require(written==8192&&closed==0,"WRAM output failed");
}
struct Work {std::uint64_t native=0,interpreter=0,blocks=0,guards=0,origin=0;std::vector<std::array<std::uint64_t,26>> rows;};
Work execute(const std::vector<std::uint8_t>& rom,const IrqCase& item,bool native,bool trace,
             pce::CodeCapture* capture,const char* dump){
    require(rom==irq_rom(item),"Exact authored IRQ ROM required");
    auto owned=std::make_unique<pce::Bus>();auto& bus=*owned;pce::Cpu cpu;
    bus.configure_hucard(rom);bus.enable_video();bus.enable_interrupts();bus.enable_psg();bus.enable_joypad(false,false);bus.power_on_cpu(cpu,0,0);
    auto step=[&]{pce::CodeCapture::Pending pending;if(capture)pending=capture->before(bus,cpu);
        const auto result=native?pce::generated_step(bus,cpu,UINT64_MAX):pce::interpret_step(bus,cpu,UINT64_MAX);
        require(result==pce::Exit::executed,"Authored IRQ opcode missed or refused; fallback forbidden");
        if(capture)capture->after(pending,cpu);};
    for(unsigned i=0;i<item.primer_steps;++i)step();
    Work work;work.origin=cpu.ticks;literal(bus,cpu,work.origin,item.initial,0);
    if(native){
        const auto before=observe(bus,cpu);const auto devices=values(bus,cpu,work.origin);const auto generations=bus.generation;
        auto guard=[&](pce::Cpu trial,std::uint64_t deadline,pce::Exit expected){const auto state=observe(bus,trial);
            require(pce::generated_step(bus,trial,deadline)==expected,"IRQ native source/deadline guard failed");
            require(observe(bus,trial)==state&&observe(bus,cpu)==before&&values(bus,cpu,work.origin)==devices&&bus.generation==generations,
                    "IRQ guard advanced CPU/WRAM/device state");++work.guards;};
        guard(cpu,cpu.ticks,pce::Exit::budget);auto wrong=cpu;wrong.mpr[3]^=1;guard(wrong,UINT64_MAX,pce::Exit::miss);
        auto source=cpu;const auto physical=pce::Bus::physical(source,source.pc);const auto byte=(*bus.bytes)[physical];
        (*bus.bytes)[physical]^=255;guard(source,UINT64_MAX,pce::Exit::miss);(*bus.bytes)[physical]=byte;
        source.pc=0xF802;const auto operand=pce::Bus::physical(source,source.pc+2);const auto old=(*bus.bytes)[operand];
        (*bus.bytes)[operand]^=1;guard(source,UINT64_MAX,pce::Exit::miss);(*bus.bytes)[operand]=old;
    }
    if(trace)irq_trace::write_initial(std::cout,observe(bus,cpu));
    for(unsigned ordinal=1;ordinal<=item.steps;++ordinal){
        const auto entry=observe(bus,cpu);const auto entries=cpu.irq_entries;step();
        literal(bus,cpu,work.origin,item.runtime_rows[ordinal-1],ordinal);
        require(cpu.irq_entries-entries==item.runtime_rows[ordinal-1].irq_count,"Actual IRQ delivery ordinal differs");
        const auto vector=cpu.irq_entries!=entries?std::optional<std::uint16_t>{cpu.irq_vector}:std::nullopt;
        require((vector?*vector:0)==item.runtime_rows[ordinal-1].irq_vector,"Actual hardware IRQ vector differs");
        const auto after=observe(bus,cpu);work.rows.push_back(values(bus,cpu,work.origin));
        if(trace){irq_trace::write_event(std::cout,ordinal,"opcode",entry,after,vector);
            irq_trace::write_instruction(std::cout,ordinal,ordinal,ordinal,entry,after,vector);}
    }
    require(cpu.pc==item.end_pc,"Authored IRQ sentinel was not reached");
    const auto total=item.primer_steps+item.steps;
    require(cpu.native_steps==(native?total:0)&&cpu.interpreter_steps==(native?0:total)&&cpu.guard_misses==0,
            "Actual whole-primer/measured instruction accounting differs");
    require(cpu.native_block_steps==(native?1U:0U)&&cpu.interpreter_block_steps==(native?0U:1U),"Software WRAM-clear TII accounting differs");
    if(trace)irq_trace::write_final(std::cout,item.steps,item.steps,observe(bus,cpu));
    if(dump)dump_new(std::filesystem::path(dump),bus.bytes->data()+0x1F0000);
    work.native=cpu.native_steps;work.interpreter=cpu.interpreter_steps;work.blocks=cpu.native_block_steps+cpu.interpreter_block_steps;return work;
}
}
int main(int argc,char** argv){try{
    if(argc==1){for(const auto& item:irq_cases)for(bool native:{false,true})execute(irq_rom(item),item,native,false,nullptr,nullptr);
        std::cout<<checks<<" authored software IRQ boundary checks; both tiers, no fallback\n";return 0;}
    require(argc==7,"irq-boundary-probe ROM CASE native|interpreter NEW_CAPTURE NEW_WRAM NEW_EXECUTION_JSON");
    const auto& item=irq_case(argv[2]);const std::string tier=argv[3];require(tier=="native"||tier=="interpreter","Explicit IRQ tier required");
    require(!std::filesystem::exists(argv[6]),"New IRQ execution report required");pce::CodeCapture capture(argv[4],4096);
    const auto work=execute(reset_probe::rom(argv[1]),item,tier=="native",true,&capture,argv[5]);capture.finish();
    std::ostringstream report;
    report<<"{\"schema\":1,\"case\":\""<<item.id<<"\",\"tier\":\""<<tier<<"\",\"primer_steps\":"<<item.primer_steps
        <<",\"measured_steps\":"<<item.steps<<",\"native_steps\":"<<work.native<<",\"interpreter_steps\":"<<work.interpreter
        <<",\"block_steps\":"<<work.blocks<<",\"pure_guards\":"<<work.guards<<",\"raw_initial_ticks\":"<<work.origin<<",\"literal_rows\":[";
    for(unsigned i=0;i<work.rows.size();++i){report<<(i?",":"")<<'[';for(unsigned j=0;j<26;++j)report<<(j?",":"")<<work.rows[i][j];report<<']';}
    report<<"]}\n";const auto text=report.str();
    const auto path=std::filesystem::path(argv[6]);
#ifdef _WIN32
    auto* output=_wfopen(path.c_str(),L"wbx");
#else
    auto* output=std::fopen(path.c_str(),"wbx");
#endif
    require(output!=nullptr,"Choose a new private IRQ execution report");
    const auto written=std::fwrite(text.data(),1,text.size(),output);const auto closed=std::fclose(output);
    require(written==text.size()&&closed==0,"IRQ execution report write failed");return 0;
}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}}
