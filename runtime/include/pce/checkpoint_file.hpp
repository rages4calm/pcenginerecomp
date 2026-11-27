#pragma once
#include "pce/checkpoint.hpp"
#include <filesystem>
#include <string>
#include <optional>
#include <vector>

namespace pce {
// Enhanced host state is separately versioned; pristine envelopes keep v1.
struct CheckpointAdapterBinding {
    std::string binding_sha256;
    std::uint32_t state_bytes=0;
};
struct CheckpointAdapterState {
    std::string binding_sha256;
    std::vector<std::uint8_t> state;
};
// Host recipe cursors, never native pointers, file handles or SDL objects.
struct CheckpointHostState {
    std::array<std::uint16_t,5> scripted{}, remote{};
    std::uint64_t input_applied=0, memory_requests=0, memory_changes=0;
    std::uint64_t source_wav_frames=0;
    std::uint64_t next_poll=0;
    std::optional<CheckpointAdapterState> adapter;
};
struct CheckpointFile {
    std::unique_ptr<MachineCheckpoint> machine;
    CheckpointHostState host;
    std::string sha256, payload_sha256;
};
bool checkpoint_hex_identity(const std::string&);
std::filesystem::path checkpoint_path(const std::filesystem::path& directory,const std::string& name);
std::string checkpoint_hash(std::span<const std::uint8_t>);
// Exclusive new file. Caller supplies exact independently checked host identity.
CheckpointFile save_checkpoint_file(const std::filesystem::path&,const std::string& identity,
                                    const Bus&,const Cpu&,const CheckpointHostState&);
// No live mutation. Header, identity, digest and full payload validate first.
CheckpointFile load_checkpoint_file(const std::filesystem::path&,const std::string& identity,const Bus&,
                                    const std::string& expected_file_sha256={},
                                    const CheckpointAdapterBinding* expected_adapter=nullptr);
} // namespace pce
