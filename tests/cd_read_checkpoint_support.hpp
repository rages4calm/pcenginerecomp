#pragma once
// Authored protocol supervision and JSON output only; no device implementation.
#include "reset_probe_support.hpp"
#include <array>
#include <string>
namespace cd_checkpoint {
struct Plan {unsigned cut=0,automatic=0,divisor=0;};
inline Plan plan(const char* path) {
    std::ifstream in(path);Plan p;std::string tail;
    if(!(in>>p.cut>>p.automatic>>p.divisor)||p.cut>7||p.automatic>1||
       (p.divisor!=3&&p.divisor!=12)||(in>>tail))throw std::runtime_error("invalid finite READ checkpoint plan");
    return p;
}
inline const std::vector<unsigned> initial{8,0,0,0,2,0},replacement{8,0,0,1,1,0};
template<class A>void wait(A& a) {
    for(unsigned i=0;i<20000;++i){if(a.request())return;a.advance(1000);}
    throw std::runtime_error("bounded request wait exceeded");
}
template<class A>void send(A& a,const std::vector<unsigned>& cdb,unsigned first=0,unsigned last=6) {
    for(unsigned i=first;i<last;++i){wait(a);if(a.input()||!a.control())throw std::runtime_error("CDB direction");
        a.write_data(cdb[i]);a.ack(true);a.advance(1);a.ack(false);a.advance(1);}
}
template<class A>void start(A& a,const std::vector<unsigned>& cdb) {
    if(a.busy())throw std::runtime_error("selection before idle");a.select();send(a,cdb);
}
template<class A>void acknowledge(A& a,bool automatic) {
    if(automatic){a.advance(21);a.advance(1);}
    else{a.ack(true);a.advance(1);a.ack(false);a.advance(1);}
}
template<class A>unsigned byte(A& a,bool automatic) {
    wait(a);if(!a.input()||a.control())throw std::runtime_error("expected DATA IN");
    const auto result=a.read_data(automatic);acknowledge(a,automatic);return result;
}
template<class A>std::vector<unsigned> prefix(A& a,const Plan& p) {
    std::vector<unsigned> bytes;
    if(p.cut==0){a.select();send(a,initial,0,3);return bytes;}
    start(a,initial);
    if(p.cut==1)return bytes;
    wait(a);
    const unsigned count=p.cut==4?2047:((p.cut==2||p.cut==3||p.cut>=6)?17:0);
    for(unsigned i=0;i<count;++i)bytes.push_back(byte(a,p.automatic));
    if(p.cut==3){bytes.push_back(a.read_data(p.automatic));if(!p.automatic)a.ack(true);a.advance(1);}
    else if(p.cut==4){a.advance(a.load_wait());a.advance(1);}
    else if(p.cut==5)a.advance(300000);
    else if(p.cut==6)a.reset_line(true);
    else if(p.cut==7)a.select();
    return bytes;
}
struct Reply {std::vector<unsigned> data,status,message;};
template<class A>Reply suffix(A& a,const Plan& p) {
    if(p.cut==0)send(a,initial,3,6);
    if(p.cut==3){if(p.automatic){a.advance(21);a.advance(1);}else{a.ack(false);a.advance(1);}}
    if(p.cut==6){a.advance(4000000);a.reset_line(false);start(a,replacement);}
    if(p.cut==7){a.advance(900000);send(a,replacement);}
    Reply r;
    for(unsigned polls=0;a.busy();++polls) {
        if(polls>40000)throw std::runtime_error("bounded response exceeded");
        if(!a.request()){a.advance(1000);continue;}
        if(!a.input())throw std::runtime_error("response direction");
        const bool data=!a.control();const auto value=a.read_data(p.automatic&&data);
        auto& result=data?r.data:(a.message()?r.message:r.status);
        if(result.size()>4096)throw std::runtime_error("response bound");result.push_back(value);
        acknowledge(a,p.automatic&&data);
    }
    if(r.status.size()!=1||r.message.size()!=1)throw std::runtime_error("status/message cardinality");return r;
}
inline void vector_json(const std::vector<unsigned>& v) {
    std::cout<<'[';for(unsigned i=0;i<v.size();++i)std::cout<<(i?",":"")<<v[i];std::cout<<']';
}
inline void reply_json(const Reply& r) {
    std::cout<<"{\"data\":";vector_json(r.data);std::cout<<",\"status\":";vector_json(r.status);
    std::cout<<",\"message\":";vector_json(r.message);std::cout<<'}';
}
}
