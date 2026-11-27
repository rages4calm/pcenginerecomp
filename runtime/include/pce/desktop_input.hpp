#pragma once
#include <array>
#include <cstdint>
#include <string>

namespace pce {
// Host-only bindings. SDL scancodes/buttons are retained as numeric lookup
// indices here so consumers need not include SDL headers in their public API.
struct DesktopInputSlot {
    std::array<std::uint16_t,512> keyboard{};
    std::array<std::uint16_t,32> gamepad_buttons{};
    int gamepad_index=-1;
    unsigned deadzone=16000;
};
struct DesktopInputProfile {
    std::array<DesktopInputSlot,5> slots{};
};
DesktopInputProfile default_desktop_input_profile();
// A <=16 KiB ASCII JSON schema1 file. Loading performs no SDL initialization,
// device opening, filesystem mutation or guest-state changes.
DesktopInputProfile read_desktop_input_profile(const std::string& path);
} // namespace pce
