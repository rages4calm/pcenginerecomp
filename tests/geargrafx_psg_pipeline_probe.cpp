// External original Gear observer. No Gear implementation bodies copied here.
#include "geargrafx_core.h"
#include "huc6280.h"
#include "huc6280_psg.h"
#include "memory.h"
#include "media.h"
#include "huc6260.h"
#include "huc6270.h"
#include "audio.h"
#include "trace_logger.h"
#include "psg_phase_fixture.hpp"
#include <iostream>
#include <memory>
#include <string>
#include <vector>
bool g_mcp_stdio_mode=true;
struct ClockTag{using type=bool(GeargrafxCore::*)(u32);friend type member(ClockTag);};
template<class Tag,typename Tag::type Pointer>struct Access{friend typename Tag::type member(Tag){return Pointer;}};
template struct Access<ClockTag,&GeargrafxCore::ClockHardware<true,false,false>>;
void clock(void* p,u32 ticks){auto& c=*static_cast<GeargrafxCore*>(p);(c.*member(ClockTag{}))(ticks);}
namespace{
constexpr unsigned frames=2048,partition=512;
constexpr std::uint64_t master=21477273,rate=44100;
std::uint64_t edge(unsigned frame){return(std::uint64_t(frame)*master+rate-1)/rate;}
template<class T>void array(const T& values){std::cout<<'[';bool comma=false;for(auto v:values){std::cout<<(comma?",":"")<<+v;comma=true;}std::cout<<']';}
template<class T>void rows(const T& values){std::cout<<'[';bool comma=false;for(auto v:values){std::cout<<(comma?",":"");array(v);comma=true;}std::cout<<']';}
}
int main(int argc,char** argv){try{
 if(argc!=4)throw std::runtime_error("usage: probe CASE DIVISOR AUTHORED_ROM");
 const auto speed=std::stoul(argv[2]);if(speed!=3&&speed!=12)throw std::runtime_error("invalid divisor");
 const PhaseCase* item=nullptr;for(const auto& c:phase_cases)if(c.name==std::string(argv[1]))item=&c;if(!item)throw std::runtime_error("unknown authored case");const auto& c=*item;
 auto core=std::make_unique<GeargrafxCore>();core->Init(nullptr);core->GetHuC6280()->SetResetValue(0);core->GetMemory()->SetResetValues(0,0,0,0);core->GetHuC6260()->SetResetValue(0);core->GetHuC6270_1()->SetSafeDefaults(false);
 if(!core->LoadMedia(argv[3],false))throw std::runtime_error("authored ROM failed loading");
 auto* cpu=core->GetHuC6280();auto* memory=core->GetMemory();auto* state=cpu->GetState();auto* psg=core->GetAudio()->GetPSG();cpu->SetHardwareClock(clock,core.get());psg->EnableHuC6280A(true);
 *core->GetHuC6270_1()->GetState()->READ_BUFFER=0;
 for(unsigned i=0;i<8;++i)memory->SetMpr(i,phase_mpr[i]);
 state->PC->SetValue(c.pc);state->A->SetValue(31);state->X->SetValue(1);state->Y->SetValue(1);state->S->SetValue(255);state->P->SetValue(5);*state->SPEED=speed==3?1:0;
 for(unsigned i=0;i<4;++i)memory->Write(0x2200+i,31);
 memory->Write(0x2020,6);memory->Write(0x2021,8);memory->Write(0x2022,5);memory->Write(0x2023,8);
 memory->Write(0x0800,0);memory->Write(0x0801,255);memory->Write(0x0804,223);memory->Write(0x0805,255);memory->Write(0x0806,c.old_dda);memory->Write(0x080a,31);
 const auto start=488-(c.size==7?19:4)*speed;clock(core.get(),start);
 auto* trace=core->GetTraceLogger();trace->Reset();trace->SetEnabledFlags(TRACE_FLAG_PSG);
 bool complete=false;unsigned calls=0;do{auto ticks=cpu->RunInstruction(&complete);auto counted=cpu->GetClockedMasterCycles();if(ticks>counted)clock(core.get(),ticks-counted);if(++calls>8)throw std::runtime_error("block did not finish");}while(!complete);
 const auto end=core->GetMasterClockCycles();
 std::vector<std::array<int,2>> sums,hpf;std::vector<unsigned> drains;
 for(unsigned total=partition;total<=frames;total+=partition){
  auto now=core->GetMasterClockCycles();auto target=edge(total);clock(core.get(),u32((target-now+speed-1)/speed*speed));
  auto* channels=psg->GetState()->CHANNELS;
  for(unsigned frame=0;frame<partition;++frame){std::array<int,2> sum{};for(unsigned side=0;side<2;++side)for(unsigned ch=0;ch<6;++ch)sum[side]+=channels[ch].output[frame*2+side];sums.push_back(sum);}
  s16 buffer[GG_AUDIO_BUFFER_SIZE];int n=psg->EndFrame(buffer);if(n!=partition*2)throw std::runtime_error("original partition count differs");for(int i=0;i<n;i+=2)hpf.push_back({buffer[i],buffer[i+1]});drains.push_back(total);
 }
 std::cout<<"{\"case\":\""<<c.name<<"\",\"divisor\":"<<speed<<",\"pc\":"<<c.pc<<",\"mpr\":[";for(unsigned i=0;i<8;++i)std::cout<<(i?",":"")<<unsigned(memory->GetMpr(i));std::cout<<"],\"physical\":[";
 for(unsigned i=0;i<c.size;++i)std::cout<<(i?",":"")<<memory->GetPhysicalAddress(c.pc+i);std::cout<<"],\"bytes\":[";for(unsigned i=0;i<c.size;++i)std::cout<<(i?",":"")<<unsigned(memory->Read(c.pc+i));
 std::cout<<"],\"start\":"<<start<<",\"end\":"<<end<<",\"final_pc\":"<<state->PC->GetValue()<<",\"dda\":"<<unsigned(psg->GetState()->CHANNELS[0].dda)<<",\"calls\":"<<calls<<",\"writes\":[";bool comma=false;for(unsigned i=0;i<trace->GetCount();++i){const auto& e=trace->GetEntry(i);if(e.type!=TRACE_PSG)continue;std::cout<<(comma?",":"")<<'['<<e.cycle<<','<<unsigned(e.psg.reg)<<','<<unsigned(e.psg.value)<<']';comma=true;}
 std::cout<<"],\"frames\":"<<frames<<",\"continuation_end\":"<<core->GetMasterClockCycles()<<",\"partition_end_frames\":";array(drains);std::cout<<",\"source_ticks\":[";for(unsigned frame=1;frame<=frames;++frame)std::cout<<(frame>1?",":"")<<edge(frame);std::cout<<"],\"source_sums\":";rows(sums);std::cout<<",\"hpf\":";rows(hpf);std::cout<<"}\n";return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
