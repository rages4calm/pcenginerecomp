// One fragment pass over the completed guest RGB frame.
// SDL GPU's main texture uses slot 0. The renderer supplies UVs at location 1.
#ifdef PCE_SPIRV
[[vk::combinedImageSampler]][[vk::binding(0,2)]]
#endif
Texture2D frame_texture : register(t0, space2);
#ifdef PCE_SPIRV
[[vk::combinedImageSampler]][[vk::binding(0,2)]]
#endif
SamplerState frame_sampler : register(s0, space2);

cbuffer Presentation : register(b0, space3) {
    float4 settings; // CRT, smooth reconstruction, LCD grid, color effect
    float4 effects; // scanline, phosphor mask, LCD grid, vignette strengths
    float4 color; // brightness, saturation, reserved, reserved
};

float4 main(
#ifdef PCE_SPIRV
    [[vk::location(0)]]
#endif
    float4 vertex_color : TEXCOORD0,
#ifdef PCE_SPIRV
    [[vk::location(1)]]
#endif
    float2 uv : TEXCOORD1) : SV_Target {
    uint width, height;
    frame_texture.GetDimensions(width, height);
    float2 size = float2(width, height);
    float2 texel = uv * size - 0.5;
    float2 footprint = clamp(fwidth(texel), 0.00390625, 1.0);

    // Preserve the center of each texel while limiting the blend to one
    // output pixel around its edge. Downscaling uses normal bilinear samples.
    float2 fraction = frac(texel);
    float2 edge = saturate((fraction - 0.5) / footprint + 0.5);
    if (settings.y > 0.5) {
        // Cubic interpolation over the full texel interval with zero
        // slope at the two sample centers.
        edge = smoothstep(0.0, 1.0, fraction);
    }
    float2 sample_uv = (floor(texel) + edge + 0.5) / size;
    float3 rgb = frame_texture.Sample(frame_sampler, sample_uv).rgb;

    if (settings.x > 0.5) {
        float scanline = 0.5 + 0.5 * cos(6.28318530718 * texel.y);
        float strength = (1.0 - smoothstep(0.35, 0.75, footprint.y)) * effects.x;
        float2 centered = 2.0 * uv - 1.0;
        float vignette = saturate(1.0 - effects.w * dot(centered * centered, centered * centered));
        rgb *= (1.0 - strength * (1.0 - scanline)) * vignette;
    }
    if (settings.z > 0.5) {
        float2 distance_to_center = abs(frac(texel + 0.5) - 0.5);
        float2 grid = smoothstep(0.28, 0.5, distance_to_center);
        float strength = (1.0 - smoothstep(0.25, 0.75, max(footprint.x, footprint.y))) * effects.z;
        rgb *= 1.0 - strength * max(grid.x, grid.y);
    }
    if (settings.w == 1.0) {
        rgb = dot(rgb, float3(0.299, 0.587, 0.114)).xxx;
    } else if (settings.w == 2.0) {
        // A horizontal UV derivative is one drawable pixel. The resulting
        // triads start at the edge of the viewport and follow its columns.
        float pixel_x = uv.x / max(abs(ddx(uv.x)), 1.0e-8);
        float column = floor(frac(pixel_x / 3.0) * 3.0);
        rgb *= float3(column == 0.0 ? 1.0 : 1.0-effects.y,
                      column == 1.0 ? 1.0 : 1.0-effects.y,
                      column == 2.0 ? 1.0 : 1.0-effects.y);
    }
    rgb = saturate(lerp(dot(rgb, float3(0.299, 0.587, 0.114)).xxx, rgb, color.y) * color.x);
    return float4(rgb, 1.0) * vertex_color;
}
