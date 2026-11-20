#include "pce/desktop_view.hpp"

#include <algorithm>
#include <array>

namespace {
using Color = std::array<std::uint8_t, 3>;
constexpr int room_width = 512;
constexpr int ground = 132;
constexpr std::uint32_t player_address = 0x1F0040;
constexpr Color stone{211, 153, 85}, leaf{126, 205, 155};

void rectangle(pce::VideoFrame& canvas, int x, int y, int width, int height, Color color) {
    const int left = std::max(0, x), right = std::min(int(canvas.width), x + width);
    if (left >= right) return;
    for (int row = std::max(0, y); row < std::min(int(canvas.height), y + height); ++row) {
        auto dest = canvas.rgb.begin() + (row * canvas.width + left) * 3;
        for (int col = left; col < right; ++col) {
            dest = std::copy(color.begin(), color.end(), dest);
        }
    }
}

void draw_room(pce::VideoFrame& canvas, int camera) {
    const int width = int(canvas.width);
    rectangle(canvas, 0, 0, width, ground, {51, 91, 126});
    rectangle(canvas, 0, 96, width, 36, {63, 113, 137});
    // Each terrain column is placed in world coordinates and clipped against
    // the viewport. Narrow and wide cameras see the same tile grid.
    for (int world_x = camera / 16 * 16; world_x < camera + width; world_x += 16) {
        const int x = world_x - camera;
        const int ridge = 74 + (world_x / 16 * 7 % 24);
        rectangle(canvas, x, ridge, 16, ground - ridge, {43, 76, 98});
        rectangle(canvas, x, ground, 16, 48, {44, 53, 66});
        rectangle(canvas, x, ground, 16, 3, {95, 156, 120});
        rectangle(canvas, x + 1, 146 + (world_x / 16 % 3) * 6, 12, 5, {57, 68, 82});
    }
    rectangle(canvas, 108 - camera, 104, 18, 28, stone);
    rectangle(canvas, 106 - camera, 100, 22, 4, {237, 181, 103});
    rectangle(canvas, 393 - camera, 106, 16, 26, leaf);
    rectangle(canvas, 391 - camera, 104, 20, 3, {157, 224, 175});
}

void draw_player(pce::VideoFrame& canvas, int x) {
    rectangle(canvas, x - 5, 112, 10, 16, {236, 107, 97});
    rectangle(canvas, x - 3, 114, 6, 5, {246, 210, 161});
    rectangle(canvas, x - 4, 128, 3, 4, {28, 35, 49});
    rectangle(canvas, x + 1, 128, 3, 4, {28, 35, 49});
}

void draw_hud(pce::VideoFrame& canvas, int player) {
    rectangle(canvas, 8, 8, 38, 10, {24, 36, 50});
    rectangle(canvas, 10, 10, 34, 6, {231, 111, 108});
    const int right_panel = int(canvas.width) - 56;
    rectangle(canvas, right_panel, 8, 48, 10, {24, 36, 50});
    rectangle(canvas, right_panel + 4, 12, 40, 2, {106, 128, 147});
    rectangle(canvas, right_panel + 4 + player * 38 / room_width, 11, 2, 4, {242, 213, 142});
}
}

bool pce::render_desktop_frame(const pce::DesktopFrameInput& input, pce::VideoFrame& output) {
    const auto player_byte = input.peek(player_address);
    if (input.peek(player_address + 1) != 0xA5 || !player_byte) return false;

    const int player = int(*player_byte) * 2;
    const int width = input.view == pce::PortView::sixteen_nine ? 320 : 240;
    const int camera = std::clamp(player - width / 2, 0, room_width - width);
    output.width = width;
    output.height = 180;
    output.rgb.resize(output.width * output.height * 3);
    draw_room(output, camera);
    draw_player(output, player - camera);
    draw_hud(output, player);
    return true;
}
