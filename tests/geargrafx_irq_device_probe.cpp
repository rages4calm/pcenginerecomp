// Authored observation around a separately compiled complete original Gear core.
// BIOS/media loading and deterministic reset options are public configuration;
// guest opcodes establish all compared CPU, mapping, RAM and device state.
#include "geargrafx_core.h"
#include "huc6280.h"
#include "huc6270.h"
#include "huc6260.h"
#include "media.h"
#include "memory.h"
#include "cdrom.h"
#include "scsi_controller.h"
#include "audio.h"
#include "trace_logger.h"
#include "irq_device_fixture.hpp"
#include "irq_trace_support.hpp"
#include "reset_probe_support.hpp"
#include <cstdio>
#include <filesystem>
#include <memory>
#include <optional>
#include <sstream>

#if defined(GG_DISABLE_DISASSEMBLER)
#error Original CPU/IRQ/device trace callbacks must remain enabled
#endif
bool g_mcp_stdio_mode = true;
namespace {
void require_device(bool value, const std::string& message) {
    if(!value) throw std::runtime_error(message);
}
template<class Tag, typename Tag::type Member> struct Access {
    friend typename Tag::type member(Tag) { return Member; }
};
#define DEVICE_FIELD(Tag, Owner, Type, Name) \
    struct Tag { using type = Type Owner::*; friend type member(Tag); }; \
    template struct Access<Tag, &Owner::Name>;
DEVICE_FIELD(Extra, HuC6280, u32, m_extra_master_cycles)
DEVICE_FIELD(ResponseOffset, ScsiController, u32, m_data_buffer_offset)
DEVICE_FIELD(DmaPending, HuC6270, u32, m_vram_transfer_pending)
DEVICE_FIELD(ReadPending, HuC6270, bool, m_pending_memory_read)
DEVICE_FIELD(WritePending, HuC6270, bool, m_pending_memory_write)
#undef DEVICE_FIELD
struct ClockTag { using type = bool (GeargrafxCore::*)(u32); friend type member(ClockTag); };
template struct Access<ClockTag, &GeargrafxCore::ClockHardware<true, false, false>>;
struct Span { std::uint64_t before, requested, after; };
struct ClockContext {
    GeargrafxCore* core;
    std::vector<Span> spans;
    std::uint64_t last_audio_flush = 0, audio_flushes = 0;
    static void clock(void* context, u32 ticks) {
        auto& self = *static_cast<ClockContext*>(context);
        require_device(self.spans.size() < 200000, "Original clock callback bound exceeded");
        const auto before = self.core->GetMasterClockCycles();
        (self.core->*member(ClockTag{}))(ticks);
        const auto after = self.core->GetMasterClockCycles();
        require_device(after == before + ticks, "Original device clock did not advance requested span");
        self.spans.push_back({before, ticks, after});
        if(after - self.last_audio_flush >= 4096) {
            // Drain the original audio buffers at actual CPU-driven times.
            // This does not add guest clocks or synthesize an IRQ/device edge.
            self.core->GetAudio()->EndFrame(nullptr, nullptr);
            self.last_audio_flush = after;
            ++self.audio_flushes;
        }
    }
};
irq_trace::State observe(GeargrafxCore& core) {
    auto* cpu = core.GetHuC6280()->GetState(); auto* memory = core.GetMemory();
    irq_trace::State out;
    out.pc = cpu->PC->GetValue(); out.a = cpu->A->GetValue();
    out.x = cpu->X->GetValue(); out.y = cpu->Y->GetValue();
    out.sp = cpu->S->GetValue(); out.p = cpu->P->GetValue();
    for(unsigned page = 0; page < 8; ++page) out.mpr[page] = memory->GetMpr(page);
    out.mpr_latch = memory->GetMprTMA(0); out.clock_divisor = *cpu->SPEED ? 3 : 12;
    out.ticks = core.GetMasterClockCycles();
    out.wram_sha256 = irq_trace::hash(std::span<const std::uint8_t>(memory->GetWorkingRAM(), 8192));
    return out;
}
std::array<std::uint64_t,39> values(GeargrafxCore& core, std::uint64_t origin,
                                  std::uint64_t entries, unsigned vector, unsigned rti,
                                  std::uint64_t waits) {
    const auto state = observe(core); auto* cpu = core.GetHuC6280()->GetState();
    auto* vdc = core.GetHuC6270_1(); auto* cd = core.GetCDROM()->GetState();
    auto* scsi = core.GetScsiController(); auto* bus = scsi->GetState();
    std::array<std::uint64_t,39> out{state.pc,state.a,state.x,state.y,state.sp,state.p,
        state.clock_divisor,state.ticks-origin};
    for(unsigned page = 0; page < 8; ++page) out[8+page] = state.mpr[page];
    out[16] = *state.mpr_latch; out[17] = entries; out[18] = vector; out[19] = rti;
    out[20] = (*cpu->IRR & 4) != 0; out[21] = *cpu->IDR; out[22] = *cpu->TIMER;
    for(unsigned i = 0; i < 3; ++i) out[23+i] = core.GetMemory()->GetWorkingRAM()[0x10+i];
    out[26] = *cpu->IRR; out[27] = *vdc->GetState()->SR;
    out[28] = *cd->ENABLED_IRQS; out[29] = *cd->ACTIVE_IRQS;
    out[30] = (*bus->SIGNALS & ScsiController::SCSI_SIGNAL_ACK) != 0;
    out[31] = *bus->SIGNALS; out[32] = static_cast<unsigned>(*bus->PHASE);
    // Device DB is the current response byte. The outgoing host data latch
    // retains the last CDB byte and is a separate original-core field.
    out[33] = *bus->DB; out[34] = scsi->*member(ResponseOffset{});
    out[35] = vdc->*member(DmaPending{}); out[36] = vdc->*member(ReadPending{});
    out[37] = vdc->*member(WritePending{}); out[38] = waits;
    return out;
}
void write_values(std::ostream& out, const std::array<std::uint64_t,39>& row) {
    out << '[';
    for(unsigned i = 0; i < row.size(); ++i) out << (i ? "," : "") << row[i];
    out << ']';
}
void literal(GeargrafxCore& core, std::uint64_t origin, const IrqDeviceLiteral& expected,
             unsigned ordinal, std::uint64_t entries, unsigned vector, unsigned rti,
             std::uint64_t waits) {
    const auto first = observe(core), second = observe(core);
    const auto row = values(core, origin, entries, vector, rti, waits);
    require_device(first == second && row == values(core,origin,entries,vector,rti,waits),
                   "Repeated original device inspection changed state");
    if(row != expected.values) {
        std::cerr << "ACTUAL"; for(auto v : row) std::cerr << ' ' << v;
        std::cerr << "\nEXPECTED"; for(auto v : expected.values) std::cerr << ' ' << v;
        std::cerr << '\n';
        throw std::runtime_error("Original Gear device literal differs at ordinal " + std::to_string(ordinal));
    }
    require_device(first.wram_sha256 == expected.wram_sha256,
                   "Original full WRAM/stack literal differs at ordinal " + std::to_string(ordinal));
}
void write_original(std::ostream& out, const GG_Trace_Entry& event) {
    out << "{\"cycle\":" << event.cycle;
    switch(event.type) {
    case TRACE_CPU:
        require_device(event.cpu.size >= 1 && event.cpu.size <= 7, "Original fetched CPU bytes unavailable");
        out << ",\"type\":\"cpu\",\"pc\":" << event.cpu.pc << ",\"bank\":" << unsigned(event.cpu.bank)
            << ",\"a\":" << unsigned(event.cpu.a) << ",\"x\":" << unsigned(event.cpu.x)
            << ",\"y\":" << unsigned(event.cpu.y) << ",\"sp\":" << unsigned(event.cpu.s)
            << ",\"p\":" << unsigned(event.cpu.p) << ",\"bytes\":[";
        for(unsigned i=0;i<event.cpu.size;++i) out << (i ? "," : "") << unsigned(event.cpu.opcodes[i]);
        out << ']'; break;
    case TRACE_CPU_IRQ:
        out << ",\"type\":\"TRACE_CPU_IRQ\",\"pc\":" << event.irq.pc << ",\"vector\":" << event.irq.vector
            << ",\"mask\":" << unsigned(event.irq.irq_mask); break;
    case TRACE_VDC:
        out << ",\"type\":\"vdc\",\"event\":" << unsigned(event.vdc.event) << ",\"chip\":" << unsigned(event.vdc.chip)
            << ",\"reg\":" << unsigned(event.vdc.reg) << ",\"raw\":" << unsigned(event.vdc.raw)
            << ",\"msb\":" << unsigned(event.vdc.msb) << ",\"value\":" << event.vdc.value
            << ",\"value2\":" << event.vdc.value2 << ",\"value3\":" << event.vdc.value3 << ",\"param\":" << event.vdc.param; break;
    case TRACE_CDROM:
        out << ",\"type\":\"cdrom\",\"event\":" << unsigned(event.cdrom.event)
            << ",\"irq_type\":" << unsigned(event.cdrom.irq_type) << ",\"active\":" << unsigned(event.cdrom.active)
            << ",\"enabled\":" << unsigned(event.cdrom.enabled) << ",\"state\":" << unsigned(event.cdrom.state)
            << ",\"lba\":" << event.cdrom.lba << ",\"param\":" << event.cdrom.param; break;
    case TRACE_SCSI:
        require_device(event.scsi.size <= 16, "Original SCSI callback data exceeds storage");
        out << ",\"type\":\"scsi\",\"event\":" << unsigned(event.scsi.event)
            << ",\"command\":" << unsigned(event.scsi.command) << ",\"phase\":" << unsigned(event.scsi.phase)
            << ",\"status\":" << unsigned(event.scsi.status) << ",\"param\":" << event.scsi.param << ",\"data\":[";
        for(unsigned i=0;i<event.scsi.size;++i) out << (i ? "," : "") << unsigned(event.scsi.data[i]);
        out << ']'; break;
    default: throw std::runtime_error("Unexpected original trace callback type");
    }
    out << '}';
}
std::FILE* new_file(const std::filesystem::path& path) {
#ifdef _WIN32
    auto* file = _wfopen(path.c_str(), L"wbx");
#else
    auto* file = std::fopen(path.c_str(), "wbx");
#endif
    require_device(file != nullptr, "Choose a new private original output");
    return file;
}
} // namespace

