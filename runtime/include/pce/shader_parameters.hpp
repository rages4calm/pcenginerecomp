#pragma once
#include <array>

namespace pce {
// Presentation percentages, independent of guest colors, clocks and state.
// Defaults reproduce the original presets. A zero effect strength disables it.
struct ShaderParameters {
    unsigned scanline=24, mask=22, grid=26, vignette=8;
    unsigned brightness=100, saturation=100;
    bool operator==(const ShaderParameters&) const=default;
    bool valid() const {
        return scanline<=100 && mask<=100 && grid<=100 && vignette<=100 &&
               brightness<=200 && saturation<=200;
    }
    std::array<float,8> uniforms() const {
        return {scanline/100.0f,mask/100.0f,grid/100.0f,vignette/100.0f,
                brightness/100.0f,saturation/100.0f,0.0f,0.0f};
    }
};
} // namespace pce
