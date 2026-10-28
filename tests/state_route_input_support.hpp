#pragma once
// Authored observer support only. No CPU or controller implementation.
#include "reset_probe_support.hpp"
#include <array>
#include <map>

namespace input_probe {
inline constexpr std::array<unsigned,8> mpr{255,248,128,129,130,131,132,0};
struct Plan {unsigned divisor=0,count=0;std::map<unsigned,unsigned> held;};
inline Plan plan(const char* path) {
    std::ifstream file(path);Plan p;unsigned n;
    if(!(file>>p.divisor>>p.count>>n) || (p.divisor!=3 && p.divisor!=12) || !p.count || p.count>512 || n!=3)
        throw std::runtime_error("invalid finite input plan");
    for(unsigned i=0;i<n;++i) {unsigned index,mask;
        if(!(file>>index>>mask) || index>=p.count || mask>4095 || !p.held.emplace(index,mask).second)
            throw std::runtime_error("invalid held injection");
    }
    std::string extra;if(file>>extra)throw std::runtime_error("trailing plan data");return p;
}
inline std::vector<std::uint8_t> code(const char* path) {
    std::ifstream file(path,std::ios::binary);
    std::vector<std::uint8_t> bytes((std::istreambuf_iterator<char>(file)),{});
    if(bytes.empty() || bytes.size()>4096)throw std::runtime_error("invalid authored code");return bytes;
}
inline unsigned length(unsigned op) {
    if(op==0xA9)return 2;if(op==0xAD || op==0x8D)return 3;if(op==0xEA)return 1;
    throw std::runtime_error("unexpected authored input opcode");
}
template<class Mapping,class Peek>std::vector<std::uint64_t> identity(unsigned index,unsigned pc,const Mapping& mapping,Peek peek) {
    std::vector<std::uint64_t> row{index,pc};row.insert(row.end(),mapping.begin(),mapping.end());
    const auto size=length(peek(pc));row.push_back(size);
    for(unsigned i=0;i<3;++i)row.push_back(i<size?((mapping[(pc+i)>>13]<<13)|((pc+i)&8191)):0);
    for(unsigned i=0;i<3;++i)row.push_back(i<size?peek(pc+i):0);return row;
}
}
