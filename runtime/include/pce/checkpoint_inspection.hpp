#pragma once
#include "pce/checkpoint_file.hpp"

namespace pce {
// Read-only typed diagnostics for one exactly bound source checkpoint. Digests
// compare state; they authorize neither live restore nor cross-build migration.
struct CheckpointInspection {
    Cpu cpu;
    CheckpointHostState host;
    std::string checkpoint_sha256, core_sha256, host_sha256;
    std::string tier_neutral_core_sha256, adapter_state_sha256;
    std::uint64_t frame=0, raster_frames=0, pending_pcm_frames=0;
    bool joypad_enabled=false;
    std::array<std::uint16_t,5> joypad_pressed{};
};
// The caller authenticates the producer package and independently configures
// its machine. An exact whole-file SHA is mandatory. Adapter checkpoints need
// the original expected binding; no adapter state or HOST field is projected.
CheckpointInspection inspect_checkpoint_state(const std::filesystem::path&,
    const std::string& identity,const std::string& expected_file_sha256,
    const Bus& configured,const CheckpointAdapterBinding* expected_adapter=nullptr);
} // namespace pce
