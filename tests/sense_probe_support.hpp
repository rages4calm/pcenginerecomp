#pragma once
// Authored bus supervisor shared by isolated executables, never device logic.
#include "reset_probe_support.hpp"
#include <array>
#include <string>
namespace sense_probe {
struct Reply {std::vector<unsigned> data;unsigned status=999,message=999;};
template<class A>void wait_request(A& a) {
    for(unsigned i=0;i<20000;++i){if(a.request())return;a.advance(1000);}
    throw std::runtime_error("bounded SCSI request wait exceeded");
}
template<class A>void start(A& a,const std::vector<unsigned>& cdb) {
    if(a.busy())throw std::runtime_error("selection requires idle bus");
    a.select();wait_request(a);
    for(auto byte:cdb){wait_request(a);if(a.input()||!a.control())throw std::runtime_error("CDB direction differs");
        a.write_data(byte);a.ack(true);a.advance(1);a.ack(false);a.advance(1);}
}
template<class A>Reply drain(A& a,bool automatic) {
    Reply r;unsigned polls=0;
    while(a.busy()) {
        if(++polls>100000)throw std::runtime_error("bounded SCSI reply exceeded");
        if(!a.request()){a.advance(1000);continue;}
        if(!a.input())throw std::runtime_error("reply direction differs");
        const bool data=!a.control();const auto byte=a.read_data(automatic&&data);
        if(data){if(r.data.size()>=4096)throw std::runtime_error("reply payload bound");r.data.push_back(byte);}
        else if(a.message()){if(r.message<=255)throw std::runtime_error("duplicate MESSAGE byte");r.message=byte;}
        else {if(r.status<=255)throw std::runtime_error("duplicate STATUS byte");r.status=byte;}
        if(automatic&&data)a.finish_auto_ack();
        else {a.ack(true);a.advance(1);a.ack(false);a.advance(1);}
    }
    if(r.status>255||r.message>255)throw std::runtime_error("status/message missing");return r;
}
inline std::vector<unsigned> command(std::istream& plan,unsigned& automatic) {
    unsigned count;if(!(plan>>automatic>>count)||automatic>1||(count!=6&&count!=10))throw std::runtime_error("CDB shape");
    std::vector<unsigned> bytes(count);for(auto& value:bytes)if(!(plan>>value)||value>255)throw std::runtime_error("CDB byte");return bytes;
}
inline void record(bool& first,const std::vector<unsigned>& cdb,unsigned automatic,const Reply& r) {
    if(!first)std::cout<<',';first=false;std::cout<<"{\"kind\":\"reply\",\"automatic\":"<<automatic<<",\"cdb\":[";
    for(unsigned i=0;i<cdb.size();++i)std::cout<<(i?",":"")<<cdb[i];std::cout<<"],\"data\":[";
    for(unsigned i=0;i<r.data.size();++i)std::cout<<(i?",":"")<<r.data[i];
    std::cout<<"],\"status\":"<<r.status<<",\"message\":"<<r.message<<'}';
}
}
