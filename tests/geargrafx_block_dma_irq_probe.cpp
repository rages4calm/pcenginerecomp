// Original Gear guest CPU execution. Observer only; original sources remain separate.
#include "geargrafx_core.h"
#include "huc6280.h"
#include "huc6270.h"
#include "huc6260.h"
#include "memory.h"
#include "media.h"
#include "cdrom.h"
#include "adpcm.h"
#include "scsi_controller.h"
#include "audio.h"
#include "trace_logger.h"
#include "block_dma_irq_support.hpp"
#include <filesystem>
#if defined(GG_DISABLE_DISASSEMBLER)
#error Actual original CPU and IRQ callbacks must be enabled
#endif
bool g_mcp_stdio_mode=true;
namespace {
using namespace block_dma;
struct ClockTag{using type=bool(GeargrafxCore::*)(u32);friend type member(ClockTag);};
template<class Tag,typename Tag::type Member>struct Access{friend typename Tag::type member(Tag){return Member;}};
template struct Access<ClockTag,&GeargrafxCore::ClockHardware<true,false,false>>;
struct Context{
 GeargrafxCore* core;std::uint64_t drained=0,calls=0,ticks=0;std::vector<std::array<std::uint64_t,3>> spans;
 static void clock(void* pointer,u32 n){auto& a=*static_cast<Context*>(pointer);const auto before=a.core->GetMasterClockCycles();(a.core->*member(ClockTag{}))(n);const auto after=a.core->GetMasterClockCycles();require(after==before+n,"Original callback clock continuity");a.spans.push_back({before,n,after});++a.calls;a.ticks+=n;if(after-a.drained>=4096){a.core->GetAudio()->EndFrame(nullptr,nullptr);a.drained=after;}}
};
struct Record{Source source;Row before;std::uint64_t ticks,internal;unsigned vector,index;bool cause;std::vector<std::array<std::uint64_t,3>> clocks;std::vector<Row> calls,callbacks;Observation after;};
struct Adapter{
 mutable GeargrafxCore core;Context context{&core};Work work;bool window=false;std::map<Source,std::uint64_t> sources;std::vector<Record> journal;const BlockDmaCase& recipe;unsigned entries=0,rtis=0,causes=0,blocks=0;std::uint64_t writes=0;
 Adapter(const char* rom,const char* cue,const BlockDmaCase& c):recipe(c){core.Init(nullptr);core.GetMedia()->SetConsoleType(GG_CONSOLE_PCE);core.GetMedia()->SetCDROMType(GG_CDROM_STANDARD);core.GetHuC6280()->SetResetValue(0);core.GetMemory()->SetResetValues(0,0,0,0);core.GetHuC6260()->SetResetValue(0);core.GetHuC6270_1()->SetSafeDefaults(false);core.GetScsiController()->SetResetValue(0);auto image=reset_probe::rom(rom);require(core.LoadBiosFromBuffer(image.data(),int(image.size()),true)&&core.LoadMedia(cue,false)&&core.GetMedia()->IsCDROMHardwareEnabled()&&!core.GetMedia()->IsSGX()&&core.GetMemory()->GetCardRAMSize()==0,"Actual original StandardCD required");core.GetHuC6280()->SetHardwareClock(Context::clock,&context);auto* logger=core.GetTraceLogger();require(logger->SetCapacity(8192),"Original logger capacity");logger->SetEnabledFlags(TRACE_FLAG_CPU|TRACE_FLAG_CPU_IRQ|TRACE_FLAG_ADPCM|TRACE_FLAG_CDROM);logger->SetEventFilter(TRACE_ADPCM,TRACE_ADPCM_FILTER_ALL);logger->SetEventFilter(TRACE_CDROM,TRACE_CDROM_FILTER_ALL);}
 unsigned pc()const{return core.GetHuC6280()->GetState()->PC->GetValue();}
 std::vector<unsigned> wram()const{auto*p=core.GetMemory()->GetWorkingRAM();return {p,p+8192};}
 std::vector<unsigned> ram()const{auto*p=core.GetAdpcm()->GetRAM();return {p,p+65536};}
 Observation observe()const{auto*c=core.GetHuC6280()->GetState();auto*a=core.GetAdpcm()->GetState();auto*d=core.GetCDROM()->GetState();Observation o;
  o.values={c->PC->GetValue(),c->A->GetValue(),c->X->GetValue(),c->Y->GetValue(),c->S->GetValue(),c->P->GetValue(),*c->SPEED?3u:12u,core.GetMasterClockCycles(),entries,rtis,*c->IDR,*c->IRR,*d->ENABLED_IRQS,*d->ACTIVE_IRQS,*core.GetScsiController()->GetState()->SIGNALS,*a->DMA,*a->LENGTH,*a->WRITE_ADDRESS,*a->HALF_IRQ,*a->END_IRQ,writes,(core.GetAdpcm()->GetStatusRegisterSnapshot()&4)?1u:0u,(*d->ENABLED_IRQS&*d->ACTIVE_IRQS)?1u:0u};
  auto*p=core.GetMemory()->GetWorkingRAM();o.stack.assign(p+256,p+512);o.wram=irq_trace::hash(std::span<const std::uint8_t>(p,8192));return o;
 }
 void measured(){work={};sources.clear();journal.clear();window=true;}
 void step(){auto*cpu=core.GetHuC6280();auto*c=cpu->GetState();auto*logger=core.GetTraceLogger();Source source{c->PC->GetValue(),{},{}};for(unsigned i=0;i<8;++i)source.mpr[i]=core.GetMemory()->GetMpr(i);
  const Row prior{c->A->GetValue(),c->X->GetValue(),c->Y->GetValue(),c->S->GetValue(),c->P->GetValue(),entries,*core.GetAdpcm()->GetState()->HALF_IRQ,*core.GetAdpcm()->GetState()->END_IRQ};logger->Reset();context.spans.clear();const auto clock_origin=context.calls;
  unsigned seen=0,instructions=0,vector=0,group_calls=0;bool complete=false,keep_cause=false;std::uint64_t ticks=0,internal=0;std::vector<Row>call_rows,events;
  do{require(++group_calls<=length+2,"Original finite continuation group exceeded");const auto first=context.spans.size();const auto returned=cpu->RunInstruction(&complete),clocked=cpu->GetClockedMasterCycles();const auto internal_end=context.spans.size();require(clocked<=returned,"Original internal clock partition differs");if(returned>clocked)Context::clock(&context,returned-clocked);require(context.spans.size()-first<=16,"Original per-call hardware callback bound exceeded");ticks+=returned;internal+=clocked;unsigned call_causes=0,call_irqs=0;
   for(;seen<logger->GetCount();++seen){const auto&e=logger->GetEntry(seen);if(e.type==TRACE_CPU){++instructions;require(e.cpu.pc==source.pc&&e.cpu.bank==source.mpr[source.pc>>13],"Original fetched source differs");for(unsigned n=0;n<e.cpu.size;++n)source.bytes.push_back(e.cpu.opcodes[n]);}
    else if(e.type==TRACE_CPU_IRQ){++entries;++work.irqs;++call_irqs;vector=e.irq.vector;require(complete,"Original IRQ delivered during incomplete block");events.push_back({group_calls,e.cycle,unsigned(e.type),e.irq.vector,e.irq.pc,e.irq.irq_mask});}
    else if(e.type==TRACE_ADPCM){if(e.adpcm.event==TRACE_ADPCM_WRITE_COMPLETE)++writes;const unsigned flag=e.adpcm.event==TRACE_ADPCM_HALF_IRQ&&e.adpcm.value==1?1:e.adpcm.event==TRACE_ADPCM_END_IRQ&&e.adpcm.value==1?2:0;if(flag&&!(causes&flag)){causes|=flag;call_causes|=flag;keep_cause=true;}events.push_back({group_calls,e.cycle,unsigned(e.type),e.adpcm.event,e.adpcm.length,e.adpcm.address,e.adpcm.reg,e.adpcm.value,e.adpcm.state});}
    else if(e.type==TRACE_CDROM)events.push_back({group_calls,e.cycle,unsigned(e.type),e.cdrom.event,e.cdrom.irq_type,e.cdrom.active,e.cdrom.enabled});else throw std::runtime_error("Unexpected original callback");}
   require(instructions==1&&!source.bytes.empty()&&logger->GetCount()==logger->GetTotalLogged(),"Original instruction trace missing/lost");if(call_causes)require(block(source.bytes[0])&&!complete&&!(prior[4]&4)&&prior[5]==0,"First actual IRQ source did not arise inside incomplete unmasked block");
   call_rows.push_back({group_calls,returned,clocked,complete?1u:0u,first,internal_end,context.spans.size(),call_causes,call_irqs});
  }while(!complete);
  const bool is_block=block(source.bytes[0]);const unsigned index=blocks+unsigned(is_block);require(group_calls==(is_block?length+2:1),"Original continuation calls counted as wrong instruction");
  if(is_block){++blocks;++work.blocks;work.block_bytes+=length;require(ticks==std::uint64_t(17+6*length+(vector?8:0))*recipe.divisor,"Independent original block clock total differs");}if(keep_cause)++work.cause_blocks;
  if(source.bytes[0]==0x40){++rtis;++work.rtis;rti_frame(observe(),recipe);}++sources[source];++work.instructions;work.calls+=group_calls;work.clock_calls+=context.calls-clock_origin;work.clock_ticks+=ticks;
  if(vector){require(vector==0xfff6,"Unexpected original IRQ vector");irq_frame(source,prior,observe(),index,recipe);}
  if(vector||keep_cause||(window&&(work.instructions<=16||(source.pc>=0xf800&&source.pc<0xf820))))journal.push_back({source,prior,ticks,internal,vector,index,keep_cause,context.spans,call_rows,events,observe()});
 }
};
void records(const std::vector<Record>&rows){std::cout<<'[';bool first=true;for(const auto&r:rows){std::cout<<(first?"":",")<<'{';source_json(std::cout,r.source);std::cout<<",\"before\":";vec(std::cout,r.before);std::cout<<",\"ticks\":"<<r.ticks<<",\"internal\":"<<r.internal<<",\"vector\":"<<r.vector<<",\"block_index\":"<<r.index<<",\"cause\":"<<(r.cause?"true":"false")<<",\"clocks\":[";for(unsigned i=0;i<r.clocks.size();++i){if(i)std::cout<<',';vec(std::cout,r.clocks[i]);}std::cout<<"],\"call_rows\":[";for(unsigned i=0;i<r.calls.size();++i){if(i)std::cout<<',';vec(std::cout,r.calls[i]);}std::cout<<"],\"callbacks\":[";for(unsigned i=0;i<r.callbacks.size();++i){if(i)std::cout<<',';vec(std::cout,r.callbacks[i]);}std::cout<<"],\"after\":";observation(std::cout,r.after);std::cout<<'}';first=false;}std::cout<<']';}
}
int main(int argc,char**argv){try{require(argc==5,"CASE ROM CUE CUT");const auto& c=block_dma_case(argv[1]);const unsigned cut=std::stoul(argv[4]);require(cut<2,"Two cuts only");Adapter a(argv[2],argv[3],c);reach(a,cut_pc(a,c,cut));const auto initial=a.observe();const auto prefix=a.work;const auto prefix_hits=a.sources;const auto prefix_journal=a.journal;a.measured();finish(a,c);final_checks(a,c);
 std::cout<<"{\"dma_counter_role\":\"committed-writes\",\"case\":\""<<c.id<<"\",\"cut_id\":"<<cut<<",\"tier\":\"gear\",\"cut\":";observation(std::cout,initial);std::cout<<",\"final\":";observation(std::cout,a.observe());std::cout<<",\"prefix_work\":";work_json(std::cout,prefix);std::cout<<",\"window_work\":";work_json(std::cout,a.work);std::cout<<",\"prefix_hits\":";hits(std::cout,prefix_hits);std::cout<<",\"window_hits\":";hits(std::cout,a.sources);std::cout<<",\"prefix_journal\":";records(prefix_journal);std::cout<<",\"journal\":";records(a.journal);std::cout<<",\"ram\":";vec(std::cout,a.ram());std::cout<<"}\n";return 0;
 }catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
