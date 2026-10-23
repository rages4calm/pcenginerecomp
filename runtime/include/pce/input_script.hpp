#pragma once
#include <array>
#include <cstdint>
#include <string>
#include <vector>

namespace pce {
struct InputEvent {
    std::uint64_t ticks=0;
    std::array<std::uint16_t,5> buttons{};
};
// Bounded host snapshots, not a save state or a change to guest sampling rules.
// PCE_INPUT 1 followed by tick and five active-high 12-bit button masks.
std::vector<InputEvent> read_input_script(const std::string& path);
} // namespace pce
