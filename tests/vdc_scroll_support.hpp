#pragma once
// Authored read-only observation/report helpers; no device implementation.
#include <array>
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <string>

namespace scroll_probe {
struct State {
    unsigned x,y,counter;
    bool pending;
    int x_clock,y_clock,lsb_clock;
    bool bxr_before;
    std::array<unsigned,16> pixels{};
    bool operator==(const State&) const=default;
};
inline void require(bool condition,const std::string& what) {
    if(!condition)throw std::runtime_error(what);
}
inline void state(std::ostream& out,const State& s) {
    out<<"{\"x\":"<<s.x<<",\"y\":"<<s.y<<",\"counter\":"<<s.counter
       <<",\"pending\":"<<unsigned(s.pending)<<",\"x_clock\":"<<s.x_clock
       <<",\"y_clock\":"<<s.y_clock<<",\"lsb_clock\":"<<s.lsb_clock
       <<",\"bxr_before\":"<<unsigned(s.bxr_before)<<",\"pixels\":[";
    for(unsigned i=0;i<s.pixels.size();++i)out<<(i?",":"")<<s.pixels[i];
    out<<"]}";
}
template<class Case> void expected(const State& actual,const Case& c) {
    require(actual.x==c.x,"Independent scroll X literal differs: "+std::string(c.id));
    require(actual.y==c.y,"Independent scroll Y literal differs: "+std::string(c.id));
    require(actual.counter==c.counter,"Independent Y counter literal differs: "+std::string(c.id));
    require(actual.pending==c.pending,"Independent pending-Y literal differs: "+std::string(c.id));
    for(unsigned i=0;i<actual.pixels.size();++i) {
        const unsigned pixel=((((c.x+i)/8)&1)^(c.y&1))?2:1;
        require(actual.pixels[i]==pixel,"Independent rendered pixel literal differs: "+std::string(c.id));
    }
}
}
