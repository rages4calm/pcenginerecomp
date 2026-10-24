#pragma once
// Authored fixture/report helpers shared by two external-process adapters.
// These helpers contain no emulated instruction or device implementation.
#include <cstdint>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <vector>

namespace reset_probe {
inline std::vector<std::uint8_t> rom(const char* name) {
    std::ifstream stream(name,std::ios::binary);
    std::vector<std::uint8_t> result((std::istreambuf_iterator<char>(stream)),{});
    if(result.size()!=262144)throw std::runtime_error("require authored 256 KiB ROM");
    return result;
}
template<class T> std::uint64_t hash(const T* data,unsigned count) {
    std::uint64_t value=14695981039346656037ULL;
    for(unsigned i=0;i<count;++i)for(unsigned byte=0;byte<sizeof(T);++byte) {
        value^=(static_cast<std::uint64_t>(data[i])>>(byte*8))&255;
        value*=1099511628211ULL;
    }
    return value;
}
inline void record(bool& first,const char* kind,const std::vector<std::uint64_t>& values) {
    if(!first)std::cout<<',';first=false;
    std::cout<<"{\"kind\":\""<<kind<<"\",\"values\":[";
    for(unsigned i=0;i<values.size();++i){if(i)std::cout<<',';std::cout<<values[i];}
    std::cout<<"]}";
}
inline void valid(unsigned profile,unsigned region,unsigned vector,unsigned registers,unsigned mpr,unsigned ram) {
    if(profile>1 || region>1 || vector<0xE000 || vector>0xFFFD || registers>255 || mpr>255 || ram>255)
        throw std::runtime_error("invalid reset fixture configuration");
}
}
