#pragma once
// Authored adapter helpers. No third-party operation implementation is included.
#include "reset_probe_support.hpp"
#include <filesystem>
#include <array>
#include <sstream>
namespace bram_probe {
inline std::vector<std::uint8_t> seed() {
    std::vector<std::uint8_t> bytes(2048);
    for(unsigned i=0;i<bytes.size();++i)bytes[i]=static_cast<std::uint8_t>(i*13+(i>>8)*37+0x31);
    return bytes;
}
inline std::vector<std::uint64_t> values(const std::uint8_t* bytes,unsigned count) {
    return std::vector<std::uint64_t>(bytes,bytes+count);
}
template<class Adapter>void execute(Adapter& a,const char* plan_name,const std::filesystem::path& prefix) {
    std::ifstream plan(plan_name);if(!plan)throw std::runtime_error("missing authored plan");
    bool first=true;unsigned exports=0;std::filesystem::path saved;std::string op;std::cout<<'[';
    while(plan>>op) {
        if(op=="r") {unsigned fast;if(!(plan>>fast)||fast>1)throw std::runtime_error("entry speed bound");a.reset(fast);}
        else if(op=="i") {unsigned count;if(!(plan>>count)||count>20000)throw std::runtime_error("instruction bound");a.instructions(count);}
        else if(op=="b") {
            reset_probe::record(first,"cpu",a.cpu());reset_probe::record(first,"bram",a.bram());
            reset_probe::record(first,"ram",a.ram());reset_probe::record(first,"gate",{a.gate()});
        }else if(op=="x") {
            saved=prefix; saved += "-"+std::to_string(exports++)+".bram";
            if(std::filesystem::exists(saved)||std::filesystem::is_symlink(saved))throw std::runtime_error("export requires new private output");
            const auto cpu=a.cpu(),ram=a.ram(),bytes=a.bram();const auto gate=a.gate();
            a.save(saved);
            if(cpu!=a.cpu()||ram!=a.ram()||bytes!=a.bram()||gate!=a.gate())throw std::runtime_error("export mutated guest state");
            std::ifstream file(saved,std::ios::binary);std::vector<std::uint8_t> actual((std::istreambuf_iterator<char>(file)),{});
            if(actual.size()!=2048||values(actual.data(),2048)!=bytes)throw std::runtime_error("raw export differs from full backing bytes");
            reset_probe::record(first,"export",values(actual.data(),2048));
        }else if(op=="l") {
            if(saved.empty())throw std::runtime_error("load before export");a.restore(saved);
        }else throw std::runtime_error("unknown authored operation");
    }
    std::cout<<"]\n";
}
}
