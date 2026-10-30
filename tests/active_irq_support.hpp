#pragma once
// Authored identities, records and independent expected values; no device bodies.
#include "active_irq_fixture.hpp"
#include "irq_trace_support.hpp"
#include "reset_probe_support.hpp"
#include <array>
#include <cstdint>
#include <map>
#include <tuple>
#include <vector>

namespace active_irq {
inline void require(bool v,const std::string&why){if(!v)throw std::runtime_error(why);}
template<class T>void vec(std::ostream&out,const T&items){out<<'[';bool first=true;for(auto v:items){out<<(first?"":",")<<+v;first=false;}out<<']';}
using Row=std::vector<std::uint64_t>;
inline constexpr unsigned limit=1500000,first=0xdead,payload=0xa65c,tail=0x5aa5,data=0x6000,sat=0x7000;
struct Observation{Row values;std::vector<unsigned>stack;std::string wram,vram;std::map<std::string,std::int64_t>active;};
inline void observation(std::ostream&out,const Observation&o){out<<"{\"values\":";vec(out,o.values);out<<",\"stack\":";vec(out,o.stack);out<<",\"wram_sha256\":\""<<o.wram<<"\",\"vram_sha256\":\""<<o.vram<<"\",\"active\":{";bool first=true;for(const auto&[key,value]:o.active){out<<(first?"":",")<<'"'<<key<<"\":"<<value;first=false;}out<<"}}";}
struct Work{std::uint64_t instructions=0,calls=0,clock_calls=0,clock_ticks=0,irqs=0,rtis=0,blocks=0,block_bytes=0,adpcm_cause_groups=0,vdc_cause_groups=0,wait_ticks=0;};
inline void work_json(std::ostream&out,const Work&w){out<<"{\"instructions\":"<<w.instructions<<",\"calls\":"<<w.calls<<",\"clock_calls\":"<<w.clock_calls<<",\"clock_ticks\":"<<w.clock_ticks<<",\"irqs\":"<<w.irqs<<",\"rtis\":"<<w.rtis<<",\"blocks\":"<<w.blocks<<",\"block_bytes\":"<<w.block_bytes<<",\"adpcm_cause_groups\":"<<w.adpcm_cause_groups<<",\"vdc_cause_groups\":"<<w.vdc_cause_groups<<",\"wait_ticks\":"<<w.wait_ticks<<'}';}
struct Source{unsigned pc;std::array<unsigned,8>mpr;std::vector<unsigned>bytes;bool operator<(const Source&b)const{return std::tie(pc,mpr,bytes)<std::tie(b.pc,b.mpr,b.bytes);}};
inline void source_json(std::ostream&out,const Source&s,const char*byte_key="bytes"){out<<"\"pc\":"<<s.pc<<",\"mpr\":";vec(out,s.mpr);out<<",\"physical\":[";for(unsigned i=0;i<s.bytes.size();++i)out<<(i?",":"")<<((s.mpr[((s.pc+i)&65535)>>13]<<13)|((s.pc+i)&8191));out<<"],\""<<byte_key<<"\":";vec(out,s.bytes);}
inline void hits(std::ostream&out,const std::map<Source,std::uint64_t>&items){out<<'[';bool first=true;for(const auto&[source,n]:items){out<<(first?"":",")<<'{';source_json(out,source,"data");out<<",\"hits\":"<<n<<'}';first=false;}out<<']';}
inline bool block(unsigned op){return op==0x73||op==0xf3;}
inline unsigned size(unsigned op){if(block(op))return 7;switch(op){case 0xa9:case 0xa2:case 0x53:case 0x29:case 0xc9:case 0xd0:case 0xf0:case 0x80:return 2;case 0x8d:case 0xad:case 0xee:return 3;default:return 1;}}
inline unsigned block_length(const Source&s){return unsigned(s.bytes[5])|(unsigned(s.bytes[6])<<8);}
inline unsigned saved_a(const ActiveIrqCase&c){return c.access==0?0xa6:2;}
inline unsigned saved_p(const ActiveIrqCase&c){return c.access==0?129:1;}
inline unsigned selected_status(const ActiveIrqCase&c){return c.source==0?4:1;}
inline std::vector<unsigned>expected_vram(){std::vector<unsigned>v(32768);for(unsigned i=0;i<2;++i){v[sat+i*4]=64;v[sat+i*4+1]=32;v[sat+i*4+2]=512;v[sat+i*4+3]=0x3000;}for(unsigned row=0;row<64;++row)v[0x4000+(row/16)*128+(row&15)]=65535;v[data]=first;v[data+1]=payload;v[data+2]=tail;return v;}
inline std::vector<unsigned>expected_wram(const ActiveIrqCase&c){std::vector<unsigned>w(8192);w[17]=1;w[18]=c.policy==0;w[20]=selected_status(c);w[21]=saved_a(c);w[22]=12;const unsigned ret=c.return_pc+unsigned(c.policy==0);w[508]=saved_a(c);w[509]=saved_p(c);w[510]=ret&255;w[511]=ret>>8;if(c.access==1){w[512]=0x5c;w[513]=0xa6;}return w;}
inline std::string vram_hash(const std::vector<unsigned>&v){std::vector<std::uint8_t>b;b.reserve(v.size()*2);for(auto word:v){b.push_back(word&255);b.push_back(word>>8);}return irq_trace::hash(b);}
inline void irq_frame(const Source&s,const Observation&o,unsigned vector,const ActiveIrqCase&c){const auto&v=o.values;const bool first=vector==0xfff8;const unsigned ret=c.return_pc+unsigned(!first);require((first?s.pc==c.target:s.pc==c.return_pc)&&v[0]==(first?c.handler1:c.handler2)&&v[1]==saved_a(c)&&v[2]==0&&v[3]==0&&v[4]==252&&v[5]==(saved_p(c)|4),"Independent active IRQ CPU/source differs");require(o.stack.size()==256&&o.stack[255]==(ret>>8)&&o.stack[254]==(ret&255)&&o.stack[253]==saved_p(c),"Independent active IRQ descending frame differs");require(v[8]==(first?1:2)&&v[9]==(first?0:1),"Independent active IRQ priority/RTI order differs");if(first)require(v[24]==1&&v[18]==1&&v[19]==1&&v[22]==1,"First active IRQ did not retain competing ADPCM source");}
inline void rti_frame(const Observation&o,const ActiveIrqCase&c){const auto&v=o.values;const unsigned ret=c.return_pc+unsigned(v[9]==2);require(v[0]==ret&&v[1]==saved_a(c)&&v[2]==0&&v[3]==0&&v[4]==255&&v[5]==saved_p(c)&&o.stack[252]==saved_a(c),"Independent active IRQ RTI restoration differs");}
template<class A>unsigned cut_pc(const A&,const ActiveIrqCase&c,unsigned cut){return cut==0?c.pre_dma:cut==1?c.handler1:c.post_ack;}
template<class A>void reach(A&a,unsigned pc){for(unsigned n=0;n<limit;++n){if(a.pc()==pc)return;a.step();}throw std::runtime_error("Active IRQ recipe bound at "+std::to_string(a.pc()));}
template<class A>void finish(A&a,const ActiveIrqCase&c){reach(a,c.done);}
template<class A>void final_checks(const A&a,const ActiveIrqCase&c){const auto o=a.observe();const auto&v=o.values;const auto ram=a.ram();require(ram.size()==65536,"ADPCM RAM extent");for(unsigned i=0;i<65536;++i){const unsigned offset=(i-0xfffeu)&65535,wanted=offset<2048?(offset*17+(offset>>8)*7+0x53)&255:0;require(ram[i]==wanted,"Independent full READ-fed ADPCM RAM differs");}const auto actual_wram=a.wram(),wanted_wram=expected_wram(c);for(unsigned i=0;i<actual_wram.size();++i)require(actual_wram[i]==wanted_wram[i],"Independent active IRQ WRAM offset "+std::to_string(i)+" actual "+std::to_string(actual_wram[i])+" expected "+std::to_string(wanted_wram[i]));require(a.vram()==expected_vram(),"Independent active IRQ full VRAM differs");require(v[0]==c.done&&v[1]==0&&v[2]==0&&v[3]==0&&v[4]==255&&v[5]==7&&v[6]==c.divisor&&v[8]==(c.policy==0?2:1)&&v[9]==v[8]&&v[16]==2048&&v[17]==2046&&v[18]==1&&v[19]==1,"Independent active IRQ endpoint differs");require(v[24]==0&&v[25]==0&&v[26]==0&&v[27]==0&&v[28]==tail&&v[29]==data+3&&v[38]==0&&o.active.at("cr")==192&&o.active.at("mwr")==3,"Independent active IRQ acknowledgement/prefetch order differs");}
}
