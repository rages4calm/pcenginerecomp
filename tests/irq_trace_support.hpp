#pragma once
// Authored serialization only. No emulator CPU/device implementation.
#include "reference_trace_support.hpp"
#include <stdexcept>
#include <string_view>

namespace irq_trace {
using State = reference_trace::State;
using reference_trace::hash;
using reference_trace::write_initial;

inline void vector(std::ostream& out, std::optional<std::uint16_t> value) {
    if(value && *value != 0xFFF6 && *value != 0xFFF8 && *value != 0xFFFA)
        throw std::invalid_argument("Invalid IRQ vector");
    if(value) out << *value; else out << "null";
}
inline void write_event(std::ostream& out, unsigned ordinal, std::string_view kind,
                        const State& entry, const State& after,
                        std::optional<std::uint16_t> irq_vector = std::nullopt) {
    if(kind != "opcode" && kind != "block-continuation" && kind != "irq-entry")
        throw std::invalid_argument("Invalid IRQ trace event kind");
    out << "{\"type\":\"event\",\"ordinal\":" << ordinal << ",\"kind\":\"" << kind << "\",\"entry\":";
    reference_trace::write_state(out, entry);
    out << ",\"state\":"; reference_trace::write_state(out, after);
    out << ",\"irq_vector\":"; vector(out, irq_vector); out << "}\n";
}
inline void write_instruction(std::ostream& out, unsigned ordinal, unsigned start, unsigned end,
                              const State& entry, const State& after,
                              std::optional<std::uint16_t> irq_vector = std::nullopt) {
    out << "{\"type\":\"instruction\",\"ordinal\":" << ordinal
        << ",\"event_start\":" << start << ",\"event_end\":" << end
        << ",\"entry_pc\":" << entry.pc << ",\"entry_mpr\":";
    reference_trace::mapping(out, entry.mpr);
    out << ",\"state\":"; reference_trace::write_state(out, after);
    out << ",\"irq_count\":" << (irq_vector ? 1 : 0) << ",\"irq_vector\":";
    vector(out, irq_vector); out << "}\n";
}
inline void write_final(std::ostream& out, unsigned instructions, unsigned events, const State& state) {
    out << "{\"type\":\"final\",\"executed\":" << instructions << ",\"events\":" << events
        << ",\"stop\":\"instruction-limit\",\"complete\":true,\"state\":";
    reference_trace::write_state(out, state); out << "}\n";
}
} // namespace irq_trace
