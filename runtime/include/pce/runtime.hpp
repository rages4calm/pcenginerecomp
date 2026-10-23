#pragma once

#include <array>
#include <cstdint>
#include <memory>
#include <optional>
#include <stdexcept>
#include <string>

namespace pce {
inline constexpr unsigned abi_version = 10;
enum Flag : std::uint8_t { C=1, Z=2, I=4, D=8, B=16, T=32, V=64, N=128 };
enum class Exit { executed, miss, unsupported, budget };
enum class BankKind { unmapped, ram, rom, io, bram };

struct Fault : std::runtime_error { using std::runtime_error::runtime_error; };

struct Cpu {
    std::uint8_t a=0, x=0, y=0, sp=0xFF, p=I;
    std::uint16_t pc=0;
    std::array<std::uint8_t,8> mpr{0xFF,0xF8,0x80,0x81,0x82,0x83,0x84,0};
    // Dedicated TAM/TMA transfer latch, not the general memory or I/O bus.
    // Zero is the deterministic sandbox initial value, not a power-on claim.
    std::uint8_t mpr_latch=0;
    std::uint64_t ticks=0, cycles=0, native_steps=0, interpreter_steps=0, guard_misses=0;
    // Completed block-instruction accounting, separate from transferred bytes.
    std::uint64_t native_block_steps=0, interpreter_block_steps=0, block_bytes=0;
    // Explicit sandbox initial speed; hardware reset/IRQ timing is separate.
    unsigned clock_divisor=3;
    void nz(std::uint8_t value) { p = (p & ~(N|Z)) | (value & N) | (value == 0 ? Z : 0); }
    void retire(unsigned count, bool native) {
        cycles += count;
        ticks += static_cast<std::uint64_t>(count)*clock_divisor;
        if(native) ++native_steps; else ++interpreter_steps;
    }
    void retire_speed(unsigned next_divisor, bool native) {
        // Two cycles at entry speed, final cycle at the selected speed.
        ticks += 2*clock_divisor;
        cycles += 2;
        clock_divisor = next_divisor;
        retire(1,native);
    }
};

// Disc INDEX 01 and leadout are LBAs without the 150-frame lead-in. Metadata
// attachment provides TOC replies, never permission to invent sector bytes.
struct CdTrack {
    std::uint32_t index1_lba=0;
    std::uint8_t type=4; // 0 audio, 4 data
};
struct CdToc {
    std::array<CdTrack,99> tracks{};
    unsigned track_count=0;
    std::uint32_t leadout_lba=0;
    std::string image_sha256; // Optional provenance for programmatic fixtures.
    void validate() const;
};
CdToc read_toc(const std::string& path); // Bounded PCE_TOC 1 descriptor, not media.

class SectorProvider;

// Clocked command transport with one bounded sector/response buffer.
struct Scsi {
    bool enabled=false, status_pending=false;
    unsigned phase=0;
    std::uint16_t signals=0;
    std::uint8_t latch=0, data=0;
    std::uint64_t master_ticks=0, deadline=0, auto_ack_deadline=0;
    unsigned event=0; // 0 none, 1 command, 2 REQ, 3 status, 4 message, 5 free, 6 data, 7 response REQ
    std::array<std::uint8_t,16> command{}, last_command{};
    std::array<std::uint8_t,2048> response{};
    bool read_active=false;
    std::uint32_t load_lba=0, current_lba=0;
    unsigned load_remaining=0;
    std::uint64_t load_deadline=0;
    unsigned response_size=0, response_index=0;
    unsigned command_size=0, last_command_size=0;
};

// Idle control and clocked transport are separate opt-in profiles.
struct CdControl {
    bool enabled=false, bram_unlocked=true, ack=false;
    std::uint8_t interrupt_enable=0, interrupt_active=0, reset=0;
    std::uint64_t reads=0, writes=0, toc_replies=0, data_bytes_acked=0;
    std::uint64_t read_commands=0, sectors_read=0, read_retries=0, read_errors=0;
    Scsi scsi;
    std::shared_ptr<SectorProvider> provider;
    std::optional<CdToc> toc;
    bool irq2() const { return (interrupt_enable & interrupt_active)!=0; }
    void advance_to(std::uint64_t ticks);
    void set_toc(const CdToc& value);
    void set_sector_provider(std::shared_ptr<SectorProvider> value);
    std::uint8_t transport_read(unsigned port);
    void transport_write(unsigned port, std::uint8_t value);
private:
    void phase(unsigned value);
    void handshake();
    void schedule(unsigned event, std::uint64_t delay);
    void update_irq();
    void start_status(std::uint8_t value, unsigned length=1);
    void read_directory();
    void read_sectors();
    void load_sector();
    void schedule_load(std::uint64_t delay);
};

// Explicit timing state; counters are guest master ticks and VDC dots, never
// host presentation time. Enum order follows the hardware counter sequence.
struct RasterTiming {
    bool enabled=false, hsync=true, vsync=true, compare_pending=false, blank_consumed=false;
    std::uint8_t control=0;
    std::uint64_t master_ticks=0, frames=0, vblank_events=0, rcr_events=0;
    unsigned hclock=0, line=0, dot=0, vdc_line=0, raster_line=0;
    unsigned divider=4, total_lines=262, h_state=0, v_state=0;
    int h_remaining=1, v_remaining=2, event_remaining=0;
    unsigned event=0; // 0 none, 1 scroll-Y checkpoint, 2 scroll-X, 3 HDS, 4 compare
    std::array<unsigned,4> horizontal{}; // HDS/HDW/HDE/HSW lengths in dots
    std::array<unsigned,4> vertical{}; // VDS/VDW/VCR/VSW counter lengths
};

// Single VDC. Raster timing is separately opt-in; VRAM accesses still settle
// synchronously. Rendering, DMA, contention and CPU IRQ delivery are separate.
struct Vdc {
    bool enabled=false, irq1=false;
    std::uint8_t selected=0, status=0;
    std::array<std::uint16_t,20> reg{};
    std::unique_ptr<std::array<std::uint16_t,32768>> vram =
        std::make_unique<std::array<std::uint16_t,32768>>();
    std::uint16_t read_buffer=0;
    std::uint64_t reads=0, writes=0, vram_changes=0;
    RasterTiming raster;
    unsigned increment() const { constexpr unsigned steps[]={1,32,64,128}; return steps[(reg[5]>>11)&3]; }
    void prefetch();
    std::uint8_t read(unsigned port);
    void write(unsigned port, std::uint8_t value);
    void enable_raster(); // Reset clock phase, latch the current register values.
    void advance(std::uint64_t delta_master_ticks);
    void write_vce_control(std::uint8_t value);
private:
    void latch_horizontal();
    void latch_vertical();
    void schedule_line_events();
    void compare_line();
    void horizontal_edge();
    void dot_tick();
    void line_tick();
    void raster_event();
};

// Deterministic Gear-reference controller protocol; host snapshots are active
// high, returned button nibbles active low. No host keyboard/turbo/accessories.
struct Joypad {
    struct Pad { unsigned buttons=2; std::uint16_t pressed=0; };
    bool enabled=false, japanese=true, cd=false, multitap=false;
    bool sel=true, clr=true, extra=false;
    unsigned selected=0;
    std::uint8_t latched=0xF0;
    std::array<Pad,5> pads{};
    std::uint64_t reads=0, writes=0;
    void reset(); // Release buttons/clear protocol; retain device configuration.
    void set_pressed(unsigned slot, unsigned mask);
    void set_type(unsigned slot, unsigned buttons);
    void set_multitap(bool value) { multitap=value; }
    std::uint8_t read();
    void write(std::uint8_t value);
};

struct Bus {
    // Explicit analysis sandbox, not a completed PC Engine memory/device model.
    std::array<BankKind,256> kind{};
    std::array<std::uint64_t,256> generation{};
    std::unique_ptr<std::array<std::uint8_t,0x200000>> bytes =
        std::make_unique<std::array<std::uint8_t,0x200000>>();
    CdControl cd;
    Vdc vdc;
    Joypad joypad;
    static std::uint32_t physical(const Cpu& cpu, std::uint16_t address) {
        return (static_cast<std::uint32_t>(cpu.mpr[address >> 13]) << 13) | (address & 0x1FFF);
    }
    std::optional<std::uint8_t> peek(std::uint32_t address) const;
    void enable_cd_control(); // Volatile, unformatted BRAM; never loads/saves a file.
    void enable_cd_transport(); // Adds a bounded command/status handshake, no media.
    void enable_vdc(); // Opt-in functional profile, deterministic zero initial state.
    void enable_video_timing(); // Adds the master-clock raster profile.
    void enable_joypad(bool japanese=true, bool cd=false);
    void sync(const Cpu& cpu); // Absolute CPU time, rejects clock regression.
    void begin_instruction(const Cpu& cpu);
    void retire(Cpu& cpu, unsigned cycles, bool native);
    void clock_cpu(Cpu& cpu, unsigned cycles); // Progress inside one instruction; no retirement/IRQ entry.
    std::uint8_t read_block(Cpu&, std::uint16_t);
    void write_block(Cpu&, std::uint16_t, std::uint8_t);
    void retire_speed(Cpu& cpu, unsigned divisor, bool native);
    void write_vdc(unsigned port, std::uint8_t value); // ST0/ST1/ST2 bypass MPRs.
    std::uint8_t read(Cpu& cpu, std::uint16_t address);
    void write(Cpu& cpu, std::uint16_t address, std::uint8_t value);
    void load(std::uint32_t address, const std::uint8_t* source, std::size_t count);
};

void push(Bus&, Cpu&, std::uint8_t);
std::uint8_t pop(Bus&, Cpu&);
// Interpreter-only block operation. Generated modules emit their own copy loop.
void interpret_block(Bus&, Cpu&, std::uint8_t opcode);
Exit interpret_step(Bus&, Cpu&, std::uint64_t deadline);
// Defined either by generated code or by the no-module stub. Single-step ABI
// makes invalidation and every instruction boundary observable from day one.
Exit generated_step(Bus&, Cpu&, std::uint64_t deadline);
Exit step(Bus&, Cpu&, std::uint64_t deadline, bool allow_interpreter=true);
const char* exit_name(Exit);
} // namespace pce
