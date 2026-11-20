#pragma once
#include "pce/checkpoint_file.hpp"
#include <algorithm>
#include <deque>
#include <limits>

namespace pce {
// Original implementation of a reversible XOR/run-length timeline, inspired by
// RondoRecomp (gminustwo), adapted with permission. Guest checkpoints only:
// consumer hosts own input cursors, presentation/audio resets and trace epochs.
class RewindTimeline {
    static constexpr std::size_t max_state=16*1024*1024;
    struct Delta {std::vector<std::uint8_t> bytes;std::string before,after;};
    std::deque<Delta> history_;
    std::vector<std::uint8_t> current_;
    std::size_t budget_,limit_,used_=0;
    std::string context_;
    static void word(std::vector<std::uint8_t>& out,std::size_t value) {
        for(unsigned n=0;n<4;++n)out.push_back(static_cast<std::uint8_t>(value>>(8*n)));
    }
    static std::size_t read(std::span<const std::uint8_t> bytes,std::size_t& pos) {
        if(pos>bytes.size() || bytes.size()-pos<4)throw Fault("truncated rewind delta");
        std::size_t value=0;for(unsigned n=0;n<4;++n)value|=std::size_t(bytes[pos++])<<(8*n);return value;
    }
public:
    RewindTimeline(std::string context,std::size_t bytes,std::size_t frames):budget_(bytes),limit_(frames),context_(std::move(context)) {
        if(!checkpoint_hex_identity(context_) || !bytes || bytes>512*1024*1024 || !frames || frames>108000)
            throw Fault("rewind requires an exact context and bounded bytes/frames");
    }
    std::size_t available() const {return history_.size();}
    std::size_t bytes() const {return used_+current_.size();}
    static std::vector<std::uint8_t> delta(std::span<const std::uint8_t> before,std::span<const std::uint8_t> after) {
        if(before.empty() || after.empty() || before.size()>max_state || after.size()>max_state)throw Fault("rewind state size out of range");
        std::vector<std::uint8_t> out;word(out,before.size());word(out,after.size());
        const auto n=std::max(before.size(),after.size());
        const auto value=[&](std::size_t i){return std::uint8_t((i<before.size()?before[i]:0)^(i<after.size()?after[i]:0));};
        for(std::size_t i=0;i<n;) {
            const auto start=i;while(i<n && !value(i))++i;word(out,i-start);
            const auto literals=i;while(i<n && value(i))++i;word(out,i-literals);
            for(auto j=literals;j<i;++j)out.push_back(value(j));
        }
        return out;
    }
    static std::vector<std::uint8_t> reverse(std::span<const std::uint8_t> current,std::span<const std::uint8_t> code) {
        std::size_t pos=0;const auto old_size=read(code,pos),new_size=read(code,pos);
        if(!old_size || !new_size || old_size>max_state || new_size>max_state || current.size()!=new_size)throw Fault("rewind delta size mismatch");
        const auto n=std::max(old_size,new_size);std::vector<std::uint8_t> out(n);std::copy(current.begin(),current.end(),out.begin());
        std::size_t i=0;
        while(i<n) {
            const auto skip=read(code,pos),literals=read(code,pos);
            if(skip>n-i || literals>n-i-skip || (!skip&&!literals) || literals>code.size()-pos)throw Fault("invalid rewind run");
            i+=skip;for(std::size_t j=0;j<literals;++j)out[i++]^=code[pos++];
        }
        if(pos!=code.size())throw Fault("trailing rewind bytes");
        out.resize(old_size);return out;
    }
    void push(std::span<const std::uint8_t> state,const std::string& context) {
        if(context!=context_ || state.empty() || state.size()>max_state || state.size()>budget_)throw Fault("rewind context or state bound mismatch");
        std::vector<std::uint8_t> next(state.begin(),state.end());
        if(current_.empty()){current_=std::move(next);return;}
        Delta edge{delta(current_,state),checkpoint_hash(current_),checkpoint_hash(state)};
        // All allocation precedes replacement. A too-large transition drops
        // history explicitly; the current checkpoint itself remains bounded.
        if(edge.bytes.size()>budget_-next.size()) {history_.clear();used_=0;current_=std::move(next);return;}
        history_.push_back(std::move(edge));used_+=history_.back().bytes.size();current_=std::move(next);
        while(history_.size()>limit_ || used_>budget_-current_.size()) {used_-=history_.front().bytes.size();history_.pop_front();}
    }
    std::vector<std::uint8_t> peek(std::size_t frames) const {
        if(!frames || frames>history_.size())throw Fault("rewind exceeds retained history");
        auto result=current_;auto edge=history_.rbegin();
        for(std::size_t i=0;i<frames;++i,++edge) {
            if(checkpoint_hash(result)!=edge->after)throw Fault("rewind current digest mismatch");
            result=reverse(result,edge->bytes);
            if(checkpoint_hash(result)!=edge->before)throw Fault("rewind predecessor digest mismatch");
        }
        return result;
    }
    void capture(const Bus& bus,const Cpu& cpu,const std::string& context) {push(encode_checkpoint(bus,cpu),context);}
    void restore(Bus& bus,Cpu& cpu,std::size_t frames,const std::string& context) {
        if(context!=context_)throw Fault("rewind context mismatch");
        auto restored=peek(frames);restore_checkpoint(bus,cpu,restored);
        for(std::size_t i=0;i<frames;++i){used_-=history_.back().bytes.size();history_.pop_back();}
        current_=std::move(restored);
    }
};
}
