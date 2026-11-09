#include "pce/bus_trace.hpp"
#include "sector_internal.hpp"
#include <cstdio>
#include <sstream>

namespace pce {
namespace {
thread_local BusTrace* attached=nullptr;
// Encoded HuC6280 sizes, including unread BRK signature and block operands.
constexpr std::array<unsigned,256> sizes{
    2,2,1,2,2,2,2,2,1,2,1,1,3,3,3,3,
    2,2,2,2,2,2,2,2,1,3,1,1,3,3,3,3,
    3,2,1,2,2,2,2,2,1,2,1,1,3,3,3,3,
    2,2,2,1,2,2,2,2,1,3,1,1,3,3,3,3,
    1,2,1,2,2,2,2,2,1,2,1,1,3,3,3,3,
    2,2,2,2,1,2,2,2,1,3,1,1,1,3,3,3,
    1,2,1,1,2,2,2,2,1,2,1,1,3,3,3,3,
    2,2,2,7,2,2,2,2,1,3,1,1,3,3,3,3,
    2,2,1,3,2,2,2,2,1,2,1,1,3,3,3,3,
    2,2,2,4,2,2,2,2,1,3,1,1,3,3,3,3,
    2,2,2,3,2,2,2,2,1,2,1,1,3,3,3,3,
    2,2,2,4,2,2,2,2,1,3,1,1,3,3,3,3,
    2,2,1,7,2,2,2,2,1,2,1,1,3,3,3,3,
    2,2,2,7,1,2,2,2,1,3,1,1,1,3,3,3,
    2,2,1,7,2,2,2,2,1,2,1,1,3,3,3,3,
    2,2,2,7,1,2,2,2,1,3,1,1,1,3,3,3,
};
BusTraceSource source(const Bus& bus,const Cpu& cpu) {
    BusTraceSource out;out.pc=cpu.pc;out.mpr=cpu.mpr;
    const auto op=bus.peek(Bus::physical(cpu,cpu.pc));
    if(!op)return out;
    out.size=sizes[*op];
    std::string identity("pce-bus-source-1\0",17);
    const auto append=[&](std::uint32_t value,unsigned count) {
        for(unsigned i=0;i<count;++i)identity.push_back(static_cast<char>(value>>(8*i)));
    };
    append(out.pc,2);
    for(auto value:out.mpr)append(value,1);
    append(out.size,1);
    for(unsigned i=0;i<out.size;++i) {
        out.physical[i]=Bus::physical(cpu,static_cast<std::uint16_t>(cpu.pc+i));
        const auto value=bus.peek(out.physical[i]);
        if(!value)return out;
        out.bytes[i]=*value;append(out.physical[i],4);append(*value,1);
    }
    out.sha256=detail::text_sha256(identity);out.available=true;return out;
}
std::string wram_hash(const Bus& bus) {
    return detail::text_sha256(std::string_view(
        reinterpret_cast<const char*>(bus.bytes->data()+0x1F0000),8192));
}
}
BusTrace::BusTrace(BusTraceLimits limits):limits_(limits) {
    if(!limits.max_calls || limits.max_calls>10000 || !limits.max_events || limits.max_events>60000 ||
       !limits.max_retired || limits.max_retired>100000 || !limits.wall_ms || limits.wall_ms>3600000)
        throw Fault("invalid finite bus trace limits");
    calls_.reserve(limits.max_calls);events_.reserve(limits.max_events);
    stop_reason_.reserve(64);
}
BusTrace::~BusTrace(){detach();}
void BusTrace::attach(Bus& bus,Cpu& cpu) {
    if(attached || bus_ || !initial_wram_sha256_.empty())throw Fault("bus trace recorder cannot attach twice or overlap on this thread");
    initial_cpu_=cpu;initial_wram_sha256_=wram_hash(bus);
    bus_=&bus;cpu_=&cpu;attached_at_=std::chrono::steady_clock::now();attached=this;
}
void BusTrace::detach() noexcept {
    if(attached==this)attached=nullptr;
    bus_=nullptr;cpu_=nullptr;active_call_.reset();fetch_depth_=0;
}
namespace {
bool hex_digest(const std::string& value,unsigned size) {
    if(value.size()!=size)return false;
    for(char ch:value)if(!((ch>='0'&&ch<='9')||(ch>='a'&&ch<='f')))return false;
    return true;
}
std::string quoted(const std::string& value) {
    if(value.empty() || value.size()>256)throw Fault("invalid bounded bus trace metadata string");
    std::string out="\"";
    constexpr char hex[]="0123456789abcdef";
    for(unsigned char ch:value) {
        if(ch=='\"'||ch=='\\'){out+='\\';out+=char(ch);}
        else if(ch<32 || ch>=127){out+="\\u00";out+=hex[ch>>4];out+=hex[ch&15];}
        else out+=char(ch);
    }
    out+='\"';return out;
}
void mapping(std::ostream& out,const std::array<std::uint8_t,8>& mpr) {
    out<<'[';for(unsigned i=0;i<8;++i){if(i)out<<',';out<<unsigned(mpr[i]);}out<<']';
}
void state(std::ostream& out,const Cpu& cpu,const std::string& wram) {
    if(!hex_digest(wram,64))throw Fault("bus trace state hash unavailable");
    out<<"{\"pc\":"<<cpu.pc<<",\"a\":"<<unsigned(cpu.a)<<",\"x\":"<<unsigned(cpu.x)
       <<",\"y\":"<<unsigned(cpu.y)<<",\"sp\":"<<unsigned(cpu.sp)<<",\"p\":"<<unsigned(cpu.p)<<",\"mpr\":";
    mapping(out,cpu.mpr);
    out<<",\"physical_pc\":"<<Bus::physical(cpu,cpu.pc)<<",\"clock_divisor\":"<<cpu.clock_divisor
       <<",\"ticks\":"<<cpu.ticks<<",\"wram_sha256\":\""<<wram<<"\"}";
}
}
std::string BusTrace::jsonl(const BusTraceMetadata& meta,const std::string& requested_stop,bool requested_complete) const {
    if(active_call_)throw Fault("cannot serialize an open bus trace call");
    if(initial_wram_sha256_.empty())throw Fault("bus trace was never attached");
    if(!hex_digest(meta.engine_revision,40) || !hex_digest(meta.source_sha256,64) ||
       !hex_digest(meta.binary_sha256,64) || !hex_digest(meta.fixture_sha256,64))
        throw Fault("bus trace requires exact producer/fixture SHA identities");
    if(meta.checkpoint_origin && (!hex_digest(meta.checkpoint_origin->sha256,64) ||
       meta.checkpoint_origin->ticks>initial_cpu_.ticks))throw Fault("invalid bus trace checkpoint origin");
    auto stop=stop_reason_.empty()?requested_stop:stop_reason_;
    bool closed_complete=requested_complete && stop_reason_.empty();
    std::uint64_t retired=0;
    for(const auto& call:calls_) {
        if(!call.source.available){closed_complete=false;stop="source-mismatch";}
        retired+=call.native+call.interpreted;
    }
    if(stop=="call-limit" && retired==limits_.max_retired && calls_.size()!=limits_.max_calls)
        stop="retirement-limit";
    if(retired>limits_.max_retired)throw Fault("bus trace retirement limit exceeded");
    if(closed_complete && !((stop=="call-limit" && calls_.size()==limits_.max_calls) ||
       (stop=="retirement-limit" && retired==limits_.max_retired))) {
        closed_complete=false;stop="cancelled";
    }
    if(!closed_complete && stop!="event-limit" && stop!="wall-limit" && stop!="fault" &&
       stop!="source-mismatch" && stop!="cancelled")throw Fault("invalid incomplete bus trace stop");
    std::ostringstream out;
    out<<"{\"type\":\"header\",\"schema\":1,\"format\":\"pce-bus-event-trace-1\",\"engine\":{\"name\":"
       <<quoted(meta.engine_name)<<",\"revision\":"<<quoted(meta.engine_revision)
       <<",\"source_sha256\":"<<quoted(meta.source_sha256)<<",\"binary_sha256\":"<<quoted(meta.binary_sha256)
       <<"},\"fixture_sha256\":"<<quoted(meta.fixture_sha256)<<",\"case\":"<<quoted(meta.case_name)
       <<",\"clock\":\"master-ticks\",\"profile\":\"software-access-callback-v1\",\"phase\":\"callback-return-before-caller-clock\",\"call_model\":\"aggregate\","
       <<"\"capabilities\":{\"mapped\":true,\"fixed_vdc\":true,\"data\":true,\"fetch\":false,\"purpose\":false,\"dummy\":false,\"idle\":false,\"mpr_latch\":false,\"irq\":true,\"tier_counters\":true},"
       <<"\"limits\":{\"calls\":"<<limits_.max_calls<<",\"events\":"<<limits_.max_events<<",\"retired\":"<<limits_.max_retired<<",\"wall_ms\":"<<limits_.wall_ms<<'}';
    if(meta.checkpoint_origin) {
        const auto& origin=*meta.checkpoint_origin;
        out<<",\"checkpoint_origin\":{\"sha256\":"<<quoted(origin.sha256)<<",\"ticks\":"<<origin.ticks
           <<",\"frame\":"<<origin.frame<<",\"native_steps\":"<<origin.native_steps
           <<",\"interpreter_steps\":"<<origin.interpreter_steps<<'}';
    }
    out<<"}\n{\"type\":\"initial\",\"state\":";
    state(out,initial_cpu_,initial_wram_sha256_);out<<"}\n";
    std::size_t event_index=0;
    for(const auto& call:calls_) {
        out<<"{\"type\":\"call-begin\",\"ordinal\":"<<call.ordinal<<",\"entry\":";
        state(out,call.entry_cpu,call.entry_wram_sha256);
        out<<",\"source\":";
        if(call.source.available)out<<"{\"kind\":\"dispatch-entry-candidate\",\"length\":"<<call.source.size
           <<",\"sha256\":"<<quoted(call.source.sha256)<<'}';
        else out<<"null";
        out<<"}\n";
        while(event_index<events_.size() && events_[event_index].call==call.ordinal) {
            const auto& event=events_[event_index++];const bool write=event.direction==BusTraceDirection::write;
            out<<"{\"type\":\"access\",\"ordinal\":"<<event.ordinal<<",\"call_ordinal\":"<<event.call
               <<",\"ticks\":"<<event.ticks<<",\"direction\":\""<<(write?"write":"read")
               <<"\",\"phase\":\""<<(write?"write-return":"read-return")<<"\",\"space\":\""
               <<(event.space==BusTraceSpace::mapped?"mapped":"fixed-vdc")<<"\",\"logical\":";
            if(event.logical)out<<*event.logical;else out<<"null";
            out<<",\"mpr\":";if(event.mpr)mapping(out,*event.mpr);else out<<"null";
            out<<",\"physical\":"<<event.physical<<",\"value\":"<<unsigned(event.value)<<",\"purpose\":null,\"dummy\":null}\n";
        }
        out<<"{\"type\":\"call-end\",\"ordinal\":"<<call.ordinal<<",\"kind\":\"execution-call\",\"state\":";
        state(out,call.end_cpu,call.end_wram_sha256);
        out<<",\"retired\":"<<call.native+call.interpreted<<",\"native\":"<<call.native
           <<",\"interpreted\":"<<call.interpreted<<",\"irq\":"<<call.irq_entries<<"}\n";
    }
    out<<"{\"type\":\"final\",\"calls\":"<<calls_.size()<<",\"retired\":"<<retired<<",\"events\":"<<events_.size()
       <<",\"stop\":"<<quoted(stop)<<",\"complete\":"<<(closed_complete?"true":"false")<<",\"state\":";
    if(calls_.empty())state(out,initial_cpu_,initial_wram_sha256_);
    else state(out,calls_.back().end_cpu,calls_.back().end_wram_sha256);
    out<<"}\n";
    auto encoded=out.str();
    if(encoded.size()>128u*1024u*1024u || 3+2*calls_.size()+events_.size()>100000)
        throw Fault("bus trace protocol admission bound exceeded");
    return encoded;
}
void BusTrace::write(const std::filesystem::path& path,const BusTraceMetadata& meta,
                     const std::string& stop,bool complete) const {
    const auto data=jsonl(meta,stop,complete);
#ifdef _WIN32
    auto* output=_wfopen(path.c_str(),L"wbx");
#else
    auto* output=std::fopen(path.c_str(),"wbx");
#endif
    if(!output)throw Fault("cannot exclusively create bus trace; choose a new file");
    const bool written=std::fwrite(data.data(),1,data.size(),output)==data.size();
    const bool flushed=std::fflush(output)==0, closed=std::fclose(output)==0;
    if(!written || !flushed || !closed)throw Fault("bus trace write failed; partial new file retained");
}
void observe_bus_access(Bus& bus,const Cpu& cpu,BusTraceDirection direction,BusTraceSpace space,
                        std::optional<std::uint16_t> logical,std::uint32_t physical,std::uint8_t value) {
    auto* trace=attached;
    if(!trace || trace->bus_!=&bus || trace->cpu_!=&cpu || !trace->active_call_ || trace->fetch_depth_)return;
    if(trace->events_.size()==trace->limits_.max_events) {
        if(trace->stop_reason_.empty())trace->stop_reason_="event-limit";
        return;
    }
    BusTraceEvent event;
    event.ordinal=trace->events_.size()+1;event.call=trace->calls_[*trace->active_call_].ordinal;
    event.ticks=cpu.ticks;event.cycles=cpu.cycles;event.direction=direction;event.space=space;
    event.logical=logical;event.physical=physical;event.value=value;
    if(space==BusTraceSpace::mapped)event.mpr=cpu.mpr;
    trace->events_.push_back(std::move(event));
}
namespace detail {
BusTraceScope::BusTraceScope(Bus& bus,Cpu& cpu) {
    auto* trace=attached;
    if(!trace || trace->bus_!=&bus || trace->cpu_!=&cpu)return;
    if(std::chrono::steady_clock::now()-trace->attached_at_>=std::chrono::milliseconds(trace->limits_.wall_ms)) {
        if(trace->stop_reason_.empty())trace->stop_reason_="wall-limit";
        trace->detach();return;
    }
    if(trace->active_call_)throw Fault("nested bus trace execution call");
    if(trace->calls_.size()==trace->limits_.max_calls) {
        if(trace->stop_reason_.empty())trace->stop_reason_="cancelled";
        return;
    }
    BusTraceCall call;
    call.ordinal=trace->calls_.size()+1;call.ticks=cpu.ticks;call.cycles=cpu.cycles;
    call.divisor=cpu.clock_divisor;call.source=source(bus,cpu);
    call.entry_cpu=cpu;call.entry_wram_sha256=wram_hash(bus);
    if(!call.source.available && trace->stop_reason_.empty())trace->stop_reason_="source-mismatch";
    trace->calls_.push_back(std::move(call));trace->active_call_=trace->calls_.size()-1;
    trace_=trace;cpu_=&cpu;native_=cpu.native_steps;interpreted_=cpu.interpreter_steps;
    irqs_=cpu.irq_entries;block_bytes_=cpu.block_bytes;
}
void BusTraceScope::finish(Exit result) noexcept {
    if(!trace_)return;
    auto& call=trace_->calls_[*trace_->active_call_];
    call.result=result;call.end_ticks=cpu_->ticks;call.end_cycles=cpu_->cycles;
    call.end_divisor=cpu_->clock_divisor;
    call.end_cpu=*cpu_;
    // The capture is host diagnostics, outside serialized guest state.
    // Hash construction is bounded and does not call guest memory callbacks.
    try {call.end_wram_sha256=wram_hash(*trace_->bus_);}
    catch(...) {if(trace_->stop_reason_.empty())trace_->stop_reason_="fault";}
    call.native=cpu_->native_steps-native_;call.interpreted=cpu_->interpreter_steps-interpreted_;
    call.irq_entries=cpu_->irq_entries-irqs_;call.block_bytes=cpu_->block_bytes-block_bytes_;
    trace_->retired_+=call.native+call.interpreted;
    if(std::chrono::steady_clock::now()-trace_->attached_at_>=std::chrono::milliseconds(trace_->limits_.wall_ms) && trace_->stop_reason_.empty())
        trace_->stop_reason_="wall-limit";
    finished_=true;
}
BusTraceScope::~BusTraceScope() {
    if(!trace_)return;
    if(!finished_) {
        finish(Exit::unsupported);
        trace_->calls_[*trace_->active_call_].faulted=true;
        if(trace_->stop_reason_.empty())trace_->stop_reason_="fault";
    }
    trace_->active_call_.reset();
    if(trace_->calls_.size()==trace_->limits_.max_calls || trace_->retired_>=trace_->limits_.max_retired ||
       !trace_->stop_reason_.empty())trace_->detach();
}
BusTraceFetch::BusTraceFetch(Bus& bus,Cpu& cpu) noexcept {
    if(attached && attached->bus_==&bus && attached->cpu_==&cpu) {
        trace_=attached;++trace_->fetch_depth_;
    }
}
BusTraceFetch::~BusTraceFetch(){if(trace_)--trace_->fetch_depth_;}
}
}
