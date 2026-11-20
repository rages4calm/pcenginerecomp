#pragma once
#include <array>
#include <cstdint>
#include <limits>
#include <stdexcept>
#include <string>

namespace pce {
struct DevLocation {
    std::uint16_t pc=0;
    std::array<std::uint8_t,8> mpr{};
    std::uint64_t native=0, interpreted=0;
};

// Main-thread instruction boundaries, separate from frame stepping and guest
// state. An exhausted probe remains paused and is never reported as a return.
class DevInstructionWindow {
public:
    enum class State { idle, running, reached, instructions, ticks };
    State state=State::idle;
    std::uint16_t pc=0;
    std::array<std::uint8_t,8> mpr{};
    std::uint8_t mask=0;
    std::uint64_t native=0, interpreted=0, elapsed=0;
    bool active() const {return state==State::running;}
    void start(const DevLocation& from,std::uint64_t now,std::uint16_t target,
               const std::array<std::uint8_t,8>& mapping,std::uint8_t selected,
               std::uint64_t instructions,std::uint64_t ticks) {
        if(!instructions || instructions>100000000 || !ticks || ticks>10000000000ULL ||
           !(selected&(1u<<(target>>13))))
            throw std::runtime_error("instruction probe requires bounded work and target source mapping");
        pc=target;mpr=mapping;mask=selected;origin=from;origin_ticks=now;
        max_instructions=instructions;max_ticks=ticks;native=interpreted=elapsed=0;state=State::running;
    }
    void update(const DevLocation& at,std::uint64_t now) {
        if(!active())return;
        if(at.native<origin.native || at.interpreted<origin.interpreted || now<origin_ticks)
            throw std::runtime_error("instruction probe counters regressed");
        native=at.native-origin.native;interpreted=at.interpreted-origin.interpreted;elapsed=now-origin_ticks;
        if(native>std::numeric_limits<std::uint64_t>::max()-interpreted)
            throw std::runtime_error("instruction probe counter overflow");
        const auto work=native+interpreted;
        bool match=at.pc==pc;
        for(unsigned i=0;i<8;++i)if((mask&(1u<<i)) && at.mpr[i]!=mpr[i])match=false;
        if(work && match)state=State::reached;
        else if(work>=max_instructions)state=State::instructions;
        else if(elapsed>=max_ticks)state=State::ticks;
    }
    void cancel(){state=State::idle;}
    std::string json() const {
        const char* names[]={"idle","running","reached","instruction_limit","tick_limit"};
        return std::string("{\"schema\":1,\"state\":\"")+names[static_cast<unsigned>(state)]+
            "\",\"native_steps\":"+std::to_string(native)+",\"interpreter_steps\":"+std::to_string(interpreted)+
            ",\"ticks\":"+std::to_string(elapsed)+",\"target_pc\":"+std::to_string(pc)+
            ",\"mpr_mask\":"+std::to_string(mask)+"}";
    }
private:
    DevLocation origin{};
    std::uint64_t origin_ticks=0,max_instructions=0,max_ticks=0;
};
}
