#include "pce/title_adapter.hpp"
#include "pce/checkpoint_file.hpp"
#include <algorithm>
#include <charconv>
#include <cstring>
#include <limits>
#include <sstream>

namespace pce {
namespace {
constexpr std::size_t no_event=static_cast<std::size_t>(-1);
constexpr std::array<std::uint8_t,256> lengths{2,2,1,2,2,2,2,2,1,2,1,1,3,3,3,3,2,2,2,2,2,2,2,2,1,3,1,1,3,3,3,3,3,2,1,2,2,2,2,2,1,2,1,1,3,3,3,3,2,2,2,1,2,2,2,2,1,3,1,1,3,3,3,3,1,2,1,2,2,2,2,2,1,2,1,1,3,3,3,3,2,2,2,2,1,2,2,2,1,3,1,1,1,3,3,3,1,2,1,1,2,2,2,2,1,2,1,1,3,3,3,3,2,2,2,7,2,2,2,2,1,3,1,1,3,3,3,3,2,2,1,3,2,2,2,2,1,2,1,1,3,3,3,3,2,2,2,4,2,2,2,2,1,3,1,1,3,3,3,3,2,2,2,3,2,2,2,2,1,2,1,1,3,3,3,3,2,2,2,4,2,2,2,2,1,3,1,1,3,3,3,3,2,2,1,7,2,2,2,2,1,2,1,1,3,3,3,3,2,2,2,7,1,2,2,2,1,3,1,1,1,3,3,3,2,2,1,7,2,2,2,2,1,2,1,1,3,3,3,3,2,2,2,7,1,2,2,2,1,3,1,1,1,3,3,3};
bool legal_opcode(std::uint8_t opcode) {
    switch(opcode){case 0x0B:case 0x1B:case 0x2B:case 0x33:case 0x3B:case 0x4B:case 0x5B:case 0x5C:
        case 0x63:case 0x6B:case 0x7B:case 0x8B:case 0x9B:case 0xAB:case 0xBB:case 0xCB:case 0xDB:
        case 0xDC:case 0xE2:case 0xEB:case 0xFB:case 0xFC:return false;default:return true;}
}
bool identifier(std::string_view text) {
    return !text.empty()&&text.size()<=64&&text.front()>='a'&&text.front()<='z'&&
        std::all_of(text.begin(),text.end(),[](char c){return(c>='a'&&c<='z')||(c>='0'&&c<='9')||c=='_'||c=='-';});
}
TitleRegisters registers(const Cpu& c) {return {c.a,c.x,c.y,c.p,c.sp,c.pc,c.mpr,c.ticks,c.cycles};}
std::uint64_t retired(const Cpu& c) {
    if(c.interpreter_steps>UINT64_MAX-c.native_steps)throw Fault("title adapter retirement total overflow");
    return c.native_steps+c.interpreter_steps;
}
std::uint32_t ram_address(const Bus& b,std::uint32_t address) {
    if(address>=b.bytes->size()||address>=0x1FE000||b.kind[address>>13]!=BankKind::ram||
       (address>=0x1EE000&&address<0x1F0000)||
       (b.arcade_card&&address>=0x80000&&address<0x88000))
        throw Fault("title adapter requires ordinary volatile RAM");
    const auto canonical=b.backing_address(address);
    if(canonical>=b.bytes->size()||canonical>=0x1FE000||b.kind[canonical>>13]!=BankKind::ram||
       (canonical>=0x1EE000&&canonical<0x1F0000))
        throw Fault("title adapter RAM backing is invalid");
    return canonical;
}
void room(std::uint64_t value,std::uint64_t extra) {
    if(extra>UINT64_MAX-value)throw Fault("title adapter statistics overflow");
}
std::string digest(std::string_view text) {
    return checkpoint_hash(std::span(reinterpret_cast<const std::uint8_t*>(text.data()),text.size()));
}
void append_u64(std::vector<std::uint8_t>& out,std::uint64_t value,unsigned count=8) {
    for(unsigned i=0;i<count;++i)out.push_back(static_cast<std::uint8_t>(value>>(8*i)));
}
std::uint64_t read_u64(std::span<const std::uint8_t> data,std::size_t offset,unsigned count=8) noexcept {
    std::uint64_t value=0;for(unsigned i=0;i<count;++i)value|=std::uint64_t(data[offset+i])<<(8*i);return value;
}
}

struct TitleAdapterContext::Impl {
    struct RamEdit {std::uint32_t address,canonical;std::uint8_t expected,replacement;};
    struct RegisterEdit {char name;std::uint8_t expected,replacement;};
    const TitleAdapterSpec& spec;
    const std::vector<std::int64_t>& settings;
    const TitleEventSpec& event;
    const TitleSource& source;
    const TitleRegisters& before;
    TitleRegisters after;
    const Bus& bus;
    std::uint64_t frame;
    std::vector<std::uint8_t> state;
    std::vector<RamEdit> ram;
    std::vector<RegisterEdit> regs;
    void register_edit(char name,std::uint8_t expected,std::uint8_t replacement) {
        if(std::any_of(regs.begin(),regs.end(),[&](const auto& r){return r.name==name;}))
            throw Fault("title adapter duplicate register edit");
        regs.push_back({name,expected,replacement});
    }
};

const TitleEventSpec& TitleAdapterContext::event() const noexcept{return impl_->event;}
const TitleSource& TitleAdapterContext::source() const noexcept{return impl_->source;}
const TitleRegisters& TitleAdapterContext::before() const noexcept{return impl_->before;}
const TitleRegisters& TitleAdapterContext::after() const noexcept{return impl_->after;}
std::uint64_t TitleAdapterContext::ticks() const noexcept{return impl_->after.ticks;}
std::uint64_t TitleAdapterContext::frame() const noexcept{return impl_->frame;}
std::int64_t TitleAdapterContext::setting(std::string_view name) const {
    const auto& fields=impl_->spec.settings;
    const auto it=std::lower_bound(fields.begin(),fields.end(),name,[](const auto& a,auto b){return a.name<b;});
    if(it==fields.end()||it->name!=name)throw Fault("unknown title adapter setting");
    return impl_->settings[static_cast<std::size_t>(it-fields.begin())];
}
std::span<std::uint8_t> TitleAdapterContext::state() noexcept{return impl_->state;}
std::uint8_t TitleAdapterContext::read_ram(std::uint32_t address) const{return (*impl_->bus.bytes)[ram_address(impl_->bus,address)];}
std::uint16_t TitleAdapterContext::read_ram_u16(std::uint32_t address) const {
    if(address>=0x1FFFFF)throw Fault("title adapter RAM extent overflow");
    return static_cast<std::uint16_t>(read_ram(address)|(std::uint16_t(read_ram(address+1))<<8));
}
void TitleAdapterContext::write_ram(std::uint32_t address,std::span<const std::uint8_t> expected,std::span<const std::uint8_t> replacement) {
    auto& p=*impl_;
    if(expected.empty()||expected.size()!=replacement.size()||expected.size()>4096||
       address>=0x200000||expected.size()>0x200000-address||p.ram.size()>4096-expected.size())
        throw Fault("title adapter RAM edit exceeds bounded transaction");
    std::vector<Impl::RamEdit> queued;queued.reserve(expected.size());
    for(std::size_t i=0;i<expected.size();++i) {
        const auto physical=address+static_cast<std::uint32_t>(i),canonical=ram_address(p.bus,physical);
        if(std::any_of(p.ram.begin(),p.ram.end(),[&](const auto& e){return e.canonical==canonical;})||
           std::any_of(queued.begin(),queued.end(),[&](const auto& e){return e.canonical==canonical;}))
            throw Fault("title adapter RAM edits overlap");
        for(const auto& event:p.spec.events)for(std::size_t j=0;j<event.data.size();++j) {
            Cpu c;c.mpr=event.mpr;
            const auto code=Bus::physical(c,static_cast<std::uint16_t>(event.pc+j));
            if(canonical==p.bus.backing_address(code))throw Fault("title adapter cannot edit a declared source site");
        }
        queued.push_back({physical,canonical,expected[i],replacement[i]});
    }
    p.ram.insert(p.ram.end(),queued.begin(),queued.end());
}
void TitleAdapterContext::write_ram_u8(std::uint32_t address,std::uint8_t expected,std::uint8_t replacement) {write_ram(address,{&expected,1},{&replacement,1});}
void TitleAdapterContext::write_ram_u16(std::uint32_t address,std::uint16_t expected,std::uint16_t replacement) {
    const std::array<std::uint8_t,2> a{static_cast<std::uint8_t>(expected),static_cast<std::uint8_t>(expected>>8)};
    const std::array<std::uint8_t,2> b{static_cast<std::uint8_t>(replacement),static_cast<std::uint8_t>(replacement>>8)};
    write_ram(address,a,b);
}
void TitleAdapterContext::set_a(std::uint8_t a,std::uint8_t b){impl_->register_edit('a',a,b);}
void TitleAdapterContext::set_x(std::uint8_t a,std::uint8_t b){impl_->register_edit('x',a,b);}
void TitleAdapterContext::set_y(std::uint8_t a,std::uint8_t b){impl_->register_edit('y',a,b);}
void TitleAdapterContext::set_p(std::uint8_t a,std::uint8_t b){impl_->register_edit('p',a,b);}

TitleAdapterRuntime::TitleAdapterRuntime(const TitleAdapterSpec* spec,std::string_view mode,std::string_view settings) {
    if(mode!="pristine"&&mode!="enhanced")throw Fault("title adapter mode requires pristine or enhanced");
    if(!spec) {
        if(mode!="pristine"||!settings.empty())throw Fault("consumer has no title adapter");
        return;
    }
    spec_=*spec;compiled_=true;enabled_=mode=="enhanced";
    if(!identifier(spec_.id)||!checkpoint_hex_identity(spec_.manifest_sha256)||spec_.state_bytes>maximum_state_bytes||
       !spec_.after||spec_.settings.size()>32||spec_.events.empty()||spec_.events.size()>256)
        throw Fault("invalid title adapter specification");
    std::sort(spec_.settings.begin(),spec_.settings.end(),[](const auto& a,const auto& b){return a.name<b.name;});
    for(std::size_t i=0;i<spec_.settings.size();++i) {
        const auto& s=spec_.settings[i];
        if(!identifier(s.name)||s.min>s.max||s.default_value<s.min||s.default_value>s.max||
           (i&&spec_.settings[i-1].name==s.name))throw Fault("invalid title adapter setting specification");
        settings_.push_back(s.default_value);
    }
    if(settings.size()>4096)throw Fault("title adapter settings exceed limit");
    std::vector<bool> seen(spec_.settings.size());
    for(std::size_t offset=0;offset<settings.size();) {
        const auto end=settings.find(',',offset);const auto token=settings.substr(offset,end==std::string_view::npos?settings.size()-offset:end-offset);
        const auto equals=token.find('=');
        if(equals==std::string_view::npos||!equals||equals+1==token.size())throw Fault("invalid title adapter setting assignment");
        const auto name=token.substr(0,equals),text=token.substr(equals+1);
        const auto it=std::lower_bound(spec_.settings.begin(),spec_.settings.end(),name,[](const auto& a,auto b){return a.name<b;});
        if(it==spec_.settings.end()||it->name!=name)throw Fault("unknown title adapter setting");
        const auto index=static_cast<std::size_t>(it-spec_.settings.begin());
        if(seen[index])throw Fault("duplicate title adapter setting");
        std::int64_t value=0;const auto result=std::from_chars(text.data(),text.data()+text.size(),value);
        if(result.ec!=std::errc{}||result.ptr!=text.data()+text.size()||std::to_string(value)!=text||value<it->min||value>it->max)
            throw Fault("invalid or out-of-range title adapter setting");
        seen[index]=true;settings_[index]=value;
        if(end==std::string_view::npos)break;
        offset=end+1;if(offset==settings.size())throw Fault("empty title adapter setting assignment");
    }
    for(std::size_t i=0;i<spec_.settings.size();++i) {
        if(!enabled_&&settings_[i]!=spec_.settings[i].default_value)throw Fault("pristine title mode requires default settings");
        if(i)canonical_+=',';
        canonical_+=spec_.settings[i].name+'='+std::to_string(settings_[i]);
    }
    for(std::size_t i=0;i<spec_.events.size();++i) {
        const auto& e=spec_.events[i];
        if(!identifier(e.name)||e.selector>15||e.data.empty()||e.data.size()>7||
           !legal_opcode(e.data[0])||lengths[e.data[0]]!=e.data.size())
            throw Fault("invalid title adapter event specification");
        for(std::size_t j=0;j<i;++j) {
            const auto& b=spec_.events[j];
            if(e.name==b.name||(e.pc==b.pc&&e.mpr==b.mpr&&e.selector==b.selector&&e.data==b.data))
                throw Fault("duplicate title adapter event");
        }
        event_order_.push_back(i);
    }
    std::stable_sort(event_order_.begin(),event_order_.end(),[&](auto a,auto b){return spec_.events[a].pc<spec_.events[b].pc;});
    std::string contract="pce-title-adapter-binding-1";
    for(const auto& part:{spec_.id,spec_.manifest_sha256,std::string(mode),canonical_}){contract+='\0';contract+=part;}
    binding_=digest(contract);
    if(enabled_)state_.resize(spec_.state_bytes);
}
bool TitleAdapterRuntime::compiled() const noexcept{return compiled_;}
bool TitleAdapterRuntime::enabled() const noexcept{return enabled_;}
const std::string& TitleAdapterRuntime::canonical_settings() const noexcept{return canonical_;}
const std::string& TitleAdapterRuntime::binding_digest() const noexcept{return binding_;}
const TitleAdapterStats& TitleAdapterRuntime::stats() const noexcept{return stats_;}
std::span<const std::uint8_t> TitleAdapterRuntime::state() const noexcept{return state_;}
const std::string& TitleAdapterRuntime::last_audit_json() const noexcept{return last_audit_;}
TitleAdapterRuntime::Pending TitleAdapterRuntime::before(const Bus& bus,const Cpu& cpu) const {
    Pending result;if(!enabled_)return result;
    retired(cpu);result.native_before=cpu.native_steps;result.interpreted_before=cpu.interpreter_steps;
    const auto first=std::lower_bound(event_order_.begin(),event_order_.end(),cpu.pc,[&](auto i,auto pc){return spec_.events[i].pc<pc;});
    for(auto it=first;it!=event_order_.end()&&spec_.events[*it].pc==cpu.pc;++it) {
        const auto& e=spec_.events[*it];
        if(e.mpr!=cpu.mpr||e.selector!=bus.hucard_mapper_latch)continue;
        TitleSource source;source.pc=cpu.pc;source.mpr=cpu.mpr;source.selector=bus.hucard_mapper_latch;source.length=static_cast<std::uint8_t>(e.data.size());
        bool good=true;
        for(std::size_t i=0;i<e.data.size();++i) {
            source.physical[i]=Bus::physical(cpu,static_cast<std::uint16_t>(cpu.pc+i));
            const auto value=bus.peek(source.physical[i]);
            if(!value||*value!=e.data[i]){good=false;break;}
            source.data[i]=*value;
        }
        if(good){result.event_index=*it;result.source=source;result.registers=registers(cpu);break;}
    }
    return result;
}
void TitleAdapterRuntime::after(const Pending& pending,Bus& bus,Cpu& cpu) {
    if(!enabled_)return;
    if(cpu.native_steps<pending.native_before||cpu.interpreter_steps<pending.interpreted_before)
        throw Fault("title adapter retirement counters regressed");
    const auto n=cpu.native_steps-pending.native_before,i=cpu.interpreter_steps-pending.interpreted_before;
    if(!n&&!i)return;
    if(n>1||i>1||n+i!=1)throw Fault("title adapter requires one retired instruction");
    if(pending.event_index==no_event)return;
    if(pending.event_index>=spec_.events.size())throw Fault("invalid title adapter pending event");
    if(cpu.ticks<pending.registers.ticks||cpu.cycles<pending.registers.cycles)
        throw Fault("title adapter guest clock regressed");
    const auto total=retired(cpu);
    if(total<=last_matched_total_)throw Fault("title adapter retirement already consumed");
    TitleAdapterContext::Impl edit{spec_,settings_,spec_.events[pending.event_index],pending.source,pending.registers,
        registers(cpu),bus,bus.vdc.video.sequence(),state_,{}, {}};
    TitleAdapterContext context(edit);spec_.after(context);
    std::uint64_t ram_changes=0,register_changes=0;std::array<std::uint64_t,256> generations{};
    for(const auto& e:edit.ram) {
        if(ram_address(bus,e.address)!=e.canonical||(*bus.bytes)[e.canonical]!=e.expected)
            throw Fault("title adapter RAM expected-byte mismatch");
        if(e.expected==e.replacement)continue;
        ++ram_changes;const auto bank=e.address>>13;
        if(bus.work_ram_mirrors&&(e.canonical>>13)==0xF8)for(unsigned alias=0xF8;alias<=0xFB;++alias)++generations[alias];
        else if(bus.hucard_profile==HuCardProfile::populous&&bank>=0x40&&bank<=0x5F)
            for(unsigned alias=0x40+(bank&3);alias<=0x5F;alias+=4)++generations[alias];
        else ++generations[bank];
    }
    const auto reg=[&](char name)->std::uint8_t&{if(name=='a')return cpu.a;if(name=='x')return cpu.x;if(name=='y')return cpu.y;return cpu.p;};
    for(const auto& e:edit.regs){if(reg(e.name)!=e.expected)throw Fault("title adapter register expected-value mismatch");register_changes+=e.expected!=e.replacement;}
    const bool changed=ram_changes||register_changes||edit.state!=state_;
    room(stats_.matched_events,1);room(stats_.transactions,changed);room(stats_.ram_bytes_changed,ram_changes);room(stats_.register_writes,register_changes);
    for(unsigned bank=0;bank<256;++bank)room(bus.generation[bank],generations[bank]);
    // Build the optional diagnostic before the nonthrowing commit.
    std::ostringstream audit;audit<<"{\"schema\":1,\"execution\":\"enhanced\",\"adapter\":\""<<spec_.id
        <<"\",\"binding_sha256\":\""<<binding_<<"\",\"event\":\""<<edit.event.name<<"\",\"pc\":"<<pending.source.pc<<",\"mpr\":[";
    for(unsigned j=0;j<8;++j)audit<<(j?",":"")<<unsigned(pending.source.mpr[j]);
    audit<<"],\"selector\":"<<unsigned(pending.source.selector)<<",\"physical\":[";
    for(unsigned j=0;j<pending.source.length;++j)audit<<(j?",":"")<<pending.source.physical[j];
    audit<<"],\"source_sha256\":\""<<checkpoint_hash(std::span(pending.source.data).first(pending.source.length))
        <<"\",\"ticks\":"<<cpu.ticks<<",\"frame\":"<<edit.frame<<",\"ram\":[";
    for(std::size_t j=0;j<edit.ram.size();++j){const auto& e=edit.ram[j];audit<<(j?",":"")<<"{\"physical\":"<<e.address<<",\"before\":"<<unsigned(e.expected)<<",\"after\":"<<unsigned(e.replacement)<<'}';}
    audit<<"],\"registers\":[";
    for(std::size_t j=0;j<edit.regs.size();++j){const auto& e=edit.regs[j];audit<<(j?",":"")<<"{\"name\":\""<<e.name<<"\",\"before\":"<<unsigned(e.expected)<<",\"after\":"<<unsigned(e.replacement)<<'}';}
    audit<<"],\"state_before_sha256\":\""<<checkpoint_hash(state_)<<"\",\"state_after_sha256\":\""<<checkpoint_hash(edit.state)<<"\",\"changed\":"<<(changed?"true":"false")<<'}';
    auto text=audit.str();
    for(const auto& e:edit.ram)(*bus.bytes)[e.canonical]=e.replacement;
    for(const auto& e:edit.regs)reg(e.name)=e.replacement;
    for(unsigned bank=0;bank<256;++bank)bus.generation[bank]+=generations[bank];
    std::copy(edit.state.begin(),edit.state.end(),state_.begin());
    ++stats_.matched_events;stats_.transactions+=changed;stats_.ram_bytes_changed+=ram_changes;stats_.register_writes+=register_changes;
    last_matched_total_=total;last_audit_.swap(text);
}
std::vector<std::uint8_t> TitleAdapterRuntime::checkpoint_state() const {
    if(!enabled_)return {};
    std::vector<std::uint8_t> out;out.reserve(56+state_.size());
    for(auto byte:std::string_view("PCETITLE"))out.push_back(static_cast<std::uint8_t>(byte));
    append_u64(out,1,4);append_u64(out,state_.size(),4);
    for(auto value:{stats_.matched_events,stats_.transactions,stats_.ram_bytes_changed,stats_.register_writes,last_matched_total_})append_u64(out,value);
    out.insert(out.end(),state_.begin(),state_.end());return out;
}
void TitleAdapterRuntime::validate_restore(std::span<const std::uint8_t> data) const {
    if(!enabled_){if(!data.empty())throw Fault("pristine title mode refuses adapter state");return;}
    if(data.size()!=56+state_.size()||std::memcmp(data.data(),"PCETITLE",8)||read_u64(data,8,4)!=1||read_u64(data,12,4)!=state_.size())
        throw Fault("unsupported title adapter checkpoint state");
    const auto events=read_u64(data,16),transactions=read_u64(data,24),bytes=read_u64(data,32),regs=read_u64(data,40),last=read_u64(data,48);
    if(transactions>events||last<events||(!transactions&&(bytes||regs))||
       (transactions<=UINT64_MAX/4096&&bytes>transactions*4096)||(transactions<=UINT64_MAX/4&&regs>transactions*4))
        throw Fault("inconsistent title adapter checkpoint counters");
}
void TitleAdapterRuntime::validate_restore(std::span<const std::uint8_t> data,std::uint64_t native_steps,std::uint64_t interpreter_steps) const {
    validate_restore(data);
    if(!enabled_)return;
    if(interpreter_steps>UINT64_MAX-native_steps || read_u64(data,48)>native_steps+interpreter_steps)
        throw Fault("title adapter checkpoint counters exceed guest retirements");
}
void TitleAdapterRuntime::commit_restore(std::span<const std::uint8_t> data) noexcept {
    if(!enabled_)return;
    stats_={read_u64(data,16),read_u64(data,24),read_u64(data,32),read_u64(data,40)};last_matched_total_=read_u64(data,48);
    std::copy(data.begin()+56,data.end(),state_.begin());last_audit_.clear();
}
std::string TitleAdapterRuntime::status_json() const {
    std::ostringstream out;out<<"{\"schema\":1,\"compiled\":"<<(compiled_?"true":"false")<<",\"mode\":\""<<(enabled_?"enhanced":"pristine")<<'"';
    if(compiled_)out<<",\"id\":\""<<spec_.id<<"\",\"manifest_sha256\":\""<<spec_.manifest_sha256<<"\",\"binding_sha256\":\""<<binding_
        <<"\",\"settings\":\""<<canonical_<<"\",\"state_bytes\":"<<state_.size()<<",\"state_sha256\":\""<<checkpoint_hash(state_)<<'"';
    out<<",\"matched_events\":"<<stats_.matched_events<<",\"transactions\":"<<stats_.transactions<<",\"ram_bytes_changed\":"<<stats_.ram_bytes_changed
        <<",\"register_writes\":"<<stats_.register_writes<<'}';return out.str();
}
} // namespace pce
