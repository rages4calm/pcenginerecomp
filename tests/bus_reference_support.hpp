#pragma once
// Authored transport/collection only. No toolkit CPU or bus implementation.
#include "reference_trace_support.hpp"
#include "bus_reference_fixture.hpp"
#include "bus_reference_hooks.hpp"
#include <iostream>
#include <stdexcept>

namespace bus_reference {
inline bool enabled=false;
inline unsigned ordinal=0,instruction=0,calls=0;
inline reference_trace::State entry;
inline BusFixtureInstruction source;
inline unsigned direct_reads=0,handler_reads=0;
inline void instruction_begin(unsigned i,const reference_trace::State& value,
                              const BusFixtureInstruction& encoded){
    if(value.pc!=encoded.pc)throw std::runtime_error("Authored source PC differs");
    instruction=i;entry=value;source=encoded;
    std::cout<<"{\"type\":\"entry\",\"instruction\":"<<i<<",\"state\":";
    reference_trace::write_state(std::cout,value);
    std::cout<<",\"source_bytes\":[";
    for(unsigned n=0;n<encoded.bytes.size();++n){if(n)std::cout<<',';std::cout<<unsigned(encoded.bytes[n]);}
    std::cout<<"]}\n";
}
inline BusFixtureInstruction candidate(const BusFixture& fixture,unsigned pc){
    for(const auto& row:fixture.instructions)if(row.pc==pc)return row;
    const auto& last=fixture.instructions.back();
    if(pc==last.pc+last.bytes.size())return {pc,{0x80,0xFE}};
    throw std::runtime_error("Candidate source outside authored code extent");
}
inline void access(std::uint64_t tick,const std::array<std::uint8_t,8>& mpr,
                   unsigned logical,unsigned physical,unsigned value,bool write,
                   bool fixed,bool direct){
    if(!enabled)return;
    if(++ordinal>1000)throw std::runtime_error("Finite reference event bound exceeded");
    if(!write){if(direct)++direct_reads;else ++handler_reads;}
    std::cout<<"{\"type\":\"access\",\"ordinal\":"<<ordinal
        <<",\"instruction\":"<<instruction<<",\"tick\":"<<tick
        <<",\"write\":"<<(write?"true":"false")<<",\"logical\":";
    if(fixed)std::cout<<"null";else std::cout<<logical;
    std::cout<<",\"physical\":"<<physical<<",\"value\":"<<value
        <<",\"fixed\":"<<(fixed?"true":"false")<<",\"direct\":"<<(direct?"true":"false")<<",\"mpr\":";
    if(fixed)std::cout<<"null";else reference_trace::mapping(std::cout,mpr);
    std::cout<<"}\n";
}
inline void retired(unsigned i,const reference_trace::State& state,bool complete=true){
    std::cout<<"{\"type\":\"retired\",\"instruction\":"<<i<<",\"state\":";
    reference_trace::write_state(std::cout,state);std::cout<<",\"retired\":"<<(complete?1:0)<<"}\n";
}
inline void finish(unsigned retired){
    std::cout<<"{\"type\":\"closure\",\"retired\":"<<retired
        <<",\"calls\":"<<calls<<",\"events\":"<<ordinal
        <<",\"direct_reads\":"<<direct_reads<<",\"handler_reads\":"<<handler_reads<<"}\n";
}
}
