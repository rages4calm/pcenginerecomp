#pragma once
// Opt-in host observation only. Capture bytes are private generated-code inputs.
#include "pce/runtime.hpp"
#include <algorithm>
#include <cstdio>
#include <filesystem>
#include <limits>
#include <sstream>
#include <unordered_map>
#include <vector>

namespace pce {
class CodeCapture {
    struct Identity {
        std::uint16_t pc=0;
        std::array<std::uint8_t,8> mpr{};
        std::array<std::uint8_t,7> data{};
        std::uint8_t length=0;
        bool operator==(const Identity&) const = default;
    };
    struct Hash {
        std::size_t operator()(const Identity& key) const noexcept {
            std::size_t result=key.pc;
            for(auto value:key.mpr) result=(result^value)*16777619U;
            for(unsigned i=0;i<key.length;++i) result=(result^key.data[i])*16777619U;
            return result^key.length;
        }
    };
    struct Entry { Identity identity; std::uint64_t native_hits=0, interpreted_hits=0; };
public:
    struct Pending {
        Identity identity;
        std::uint64_t native_before=0, interpreted_before=0;
        bool readable=false;
    };
private:
    std::FILE* file_=nullptr;
    std::size_t capacity_;
    std::vector<Entry> entries_;
    std::unordered_map<Identity,std::size_t,Hash> index_;
    std::array<std::uint32_t,65536> last_{};
    std::uint64_t retired_=0, dropped_=0, unreadable_=0;
    bool finished_=false;
public:
    CodeCapture(const std::filesystem::path& path,std::size_t capacity):capacity_(capacity) {
        if(capacity<1 || capacity>65536) throw Fault("code-capture limit requires 1..65536");
        // Exclusive create prevents symlink/hardlink/source replacement, even
        // if another process creates this name after argument validation.
#ifdef _WIN32
        file_=_wfopen(path.c_str(),L"wx");
#else
        file_=std::fopen(path.c_str(),"wx");
#endif
        if(!file_) throw Fault("cannot exclusively create code capture; choose a new output file");
        last_.fill(std::numeric_limits<std::uint32_t>::max());
        entries_.reserve(capacity_); index_.reserve(capacity_);
    }
    CodeCapture(const CodeCapture&)=delete;
    CodeCapture& operator=(const CodeCapture&)=delete;
    ~CodeCapture() {if(file_) std::fclose(file_);}
    Pending before(const Bus& bus,const Cpu& cpu) const {
        static constexpr std::array<std::uint8_t,256> lengths{1,2,1,2,2,2,2,2,1,2,1,1,3,3,3,3,2,2,2,2,2,2,2,2,1,3,1,1,3,3,3,3,3,2,1,2,2,2,2,2,1,2,1,1,3,3,3,3,2,2,2,1,2,2,2,2,1,3,1,1,3,3,3,3,1,2,1,2,2,2,2,2,1,2,1,1,3,3,3,3,2,2,2,2,1,2,2,2,1,3,1,1,1,3,3,3,1,2,1,1,2,2,2,2,1,2,1,1,3,3,3,3,2,2,2,7,2,2,2,2,1,3,1,1,3,3,3,3,2,2,1,3,2,2,2,2,1,2,1,1,3,3,3,3,2,2,2,4,2,2,2,2,1,3,1,1,3,3,3,3,2,2,2,3,2,2,2,2,1,2,1,1,3,3,3,3,2,2,2,4,2,2,2,2,1,3,1,1,3,3,3,3,2,2,1,7,2,2,2,2,1,2,1,1,3,3,3,3,2,2,2,7,1,2,2,2,1,3,1,1,1,3,3,3,2,2,1,7,2,2,2,2,1,2,1,1,3,3,3,3,2,2,2,7,1,2,2,2,1,3,1,1,1,3,3,3};
        Pending pending;
        pending.native_before=cpu.native_steps;pending.interpreted_before=cpu.interpreter_steps;
        auto& key=pending.identity;key.pc=cpu.pc;key.mpr=cpu.mpr;
        auto opcode=bus.peek(Bus::physical(cpu,cpu.pc));
        if(!opcode) return pending;
        key.length=lengths[*opcode];key.data[0]=*opcode;
        for(unsigned i=1;i<key.length;++i) {
            auto byte=bus.peek(Bus::physical(cpu,static_cast<std::uint16_t>(cpu.pc+i)));
            if(!byte) return pending;
            key.data[i]=*byte;
        }
        pending.readable=true;return pending;
    }
    void after(const Pending& pending,const Cpu& cpu) {
        const auto native=cpu.native_steps-pending.native_before;
        const auto interpreted=cpu.interpreter_steps-pending.interpreted_before;
        if(!native && !interpreted) return; // guard misses, budgets and traps are not instructions.
        if(native+interpreted!=1) throw Fault("invalid code-capture retirement delta");
        ++retired_;
        if(!pending.readable) {++unreadable_;return;}
        const auto& key=pending.identity;
        auto candidate=last_[key.pc];
        std::size_t index;
        if(candidate<entries_.size() && entries_[candidate].identity==key) index=candidate;
        else {
            const auto found=index_.find(key);
            if(found!=index_.end()) index=found->second;
            else {
                if(entries_.size()==capacity_) {++dropped_;return;}
                index=entries_.size();entries_.push_back({key});index_.emplace(key,index);
            }
            last_[key.pc]=static_cast<std::uint32_t>(index);
        }
        entries_[index].native_hits+=native;entries_[index].interpreted_hits+=interpreted;
    }
    void finish() {
        if(finished_) throw Fault("code capture already finalized");
        std::vector<const Entry*> ordered;ordered.reserve(entries_.size());
        for(const auto& entry:entries_) ordered.push_back(&entry);
        std::sort(ordered.begin(),ordered.end(),[](const auto* a,const auto* b) {
            const auto& x=a->identity;const auto& y=b->identity;
            if(x.mpr!=y.mpr) return x.mpr<y.mpr;
            if(x.pc!=y.pc) return x.pc<y.pc;
            if(x.data!=y.data) return x.data<y.data;
            return x.length<y.length;
        });
        std::ostringstream json;
        json<<"{\"schema\":1,\"runtime_abi\":14,\"capacity\":"<<capacity_
            <<",\"dropped_instructions\":"<<dropped_<<",\"unreadable_instructions\":"<<unreadable_
            <<",\"retired_instructions\":"<<retired_<<",\"complete\":"<<(!dropped_&&!unreadable_ ? "true":"false")
            <<",\"observations\":[";
        bool comma=false;
        for(const auto* entry:ordered) {
            const auto& key=entry->identity;
            json<<(comma ? ",":"")<<"{\"pc\":"<<key.pc<<",\"mpr\":[";comma=true;
            for(unsigned i=0;i<8;++i) json<<(i ? ",":"")<<unsigned(key.mpr[i]);
            json<<"],\"physical\":[";
            for(unsigned i=0;i<key.length;++i) {
                auto logical=static_cast<std::uint16_t>(key.pc+i);
                json<<(i ? ",":"")<<((unsigned(key.mpr[logical>>13])<<13)|(logical&8191));
            }
            json<<"],\"data\":[";
            for(unsigned i=0;i<key.length;++i) json<<(i ? ",":"")<<unsigned(key.data[i]);
            json<<"],\"native_hits\":"<<entry->native_hits<<",\"interpreted_hits\":"<<entry->interpreted_hits<<'}';
        }
        json<<"]}\n";
        const auto text=json.str();
        if(std::fwrite(text.data(),1,text.size(),file_)!=text.size() || std::fflush(file_)!=0)
            throw Fault("cannot write code capture");
        finished_=true;
    }
};
} // namespace pce
