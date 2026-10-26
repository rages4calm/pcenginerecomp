// Authored accounting observer around the separately built ORIGINAL core.
// It observes the exact RunSub entry decision; the original core performs
// every opcode, stack write, interrupt entry, block transfer and device clock.
#include <libretro.h>
#include <mednafen/pce/pce.h>
#include <mednafen/pce/huc.h>
#include <mednafen/pce/vce.h>
#include "irq_trace_support.hpp"
#include <cstdarg>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <memory>
#include <sstream>
#include <stdexcept>

extern VCE* vce;
namespace {
std::string private_directory;
void log_message(enum retro_log_level,const char* format,...) {
    va_list values;va_start(values,format);std::vfprintf(stderr,format,values);va_end(values);
}
bool environment(unsigned command,void* data) {
    switch(command) {
    case RETRO_ENVIRONMENT_GET_SYSTEM_DIRECTORY:case RETRO_ENVIRONMENT_GET_SAVE_DIRECTORY:
        *static_cast<const char**>(data)=private_directory.c_str();return true;
    case RETRO_ENVIRONMENT_GET_LOG_INTERFACE:static_cast<retro_log_callback*>(data)->log=log_message;return true;
    case RETRO_ENVIRONMENT_SET_PIXEL_FORMAT:return true;
    default:return false;
    }
}
void video(const void*,unsigned,unsigned,std::size_t){}
void audio(std::int16_t,std::int16_t){}
std::size_t audio_batch(const std::int16_t*,std::size_t count){return count;}
void poll(){}
std::int16_t input(unsigned,unsigned,unsigned,unsigned){return 0;}
int32 MDFN_FASTCALL clock_devices(int32 timestamp){return vce->SyncReal(timestamp);}

template<class T,typename T::type Member>struct Access{friend typename T::type member(T){return Member;}};
#define FIELD(Name,Type,Field) struct Name{using type=Type HuC6280::*;friend type member(Name);};template struct Access<Name,&HuC6280::Field>;
FIELD(PC,uint32,PC) FIELD(A,uint8,A) FIELD(X,uint8,X) FIELD(Y,uint8,Y) FIELD(S,uint8,S) FIELD(P,uint8,P) FIELD(Speed,uint8,speed)
FIELD(Sampled,int32,IRQSample) FIELD(Lines,uint32,IRQlow) FIELD(Mask,uint8,IRQMask) FIELD(SampledI,int32,IFlagSample)
FIELD(PIMask,uint32,PIMaskCache) FIELD(Block,uint32,in_block_move) FIELD(Running,int32,runrunrun)
FIELD(Overclock,uint32,overclock_rate) FIELD(Wai,bool,EmulateWAI)
struct MPR{using type=uint8(HuC6280::*)[9];friend type member(MPR);};template struct Access<MPR,&HuC6280::MPR>;
#undef FIELD

struct Pipeline {
    std::int32_t sampled,sampled_i,running;
    std::uint32_t lines,enabled_mask,pi_mask,block,overclock,pc,ticks,p;
    bool wai;
    bool operator==(const Pipeline&)const=default;
};
struct Observation {irq_trace::State state;Pipeline pipeline;bool operator==(const Observation&)const=default;};
Observation observe() {
    Observation out;auto& s=out.state;
    s.pc=static_cast<std::uint16_t>(HuCPU.*member(PC{}));s.a=HuCPU.*member(A{});s.x=HuCPU.*member(X{});s.y=HuCPU.*member(Y{});
    s.sp=HuCPU.*member(S{});s.p=HuCPU.*member(P{});s.clock_divisor=(HuCPU.*member(Speed{}))?3:12;s.ticks=HuCPU.Timestamp();s.mpr_latch=std::nullopt;
    for(unsigned page=0;page<8;++page)s.mpr[page]=(HuCPU.*member(MPR{}))[page];
    s.wram_sha256=reference_trace::hash(std::span<const std::uint8_t>(BaseRAM,8192));
    out.pipeline={HuCPU.*member(Sampled{}),HuCPU.*member(SampledI{}),HuCPU.*member(Running{}),HuCPU.*member(Lines{}),HuCPU.*member(Mask{}),
        HuCPU.*member(PIMask{}),HuCPU.*member(Block{}),HuCPU.*member(Overclock{}),HuCPU.*member(PC{}),HuCPU.Timestamp(),HuCPU.*member(P{}),HuCPU.*member(Wai{})};
    return out;
}
Observation pure_observe() {
    const auto first=observe(),second=observe();
    if(first!=second)throw std::runtime_error("Repeated original CPU/IRQ/WRAM observation changed state");
    return first;
}
enum class Kind {opcode,continuation,irq,reset};
struct Decision {Kind kind;std::optional<std::uint16_t> vector;};
const char* label(Kind kind) {
    switch(kind){case Kind::opcode:return "opcode";case Kind::continuation:return "block-continuation";case Kind::irq:return "irq-entry";case Kind::reset:return "reset";}
    throw std::runtime_error("Unknown original call classification");
}
Decision classify(const Pipeline& p) {
    if(p.overclock!=1 || p.wai || p.enabled_mask>7 || (p.sampled_i!=0 && p.sampled_i!=HuC6280::I_FLAG))
        throw std::runtime_error("Unsupported original CPU stepping configuration");
    if(p.block) {
        if(p.block>5)throw std::runtime_error("Unknown original block continuation");
        return {Kind::continuation,std::nullopt};
    }
    // Observe the original branch inputs, including its timer exception and
    // sampled IRQ1/2 priority. Live P is deliberately not the decision rule.
    if(std::uint32_t(p.sampled)|p.lines) {
        if(std::uint32_t(p.sampled)&HuC6280::IQRESET)return {Kind::reset,std::nullopt};
        if((p.lines&HuC6280::IQTIMER&p.enabled_mask) && !p.sampled_i)return {Kind::irq,0xFFFA};
        if(std::uint32_t(p.sampled)&HuC6280::IQIRQ1)return {Kind::irq,0xFFF8};
        if(std::uint32_t(p.sampled)&HuC6280::IQIRQ2)return {Kind::irq,0xFFF6};
    }
    return {Kind::opcode,std::nullopt};
}
void pipeline_json(std::ostream& out,const Pipeline& p) {
    out<<"{\"irq_sample\":"<<p.sampled<<",\"irq_low\":"<<p.lines<<",\"irq_enabled_mask\":"<<p.enabled_mask
       <<",\"i_flag_sample\":"<<p.sampled_i<<",\"pi_mask_cache\":"<<p.pi_mask<<",\"in_block_move\":"<<p.block
       <<",\"runrunrun\":"<<p.running<<",\"overclock\":"<<p.overclock<<",\"emulate_wai\":"<<(p.wai?"true":"false")
       <<",\"raw_pc\":"<<p.pc<<",\"p\":"<<p.p<<",\"ticks\":"<<p.ticks<<'}';
}
class Journal {
    struct Close {void operator()(std::FILE* file)const{if(file)std::fclose(file);}};
    std::unique_ptr<std::FILE,Close> file;
    std::size_t bytes=0;
public:
    unsigned calls=0;
    explicit Journal(const std::filesystem::path& path) {
#ifdef _WIN32
        file.reset(_wfopen(path.c_str(),L"wx"));
#else
        file.reset(std::fopen(path.c_str(),"wx"));
#endif
        if(!file)throw std::runtime_error("Choose a NEW private call journal");
        write("{\"type\":\"header\",\"schema\":1,\"format\":\"pce-beetle-call-journal-1\",\"decision\":\"original-runsub-irq-pipeline-v1\"}\n");
    }
    void write(const std::string& text) {
        if(text.size()>64*1024*1024-bytes)throw std::runtime_error("Original call journal byte bound exceeded");
        if(std::fwrite(text.data(),1,text.size(),file.get())!=text.size() || std::fflush(file.get()))throw std::runtime_error("Original call journal write failed");
        bytes+=text.size();
    }
    void call(const char* phase,unsigned opcode,const Decision& decision,const Pipeline& before,const Pipeline& after) {
        if(++calls>99997)throw std::runtime_error("Original call journal record bound exceeded");
        std::ostringstream out;out<<"{\"type\":\"call\",\"ordinal\":"<<calls<<",\"phase\":\""<<phase<<"\",\"opcode_ordinal\":"<<opcode
            <<",\"kind\":\""<<label(decision.kind)<<"\",\"irq_vector\":";irq_trace::vector(out,decision.vector);
        out<<",\"entry\":";pipeline_json(out,before);out<<",\"state\":";pipeline_json(out,after);out<<"}\n";write(out.str());
    }
    void finish(unsigned measured,unsigned primer,unsigned events) {
        std::ostringstream out;out<<"{\"type\":\"final\",\"calls\":"<<calls<<",\"measured_instructions\":"<<measured<<",\"primer_instructions\":"<<primer<<",\"measured_events\":"<<events<<",\"complete\":true}\n";write(out.str());
    }
};
unsigned events=0,completed=0;
Observation invoke(Journal& journal,const char* phase,unsigned ordinal,Kind expected,bool measured) {
    const auto before=pure_observe();const auto decision=classify(before.pipeline);
    if(decision.kind!=expected)throw std::runtime_error("Unexpected original RunSub decision before call");
    if(journal.calls>=99997 || (measured && events+completed+3>=100000))throw std::runtime_error("Original trace record bound exceeded before execution");
    HuCPU.Run(true); // Original core executes precisely its selected path.
    const auto after=pure_observe();journal.call(phase,ordinal,decision,before.pipeline,after.pipeline);
    if(expected!=Kind::reset && after.state.ticks<=before.state.ticks)throw std::runtime_error("Original call clock wrapped or failed to progress");
    if(expected==Kind::irq && (after.pipeline.block || !(after.state.p&HuC6280::I_FLAG)))throw std::runtime_error("Unexpected original IRQ-entry result");
    if(measured)irq_trace::write_event(std::cout,++events,label(expected),before.state,after.state,decision.vector);
    return after;
}
void step_opcode(Journal& journal,const char* phase,unsigned ordinal,bool measured) {
    const auto entry=pure_observe().state;const unsigned start=events+1;
    auto after=invoke(journal,phase,ordinal,Kind::opcode,measured);
    while(after.pipeline.block)after=invoke(journal,phase,ordinal,Kind::continuation,measured);
    const auto decision=classify(after.pipeline);std::optional<std::uint16_t> vector;
    if(decision.kind==Kind::irq) {vector=decision.vector;after=invoke(journal,phase,ordinal,Kind::irq,measured);}
    if(classify(after.pipeline).kind!=Kind::opcode)throw std::runtime_error("Reset or ambiguous original boundary after retirement");
    if(measured) {irq_trace::write_instruction(std::cout,ordinal,start,events,entry,after.state,vector);++completed;}
}
unsigned count(const char* text,unsigned maximum) {
    const std::string value=text;std::size_t used=0;const auto n=std::stoul(value,&used);
    if(used!=value.size() || n>maximum)throw std::runtime_error("Bounded integer required");return static_cast<unsigned>(n);
}
void dump_new(const std::filesystem::path& path) {
#ifdef _WIN32
    auto* file=_wfopen(path.c_str(),L"wx");
#else
    auto* file=std::fopen(path.c_str(),"wx");
#endif
    if(!file)throw std::runtime_error("Choose NEW private WRAM output");
    const auto n=std::fwrite(BaseRAM,1,8192,file);const auto closed=std::fclose(file);
    if(n!=8192 || closed)throw std::runtime_error("Final WRAM write failed");
}
}
int main(int argc,char**argv) {
    try {
        std::cout<<std::unitbuf;
        if(argc!=6)throw std::runtime_error("beetle-irq AUTHORED_ROM MEASURED_STEPS PRIMER_STEPS NEW_WRAM NEW_CALL_JOURNAL");
        const auto steps=count(argv[2],30000),primer=count(argv[3],10000);
        if(!steps)throw std::runtime_error("At least one actual opcode required");
        const auto rom=std::filesystem::absolute(argv[1]),dump=std::filesystem::absolute(argv[4]),journal_path=std::filesystem::absolute(argv[5]);
        if(!std::filesystem::is_regular_file(rom) || std::filesystem::file_size(rom)!=262144 || std::filesystem::exists(dump) || std::filesystem::exists(journal_path) || dump==journal_path)
            throw std::runtime_error("Require authored HuCard and distinct NEW private outputs");
        private_directory=dump.parent_path().string();Journal journal(journal_path);
        retro_set_environment(environment);retro_set_video_refresh(video);retro_set_audio_sample(audio);retro_set_audio_sample_batch(audio_batch);retro_set_input_poll(poll);retro_set_input_state(input);retro_init();
        const auto name=rom.string();const retro_game_info info{name.c_str(),nullptr,0,nullptr};
        if(!retro_load_game(&info) || PCE_IsCD)throw std::runtime_error("Original HuCard load failed");
        std::vector<bpp_t> pixels(2048*264);std::array<int32,264> widths{};MDFN_Rect display{};MDFN_Surface surface{pixels.data(),2048,264,2048};
        vce->SetPixelFormat(nullptr,0);vce->StartFrame(&surface,&display,widths.data(),false);vce->SetCDEvent(0x3FFFFFFF);HuCPU.SetEventHandler(clock_devices);
        const auto reset=invoke(journal,"reset",0,Kind::reset,false);
        if(reset.state.ticks!=0 || reset.state.p!=4 || reset.state.clock_divisor!=12 || classify(reset.pipeline).kind!=Kind::opcode)
            throw std::runtime_error("Unexpected original reset boundary");
        for(unsigned n=1;n<=primer;++n)step_opcode(journal,"primer",n,false);
        irq_trace::write_initial(std::cout,pure_observe().state);
        for(unsigned n=1;n<=steps;++n)step_opcode(journal,"measured",n,true);
        const auto final=pure_observe().state;dump_new(dump);journal.finish(steps,primer,events);irq_trace::write_final(std::cout,steps,events,final);
        retro_unload_game();retro_deinit();return 0;
    }catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
}
