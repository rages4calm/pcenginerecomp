#pragma once

#include <algorithm>
#include <array>
#include <bit>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <optional>
#include <span>
#include <stdexcept>
#include <string>
#include <type_traits>
#include <vector>

namespace pce::checkpoint {
inline constexpr std::size_t maximum_bytes=64u*1024u*1024u;
struct ArchiveError : std::runtime_error { using std::runtime_error::runtime_error; };
template<class> inline constexpr bool dependent_false=false;
template<class T> struct is_array : std::false_type {};
template<class T,std::size_t N> struct is_array<std::array<T,N>> : std::true_type {};
template<class T> struct is_optional : std::false_type {};
template<class T> struct is_optional<std::optional<T>> : std::true_type {};
template<class T> constexpr std::size_t minimum_size() {
    if constexpr(std::is_arithmetic_v<T>) return sizeof(T);
    else if constexpr(is_array<T>::value) return std::tuple_size_v<T>*minimum_size<typename T::value_type>();
    else return 1;
}

// Fieldwise canonical little-endian format. Object representations, padding,
// pointers, native streams and allocator state never enter a checkpoint.
class Writer {
public:
    std::vector<std::uint8_t> data;
    Writer() { data.reserve(8u*1024u*1024u); }
    template<class... Ts> void operator()(const Ts&... values) { (value(values),...); }
    template<class T> void vector(const std::vector<T>& values,std::size_t maximum) {
        if(values.size()>maximum || values.size()>UINT32_MAX) throw ArchiveError("checkpoint vector exceeds limit");
        value(static_cast<std::uint32_t>(values.size()));
        if constexpr(std::is_same_v<T,std::uint8_t>) append(values);
        else for(const auto& item:values) value(item);
    }
    void string(const std::string& text,std::size_t maximum=4096) {
        if(text.size()>maximum || text.size()>UINT32_MAX) throw ArchiveError("checkpoint string exceeds limit");
        value(static_cast<std::uint32_t>(text.size()));
        append(std::span(reinterpret_cast<const std::uint8_t*>(text.data()),text.size()));
    }
    void append(std::span<const std::uint8_t> bytes) {
        if(bytes.size()>maximum_bytes-data.size()) throw ArchiveError("checkpoint exceeds 64 MiB limit");
        data.insert(data.end(),bytes.begin(),bytes.end());
    }
private:
    template<class T> void value(const T& item) {
        if constexpr(std::is_same_v<T,bool>) { const std::uint8_t byte=item ? 1:0; append({&byte,1}); }
        else if constexpr(std::is_integral_v<T>) {
            static_assert(sizeof(T)==1 || sizeof(T)==2 || sizeof(T)==4 || sizeof(T)==8);
            using U=std::make_unsigned_t<T>;
            U bits;
            if constexpr(std::is_signed_v<T>) bits=std::bit_cast<U>(item); else bits=item;
            std::array<std::uint8_t,sizeof(T)> bytes{};
            for(std::size_t i=0;i<sizeof(T);++i) bytes[i]=static_cast<std::uint8_t>(bits>>(i*8));
            append(bytes);
        } else if constexpr(std::is_floating_point_v<T>) {
            static_assert(std::numeric_limits<T>::is_iec559 && (sizeof(T)==4 || sizeof(T)==8));
            if(!std::isfinite(item)) throw ArchiveError("checkpoint contains nonfinite floating state");
            if constexpr(sizeof(T)==4) value(std::bit_cast<std::uint32_t>(item));
            else value(std::bit_cast<std::uint64_t>(item));
        } else if constexpr(is_array<T>::value) {
            if constexpr(std::is_same_v<typename T::value_type,std::uint8_t>) append(item);
            else for(const auto& element:item) value(element);
        } else if constexpr(is_optional<T>::value) { value(item.has_value()); if(item) value(*item); }
        else if constexpr(std::is_same_v<T,std::string>) string(item);
        else static_assert(dependent_false<T>,"checkpoint fields require an explicit serializer");
    }
};

class Reader {
public:
    explicit Reader(std::span<const std::uint8_t> bytes):data_(bytes) {
        if(bytes.size()>maximum_bytes) throw ArchiveError("checkpoint exceeds 64 MiB limit");
    }
    template<class... Ts> void operator()(Ts&... values) { (value(values),...); }
    std::size_t remaining() const { return data_.size()-position_; }
    std::size_t position() const { return position_; }
    void finish() const { if(remaining()) throw ArchiveError("checkpoint has trailing bytes"); }
    template<class T> void vector(std::vector<T>& values,std::size_t maximum) {
        std::uint32_t count=0; value(count);
        if(count>maximum || count>remaining()/minimum_size<T>()) throw ArchiveError("checkpoint vector exceeds bounds");
        values.resize(count);
        if constexpr(std::is_same_v<T,std::uint8_t>) {
            const auto bytes=take(count);std::copy(bytes.begin(),bytes.end(),values.begin());
        } else for(auto& item:values) value(item);
    }
    void string(std::string& text,std::size_t maximum=4096) {
        std::uint32_t count=0; value(count);
        if(count>maximum || count>remaining()) throw ArchiveError("checkpoint string exceeds bounds");
        const auto bytes=take(count);
        text.assign(reinterpret_cast<const char*>(bytes.data()),bytes.size());
    }
    std::span<const std::uint8_t> take(std::size_t count) {
        if(count>remaining()) throw ArchiveError("truncated checkpoint");
        const auto bytes=data_.subspan(position_,count); position_+=count; return bytes;
    }
private:
    std::span<const std::uint8_t> data_;
    std::size_t position_=0;
    template<class T> void value(T& item) {
        if constexpr(std::is_same_v<T,bool>) {
            const auto byte=take(1)[0]; if(byte>1) throw ArchiveError("invalid checkpoint boolean"); item=byte!=0;
        } else if constexpr(std::is_integral_v<T>) {
            using U=std::make_unsigned_t<T>; U bits=0;
            const auto bytes=take(sizeof(T));
            for(std::size_t i=0;i<sizeof(T);++i) bits|=static_cast<U>(bytes[i])<<(i*8);
            if constexpr(std::is_signed_v<T>) item=std::bit_cast<T>(bits); else item=bits;
        } else if constexpr(std::is_floating_point_v<T>) {
            if constexpr(sizeof(T)==4) { std::uint32_t bits=0; value(bits); item=std::bit_cast<T>(bits); }
            else { std::uint64_t bits=0; value(bits); item=std::bit_cast<T>(bits); }
            if(!std::isfinite(item)) throw ArchiveError("checkpoint contains nonfinite floating state");
        } else if constexpr(is_array<T>::value) {
            if constexpr(std::is_same_v<typename T::value_type,std::uint8_t>) {
                const auto bytes=take(item.size()); std::copy(bytes.begin(),bytes.end(),item.begin());
            } else for(auto& element:item) value(element);
        } else if constexpr(is_optional<T>::value) {
            bool present=false; value(present); if(present) { item.emplace(); value(*item); } else item.reset();
        } else if constexpr(std::is_same_v<T,std::string>) string(item);
        else static_assert(dependent_false<T>,"checkpoint fields require an explicit serializer");
    }
};
static_assert(sizeof(unsigned)==4 && sizeof(int)==4 && sizeof(std::size_t)==8,
              "checkpoint v1 requires a 64-bit target with 32-bit int");
} // namespace pce::checkpoint
