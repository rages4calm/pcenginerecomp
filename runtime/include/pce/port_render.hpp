#pragma once
#include "pce/video.hpp"
#include <optional>

namespace pce {

// Host-owned scene data only. These helpers neither read a live Bus nor infer
// historical VRAM, palettes, sprite priority, collisions or scanline limits.
// A port owns the snapshot and first qualifies its original-size reconstruction.
struct PortLayerInput {
    unsigned width=0, height=0;
    // Empty means backdrop. Nonzero values are palette/color indices 1..255
    // whose low nibble is nonzero; all background color-zero entries become 0.
    std::span<const std::uint16_t> background{};
    // Empty means no sprites. Otherwise supply the FIRST candidate sprite at
    // each pixel, after resolving sprite order: 0 or 257..511, low nibble != 0.
    std::span<const std::uint16_t> sprites{};
    // One 0/1 per sprite-plane pixel. 1 is in front of nontransparent background.
    std::span<const std::uint8_t> sprite_front{};
    // Exactly 512 GRB9 entries, or height*512 entries captured for each row.
    // Per-row data is supplied by the port, never recovered from current state.
    std::span<const std::uint16_t> palettes{};
    // Empty is standard RGB, otherwise exactly one or height VCE control bytes.
    std::span<const std::uint8_t> controls{};
    // Explicit source for transparent background RGB, e.g. 0x100 for a port's
    // verified blank/border scene. It does not make color zero opaque or infer CR.
    std::uint16_t backdrop=0;
};

struct PortLayerFrame {
    VideoFrame image;
    // Background alone, including the backdrop: useful beneath visible sprites.
    VideoFrame background;
    // A sprite hidden by opaque background, otherwise the background itself.
    // Useful when a presentation effect moves/removes foreground scenery.
    VideoFrame behind_background;
    std::vector<std::uint8_t> sprite_visible;
};

PortLayerFrame compose_port_layers(const PortLayerInput&);

// Host tile cells are explicit rather than packed hardware BAT words. Mirroring
// is a presentation feature; it does not imply the hardware flips BG tiles.
struct PortMapCell {
    std::uint32_t tile=0;
    std::uint8_t palette=0;
    bool flip_x=false, flip_y=false;
    bool operator==(const PortMapCell&) const = default;
};
struct PortTilemapView {
    unsigned columns=0, rows=0;
    std::span<const PortMapCell> cells{};
    // Consecutive 8x8 tiles, one 0..15 color per byte. No guest memory is read.
    std::span<const std::uint8_t> pixels{};
};
struct PortRowScroll { std::int32_t x=0, y=0; };
struct PortClip { std::int32_t left=0, top=0, right=0, bottom=0; };
enum class PortMapAddress { wrap, clip };
struct PortViewport {
    unsigned width=0, height=0;
    std::int32_t x=0, y=0;
    // Empty or exactly height offsets, added to x/y for each output row.
    std::span<const PortRowScroll> row_scroll{};
    PortMapAddress address=PortMapAddress::wrap;
    std::uint16_t outside=0;
    // Optional half-open OUTPUT rectangle. Other pixels receive outside.
    std::optional<PortClip> clip{};
};

// Up to 8192 per output axis / 16M output pixels, 1024 per map axis / 1M cells,
// and 65536 8x8 tiles. Invalid indices, palette values or shapes throw Fault.
std::vector<std::uint16_t> sample_port_tilemap(const PortTilemapView&,const PortViewport&);

} // namespace pce
