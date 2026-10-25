#pragma once

#include <array>
#include <cstdint>
#include <memory>

namespace pce {
struct ArcadePort {
    std::uint32_t base=0;
    std::uint16_t offset=0, increment=0;
    std::uint8_t control=0;
};

// Functional Arcade Card Duo data ports. The four physical windows are I/O,
// not executable RAM aliases: an access can advance its selected pointer.
// RAM contents and all pointer/shifter fields are guest state. No persistence
// or warm reset is implicit in this deterministic setup-only profile.
struct ArcadeCard {
    std::array<ArcadePort,4> ports{};
    std::unique_ptr<std::array<std::uint8_t,0x200000>> ram;
    std::uint32_t shift_register=0;
    std::uint8_t shift_amount=0, rotate_amount=0;
    std::uint64_t reads=0, writes=0;

    explicit ArcadeCard(std::uint8_t ram_fill=0);
    std::uint32_t effective_address(unsigned port) const;
    std::uint8_t read_data(unsigned port);
    void write_data(unsigned port,std::uint8_t value);
    std::uint8_t read_register(std::uint16_t offset);
    void write_register(std::uint16_t offset,std::uint8_t value);

private:
    void advance(unsigned port);
    void add_offset(unsigned port);
};
} // namespace pce
