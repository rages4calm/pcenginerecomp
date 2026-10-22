#pragma once

#include <array>
#include <cstdint>
#include <memory>
#include <optional>
#include <stdexcept>
#include <string>

namespace pce {
inline constexpr unsigned abi_version = 1;
enum Flag : std::uint8_t { C=1, Z=2, I=4, D=8, B=16, T=32, V=64, N=128 };
enum class Exit { executed, miss, unsupported, budget };
enum class BankKind { unmapped, ram, rom, io };

struct Fault : std::runtime_error { using std::runtime_error::runtime_error; };

struct Cpu {
    std::uint8_t a=0, x=0, y=0, sp=0xFF, p=I;
    std::uint16_t pc=0;
    std::array<std::uint8_t,8> mpr{0xFF,0xF8,0x80,0x81,0x82,0x83,0x84,0};
    std::uint64_t ticks=0, cycles=0, native_steps=0, interpreter_steps=0, guard_misses=0;
    // Baseline sandbox starts at high speed. CSL/CSH and IRQ delivery are
    // intentionally unsupported until bus-cycle scheduling is implemented.
    unsigned clock_divisor=3;
    void nz(std::uint8_t value) { p = (p & ~(N|Z)) | (value & N) | (value == 0 ? Z : 0); }
    void retire(unsigned count, bool native) {
        cycles += count;
        ticks += static_cast<std::uint64_t>(count)*clock_divisor;
        if(native) ++native_steps; else ++interpreter_steps;
    }
};

struct Bus {
    // Explicit analysis sandbox, not a completed PC Engine memory/device model.
    std::array<BankKind,256> kind{};
    std::array<std::uint64_t,256> generation{};
    std::unique_ptr<std::array<std::uint8_t,0x200000>> bytes =
        std::make_unique<std::array<std::uint8_t,0x200000>>();
    static std::uint32_t physical(const Cpu& cpu, std::uint16_t address) {
        return (static_cast<std::uint32_t>(cpu.mpr[address >> 13]) << 13) | (address & 0x1FFF);
    }
    std::optional<std::uint8_t> peek(std::uint32_t address) const;
    std::uint8_t read(const Cpu& cpu, std::uint16_t address) const;
    void write(const Cpu& cpu, std::uint16_t address, std::uint8_t value);
    void load(std::uint32_t address, const std::uint8_t* source, std::size_t count);
};

void push(Bus&, Cpu&, std::uint8_t);
std::uint8_t pop(Bus&, Cpu&);
Exit interpret_step(Bus&, Cpu&, std::uint64_t deadline);
// Defined either by generated code or by the no-module stub. Single-step ABI
// makes invalidation and every instruction boundary observable from day one.
Exit generated_step(Bus&, Cpu&, std::uint64_t deadline);
Exit step(Bus&, Cpu&, std::uint64_t deadline, bool allow_interpreter=true);
const char* exit_name(Exit);
} // namespace pce
