#pragma once
#include "pce/checkpoint_file.hpp"
#include <fstream>
#include <sstream>
#include <utility>
#include <iterator>

namespace pce {
// Startup-owned, reviewed admission capability. This is integrity binding,
// not remote authentication or permission to load arbitrary cross-build state.
struct CheckpointContinuation {
    std::string source_identity, destination_identity, checkpoint_sha256, receipt_sha256;
};
inline CheckpointContinuation read_checkpoint_continuation(
        const std::filesystem::path& path,const std::string& expected_sha256) {
    if(!checkpoint_hex_identity(expected_sha256) || std::filesystem::is_symlink(path) ||
       !std::filesystem::is_regular_file(path) || std::filesystem::file_size(path)>512)
        throw Fault("invalid checkpoint continuation permit");
    std::ifstream input(path,std::ios::binary);
    std::array<char,513> buffer{};input.read(buffer.data(),buffer.size());
    const auto count=input.gcount();
    if(input.bad() || count<=0 || count>512 || !input.eof())
        throw Fault("checkpoint continuation permit exceeds bounded read");
    const std::string raw(buffer.data(),static_cast<std::size_t>(count));
    if(checkpoint_hash(std::span(
            reinterpret_cast<const std::uint8_t*>(raw.data()),raw.size()))!=expected_sha256)
        throw Fault("checkpoint continuation permit digest mismatch");
    std::istringstream stream(raw);std::string magic,version,key,extra;
    CheckpointContinuation result;
    if(!(stream>>magic>>version) || magic!="PCE_CHECKPOINT_CONTINUATION" || version!="1")
        throw Fault("unsupported checkpoint continuation permit");
    for(auto field:{std::pair{"source_identity",&result.source_identity},
                    std::pair{"destination_identity",&result.destination_identity},
                    std::pair{"checkpoint_sha256",&result.checkpoint_sha256},
                    std::pair{"receipt_sha256",&result.receipt_sha256}}) {
        if(!(stream>>key>>*field.second) || key!=field.first || !checkpoint_hex_identity(*field.second))
            throw Fault("invalid checkpoint continuation permit fields");
    }
    if(stream>>extra)throw Fault("trailing checkpoint continuation permit fields");
    return result;
}
} // namespace pce
