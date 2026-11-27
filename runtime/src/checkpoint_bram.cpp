#include "pce/checkpoint_bram.hpp"
#include <algorithm>
#ifdef _WIN32
#ifndef NOMINMAX
#define NOMINMAX
#endif
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#endif

namespace pce {
namespace {
void require_ordinary_source(const std::filesystem::path& path) {
    const auto absolute=std::filesystem::absolute(path);
    auto current=absolute.root_path();
    const auto inspect=[](const std::filesystem::path& component) {
        const auto status=std::filesystem::symlink_status(component);
        if(std::filesystem::is_symlink(status))throw Fault("checkpoint BRAM source links are not supported");
#ifdef _WIN32
        const auto attributes=GetFileAttributesW(component.c_str());
        if(attributes==INVALID_FILE_ATTRIBUTES || (attributes&FILE_ATTRIBUTE_REPARSE_POINT))
            throw Fault("checkpoint BRAM source reparse points are not supported");
#endif
    };
    inspect(current);
    for(const auto& part:absolute.relative_path()) {
        if(part=="..")throw Fault("checkpoint BRAM source parent traversal is not supported");
        current/=part;inspect(current);
    }
    if(!std::filesystem::is_regular_file(std::filesystem::symlink_status(absolute)) ||
       std::filesystem::hard_link_count(absolute)!=1)
        throw Fault("checkpoint BRAM diagnostic requires an ordinary singly linked source file");
}
void require_bram_layout(const Bus& bus) {
    constexpr auto begin=CheckpointBramDiagnostic::physical_address;
    if(!bus.bytes || !bus.cd.enabled || bus.hucard || bus.kind[0xF7]!=BankKind::bram)
        throw Fault("checkpoint BRAM diagnostic requires an explicit CD/F7 BRAM profile");
    for(unsigned bank=0;bank<bus.kind.size();++bank)
        if(bus.kind[bank]==BankKind::bram && bank!=0xF7)
            throw Fault("checkpoint BRAM diagnostic requires the canonical F7 bank layout");
    // Require the entire physical bank's backing, not a guest-visible alias or
    // the gated Bus::read/peek APIs. Only its first 2048 bytes are diagnostic BRAM.
    if(begin+8192>bus.bytes->size()) throw Fault("checkpoint BRAM backing exceeds memory");
    for(unsigned offset=0;offset<8192;++offset)
        if(bus.backing_address(begin+offset)!=begin+offset)
            throw Fault("checkpoint BRAM diagnostic refuses noncanonical backing");
}
}
CheckpointBramDiagnostic inspect_checkpoint_bram(const std::filesystem::path& path,
    const std::string& identity,const std::string& expected_file_sha256,const Bus& configured) {
    if(!checkpoint_hex_identity(identity) || !checkpoint_hex_identity(expected_file_sha256))
        throw Fault("checkpoint BRAM diagnostic requires exact identity and whole-file SHA256");
    require_ordinary_source(path);
    require_bram_layout(configured);
    // This authenticates the complete envelope and decodes/validates all CORE,
    // host state, immutable ROM, profiles and provider binding before extraction.
    // Omitting an adapter binding intentionally rejects schema 2.
    const auto checkpoint=load_checkpoint_file(path,identity,configured,expected_file_sha256);
    require_bram_layout(checkpoint.machine->bus);
    CheckpointBramDiagnostic result;
    std::copy_n(checkpoint.machine->bus.bytes->begin()+result.physical_address,
                result.bytes.size(),result.bytes.begin());
    result.checkpoint_sha256=checkpoint.sha256;
    result.core_sha256=checkpoint.payload_sha256;
    result.bram_sha256=checkpoint_hash(result.bytes);
    result.frame=checkpoint.machine->bus.vdc.video.sequence();
    result.raster_frames=checkpoint.machine->bus.vdc.raster.frames;
    result.pending_pcm_frames=checkpoint.machine->bus.pcm.queued_frames();
    result.cpu=checkpoint.machine->cpu;
    result.host=checkpoint.host;
    return result;
}
} // namespace pce