int main(int argc, char** argv) {
    try {
        std::cout << std::unitbuf;
        require_device(argc == 6, "gear-irq-device AUTHORED_BIOS AUTHORED_CUE CASE NEW_WRAM NEW_JOURNAL");
        const auto& item = irq_device_case(argv[3]);
        const auto bios = reset_probe::rom(argv[1]);
        require_device(bios == irq_device_rom(item), "Exact authored original device BIOS required");
        std::unique_ptr<std::FILE,decltype(&std::fclose)> journal(new_file(argv[5]), &std::fclose);
        GeargrafxCore core; core.Init(nullptr);
        core.GetMedia()->SetConsoleType(GG_CONSOLE_PCE); core.GetMedia()->SetCDROMType(GG_CDROM_STANDARD);
        core.GetHuC6280()->SetResetValue(0); core.GetMemory()->SetResetValues(0,0,0,0);
        core.GetHuC6260()->SetResetValue(0); core.GetHuC6270_1()->SetSafeDefaults(false);
        core.GetScsiController()->SetResetValue(0);
        require_device(core.LoadBiosFromBuffer(bios.data(),static_cast<int>(bios.size()),true) &&
                       core.LoadMedia(argv[2],false) && core.GetMedia()->IsCDROMHardwareEnabled() &&
                       !core.GetMedia()->IsSGX() && core.GetMedia()->GetCDROMType()==GG_CDROM_STANDARD &&
                       core.GetMedia()->GetCardRAMSize()==0 && core.GetMemory()->GetCardRAMSize()==0,
                       "Actual authored standard System Card CD profile without expanded Card RAM required");
        ClockContext context{&core}; auto* cpu = core.GetHuC6280();
        cpu->SetHardwareClock(ClockContext::clock, &context);
        auto* logger = core.GetTraceLogger();
        require_device(logger->SetCapacity(4096), "Original trace callback capacity unavailable");
        logger->SetEnabledFlags(TRACE_FLAG_CPU|TRACE_FLAG_CPU_IRQ|TRACE_FLAG_VDC|TRACE_FLAG_CDROM|TRACE_FLAG_SCSI);
        logger->SetEventFilter(TRACE_VDC,TRACE_VDC_FILTER_ALL);
        logger->SetEventFilter(TRACE_CDROM,TRACE_CDROM_FILTER_ALL);
        logger->SetEventFilter(TRACE_SCSI,TRACE_SCSI_FILTER_ALL);
        std::uint64_t entries=0, waits=0, origin=0; unsigned last_vector=0, rti=0, blocks=0;
        auto step = [&](const char* phase,unsigned ordinal) {
            logger->Reset(); context.spans.clear();
            const auto entry=observe(core);
            const auto entry_values=values(core,origin,entries,last_vector,rti,waits);
            unsigned calls=0; bool complete=false;
            std::uint64_t returned=0, internal=0, extra=0;
            do {
                require_device(++calls<=65538,"Original continuation call bound exceeded");
                const auto ticks=cpu->RunInstruction(&complete);
                const auto clocked=cpu->GetClockedMasterCycles(); // Observe BEFORE wrapper drain.
                const auto stalls=cpu->*member(Extra{});
                require_device(clocked<=ticks,"Original internally clocked ticks exceed returned total");
                returned+=ticks; internal+=clocked; extra+=stalls;
                if(ticks>clocked) ClockContext::clock(&context,ticks-clocked);
            } while(!complete);
            require_device(std::string_view(phase)!="measured" || calls==1,
                           "Measured aggregate model requires exactly one original call");
            unsigned cpu_records=0, irq_records=0, opcode=0;
            std::optional<std::uint16_t> delivered;
            for(unsigned i=0;i<logger->GetCount();++i) {
                const auto& event=logger->GetEntry(i);
                if(event.type==TRACE_CPU) {
                    ++cpu_records; opcode=event.cpu.opcodes[0];
                    require_device(event.cpu.pc==entry.pc && event.cpu.bank==entry.mpr[entry.pc>>13],
                                   "Original fetched source context differs");
                } else if(event.type==TRACE_CPU_IRQ) {
                    ++irq_records; ++entries; last_vector=event.irq.vector; delivered=event.irq.vector;
                    require_device(*delivered==0xFFF6 || *delivered==0xFFF8 || *delivered==0xFFFA,
                                   "Original hardware IRQ vector unavailable");
                }
            }
            require_device(cpu_records==1 && irq_records<=1 && logger->GetCount()==logger->GetTotalLogged(),
                           "Original CPU/IRQ callback count or trace loss differs");
            if(opcode==0x40) ++rti;
            if(opcode==0x73 || opcode==0xC3 || opcode==0xD3 || opcode==0xE3 || opcode==0xF3) ++blocks;
            waits+=extra;
            const auto after=observe(core); const auto row=values(core,origin,entries,last_vector,rti,waits);
            require_device(after==observe(core) && row==values(core,origin,entries,last_vector,rti,waits),
                           "Repeated original post-call inspection changed state");
            std::ostringstream record;
            record << "{\"phase\":\"" << phase << "\",\"ordinal\":" << ordinal << ",\"original_calls\":" << calls << ",\"entry\":";
            reference_trace::write_state(record,entry); record << ",\"state\":"; reference_trace::write_state(record,after);
            record << ",\"entry_values\":"; write_values(record,entry_values); record << ",\"values\":"; write_values(record,row);
            record << ",\"returned_ticks\":" << returned << ",\"internal_clocked_ticks\":" << internal
                   << ",\"extra_ticks\":" << extra << ",\"clocks\":[";
            for(unsigned i=0;i<context.spans.size();++i) {
                const auto& span=context.spans[i];
                record << (i ? "," : "") << "{\"before\":" << span.before << ",\"requested\":" << span.requested << ",\"after\":" << span.after << '}';
            }
            record << "],\"original_trace\":[";
            for(unsigned i=0;i<logger->GetCount();++i) {
                if(i) record << ',';
                write_original(record,logger->GetEntry(i));
            }
            record << "]}\n"; const auto raw=record.str();
            require_device(std::fwrite(raw.data(),1,raw.size(),journal.get())==raw.size() && std::fflush(journal.get())==0,
                           "Original device journal write failed");
            return delivered;
        };
        for(unsigned i=0;i<item.primer_steps;++i)
            require_device(!step("primer",i+1),"Masked guest software primer delivered an IRQ");
        origin=observe(core).ticks;
        literal(core,origin,item.initial,0,entries,last_vector,rti,waits);
        irq_trace::write_initial(std::cout,observe(core));
        for(unsigned ordinal=1;ordinal<=item.steps;++ordinal) {
            const auto entry=observe(core); const auto delivered=step("measured",ordinal);
            literal(core,origin,item.gear_rows[ordinal-1],ordinal,entries,last_vector,rti,waits);
            const auto& expected=item.gear_rows[ordinal-1];
            require_device(unsigned(delivered.has_value())==expected.irq_count &&
                           (delivered ? *delivered : 0)==expected.irq_vector,"Actual original hardware IRQ callback differs");
            const auto after=observe(core);
            irq_trace::write_event(std::cout,ordinal,"opcode",entry,after,delivered);
            irq_trace::write_instruction(std::cout,ordinal,ordinal,ordinal,entry,after,delivered);
        }
        require_device(observe(core).pc==item.end_pc && blocks==item.block_steps,"Original sentinel/block completion count differs");
        irq_trace::write_final(std::cout,item.steps,item.steps,observe(core));
        std::unique_ptr<std::FILE,decltype(&std::fclose)> dump(new_file(argv[4]),&std::fclose);
        require_device(std::fwrite(core.GetMemory()->GetWorkingRAM(),1,8192,dump.get())==8192,
                       "Original final WRAM write failed");
        require_device(std::fflush(dump.get())==0,"Original final WRAM flush failed");
        std::cerr << "GEAR_IRQ_DEVICE " << item.steps << " primer=" << item.primer_steps << " blocks=" << blocks
                  << " irq=" << entries << " dynamic_wait_ticks=" << waits << " audio_flushes=" << context.audio_flushes
                  << " profile=standard card_ram=0\n";
        return 0;
    } catch(const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
