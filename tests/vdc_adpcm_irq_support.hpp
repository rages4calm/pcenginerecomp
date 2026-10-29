#pragma once
// Authored observations and independent RAM/CPU expectations, no device bodies.
#include "vdc_adpcm_irq_fixture.hpp"
#include "irq_trace_support.hpp"
#include "reset_probe_support.hpp"
#include <array>
#include <cstdint>
#include <map>
#include <tuple>
#include <vector>

namespace vdc_adpcm {
inline void require(bool value,const std::string&why){if(!value)throw std::runtime_error(why);}
template<class T>void vec(std::ostream&out,const T&items){out<<'[';bool first=true;for(auto v:items){out<<(first?"":",")<<+v;first=false;}out<<']';}
using Row=std::vector<std::uint64_t>;
inline constexpr unsigned limit=1500000,words=4096,payload=0xa65c,tail=0x5aa5;
// Old23 CPU/CD/ADPCM fields; status,irq1,VRAMDMA,pendingR,pendingW,buffer,
// MARR,MAWR,SOUR,DESR,LENR,bus,delay,wait_ticks,VCEdiv,DMAwords,CPU sample,AR.
struct Observation{Row values;std::vector<unsigned>stack;std::string wram,vram;};
inline void observation(std::ostream&out,const Observation&o){out<<"{\"values\":";vec(out,o.values);out<<",\"stack\":";vec(out,o.stack);out<<",\"wram_sha256\":\""<<o.wram<<"\",\"vram_sha256\":\""<<o.vram<<"\"}";}
struct Work{std::uint64_t instructions=0,calls=0,clock_calls=0,clock_ticks=0,irqs=0,rtis=0,blocks=0,block_bytes=0,adpcm_cause_groups=0,vdc_cause_groups=0,wait_ticks=0;};
inline void work_json(std::ostream&out,const Work&w){out<<"{\"instructions\":"<<w.instructions<<",\"calls\":"<<w.calls<<",\"clock_calls\":"<<w.clock_calls<<",\"clock_ticks\":"<<w.clock_ticks<<",\"irqs\":"<<w.irqs<<",\"rtis\":"<<w.rtis<<",\"blocks\":"<<w.blocks<<",\"block_bytes\":"<<w.block_bytes<<",\"adpcm_cause_groups\":"<<w.adpcm_cause_groups<<",\"vdc_cause_groups\":"<<w.vdc_cause_groups<<",\"wait_ticks\":"<<w.wait_ticks<<'}';}
struct Source{unsigned pc;std::array<unsigned,8>mpr;std::vector<unsigned>bytes;bool operator<(const Source&b)const{return std::tie(pc,mpr,bytes)<std::tie(b.pc,b.mpr,b.bytes);}};
inline void source_json(std::ostream&out,const Source&s,const char*byte_key="bytes"){out<<"\"pc\":"<<s.pc<<",\"mpr\":";vec(out,s.mpr);out<<",\"physical\":[";for(unsigned i=0;i<s.bytes.size();++i)out<<(i?",":"")<<((s.mpr[((s.pc+i)&65535)>>13]<<13)|((s.pc+i)&8191));out<<"],\""<<byte_key<<"\":";vec(out,s.bytes);}
inline void hits(std::ostream&out,const std::map<Source,std::uint64_t>&items){out<<'[';bool first=true;for(const auto&[source,n]:items){out<<(first?"":",")<<'{';source_json(out,source,"data");out<<",\"hits\":"<<n<<'}';first=false;}out<<']';}
inline bool block(unsigned op){return op==0x73||op==0xf3;}
inline unsigned size(unsigned op){if(block(op))return 7;switch(op){case 0xa9:case 0xa2:case 0x53:case 0x29:case 0xc9:case 0xd0:case 0xf0:case 0x80:return 2;case 0x8d:case 0xad:case 0xee:return 3;default:return 1;}}
inline unsigned block_length(const Source&s){return unsigned(s.bytes[5])|(unsigned(s.bytes[6])<<8);}
inline unsigned saved_a(const VdcAdpcmCase&c){return c.access==0?0xa6:2;}
inline unsigned saved_p(const VdcAdpcmCase&c){return c.access==0?129:1;}
inline std::vector<unsigned>expected_vram(){std::vector<unsigned>v(32768);v[0]=v[0x2000]=payload;v[words-1]=v[0x2000+words-1]=tail;return v;}
inline std::vector<unsigned>expected_wram(const VdcAdpcmCase&c){std::vector<unsigned>w(8192);w[17]=1;w[18]=c.policy==0;w[20]=16;w[21]=saved_a(c);w[22]=12;const unsigned ret=c.return_pc+unsigned(c.policy==0);w[508]=saved_a(c);w[509]=saved_p(c);w[510]=ret&255;w[511]=ret>>8;if(c.access==1){w[512]=0x5c;w[513]=0xa6;}return w;}
inline std::string vram_hash(const std::vector<unsigned>&v){std::vector<std::uint8_t>bytes;bytes.reserve(v.size()*2);for(auto word:v){bytes.push_back(word&255);bytes.push_back(word>>8);}return irq_trace::hash(bytes);}
inline void irq_frame(const Source&s,const Observation&o,unsigned vector,const VdcAdpcmCase&c){const auto&v=o.values;const unsigned first=vector==0xfff8,ret=first?c.return_pc:c.return_pc+1;require((first?s.pc==c.target:s.pc==c.return_pc)&&v[0]==(first?c.handler1:c.handler2)&&v[1]==saved_a(c)&&v[2]==0&&v[3]==0&&v[4]==252&&v[5]==(saved_p(c)|4),"Independent overlap IRQ CPU/source differs");require(o.stack.size()==256&&o.stack[255]==(ret>>8)&&o.stack[254]==(ret&255)&&o.stack[253]==saved_p(c),"Independent overlap descending frame differs");require(v[8]==(first?1:2)&&v[9]==(first?0:1),"Independent priority/RTI order differs");if(first)require(v[11]==3&&v[24]==1&&v[25]==0&&v[18]==1&&v[19]==1&&v[22]==1,"First IRQ did not select IRQ1 while both device lines live");}
inline void rti_frame(const Observation&o,const VdcAdpcmCase&c){const auto&v=o.values;const unsigned ret=c.return_pc+unsigned(v[9]==2);require(v[0]==ret&&v[1]==saved_a(c)&&v[2]==0&&v[3]==0&&v[4]==255&&v[5]==saved_p(c)&&o.stack[252]==saved_a(c),"Independent overlap RTI restoration differs");}
template<class A>unsigned cut_pc(const A&,const VdcAdpcmCase&c,unsigned cut){return cut==0?c.pre_dma:cut==1?c.handler1:c.post_ack;}
template<class A>void reach(A&a,unsigned pc){for(unsigned n=0;n<limit;++n){if(a.pc()==pc)return;a.step();}throw std::runtime_error("Autonomous overlap bound at "+std::to_string(a.pc()));}
template<class A>void finish(A&a,const VdcAdpcmCase&c){reach(a,c.done);}
template<class A>void final_checks(const A&a,const VdcAdpcmCase&c){const auto o=a.observe();const auto&v=o.values;const auto ram=a.ram();require(ram.size()==65536,"ADPCM RAM extent");for(unsigned i=0;i<65536;++i){const unsigned offset=(i-0xfffeu)&65535,wanted=offset<2048?(offset*17+(offset>>8)*7+0x53)&255:0;require(ram[i]==wanted,"Independent full READ-fed ADPCM RAM differs");}require(a.wram()==expected_wram(c),"Independent WRAM/status/result/frame differs");require(a.vram()==expected_vram(),"Independent full VRAM DMA image differs");require(v[0]==c.done&&v[1]==0&&v[2]==0&&v[3]==0&&v[4]==255&&v[5]==7&&v[6]==c.divisor&&v[8]==(c.policy==0?2:1)&&v[9]==v[8]&&v[16]==2048&&v[17]==2046&&v[18]==1&&v[19]==1,"Independent overlap endpoint CPU/ADPCM differs");require(v[14]==0&&v[15]==0&&v[22]==0&&v[24]==0&&v[25]==0&&v[26]==0&&v[27]==0&&v[29]==2&&v[31]==words&&v[32]==0x2000+words&&v[33]==65535&&v[38]==words,"Independent completed queue/DMA/register endpoint differs");}
}
