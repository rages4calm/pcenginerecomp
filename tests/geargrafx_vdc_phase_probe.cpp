// Authored observations around the unmodified original Gear CPU/VDC bodies.
#include "geargrafx_core.h"
#include "huc6280.h"
#include "huc6270.h"
#include "huc6260.h"
#include "memory.h"
#include "media.h"
#include "audio.h"
#include "trace_logger.h"
#include "vdc_phase_fixture.hpp"
#include "reset_probe_support.hpp"
#include <array>
#include <map>
#include <tuple>
bool g_mcp_stdio_mode=true;
namespace {
using Row=std::vector<std::uint64_t>;
void require(bool ok,const char*why){if(!ok)throw std::runtime_error(why);}
template<class T>void vec(const T&v){std::cout<<'[';bool first=true;for(auto x:v){std::cout<<(first?"":",")<<+x;first=false;}std::cout<<']';}
template<class T,typename T::type M>struct Access{friend typename T::type member(T){return M;}};
#define FIELD(N,O,T,F) struct N{using type=T O::*;friend type member(N);};template struct Access<N,&O::F>;
FIELD(Extra,HuC6280,u32,m_extra_master_cycles)
FIELD(ReadPending,HuC6270,bool,m_pending_memory_read) FIELD(WritePending,HuC6270,bool,m_pending_memory_write)
FIELD(Delay,HuC6270,s32,m_transfer_delay) FIELD(Carry,HuC6270,u32,m_cpu_vram_cycles)
FIELD(Dma,HuC6270,u32,m_vram_transfer_pending) FIELD(Sat,HuC6270,u16,m_sat_transfer_pending)
FIELD(Burst,HuC6270,bool,m_burst_mode) FIELD(Control,HuC6270,u16,m_latched_cr) FIELD(Mode,HuC6270,u16,m_latched_mwr)
FIELD(Sprites,HuC6270,int,m_sprite_count) FIELD(HRemaining,HuC6270,s32,m_clocks_to_next_h_state)
FIELD(BgStart,HuC6270,s32,m_load_bg_start_clock) FIELD(BgEnd,HuC6270,s32,m_load_bg_end_clock)
FIELD(HSync,HuC6270,s32,m_hsync_start_clock) FIELD(Latch,HuC6270,u16,m_vram_openbus)
#undef FIELD
struct Clock{using type=bool(GeargrafxCore::*)(u32);friend type member(Clock);};template struct Access<Clock,&GeargrafxCore::ClockHardware<false,false,false>>;
Row phase(GeargrafxCore&core){auto*v=core.GetHuC6270_1();auto*s=v->GetState();auto*e=core.GetHuC6260()->GetState();return{core.GetMasterClockCycles(),static_cast<unsigned>(*e->HPOS),static_cast<unsigned>(*s->HPOS),static_cast<unsigned>(*s->VPOS),static_cast<unsigned>(*e->VPOS),static_cast<unsigned>(*s->V_STATE),static_cast<unsigned>(*s->H_STATE),static_cast<unsigned>(v->*member(HRemaining{})),static_cast<unsigned>(core.GetHuC6260()->GetClockDivider()),v->*member(ReadPending{}),v->*member(WritePending{}),static_cast<unsigned>(v->*member(Delay{})),v->*member(Carry{}),v->*member(Dma{}),v->*member(Sat{}),v->*member(Burst{}),v->*member(Control{}),v->*member(Mode{}),static_cast<unsigned>(v->*member(Sprites{})),static_cast<unsigned>(v->*member(BgStart{})),static_cast<unsigned>(v->*member(BgEnd{})),static_cast<unsigned>(v->*member(HSync{})),*s->READ_BUFFER,s->R[1],s->R[0],s->R[16],s->R[17],s->R[18],v->*member(Latch{}),*s->AR,*s->SR,unsigned((*core.GetHuC6280()->GetState()->IRR&2)!=0),s->R[10],s->R[11],s->R[5]};}
Row cpu_row(GeargrafxCore&core){auto*c=core.GetHuC6280()->GetState();Row r{c->PC->GetValue(),c->A->GetValue(),c->X->GetValue(),c->Y->GetValue(),c->S->GetValue(),c->P->GetValue(),*c->SPEED?3u:12u,core.GetMasterClockCycles()};for(unsigned i=0;i<8;++i)r.push_back(core.GetMemory()->GetMpr(i));return r;}
struct Context{GeargrafxCore*core;std::uint64_t calls=0,drained=0;bool inside=false,retain=false;unsigned last_extra=0;std::vector<Row>spans;
 static void clock(void*p,u32 ticks){auto&a=*static_cast<Context*>(p);const auto extra=a.core->GetHuC6280()->*member(Extra{});const bool dynamic=a.inside&&extra>a.last_extra;require(!dynamic||(extra-a.last_extra==3&&ticks==3),"Original dynamic callback is not StallFastCycle");a.last_extra=extra;const auto pre=phase(*a.core);(a.core->*member(Clock{}))(ticks);const auto post=phase(*a.core);require(post[0]==pre[0]+ticks,"Original hardware callback continuity differs");if(a.retain)a.spans.push_back({pre[0],ticks,post[0],unsigned(dynamic),pre[1],pre[13],post[13],pre[9],post[9],pre[12],pre[6],pre[21]});++a.calls;if(post[0]-a.drained>=4096){a.core->GetAudio()->EndFrame(nullptr,nullptr);a.drained=post[0];}}
};
struct Source{unsigned pc;std::array<unsigned,8>mpr;std::vector<unsigned>bytes;bool operator<(const Source&b)const{return std::tie(pc,mpr,bytes)<std::tie(b.pc,b.mpr,b.bytes);}};
void source(const Source&s,const char*field){std::cout<<"\"pc\":"<<s.pc<<",\"mpr\":";vec(s.mpr);std::cout<<",\"physical\":[";for(unsigned i=0;i<s.bytes.size();++i)std::cout<<(i?",":"")<<((s.mpr[((s.pc+i)&65535)>>13]<<13)|((s.pc+i)&8191));std::cout<<"],\""<<field<<"\":";vec(s.bytes);}
struct Record{Source source;Row before,after,cb,ca;std::uint64_t ticks,waits,internal;unsigned calls;std::vector<Row>clocks,call_rows,events;};
struct Adapter{GeargrafxCore core;Context context{&core};std::map<Source,unsigned>hits;std::vector<Record>records;std::uint64_t n=0,calls=0,blocks=0,bytes=0,waits=0;
 Adapter(const char*rom){core.Init(nullptr);core.GetMedia()->SetConsoleType(GG_CONSOLE_PCE);core.GetHuC6280()->SetResetValue(0);core.GetMemory()->SetResetValues(0,0,0,0);core.GetHuC6260()->SetResetValue(0);core.GetHuC6270_1()->SetSafeDefaults(false);auto image=reset_probe::rom(rom);require(core.LoadHuCardFromBuffer(image.data(),image.size(),"authored-phase.pce")&&!core.GetMedia()->IsCDROMHardwareEnabled()&&!core.GetMedia()->IsSGX(),"Original base HuCard profile required");core.GetHuC6280()->SetHardwareClock(Context::clock,&context);auto*l=core.GetTraceLogger();require(l->SetCapacity(8192),"Original observer capacity refused");l->SetEnabledFlags(TRACE_FLAG_CPU|TRACE_FLAG_CPU_IRQ|TRACE_FLAG_VDC);l->SetEventFilter(TRACE_VDC,TRACE_VDC_FILTER_DEFAULT);}
 void step(const PhaseCase&c){auto*cpu=core.GetHuC6280();const auto before=phase(core),cb=cpu_row(core);Source fetched{static_cast<unsigned>(cb[0]),{},{}};for(unsigned i=0;i<8;++i)fetched.mpr[i]=core.GetMemory()->GetMpr(i);const bool selected=fetched.pc==c.launch||fetched.pc==c.target;context.retain=selected;context.spans.clear();auto*l=core.GetTraceLogger();l->Reset();unsigned seen=0,source_rows=0,call_count=0;std::uint64_t ticks=0,internal_total=0,wait_total=0;bool complete=false;std::vector<Row>call_rows,events;
  do{require(++call_count<=6002,"Original finite continuation bound exceeded");context.last_extra=0;const auto first=context.spans.size();context.inside=true;const auto returned=cpu->RunInstruction(&complete),inside=cpu->GetClockedMasterCycles(),extra=cpu->*member(Extra{});context.inside=false;const auto inside_end=context.spans.size();require(inside<=returned,"Original internal/returned clocks differ");if(returned>inside)Context::clock(&context,returned-inside);ticks+=returned;internal_total+=inside;wait_total+=extra;
   for(;seen<l->GetCount();++seen){const auto&e=l->GetEntry(seen);if(e.type==TRACE_CPU){++source_rows;require(e.cpu.pc==fetched.pc&&e.cpu.bank==fetched.mpr[fetched.pc>>13],"Original fetched source bank/PC differs");for(unsigned i=0;i<e.cpu.size;++i)fetched.bytes.push_back(e.cpu.opcodes[i]);}else if(e.type==TRACE_VDC){if(selected)events.push_back({call_count,e.cycle,unsigned(e.type),e.vdc.event,e.vdc.chip,e.vdc.reg,e.vdc.raw,e.vdc.msb,e.vdc.value,e.vdc.value2,e.vdc.value3,e.vdc.param});}else throw std::runtime_error("Original unexpected CPU IRQ/source event");}
   require(source_rows==1&&l->GetCount()==l->GetTotalLogged(),"Original one TRACE_CPU per completed group or loss differs");if(selected)call_rows.push_back({call_count,returned,inside,unsigned(complete),first,inside_end,context.spans.size(),extra});
  }while(!complete);
  const bool block=fetched.bytes[0]==0x73||fetched.bytes[0]==0xf3;const unsigned length=block?(fetched.bytes[5]|fetched.bytes[6]<<8):0;require(call_count==(block?length+2:1),"Original N+2 actual calls/source operand differs");++n;calls+=call_count;waits+=wait_total;if(block){++blocks;bytes+=length;}++hits[fetched];if(selected)records.push_back({fetched,before,phase(core),cb,cpu_row(core),ticks,wait_total,internal_total,call_count,context.spans,call_rows,events});
 }
};
void records(const std::vector<Record>&rows){std::cout<<'[';bool first=true;for(const auto&r:rows){std::cout<<(first?"":",")<<'{';source(r.source,"bytes");std::cout<<",\"before\":";vec(r.before);std::cout<<",\"after\":";vec(r.after);std::cout<<",\"cpu_before\":";vec(r.cb);std::cout<<",\"cpu_after\":";vec(r.ca);std::cout<<",\"ticks\":"<<r.ticks<<",\"wait_ticks\":"<<r.waits<<",\"calls\":"<<r.calls<<",\"internal\":"<<r.internal<<",\"clocks\":[";for(unsigned i=0;i<r.clocks.size();++i){if(i)std::cout<<',';vec(r.clocks[i]);}std::cout<<"],\"call_rows\":[";for(unsigned i=0;i<r.call_rows.size();++i){if(i)std::cout<<',';vec(r.call_rows[i]);}std::cout<<"],\"events\":[";for(unsigned i=0;i<r.events.size();++i){if(i)std::cout<<',';vec(r.events[i]);}std::cout<<"]}";first=false;}std::cout<<']';}
}
int main(int argc,char**argv){try{require(argc==3,"CASE ROM");const auto&c=phase_case(argv[1]);Adapter a(argv[2]);while(a.core.GetHuC6280()->GetState()->PC->GetValue()!=c.done){require(a.n<1000,"Authored source extent exceeded");a.step(c);}std::cout<<"{\"schema\":1,\"case\":\""<<c.id<<"\",\"tier\":\"gear\",\"runtime_abi\":null,\"instructions\":"<<a.n<<",\"calls\":"<<a.calls<<",\"clock_calls\":"<<a.context.calls<<",\"blocks\":"<<a.blocks<<",\"block_bytes\":"<<a.bytes<<",\"wait_ticks\":"<<a.waits<<",\"records\":";records(a.records);std::cout<<",\"final_cpu\":";vec(cpu_row(a.core));std::cout<<",\"final_phase\":";vec(phase(a.core));std::cout<<",\"wram\":[";auto*w=a.core.GetMemory()->GetWorkingRAM();for(unsigned i=0;i<8192;++i)std::cout<<(i?",":"")<<+w[i];std::cout<<"],\"vram\":[";auto*v=a.core.GetHuC6270_1()->GetVRAM();for(unsigned i=0;i<32768;++i)std::cout<<(i?",":"")<<v[i];std::cout<<"],\"hits\":[";bool first=true;for(const auto&[s,count]:a.hits){std::cout<<(first?"":",")<<'{';source(s,"data");std::cout<<",\"hits\":"<<count<<'}';first=false;}std::cout<<"]}\n";return 0;
 }catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
