#pragma once
#include "pce/checkpoint_file.hpp"

namespace pce {
// An offline diagnostic copy, not an authenticated game SAVE. No guest reads,
// clocks, restore, sector reads or persistence policy changes are performed.
// The canonical loader still checks the provider's immutable metadata.
struct CheckpointBramDiagnostic {
    static constexpr std::uint32_t physical_address=0xF7u*8192u;
    std::array<std::uint8_t,2048> bytes{};
    std::string checkpoint_sha256, core_sha256, bram_sha256;
    std::uint64_t frame=0, raster_frames=0, pending_pcm_frames=0;
    Cpu cpu;
    CheckpointHostState host;
};
// The caller must independently authenticate the original source package and
// derive its exact checkpoint identity and configured Bus. The checkpoint's
// expected whole-file SHA256 is mandatory. Schema-2 adapter checkpoints are
// deliberately refused in v1, rather than dropping their state/binding.
CheckpointBramDiagnostic inspect_checkpoint_bram(const std::filesystem::path&,
    const std::string& identity,const std::string& expected_file_sha256,
    const Bus& configured);
} // namespace pce
