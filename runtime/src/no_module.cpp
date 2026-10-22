#include "pce/runtime.hpp"
namespace pce {
Exit generated_step(Bus&, Cpu& s, std::uint64_t deadline) {
    return s.ticks >= deadline ? Exit::budget : Exit::miss;
}
}
