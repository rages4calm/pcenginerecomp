#pragma once
// Authored observation/serialization; no CPU or device implementations.
#include "irq_trace_support.hpp"
#include "adpcm_irq_fixture.hpp"
#include <array>
#include <iostream>
#include <string>
namespace adpcm_irq {
inline std::uint64_t checks=0;
inline void require(bool ok,const std::string& message){++checks;if(!ok)throw std::runtime_error(message);}
using Values=std::array<std::uint64_t,36>;
inline void values_json(std::ostream& out,const Values& row){out<<'[';for(unsigned i=0;i<row.size();++i)out<<(i?",":"")<<row[i];out<<']';}
inline void literal(const Values& row,const std::string& wram,const AdpcmIrqLiteral& wanted,unsigned ordinal){
    if(row!=wanted.values){std::cerr<<"ACTUAL";for(auto v:row)std::cerr<<' '<<v;
        std::cerr<<"\nEXPECTED";for(auto v:wanted.values)std::cerr<<' '<<v;std::cerr<<'\n';
        throw std::runtime_error("ADPCM IRQ literal differs at ordinal "+std::to_string(ordinal));}
    require(wram==wanted.wram_sha256,"Full authored WRAM/stack differs at "+std::to_string(ordinal));
}
inline void row_json(std::ostream& out,const Values& row,const std::string& wram,unsigned vector){
    out<<"{\"values\":";values_json(out,row);out<<",\"wram_sha256\":\""<<wram<<"\",\"irq_vector\":"<<vector<<'}';
}
}
