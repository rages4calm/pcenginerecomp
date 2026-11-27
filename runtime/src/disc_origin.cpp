#include "pce/disc_origin.hpp"
#include <sstream>

namespace pce {
namespace {
thread_local DiscOrigin* attached=nullptr;
int load_register(unsigned op) {
    switch(op) {
    case 0xA5:case 0xB5:case 0xAD:case 0xBD:case 0xB9:case 0xA1:case 0xB1:case 0xB2:case 0x68:return 0;
    case 0xA6:case 0xB6:case 0xAE:case 0xBE:case 0xFA:return 1;
    case 0xA4:case 0xB4:case 0xAC:case 0xBC:case 0x7A:return 2;
    default:return -1;
    }
}
int store_register(unsigned op) {
    switch(op) {
    case 0x85:case 0x95:case 0x8D:case 0x9D:case 0x99:case 0x81:case 0x91:case 0x92:case 0x48:return 0;
    case 0x86:case 0x96:case 0x8E:case 0xDA:return 1;
    case 0x84:case 0x94:case 0x8C:case 0x5A:return 2;
    default:return -1;
    }
}
bool block(unsigned op) {return op==0x73 || op==0xC3 || op==0xD3 || op==0xE3 || op==0xF3;}
}
DiscOrigin::~DiscOrigin(){detach();}
void DiscOrigin::attach(Bus& bus,Cpu& cpu) {
    if(attached && attached!=this)throw Fault("another disc origin observer is attached");
    bus_=&bus;cpu_=&cpu;attached=this;reset();
}
void DiscOrigin::detach() noexcept {if(attached==this)attached=nullptr;bus_=nullptr;cpu_=nullptr;}
bool DiscOrigin::matches(const Bus& bus,const Cpu& cpu) const {return bus_==&bus && cpu_==&cpu;}
DiscOrigin* disc_origin(Bus& bus,Cpu& cpu) noexcept {
    return attached && attached->matches(bus,cpu) ? attached:nullptr;
}
void DiscOrigin::reset() {
    ram_.clear();registers_={};saved_={};last_read_.reset();active_=false;fetch_depth=0;
    reads_=writes_=0;++epoch_;
    last_native_=cpu_ ? cpu_->native_steps:0;
    last_interpreted_=cpu_ ? cpu_->interpreter_steps:0;
}
std::optional<DiscOrigin::Tag> DiscOrigin::tag(std::uint32_t address) const {
    if(!bus_ || address>=0x200000 || bus_->kind[address>>13]!=BankKind::ram)return {};
    const auto found=ram_.find(bus_->backing_address(address));
    if(found==ram_.end() || bus_->peek(address)!=found->second.value)return {};
    return found->second;
}
void DiscOrigin::invalidate(std::uint32_t address,std::size_t length) {
    if(!bus_ || address>0x200000 || length>0x200000-address)throw Fault("invalid disc origin invalidate range");
    for(std::size_t i=0;i<length;++i)ram_.erase(bus_->backing_address(address+static_cast<std::uint32_t>(i)));
    registers_={};
}
void invalidate_disc_origin(Bus& bus,std::uint32_t address,std::size_t length) {
    if(attached && attached->matches(bus,*attached->cpu_))attached->invalidate(address,length);
}
void DiscOrigin::begin() {
    if(active_)throw Fault("nested disc origin execution");
    if(cpu_->native_steps!=last_native_ || cpu_->interpreter_steps!=last_interpreted_)
        registers_={}; // Direct execution between observed calls has unknown effects.
    active_=true;last_read_.reset();saved_=registers_;
    entry_pc_=cpu_->pc;entry_irqs_=cpu_->irq_entries;
    const auto op=bus_->peek(Bus::physical(*cpu_,cpu_->pc));
    opcode_=op ? *op:256;
    const std::array<std::uint8_t,3> values{cpu_->a,cpu_->x,cpu_->y};
    for(unsigned i=0;i<3;++i)if(saved_[i] && saved_[i]->value!=values[i])saved_[i].reset();
}
void DiscOrigin::read(std::uint32_t physical,std::uint8_t value,std::optional<std::uint64_t> disc) {
    if(!active_ || fetch_depth)return;
    ++reads_;last_read_=disc ? std::optional<Tag>(Tag{*disc,value}):tag(physical);
}
void DiscOrigin::write(std::uint32_t physical,std::uint8_t value) {
    if(!bus_ || physical>=0x200000 || bus_->kind[physical>>13]!=BankKind::ram)return;
    const auto address=bus_->backing_address(physical);
    ram_.erase(address);
    if(!active_)return;
    ++writes_;
    if(cpu_->pc!=entry_pc_ || cpu_->irq_entries!=entry_irqs_)return;
    std::optional<Tag> source;
    if(block(opcode_))source=last_read_;
    else if(const auto reg=store_register(opcode_);reg>=0)source=saved_[reg];
    if(source && source->value==value && bus_->peek(physical)==value)ram_[address]=*source;
}
void DiscOrigin::finish(Exit result) {
    if(!active_)return;
    active_=false;
    last_native_=cpu_->native_steps;last_interpreted_=cpu_->interpreter_steps;
    if(result!=Exit::executed || cpu_->irq_entries!=entry_irqs_){registers_={};return;}
    registers_={};
    if(load_register(opcode_)>=0) {
        registers_=saved_;registers_[load_register(opcode_)]=last_read_;
    } else if(store_register(opcode_)>=0)registers_=saved_;
    else {
        switch(opcode_) {
        case 0xAA:registers_=saved_;registers_[1]=saved_[0];break;
        case 0x8A:registers_=saved_;registers_[0]=saved_[1];break;
        case 0xA8:registers_=saved_;registers_[2]=saved_[0];break;
        case 0x98:registers_=saved_;registers_[0]=saved_[2];break;
        case 0x22:registers_=saved_;std::swap(registers_[0],registers_[1]);break;
        case 0x42:registers_=saved_;std::swap(registers_[0],registers_[2]);break;
        case 0x02:registers_=saved_;std::swap(registers_[1],registers_[2]);break;
        default:break; // Unmodelled metadata destroys register provenance.
        }
    }
    const std::array<std::uint8_t,3> values{cpu_->a,cpu_->x,cpu_->y};
    for(unsigned i=0;i<3;++i)if(registers_[i] && registers_[i]->value!=values[i])registers_[i].reset();
}
std::string DiscOrigin::json(std::uint32_t address,unsigned length) const {
    if(!bus_ || !length || length>256 || address>=0x200000 || length>0x200000-address)
        throw Fault("disc origin query requires 1..256 physical bytes");
    std::ostringstream out;
    out<<"{\"schema\":1,\"epoch\":"<<epoch_<<",\"address\":"<<address<<",\"length\":"<<length
       <<",\"reads\":"<<reads_<<",\"writes\":"<<writes_<<",\"offsets\":[";
    for(unsigned i=0;i<length;++i) {
        if(i)out<<',';
        const auto origin=tag(address+i);
        if(origin)out<<origin->offset;else out<<"null";
    }
    out<<"]}";
    return out.str();
}
namespace detail {
DiscOriginScope::DiscOriginScope(Bus& bus,Cpu& cpu):observer(disc_origin(bus,cpu)){if(observer)observer->begin();}
DiscOriginScope::~DiscOriginScope(){if(observer)observer->finish(Exit::unsupported);}
void DiscOriginScope::finish(Exit result){if(observer){observer->finish(result);observer=nullptr;}}
DiscOriginFetch::DiscOriginFetch(Bus& bus,Cpu& cpu):observer(disc_origin(bus,cpu)){if(observer)++observer->fetch_depth;}
DiscOriginFetch::~DiscOriginFetch(){if(observer)--observer->fetch_depth;}
}
}
