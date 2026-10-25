#pragma once
#include <array>
#include <cstdint>
#include <span>
#include <string>
#include <vector>

namespace pce {
struct Vdc;

// Deterministic zero-initialized functional HuC6260 palette. Bus integration
// supplies the mapped-access wait and propagates control to the raster clock.
struct Vce {
    bool enabled=false;
    std::uint8_t control=0;
    std::uint16_t address=0;
    std::array<std::uint16_t,512> palette{};
    std::uint64_t reads=0, writes=0;
    std::uint8_t read(unsigned port);
    void write(unsigned port, std::uint8_t value);
};

struct VideoFrame {
    unsigned width=0, height=0;
    std::vector<std::uint8_t> rgb;
};

// Standard RGB keeps the existing floor(three-bit-channel * 255 / 7)
// expansion. Control bit 7 selects the full-range Mesen digital grayscale
// profile over those RGB values; it is not an analog colorburst simulation.
std::array<std::uint8_t,3> vce_rgb(std::uint16_t color, std::uint8_t control);

// A current-state inspection image, not a capture of raster history. Rendering
// never changes guest clocks, VRAM, status, sprite collisions or IRQ state.
// satb is empty for background-only inspection, or exactly 256 sprite words.
VideoFrame render_snapshot(const Vdc&, const Vce&,
                           std::span<const std::uint16_t> satb={});
// Decode a historical line's VDC color indices. Scroll Y is the already
// incremented/latching counter, not a frame-relative offset. The caller owns
// timing and converts palette values when individual dots reach the VCE.
void render_scanline_indices(const Vdc&, unsigned sprite_y, unsigned scroll_x,
                             unsigned scroll_y, std::uint16_t control,
                             std::uint16_t mode, std::span<std::uint16_t> output);
void write_ppm(const VideoFrame&, const std::string& path);
} // namespace pce
