#pragma once
// Authored finite protocol supervision and observers; no device implementation.
#include "reset_probe_support.hpp"
#include <array>
#include <string>
#include <sstream>
namespace dma_checkpoint {
struct Plan {unsigned cut=0,mode=0,divisor=0;};
inline Plan plan(const char* path) {std::ifstream in(path);Plan p;std::string tail;
 if(!(in>>p.cut>>p.mode>>p.divisor)||p.cut>7||(p.mode!=1&&p.mode!=2)||(p.divisor!=3&&p.divisor!=12)||(in>>tail))throw std::runtime_error("invalid bounded DMA plan");return p;}
inline void require(bool value,const char* why){if(!value)throw std::runtime_error(why);}
struct Mark {std::string name;std::vector<std::uint64_t> values;};
template<class A>void mark(A& a,const char* name){a.journal.push_back({name,a.snapshot()});}
template<class A,class P>void until(A& a,P predicate,unsigned bound=1000000) {
 for(unsigned n=0;n<bound;++n){if(predicate())return;a.advance(1);}std::ostringstream detail;detail<<"bounded DMA wait exceeded after "<<(a.journal.empty()?"start":a.journal.back().name)<<" snapshot";for(auto v:a.snapshot())detail<<' '<<v;detail<<" "<<a.error_state();throw std::runtime_error(detail.str());}
template<class A>void req(A& a){for(unsigned n=0;n<20000;++n){if(a.request())return;a.advance(1000);}throw std::runtime_error("bounded CD request wait");}
template<class A>void send(A& a,unsigned lba,unsigned count){
 a.write(0x1800,0);const unsigned cdb[]={8,0,0,lba,count,0};
 for(auto value:cdb){req(a);require(!a.input()&&a.control(),"CDB phase");a.write(0x1801,value);a.write(0x1802,0x8c);a.advance(1);a.write(0x1802,0x0c);a.advance(1);}}
template<class A>void setup(A& a){
 a.write(0x180d,128);a.write(0x180d,0);a.write(0x1808,0xfe);a.write(0x1809,0xff);a.write(0x180d,3);a.write(0x180d,0);a.write(0x1802,12);}
template<class A>void first(A& a){
 if(!a.request()&&(!(a.dma()&3)||!a.dma_remaining())&&!a.write_remaining()) {auto n=a.load_wait();if(n>1)a.advance_safe(n-1);}
 until(a,[&]{return a.request()&&a.input()&&!a.control();});}
template<class A>void prefix(A& a,const Plan& p){
 setup(a);send(a,0,p.cut==5?2:1);
 if(p.cut==0){a.write(0x180b,p.mode);mark(a,"waiting-first-req");return;}
 first(a);a.write(0x180b,p.mode);mark(a,"arm-end");
 if(p.cut==1)until(a,[&]{return a.dma_remaining()>0&&!a.write_remaining();});
 if(p.cut==2)until(a,[&]{return a.write_remaining()>0&&a.ack();});
 if(p.cut==3)until(a,[&]{return a.length()>0&&!a.write_remaining()&&a.ack();});
 if(p.cut==4){until(a,[&]{return a.dma_remaining()>0&&!a.write_remaining();});a.write(0x180b,0);}
 if(p.cut==5)until(a,[&]{return a.length()==2048&&!a.write_remaining()&&!a.ack();});
 if(p.cut==6)a.write(0x180d,128);
 if(p.cut==7)a.write(0x1804,2);
 mark(a,"cut");
}
struct Reply {std::vector<unsigned> ram,status,message,flags;};
template<class A>Reply suffix(A& a,const Plan& p){
 if(p.cut==0){first(a);if(p.mode==1)a.write(0x180b,1);}
 if(p.cut==4){const auto before=a.ram();const auto remaining=a.dma_remaining();a.advance(120);require(a.ram()==before&&a.dma_remaining()==remaining,"disabled DMA did not freeze");a.write(0x180b,p.mode);}
 if(p.cut==5){first(a);if(p.mode==1)a.write(0x180b,1);}
 if(p.cut>=6){
  if(p.cut==6){const auto before=a.ram();a.advance(200);require(a.ram()==before,"reset-held ADPCM committed RAM");}
  else a.advance(200);
  mark(a,"after-reset-hold");a.write(0x180b,0);a.write(0x180d,128);a.write(0x1804,2);a.advance(200);a.write(0x1804,0);setup(a);send(a,1,1);first(a);a.write(0x180b,p.mode);
 }
 const auto target=p.cut==5?4096u:2048u;
 until(a,[&]{return a.length()==target&&!a.write_remaining();});mark(a,"payload-committed");
 a.write(0x180b,0);
 Reply result;
 for(unsigned n=0;a.busy();++n){require(n<40000,"bounded status wait");if(!a.request()){a.advance(1000);continue;}
  require(a.input()&&a.control(),"unexpected undrained DMA payload");const bool message=a.message();const auto value=a.read(0x1801);(message?result.message:result.status).push_back(value);
  a.write(0x1802,0x8c);a.advance(1);a.write(0x1802,0x0c);a.advance(1);
 }
 result.ram=a.ram();result.flags={a.length(),a.write_address(),a.half(),a.end(),a.irq()};
 a.write(0x1802,0);result.flags.insert(result.flags.end(),{a.irq(),a.half(),a.end()});
 a.write(0x1802,12);result.flags.push_back(a.irq());a.write(0x180d,16);
 result.flags.insert(result.flags.end(),{a.end(),a.half(),a.irq()});a.write(0x180d,128);
 result.flags.insert(result.flags.end(),{a.irq(),a.half(),a.end()});mark(a,"acknowledged-end");return result;
}
template<class T>void vector_json(const T& values){std::cout<<'[';bool first=true;for(auto v:values){std::cout<<(first?"":",")<<+v;first=false;}std::cout<<']';}
inline void reply_json(const Reply& r){std::cout<<"{\"ram\":";vector_json(r.ram);std::cout<<",\"status\":";vector_json(r.status);std::cout<<",\"message\":";vector_json(r.message);std::cout<<",\"flags\":";vector_json(r.flags);std::cout<<'}';}
inline void journal_json(const std::vector<Mark>& rows){std::cout<<'[';bool first=true;for(const auto& row:rows){std::cout<<(first?"":",")<<"{\"label\":\""<<row.name<<"\",\"values\":";vector_json(row.values);std::cout<<'}';first=false;}std::cout<<']';}
}
