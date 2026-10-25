#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <span>
#include <vector>

namespace pce {
enum class HuCardHeader { none, copier512 };
enum class HuCardEncoding { linear, bit_reversed };
enum class HuCardProfile { none, base, sf2, populous };
struct HuCardImage {
    std::vector<std::uint8_t> rom;
    unsigned header_bytes=0;
    bool bit_reversed=false;
};

// Explicit dump interpretation only. No header, region, board or title guessing.
HuCardImage decode_hucard(std::span<const std::uint8_t>,HuCardHeader,HuCardEncoding,
                         HuCardProfile=HuCardProfile::base);
// Profiles name a caller-selected board; sizes never infer a board or title.
void validate_hucard_size(std::size_t,HuCardProfile);
// Selected standard compatibility map, not every physical cartridge board.
std::array<std::uint8_t,128> hucard_bank_map(std::size_t decoded_size,
                                          HuCardProfile=HuCardProfile::base);
} // namespace pce
