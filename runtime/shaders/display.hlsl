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
    float4 settings;
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
    float2 edge = saturate((frac(texel) - 0.5) / footprint + 0.5);
    float2 sample_uv = (floor(texel) + edge + 0.5) / size;
    float3 rgb = frame_texture.Sample(frame_sampler, sample_uv).rgb;

    if (settings.x > 0.5) {
        float scanline = 0.5 + 0.5 * cos(6.28318530718 * texel.y);
        float strength = (1.0 - smoothstep(0.35, 0.75, footprint.y)) * 0.24;
        float2 centered = 2.0 * uv - 1.0;
        float vignette = 1.0 - 0.08 * dot(centered * centered, centered * centered);
        rgb *= (1.0 - strength * (1.0 - scanline)) * vignette;
    }
    return float4(rgb, 1.0) * vertex_color;
}
