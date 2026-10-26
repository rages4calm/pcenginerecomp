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
#include "vram_active_fixture.hpp"
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
DEVICE_FIELD(PendingIrq, HuC6280, s32, m_irq_pending)
DEVICE_FIELD(ResponseOffset, ScsiController, u32, m_data_buffer_offset)
DEVICE_FIELD(DmaPending, HuC6270, u32, m_vram_transfer_pending)
DEVICE_FIELD(ReadPending, HuC6270, bool, m_pending_memory_read)
DEVICE_FIELD(WritePending, HuC6270, bool, m_pending_memory_write)
DEVICE_FIELD(TransferDelay, HuC6270, s32, m_transfer_delay)
DEVICE_FIELD(SlotCarry, HuC6270, u32, m_cpu_vram_cycles)
DEVICE_FIELD(VramBus, HuC6270, u16, m_vram_openbus)
DEVICE_FIELD(Burst, HuC6270, bool, m_burst_mode)
DEVICE_FIELD(LatchedCr, HuC6270, u16, m_latched_cr)
DEVICE_FIELD(LatchedMwr, HuC6270, u16, m_latched_mwr)
DEVICE_FIELD(BgStart, HuC6270, s32, m_load_bg_start_clock)
DEVICE_FIELD(BgEnd, HuC6270, s32, m_load_bg_end_clock)
DEVICE_FIELD(HsyncStart, HuC6270, s32, m_hsync_start_clock)
DEVICE_FIELD(SpriteCount, HuC6270, s32, m_sprite_count)
DEVICE_FIELD(SatPending, HuC6270, u16, m_sat_transfer_pending)
DEVICE_FIELD(CachedAllow, HuC6270, bool, m_allow_vram_access)
#undef DEVICE_FIELD
struct ClockTag { using type = bool (GeargrafxCore::*)(u32); friend type member(ClockTag); };
template struct Access<ClockTag, &GeargrafxCore::ClockHardware<true, false, false>>;
struct Kernel {
    unsigned cpu_extra, cpu_clocked, cpu_p, cpu_mask, irr;
    s32 cpu_pending;
    unsigned vdc_status, dma_pending, read_pending, write_pending, vram_carry;
    s32 vram_delay;
    unsigned marr, mawr, dcr, sour, desr, lenr, read_buffer, vram_bus;
    unsigned divider, burst, latched_cr, latched_mwr;
    s32 hpos, vpos, hstate, vstate, bg_start, bg_end, hsync_start;
    unsigned cd_enabled, cd_active, scsi_signals, scsi_phase, scsi_data, response_index;
    s32 sprite_count;
    unsigned sat_pending, cached_allow, vwr;
    bool operator==(const Kernel&) const = default;
};
// hpos is VCE master HPOS; vpos is the original VDC scanline.
// cached_allow is the last original predicate cache, not present eligibility.
// Never call IsCpuVramSlotAvailable() here: it mutates that cache.
Kernel kernel(GeargrafxCore& core) {
    auto* cpu=core.GetHuC6280(); auto* c=cpu->GetState();
    auto* vdc=core.GetHuC6270_1(); auto* v=vdc->GetState();
    auto* cd=core.GetCDROM()->GetState(); auto* scsi=core.GetScsiController(); auto* s=scsi->GetState();
    return {cpu->*member(Extra{}),cpu->GetClockedMasterCycles(),c->P->GetValue(),*c->IDR,*c->IRR,
        cpu->*member(PendingIrq{}),*v->SR,vdc->*member(DmaPending{}),unsigned(vdc->*member(ReadPending{})),
        unsigned(vdc->*member(WritePending{})),vdc->*member(SlotCarry{}),vdc->*member(TransferDelay{}),
        v->R[1],v->R[0],v->R[15],v->R[16],v->R[17],v->R[18],*v->READ_BUFFER,vdc->*member(VramBus{}),
        static_cast<unsigned>(core.GetHuC6260()->GetClockDivider()),unsigned(vdc->*member(Burst{})),
        vdc->*member(LatchedCr{}),vdc->*member(LatchedMwr{}),*core.GetHuC6260()->GetState()->HPOS,
        *v->VPOS,*v->H_STATE,*v->V_STATE,vdc->*member(BgStart{}),vdc->*member(BgEnd{}),
        vdc->*member(HsyncStart{}),*cd->ENABLED_IRQS,*cd->ACTIVE_IRQS,*s->SIGNALS,
        static_cast<unsigned>(*s->PHASE),*s->DB,scsi->*member(ResponseOffset{}),
        vdc->*member(SpriteCount{}),vdc->*member(SatPending{}),unsigned(vdc->*member(CachedAllow{})),v->R[2]};
}
void write_kernel(std::ostream& out,const Kernel& k) {
    out << "{\"cpu_extra\":" << k.cpu_extra << ",\"cpu_clocked\":" << k.cpu_clocked
        << ",\"cpu_pending\":" << k.cpu_pending << ",\"cpu_p\":" << k.cpu_p << ",\"cpu_mask\":" << k.cpu_mask
        << ",\"irr\":" << k.irr << ",\"vdc_status\":" << k.vdc_status << ",\"dma_pending\":" << k.dma_pending
        << ",\"read_pending\":" << k.read_pending << ",\"write_pending\":" << k.write_pending
        << ",\"vram_carry\":" << k.vram_carry << ",\"vram_delay\":" << k.vram_delay
        << ",\"marr\":" << k.marr << ",\"mawr\":" << k.mawr << ",\"dcr\":" << k.dcr
        << ",\"sour\":" << k.sour << ",\"desr\":" << k.desr << ",\"lenr\":" << k.lenr
        << ",\"read_buffer\":" << k.read_buffer << ",\"vram_bus\":" << k.vram_bus
        << ",\"divider\":" << k.divider << ",\"burst\":" << k.burst << ",\"latched_cr\":" << k.latched_cr
        << ",\"latched_mwr\":" << k.latched_mwr << ",\"hpos\":" << k.hpos << ",\"vpos\":" << k.vpos
        << ",\"hstate\":" << k.hstate << ",\"vstate\":" << k.vstate << ",\"bg_start\":" << k.bg_start
        << ",\"bg_end\":" << k.bg_end << ",\"hsync_start\":" << k.hsync_start
        << ",\"cd_enabled\":" << k.cd_enabled << ",\"cd_active\":" << k.cd_active
        << ",\"scsi_signals\":" << k.scsi_signals << ",\"scsi_phase\":" << k.scsi_phase
        << ",\"scsi_data\":" << k.scsi_data << ",\"response_index\":" << k.response_index
        << ",\"sprite_count\":" << k.sprite_count << ",\"sat_pending\":" << k.sat_pending
        << ",\"cached_allow\":" << k.cached_allow << ",\"vwr\":" << k.vwr << '}';
}
struct Span {
    std::uint64_t before, requested, after;
    bool inline_clock;
    Kernel source_before, source_after;
};
struct ClockContext {
    GeargrafxCore* core;
    std::vector<Span> spans;
    bool inside_cpu=false;
    std::uint64_t last_audio_flush = 0, audio_flushes = 0;
    static void clock(void* context, u32 ticks) {
        auto& self = *static_cast<ClockContext*>(context);
        require_device(self.spans.size() < 200000, "Original clock callback bound exceeded");
        const auto before = self.core->GetMasterClockCycles();
        const auto source_before=kernel(*self.core);
        require_device(source_before==kernel(*self.core),
                       "Repeated original pre-clock kernel inspection changed state");
        (self.core->*member(ClockTag{}))(ticks);
        const auto after = self.core->GetMasterClockCycles();
        const auto source_after=kernel(*self.core);
        require_device(source_after==kernel(*self.core),
                       "Repeated original post-clock kernel inspection changed state");
        require_device(after == before + ticks, "Original device clock did not advance requested span");
        // Hardware has run; ORIGINAL ClockHardwareCycles has not yet updated
        // its clocked counter or called CheckIRQs. Retain this raw phase.
        self.spans.push_back({before,ticks,after,self.inside_cpu,source_before,source_after});
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
std::vector<std::uint8_t> vram_bytes(GeargrafxCore& core) {
    const auto* words=core.GetHuC6270_1()->GetVRAM();
    std::vector<std::uint8_t> bytes(65536);
    for(unsigned i=0;i<32768;++i) {
        bytes[2*i]=static_cast<std::uint8_t>(words[i]);
        bytes[2*i+1]=static_cast<std::uint8_t>(words[i]>>8);
    }
    return bytes;
}
std::string vram_hash(GeargrafxCore& core) {
    const auto bytes=vram_bytes(core);
    return irq_trace::hash(bytes);
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
void literal(GeargrafxCore& core, std::uint64_t origin, const VramActiveLiteral& expected,
             unsigned ordinal, std::uint64_t entries, unsigned vector, unsigned rti,
             std::uint64_t waits) {
    const auto first = observe(core), second = observe(core);
    const auto first_vram=vram_hash(core),second_vram=vram_hash(core);
    const auto row = values(core, origin, entries, vector, rti, waits);
    require_device(first == second && first_vram == second_vram && row == values(core,origin,entries,vector,rti,waits),
                   "Repeated original device inspection changed state");
    if(row != expected.values) {
        std::cerr << "ACTUAL"; for(auto v : row) std::cerr << ' ' << v;
        std::cerr << "\nEXPECTED"; for(auto v : expected.values) std::cerr << ' ' << v;
        std::cerr << '\n';
        throw std::runtime_error("Original Gear device literal differs at ordinal " + std::to_string(ordinal));
    }
    require_device(first.wram_sha256 == expected.wram_sha256,
                   "Original full WRAM/stack literal differs at ordinal " + std::to_string(ordinal));
    require_device(first_vram == expected.vram_sha256,
                   "Original full little-endian VRAM literal differs at ordinal " + std::to_string(ordinal));
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
        require_device(argc == 7, "gear-vram-active AUTHORED_BIOS AUTHORED_CUE CASE NEW_WRAM NEW_VRAM NEW_JOURNAL");
        const auto& item = vram_active_case(argv[3]);
        const auto bios = reset_probe::rom(argv[1]);
        require_device(bios == vram_active_rom(item), "Exact authored original device BIOS required");
        std::unique_ptr<std::FILE,decltype(&std::fclose)> journal(new_file(argv[6]), &std::fclose);
        GeargrafxCore core; core.Init(nullptr);
        core.GetMedia()->SetConsoleType(GG_CONSOLE_PCE); core.GetMedia()->SetCDROMType(GG_CDROM_STANDARD);
        core.GetHuC6280()->SetResetValue(0); core.GetMemory()->SetResetValues(0,0,0,0);
        core.GetHuC6260()->SetResetValue(0); core.GetHuC6270_1()->SetSafeDefaults(false);
        core.GetHuC6270_1()->SetNoSpriteLimit(false);
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
            const auto entry_kernel=kernel(core);
            const auto entry_vram=vram_hash(core);
            const auto entry_values=values(core,origin,entries,last_vector,rti,waits);
            require_device(entry==observe(core) && entry_kernel==kernel(core) && entry_vram==vram_hash(core) &&
                           entry_values==values(core,origin,entries,last_vector,rti,waits),
                           "Repeated original pre-call inspection changed state");
            unsigned calls=0; bool complete=false;
            std::uint64_t returned=0, internal=0, extra=0;
            s32 pending_at_return=0;
            Kernel kernel_at_return{};
            do {
                require_device(++calls<=65538,"Original continuation call bound exceeded");
                context.inside_cpu=true;
                const auto ticks=cpu->RunInstruction(&complete);
                context.inside_cpu=false;
                const auto clocked=cpu->GetClockedMasterCycles(); // Observe BEFORE wrapper drain.
                const auto stalls=cpu->*member(Extra{});
                pending_at_return=cpu->*member(PendingIrq{});
                kernel_at_return=kernel(core);
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
            const bool is_block=opcode==0x73 || opcode==0xC3 || opcode==0xD3 || opcode==0xE3 || opcode==0xF3;
            if(is_block) ++blocks;
            const bool partition_only=std::string_view(phase)=="primer" && is_block;
            waits+=extra;
            const auto after=observe(core); const auto row=values(core,origin,entries,last_vector,rti,waits);
            const auto after_vram=vram_hash(core);
            const auto final_kernel=kernel(core);
            require_device(after==observe(core) && after_vram==vram_hash(core) && final_kernel==kernel(core) &&
                           row==values(core,origin,entries,last_vector,rti,waits),
                           "Repeated original post-call inspection changed state");
            std::ostringstream record;
            record << "{\"phase\":\"" << phase << "\",\"ordinal\":" << ordinal << ",\"original_calls\":" << calls
                   << ",\"clock_detail\":\"" << (partition_only ? "partition-only" : "full-kernel") << "\",\"entry\":";
            reference_trace::write_state(record,entry); record << ",\"state\":"; reference_trace::write_state(record,after);
            record << ",\"entry_vram_sha256\":\"" << entry_vram << "\",\"vram_sha256\":\"" << after_vram << '"';
            record << ",\"kernel_entry\":"; write_kernel(record,entry_kernel);
            record << ",\"entry_values\":"; write_values(record,entry_values); record << ",\"values\":"; write_values(record,row);
            record << ",\"returned_ticks\":" << returned << ",\"internal_clocked_ticks\":" << internal
                   << ",\"extra_ticks\":" << extra << ",\"pending_at_return\":" << pending_at_return
                   << ",\"kernel_at_return\":";
            write_kernel(record,kernel_at_return);
            record << ",\"kernel_final\":"; write_kernel(record,final_kernel);
            record << ",\"clocks\":[";
            for(unsigned i=0;i<context.spans.size();++i) {
                const auto& span=context.spans[i];
                record << (i ? "," : "") << "{\"before\":" << span.before << ",\"requested\":" << span.requested
                       << ",\"after\":" << span.after << ",\"context\":\"" << (span.inline_clock?"inline":"wrapper")
                       << "\",\"extra_before\":" << span.source_before.cpu_extra
                       << ",\"clocked_before\":" << span.source_before.cpu_clocked
                       << ",\"pending_before\":" << span.source_before.cpu_pending
                       << ",\"p_before\":" << span.source_before.cpu_p << ",\"mask_before\":" << span.source_before.cpu_mask;
                if(!partition_only) {
                    record << ",\"source_before\":"; write_kernel(record,span.source_before);
                    record << ",\"source_after\":"; write_kernel(record,span.source_after);
                    record << ",\"pending_after_inside_callback\":" << span.source_after.cpu_pending
                           << ",\"after_phase\":\"" << (span.inline_clock ? "before-cpu-resample" : "no-cpu-resample") << '"';
                }
                record << '}';
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
        literal(core,origin,item.gear_initial,0,entries,last_vector,rti,waits);
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
        std::unique_ptr<std::FILE,decltype(&std::fclose)> vram_dump(new_file(argv[5]),&std::fclose);
        const auto final_vram=vram_bytes(core);
        require_device(std::fwrite(final_vram.data(),1,final_vram.size(),vram_dump.get())==final_vram.size() &&
                       std::fflush(vram_dump.get())==0,"Original final little-endian VRAM write failed");
        std::cerr << "GEAR_VRAM_ACTIVE " << item.steps << " primer=" << item.primer_steps << " blocks=" << blocks
                  << " irq=" << entries << " dynamic_wait_ticks=" << waits << " audio_flushes=" << context.audio_flushes
                  << " profile=standard card_ram=0\n";
        return 0;
    } catch(const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
