#pragma once
#include "pce/runtime.hpp"
#include <memory>
#include <span>
#include <vector>

namespace pce {
// Versioned developer state, not a portable game-save or emulator-state API.
// Caller must bind the enclosing file to exact binary/module/media identities.
struct MachineCheckpoint {
    Cpu cpu;
    Bus bus;
};
std::vector<std::uint8_t> encode_checkpoint(const Bus&,const Cpu&);
// Configured is an independently initialized machine with the checked source
// media attached. Its read-only provider is reused; no provider state is dumped.
std::unique_ptr<MachineCheckpoint> decode_checkpoint(std::span<const std::uint8_t>,const Bus& configured);
// All decoding, allocation and validation finish before either live object is
// changed. Commit consists only of nonthrowing moves.
void restore_checkpoint(Bus&,Cpu&,std::span<const std::uint8_t>);
} // namespace pce
