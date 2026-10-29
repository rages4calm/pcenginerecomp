#pragma once
// Observation and independent authored CPU boundary expectations; no device implementation.
#include "dma_irq_checkpoint_fixture.hpp"
#include "irq_trace_support.hpp"
#include "reset_probe_support.hpp"
#include <map>
#include <sstream>
#include <array>

namespace dma_irq {
inline void require(bool v,const std::string& why){if(!v)throw std::runtime_error(why);}
template<class T>void vec(std::ostream& out,const T& values){out<<'[';bool first=true;for(auto v:values){out<<(first?"":",")<<+v;first=false;}out<<']';}
inline constexpr unsigned limit=1500000;
using Row=std::vector<std::uint64_t>;
// PC,A,X,Y,SP,P,divisor,ticks,entries,RTIs,mask,requests,CDenable,CDactive,
// signals,DMA,length,write_address,half,end,counter,pending-write,irq2.
// Counter role is explicit in each report: toolkit captured-bytes; Gear committed-writes.
struct Observation{Row values;std::vector<unsigned> stack;std::string wram;};
inline void observation(std::ostream& out,const Observation& o){out<<"{\"values\":";vec(out,o.values);out<<",\"stack\":";vec(out,o.stack);out<<",\"wram_sha256\":\""<<o.wram<<"\"}";}
struct Work {std::uint64_t instructions=0,calls=0,clock_calls=0,clock_ticks=0,irqs=0,rtis=0;};
inline void work_json(std::ostream& out,const Work& w){out<<"{\"instructions\":"<<w.instructions<<",\"calls\":"<<w.calls<<",\"clock_calls\":"<<w.clock_calls<<",\"clock_ticks\":"<<w.clock_ticks<<",\"irqs\":"<<w.irqs<<",\"rtis\":"<<w.rtis<<'}';}
struct Source{unsigned pc;std::array<unsigned,8> mpr;std::vector<unsigned> bytes;bool operator<(const Source& b)const{return std::tie(pc,mpr,bytes)<std::tie(b.pc,b.mpr,b.bytes);}};
inline void hits(std::ostream& out,const std::map<Source,std::uint64_t>& rows){out<<'[';bool first=true;for(const auto& [s,n]:rows){out<<(first?"":",")<<"{\"pc\":"<<s.pc<<",\"mpr\":";vec(out,s.mpr);out<<",\"physical\":[";for(unsigned i=0;i<s.bytes.size();++i)out<<(i?",":"")<<((s.mpr[((s.pc+i)&65535)>>13]<<13)|((s.pc+i)&8191));out<<"],\"data\":";vec(out,s.bytes);out<<",\"hits\":"<<n<<'}';first=false;}out<<']';}
inline unsigned size(unsigned opcode){switch(opcode){case 0xa9:case 0xa2:case 0x53:case 0x29:case 0xc9:case 0xd0:case 0xf0:case 0x80:return 2;case 0x8d:case 0xad:case 0xee:return 3;default:return 1;}}
inline unsigned next_pc(const Source& s,unsigned p){const auto op=s.bytes[0];unsigned pc=(s.pc+s.bytes.size())&65535;bool branch=op==0x80||(op==0xd0&&!(p&2))||(op==0xf0&&(p&2));if(branch)pc=(pc+static_cast<std::int8_t>(s.bytes[1]))&65535;return pc;}
inline unsigned nz(unsigned p,unsigned a){return (p&~130)|(a==0?2:0)|(a&128);}
inline unsigned resulting_p(const Source& s,unsigned a,unsigned p,unsigned after_a){
 switch(s.bytes[0]){case 0xa9:case 0xad:case 0x29:case 0x68:return nz(p,after_a);case 0xc9:{const unsigned value=s.bytes[1];return (p&~131)|(a>=value?1:0)|(a==value?2:0)|((a-value)&128);}case 0x58:return p&~4;case 0x78:return p|4;default:return p;}}
inline void irq_frame(const Source& source,unsigned a,unsigned p,unsigned after_a,const Observation& o){
 const auto& v=o.values;const unsigned next=next_pc(source,p),status=resulting_p(source,a,p,after_a)&~16;
 require(v[0]==0xf800&&v[4]==252,"Authored IRQ2 handler/stack pointer differs");
 require(o.stack.size()==256&&o.stack[255]==(next>>8)&&o.stack[254]==(next&255)&&o.stack[253]==status,"Independent guest IRQ frame differs");
 require((v[5]&4)&&!(v[5]&40),"IRQ entry did not set I/clear D,T");
}
inline void rti_frame(const Observation& o){const auto& v=o.values;require(v[4]==255&&v[0]==(o.stack[254]|(o.stack[255]<<8))&&v[5]==(o.stack[253]&~16u)&&v[1]==o.stack[252],"Independent RTI PC/P/A/stack restoration differs");}
template<class A>unsigned cut_pc(const A& a,const DmaIrqCase& c,unsigned cut){return cut==0?c.pre_cli:(c.kind<2?c.handler:c.post_dma);}
template<class A>void reach(A& a,unsigned pc){for(unsigned n=0;n<limit;++n){if(a.pc()==pc)return;a.step();}throw std::runtime_error("Autonomous guest instruction bound at "+std::to_string(a.pc()));}
template<class A>void finish(A& a,const DmaIrqCase& c){reach(a,c.done);}
template<class A>void final_checks(const A& a,const DmaIrqCase& c){auto o=a.observe();const auto& v=o.values;const auto ram=a.ram();require(ram.size()==65536,"ADPCM RAM extent");for(unsigned i=0;i<65536;++i){const unsigned offset=(i-0xfffeu)&65535;const unsigned expected=offset<2048?(offset*17+(offset>>8)*7+0x53)&255:0;require(ram[i]==expected,"Independent full RAM pattern differs at "+std::to_string(i));}
 require(v[0]==c.done&&v[4]==255&&v[6]==c.divisor&&v[16]==2048&&v[17]==2046&&v[18]==1&&v[19]==1,"Independent endpoint CPU/ADPCM literal differs");
 require((v[14]&128)==0&&v[15]==0&&v[21]==0&&!v[22],"Guest did not release CD/DMA/IRQ2");
 const auto w=a.wram();require(w[16]==0&&w[17]==0&&w[18]==unsigned(c.kind<2),"Independent guest reply/handler witness differs");require(v[8]==unsigned(c.kind<2)&&v[9]==unsigned(c.kind<2),"Independent actual IRQ/RTI count differs");
}
}
