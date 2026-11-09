#pragma once

#include "pce/runtime.hpp"
#include <filesystem>
#include <chrono>
#include <vector>

namespace pce {
// Software callback observations only: no synthetic fetch, dummy or idle cycles.
// Recorder ownership is host-side; it is not part of CPU/Bus/checkpoint state.
struct BusTraceLimits {
    std::size_t max_calls=10000, max_events=60000;
    std::uint64_t max_retired=100000, wall_ms=60000;
};
struct BusTraceCheckpointOrigin {
    std::string sha256;
    std::uint64_t ticks=0, frame=0, native_steps=0, interpreter_steps=0;
};
struct BusTraceMetadata {
    std::string engine_name, engine_revision, source_sha256, binary_sha256;
    std::string fixture_sha256, case_name;
    std::optional<BusTraceCheckpointOrigin> checkpoint_origin;
};
struct BusTraceSource {
    std::uint16_t pc=0;
    std::array<std::uint8_t,8> mpr{};
    std::array<std::uint32_t,7> physical{};
    std::array<std::uint8_t,7> bytes{};
    unsigned size=0;
    bool available=false;
    // SHA256(pce-bus-source-1 NUL, PC u16le, MPR[8], size u8,
    //        each encoded byte's physical u32le then byte). Entry snapshot.
    std::string sha256;
};
enum class BusTraceDirection { read, write };
enum class BusTraceSpace { mapped, fixed_vdc };
struct BusTraceEvent {
    std::uint64_t ordinal=0, call=0, ticks=0, cycles=0;
    BusTraceDirection direction=BusTraceDirection::read;
    BusTraceSpace space=BusTraceSpace::mapped;
    std::optional<std::uint16_t> logical;
    std::optional<std::array<std::uint8_t,8>> mpr;
    std::uint32_t physical=0;
    std::uint8_t value=0;
};
struct BusTraceCall {
    std::uint64_t ordinal=0, ticks=0, cycles=0, end_ticks=0, end_cycles=0;
    unsigned divisor=0, end_divisor=0;
    BusTraceSource source;
    Cpu entry_cpu, end_cpu;
    std::string entry_wram_sha256, end_wram_sha256;
    Exit result=Exit::unsupported;
    bool faulted=false;
    std::uint64_t native=0, interpreted=0, irq_entries=0, block_bytes=0;
};
namespace detail { class BusTraceScope; class BusTraceFetch; }
class BusTrace {
public:
    explicit BusTrace(BusTraceLimits limits={});
    ~BusTrace();
    BusTrace(const BusTrace&)=delete;
    BusTrace& operator=(const BusTrace&)=delete;
    // One active recorder per execution thread. Attach before execution and
    // detach before moving execution to another thread. Host peeks are excluded.
    void attach(Bus&,Cpu&);
    void detach() noexcept;
    const std::vector<BusTraceCall>& calls() const noexcept {return calls_;}
    const std::vector<BusTraceEvent>& events() const noexcept {return events_;}
    const BusTraceLimits& limits() const noexcept {return limits_;}
    bool complete() const noexcept {return stop_reason_.empty() &&
        (calls_.size()==limits_.max_calls || retired_==limits_.max_retired) && !active_call_;}
    const std::string& stop_reason() const noexcept {return stop_reason_;}
    // Final state is retained at the last observed boundary, even if the guest
    // subsequently continues. No encoded guest bytes are written to JSONL.
    std::string jsonl(const BusTraceMetadata&,const std::string& stop="call-limit",bool complete=true) const;
    void write(const std::filesystem::path&,const BusTraceMetadata&,
               const std::string& stop="call-limit",bool complete=true) const;
private:
    friend class detail::BusTraceScope;
    friend class detail::BusTraceFetch;
    friend void observe_bus_access(Bus&,const Cpu&,BusTraceDirection,BusTraceSpace,
                                   std::optional<std::uint16_t>,std::uint32_t,std::uint8_t);
    BusTraceLimits limits_;
    Bus* bus_=nullptr;
    Cpu* cpu_=nullptr;
    std::vector<BusTraceCall> calls_;
    std::vector<BusTraceEvent> events_;
    std::string stop_reason_;
    std::optional<std::size_t> active_call_;
    unsigned fetch_depth_=0;
    Cpu initial_cpu_;
    std::string initial_wram_sha256_;
    std::uint64_t retired_=0;
    std::chrono::steady_clock::time_point attached_at_;
};

// Internal execution hooks. They never invoke a caller-provided callback.
void observe_bus_access(Bus&,const Cpu&,BusTraceDirection,BusTraceSpace,
                        std::optional<std::uint16_t>,std::uint32_t,std::uint8_t);
namespace detail {
class BusTraceScope {
public:
    BusTraceScope(Bus&,Cpu&);
    ~BusTraceScope();
    void finish(Exit) noexcept;
private:
    BusTrace* trace_=nullptr;
    Cpu* cpu_=nullptr;
    std::uint64_t native_=0, interpreted_=0, irqs_=0, block_bytes_=0;
    bool finished_=false;
};
class BusTraceFetch {
public:
    BusTraceFetch(Bus&,Cpu&) noexcept;
    ~BusTraceFetch();
private:
    BusTrace* trace_=nullptr;
};
}
}
