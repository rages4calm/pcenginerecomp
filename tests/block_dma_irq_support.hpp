#pragma once
// Authored observer/independent expectations, never a copied device implementation.
#include "block_dma_irq_fixture.hpp"
#include "irq_trace_support.hpp"
#include "reset_probe_support.hpp"
#include <map>
#include <sstream>
#include <array>
#include <cstdint>
#include <tuple>
#include <vector>

namespace block_dma {
inline void require(bool v,const std::string& why){if(!v)throw std::runtime_error(why);}
template<class T>void vec(std::ostream& out,const T& values){out<<'[';bool first=true;for(auto v:values){out<<(first?"":",")<<+v;first=false;}out<<']';}
inline constexpr unsigned limit=1500000,length=1023;
using Row=std::vector<std::uint64_t>;
// PC,A,X,Y,SP,P,divisor,ticks,entries,RTIs,mask,requests,CDenable,CDactive,
// signals,DMA,length,write_address,half,end,counter,pending-write,irq2.
struct Observation{Row values;std::vector<unsigned> stack;std::string wram;};
inline void observation(std::ostream& out,const Observation&o){out<<"{\"values\":";vec(out,o.values);out<<",\"stack\":";vec(out,o.stack);out<<",\"wram_sha256\":\""<<o.wram<<"\"}";}
struct Work{std::uint64_t instructions=0,calls=0,clock_calls=0,clock_ticks=0,irqs=0,rtis=0,blocks=0,block_bytes=0,cause_blocks=0;};
inline void work_json(std::ostream&out,const Work&w){out<<"{\"instructions\":"<<w.instructions<<",\"calls\":"<<w.calls<<",\"clock_calls\":"<<w.clock_calls<<",\"clock_ticks\":"<<w.clock_ticks<<",\"irqs\":"<<w.irqs<<",\"rtis\":"<<w.rtis<<",\"blocks\":"<<w.blocks<<",\"block_bytes\":"<<w.block_bytes<<",\"cause_blocks\":"<<w.cause_blocks<<'}';}
struct Source{unsigned pc;std::array<unsigned,8>mpr;std::vector<unsigned>bytes;bool operator<(const Source&b)const{return std::tie(pc,mpr,bytes)<std::tie(b.pc,b.mpr,b.bytes);}};
inline void source_json(std::ostream&out,const Source&s,const char* byte_key="bytes"){out<<"\"pc\":"<<s.pc<<",\"mpr\":";vec(out,s.mpr);out<<",\"physical\":[";for(unsigned i=0;i<s.bytes.size();++i)out<<(i?",":"")<<((s.mpr[((s.pc+i)&65535)>>13]<<13)|((s.pc+i)&8191));out<<"],\""<<byte_key<<"\":";vec(out,s.bytes);}
inline void hits(std::ostream&out,const std::map<Source,std::uint64_t>&rows){out<<'[';bool first=true;for(const auto&[s,n]:rows){out<<(first?"":",")<<'{';source_json(out,s,"data");out<<",\"hits\":"<<n<<'}';first=false;}out<<']';}
inline bool block(unsigned op){return op==0x73||op==0xc3||op==0xd3||op==0xe3||op==0xf3;}
inline unsigned size(unsigned op){if(block(op))return 7;switch(op){case 0xa9:case 0xa2:case 0x53:case 0x29:case 0xc9:case 0xd0:case 0xf0:case 0x80:return 2;case 0x8d:case 0xad:case 0xee:return 3;default:return 1;}}
inline unsigned data(unsigned i){return(i*29+(i>>6)*11+0x27)&255;}
inline std::vector<unsigned> expected_wram(const BlockDmaCase&c){std::vector<unsigned>w(8192);w[18]=unsigned(c.kind==0);w[508]=c.kind==0?2:0;w[509]=1;w[510]=2;
 if(c.family<2)for(unsigned i=0;i<length;++i)w[512+i]=data(i);else if(c.family==2)w[512]=data(length-1);else if(c.family==3){w[512]=data(length-1);w[513]=data(length-2);}else for(unsigned i=0;i<length;++i)w[512+i]=data(i&1);return w;}
inline void irq_frame(const Source&s,const Row&before,const Observation&o,unsigned index,const BlockDmaCase&c){const auto&v=o.values;const unsigned x=c.loops-index+1,p=1|(x==c.loops?0:(x&128));require(block(s.bytes[0])&&s.pc==c.block&&before.size()==8&&before[0]==2&&before[1]==x&&before[2]==0&&before[3]==255&&before[4]==p&&before[5]==0&&!(before[4]&4),"Independent IRQ block source/registers differ");
 const unsigned ret=c.block+7;require(v[0]==c.handler&&v[1]==2&&v[2]==x&&v[3]==0&&v[4]==252&&v[5]==(p|4)&&v[8]==1&&v[9]==0,"Independent completed block IRQ CPU state differs");require(o.stack.size()==256&&o.stack[255]==(ret>>8)&&o.stack[254]==(ret&255)&&o.stack[253]==p,"Independent block-completed IRQ stack differs");}
inline void rti_frame(const Observation&o,const BlockDmaCase&c){const auto&v=o.values;require(v[0]==c.block+7&&v[1]==2&&v[3]==0&&v[4]==255&&v[5]==o.stack[253]&&o.stack[252]==2,"Independent block IRQ RTI differs");}
template<class A>unsigned cut_pc(const A&,const BlockDmaCase&c,unsigned cut){return cut==0?c.pre_arm:(c.kind==0?c.handler:c.post_dma);}
template<class A>void reach(A&a,unsigned pc){for(unsigned n=0;n<limit;++n){if(a.pc()==pc)return;a.step();}throw std::runtime_error("Autonomous block instruction bound at "+std::to_string(a.pc()));}
template<class A>void finish(A&a,const BlockDmaCase&c){reach(a,c.done);}
template<class A>void final_checks(const A&a,const BlockDmaCase&c){const auto o=a.observe();const auto&v=o.values;const auto ram=a.ram();require(ram.size()==65536,"ADPCM RAM extent");for(unsigned i=0;i<65536;++i){const unsigned off=(i-0xfffeu)&65535,wanted=off<2048?(off*17+(off>>8)*7+0x53)&255:0;require(ram[i]==wanted,"Independent READ-fed ADPCM RAM differs");}require(v[0]==c.done&&v[1]==0&&v[2]==0&&v[3]==0&&v[4]==255&&v[5]==7&&v[6]==c.divisor&&v[8]==unsigned(c.kind==0)&&v[9]==unsigned(c.kind==0)&&v[16]==2048&&v[17]==2046&&v[18]==1&&v[19]==1,"Independent endpoint CPU/ADPCM differs");require((v[14]&128)==0&&v[15]==0&&!v[21]&&!v[22],"Guest did not finish READ/DMA/IRQ");require(a.wram()==expected_wram(c),"Independent complete WRAM/block/witness/stack residue differs");}
}
