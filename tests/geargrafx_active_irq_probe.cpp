// Authored active-display IRQ observations; original Gear is built separately.
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
#include "active_irq_support.hpp"
#include "geargrafx_active_irq_observer.hpp"
#if defined(GG_DISABLE_DISASSEMBLER)
#error Original CPU/device callbacks must remain enabled
#endif
bool g_mcp_stdio_mode=true;
namespace {
using namespace active_irq;
using active_irq_gear::Extra;
using active_irq_gear::Pending;
using active_irq_gear::Dma;
using active_irq_gear::ReadPending;
using active_irq_gear::WritePending;
using active_irq_gear::Delay;
using VramBus=active_irq_gear::Latch;
using Context=active_irq_gear::Context;
using Edge=active_irq_gear::Edge;
struct Record{Source source;Row before;std::uint64_t ticks,internal,waits;unsigned vector,causes;std::vector<Row>clocks,calls,callbacks;std::vector<Edge>edges;Observation after;active_irq_gear::Kernel active_before;};
struct Adapter{
 mutable GeargrafxCore core;Context context{&core};const ActiveIrqCase&recipe;Work work;bool window=false;std::map<Source,std::uint64_t>sources;std::vector<Record>journal;unsigned entries=0,rtis=0,last_vector=0,seen_causes=0;std::uint64_t writes=0,total_waits=0;
 Adapter(const char*rom,const char*cue,const ActiveIrqCase&c):recipe(c){core.Init(nullptr);core.GetMedia()->SetConsoleType(GG_CONSOLE_PCE);core.GetMedia()->SetCDROMType(GG_CDROM_STANDARD);core.GetHuC6280()->SetResetValue(0);core.GetMemory()->SetResetValues(0,0,0,0);core.GetHuC6260()->SetResetValue(0);core.GetHuC6270_1()->SetSafeDefaults(false);core.GetScsiController()->SetResetValue(0);auto image=reset_probe::rom(rom);require(core.LoadBiosFromBuffer(image.data(),int(image.size()),true)&&core.LoadMedia(cue,false)&&core.GetMedia()->IsCDROMHardwareEnabled()&&!core.GetMedia()->IsSGX()&&core.GetMemory()->GetCardRAMSize()==0,"Actual original StandardCD profile required");core.GetHuC6280()->SetHardwareClock(Context::clock,&context);auto*log=core.GetTraceLogger();require(log->SetCapacity(8192),"Original finite logger capacity");log->SetEnabledFlags(TRACE_FLAG_CPU|TRACE_FLAG_CPU_IRQ|TRACE_FLAG_VDC|TRACE_FLAG_ADPCM|TRACE_FLAG_CDROM);log->SetEventFilter(TRACE_VDC,TRACE_VDC_FILTER_DEFAULT);log->SetEventFilter(TRACE_ADPCM,TRACE_ADPCM_FILTER_ALL);log->SetEventFilter(TRACE_CDROM,TRACE_CDROM_FILTER_ALL);}
 unsigned pc()const{return core.GetHuC6280()->GetState()->PC->GetValue();}
 std::vector<unsigned>wram()const{auto*p=core.GetMemory()->GetWorkingRAM();return{p,p+8192};}
 std::vector<unsigned>ram()const{auto*p=core.GetAdpcm()->GetRAM();return{p,p+65536};}
 std::vector<unsigned>vram()const{auto*p=core.GetHuC6270_1()->GetVRAM();return{p,p+32768};}
 Observation observe()const{auto*cpu=core.GetHuC6280();auto*c=cpu->GetState();auto*a=core.GetAdpcm()->GetState();auto*d=core.GetCDROM()->GetState();auto*v=core.GetHuC6270_1();auto*s=v->GetState();Observation o;
  o.values={c->PC->GetValue(),c->A->GetValue(),c->X->GetValue(),c->Y->GetValue(),c->S->GetValue(),c->P->GetValue(),*c->SPEED?3u:12u,core.GetMasterClockCycles(),entries,rtis,*c->IDR,*c->IRR,*d->ENABLED_IRQS,*d->ACTIVE_IRQS,*core.GetScsiController()->GetState()->SIGNALS,*a->DMA,*a->LENGTH,*a->WRITE_ADDRESS,*a->HALF_IRQ,*a->END_IRQ,writes,(core.GetAdpcm()->GetStatusRegisterSnapshot()&4)?1u:0u,(*d->ENABLED_IRQS&*d->ACTIVE_IRQS)?1u:0u,*s->SR,unsigned((*c->IRR&2)!=0),v->*member(Dma{}),unsigned(v->*member(ReadPending{})),unsigned(v->*member(WritePending{})),*s->READ_BUFFER,s->R[1],s->R[0],s->R[16],s->R[17],s->R[18],v->*member(VramBus{}),static_cast<unsigned>(v->*member(Delay{})),total_waits,static_cast<unsigned>(core.GetHuC6260()->GetClockDivider()),s->R[16],static_cast<unsigned>(cpu->*member(Pending{})),*s->AR,last_vector};
  auto*p=core.GetMemory()->GetWorkingRAM();o.stack.assign(p+256,p+512);o.wram=irq_trace::hash(std::span<const std::uint8_t>(p,8192));o.vram=vram_hash(vram());
  const auto k=active_irq_gear::kernel(core);
  o.active={{"hpos",k.hpos},{"vpos",k.vpos},{"hstate",k.hstate},{"vstate",k.vstate},
    {"hremaining",k.hremaining},{"raster",k.raster},{"sprite_count",k.sprite_count},
    {"bg_start",k.bg_start},{"bg_end",k.bg_end},{"hsync",k.hsync},{"sat_pending",k.sat_pending},
    {"burst",k.burst},{"latched_cr",k.latched_cr},{"latched_mwr",k.latched_mwr},
    {"cr",k.cr},{"mwr",k.mwr},{"rcr",k.rcr},{"divider",k.divider},{"carry",k.carry}};
  return o;
 }
 void measured(){work={};sources.clear();journal.clear();window=true;}
 void step(){const auto active_before=active_irq_gear::kernel(core);
  if(pc()==recipe.target)require(active_before.vstate==1&&!active_before.burst&&
    active_before.hpos>=active_before.bg_start&&active_before.hpos<active_before.bg_end&&
    active_before.read_pending&&!active_before.write_pending&&!active_before.dma&&!active_before.sat_pending&&
    (active_before.irr&2)&&active_before.mask==4&&!(active_before.p&4)&&
    active_before.latched_cr==(192|selected_status(recipe))&&active_before.latched_mwr==3,
    "Original target is not a naturally queued active-display access with selected IRQ1");
  auto*cpu=core.GetHuC6280();auto*c=cpu->GetState();auto*log=core.GetTraceLogger();auto*v=core.GetHuC6270_1();auto*a=core.GetAdpcm()->GetState();Source source{c->PC->GetValue(),{},{}};for(unsigned i=0;i<8;++i)source.mpr[i]=core.GetMemory()->GetMpr(i);const Row prior{c->A->GetValue(),c->X->GetValue(),c->Y->GetValue(),c->S->GetValue(),c->P->GetValue(),entries,*a->HALF_IRQ,*a->END_IRQ,unsigned((*c->IRR&2)!=0),(*core.GetCDROM()->GetState()->ENABLED_IRQS&*core.GetCDROM()->GetState()->ACTIVE_IRQS)?1u:0u,v->*member(Dma{}),unsigned(v->*member(ReadPending{})),unsigned(v->*member(WritePending{})),total_waits};
  log->Reset();context.begin(true);const auto clock_origin=context.calls;unsigned calls=0,seen=0,instructions=0,vector=0,causes=0;bool complete=false;std::uint64_t returned_total=0,internal_total=0,wait_total=0;std::vector<Row>call_rows,events;
  do{require(++calls<=6002,"Original declared finite block continuation bound");const auto first=context.spans.size();context.last_extra=0;context.inside=true;const auto returned=cpu->RunInstruction(&complete),internal=cpu->GetClockedMasterCycles(),extra=cpu->*member(Extra{});context.inside=false;const auto internal_end=context.spans.size();require(internal<=returned,"Original clock partition differs");if(returned>internal)Context::clock(&context,returned-internal);returned_total+=returned;internal_total+=internal;wait_total+=extra;total_waits+=extra;unsigned call_causes=0,call_irqs=0;
   for(;seen<log->GetCount();++seen){const auto&e=log->GetEntry(seen);if(e.type==TRACE_CPU){++instructions;require(e.cpu.pc==source.pc&&e.cpu.bank==source.mpr[source.pc>>13],"Original full fetched source differs");for(unsigned n=0;n<e.cpu.size;++n)source.bytes.push_back(e.cpu.opcodes[n]);}
    else if(e.type==TRACE_CPU_IRQ){++entries;++work.irqs;++call_irqs;vector=last_vector=e.irq.vector;require(complete,"Original IRQ delivered before whole instruction completed");events.push_back({calls,e.cycle,unsigned(e.type),e.irq.vector,e.irq.pc,e.irq.irq_mask});}
    else if(e.type==TRACE_ADPCM){if(e.adpcm.event==TRACE_ADPCM_WRITE_COMPLETE)++writes;const unsigned bit=e.adpcm.event==TRACE_ADPCM_HALF_IRQ&&e.adpcm.value==1?1:e.adpcm.event==TRACE_ADPCM_END_IRQ&&e.adpcm.value==1?2:0;if(bit&&!(seen_causes&bit)){seen_causes|=bit;call_causes|=bit;}events.push_back({calls,e.cycle,unsigned(e.type),e.adpcm.event,e.adpcm.length,e.adpcm.address,e.adpcm.reg,e.adpcm.value,e.adpcm.state});}
    else if(e.type==TRACE_VDC){if(e.vdc.event==(recipe.source==0?TRACE_VDC_SCANLINE_IRQ:TRACE_VDC_SPRITE_COLLISION_IRQ)&&!(seen_causes&4)){seen_causes|=4;call_causes|=4;}events.push_back({calls,e.cycle,unsigned(e.type),e.vdc.event,e.vdc.chip,e.vdc.reg,e.vdc.raw,e.vdc.msb,e.vdc.value,e.vdc.value2,e.vdc.value3,e.vdc.param});}
    else if(e.type==TRACE_CDROM)events.push_back({calls,e.cycle,unsigned(e.type),e.cdrom.event,e.cdrom.irq_type,e.cdrom.active,e.cdrom.enabled});else throw std::runtime_error("Unexpected original callback type");}
   require(instructions==1&&!source.bytes.empty()&&log->GetCount()==log->GetTotalLogged(),"Original source trace missing/lost");if(call_causes)causes|=call_causes;
   call_rows.push_back({calls,returned,internal,complete?1u:0u,first,internal_end,context.spans.size(),extra,call_irqs,call_causes});
  }while(!complete);
  require(calls==(block(source.bytes[0])?block_length(source)+2:1),"Original calls differ from source operand N+2 grouping");if(block(source.bytes[0])){++work.blocks;work.block_bytes+=block_length(source);}if(causes&3)++work.adpcm_cause_groups;if(causes&4)++work.vdc_cause_groups;if(source.bytes[0]==0x40){++rtis;++work.rtis;rti_frame(observe(),recipe);}++sources[source];++work.instructions;work.calls+=calls;work.clock_calls+=context.calls-clock_origin;work.clock_ticks+=returned_total;work.wait_ticks+=wait_total;
  if(vector){require(vector==(prior[5]==0?0xfff8:0xfff6),"Actual original overlap priority differs");try{irq_frame(source,observe(),vector,recipe);}catch(...){std::cerr<<"Original IRQ frame source="<<source.pc<<" vector="<<vector<<" observation=";observation(std::cerr,observe());std::cerr<<"\n";throw;}}if(source.pc==recipe.target&&!(vector==0xfff8&&wait_total>0)){std::cerr<<"Original target counterexample pc="<<source.pc<<" ticks="<<returned_total<<" waits="<<wait_total<<" vector="<<vector<<" before=";active_irq_gear::write_kernel(std::cerr,active_before);std::cerr<<" after=";observation(std::cerr,observe());std::cerr<<"\n";throw std::runtime_error("Original target did not retire queued access with IRQ1 priority");}
  if(source.pc==recipe.target){
   unsigned grants=0;
   for(const auto&edge:context.edges)if(edge.before.read_pending&&!edge.after.read_pending&&context.spans[edge.span][3]){
    ++grants;require(edge.before.irr==3&&edge.after.irr==3&&edge.before.sample==3&&edge.after.sample==3&&
      edge.before.half&&edge.before.end&&edge.before.cd_enabled==12,
      "Original dynamic grant did not preserve both sampled sources");
   }
   require(grants==1,"Original target must have exactly one observed dynamic read grant");
  }
  if(causes||vector||source.pc==recipe.target||source.pc==recipe.pre_dma||(source.pc>=recipe.handler1&&source.pc<recipe.handler2+64)||(window&&work.instructions<=16))journal.push_back({source,prior,returned_total,internal_total,wait_total,vector,causes,context.spans,call_rows,events,context.edges,observe(),active_before});
 }
};
void records(const std::vector<Record>&items){std::cout<<'[';bool first=true;for(const auto&r:items){std::cout<<(first?"":",")<<'{';source_json(std::cout,r.source);std::cout<<",\"active_before\":";active_irq_gear::write_kernel(std::cout,r.active_before);std::cout<<",\"before\":";vec(std::cout,r.before);std::cout<<",\"ticks\":"<<r.ticks<<",\"internal\":"<<r.internal<<",\"wait_ticks\":"<<r.waits<<",\"vector\":"<<r.vector<<",\"causes\":"<<r.causes<<",\"clocks\":[";for(unsigned i=0;i<r.clocks.size();++i){if(i)std::cout<<',';vec(std::cout,r.clocks[i]);}std::cout<<"],\"call_rows\":[";for(unsigned i=0;i<r.calls.size();++i){if(i)std::cout<<',';vec(std::cout,r.calls[i]);}std::cout<<"],\"callbacks\":[";for(unsigned i=0;i<r.callbacks.size();++i){if(i)std::cout<<',';vec(std::cout,r.callbacks[i]);}std::cout<<"],\"edges\":[";for(unsigned i=0;i<r.edges.size();++i){if(i)std::cout<<',';const auto&e=r.edges[i];std::cout<<"{\"span\":"<<e.span<<",\"kinds\":"<<e.kinds<<",\"before\":";active_irq_gear::write_kernel(std::cout,e.before);std::cout<<",\"after\":";active_irq_gear::write_kernel(std::cout,e.after);std::cout<<'}';}std::cout<<"],\"after\":";observation(std::cout,r.after);std::cout<<'}';first=false;}std::cout<<']';}
}
int main(int argc,char**argv){try{require(argc==5,"CASE ROM CUE CUT");const auto&c=active_irq_case(argv[1]);const auto cut=std::stoul(argv[4]);require(cut<3,"Three natural cuts only");Adapter a(argv[2],argv[3],c);reach(a,cut_pc(a,c,cut));const auto initial=a.observe();const auto prefix=a.work;const auto prefix_hits=a.sources;const auto prefix_journal=a.journal;a.measured();finish(a,c);try{final_checks(a,c);}catch(...){const auto actual=a.wram(),expected=expected_wram(c);std::cerr<<"Original WRAM differences:";for(unsigned i=0;i<actual.size();++i)if(actual[i]!=expected[i])std::cerr<<" "<<i<<":"<<actual[i]<<"/"<<expected[i];std::cerr<<" observation=";observation(std::cerr,a.observe());std::cerr<<"\n";throw;}
 std::cout<<"{\"dma_counter_role\":\"committed-writes\",\"vdc_counter_role\":\"source-progress\",\"case\":\""<<c.id<<"\",\"cut_id\":"<<cut<<",\"tier\":\"gear\",\"cut\":";observation(std::cout,initial);std::cout<<",\"final\":";observation(std::cout,a.observe());std::cout<<",\"prefix_work\":";work_json(std::cout,prefix);std::cout<<",\"window_work\":";work_json(std::cout,a.work);std::cout<<",\"prefix_hits\":";hits(std::cout,prefix_hits);std::cout<<",\"window_hits\":";hits(std::cout,a.sources);std::cout<<",\"prefix_journal\":";records(prefix_journal);std::cout<<",\"journal\":";records(a.journal);std::cout<<",\"ram\":";vec(std::cout,a.ram());std::cout<<",\"vram\":";vec(std::cout,a.vram());std::cout<<"}\n";return 0;
 }catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
