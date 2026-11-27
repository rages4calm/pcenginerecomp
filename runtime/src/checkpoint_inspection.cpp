#include "pce/checkpoint_inspection.hpp"
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
        if(std::filesystem::is_symlink(status))throw Fault("checkpoint inspection source links are not supported");
#ifdef _WIN32
        const auto attributes=GetFileAttributesW(component.c_str());
        if(attributes==INVALID_FILE_ATTRIBUTES || (attributes&FILE_ATTRIBUTE_REPARSE_POINT))
            throw Fault("checkpoint inspection source reparse points are not supported");
#endif
    };
    inspect(current);
    for(const auto& part:absolute.relative_path()) {
        if(part=="..")throw Fault("checkpoint inspection source parent traversal is not supported");
        current/=part;inspect(current);
    }
    if(!std::filesystem::is_regular_file(std::filesystem::symlink_status(absolute)) ||
       std::filesystem::hard_link_count(absolute)!=1)
        throw Fault("checkpoint inspection requires an ordinary singly linked source file");
}
}
CheckpointInspection inspect_checkpoint_state(const std::filesystem::path& path,
    const std::string& identity,const std::string& expected_file_sha256,
    const Bus& configured,const CheckpointAdapterBinding* expected_adapter) {
    if(!checkpoint_hex_identity(identity) || !checkpoint_hex_identity(expected_file_sha256))
        throw Fault("checkpoint inspection requires exact identity and whole-file SHA256");
    require_ordinary_source(path);
    // The original must validate before any projection. Decode remains private;
    // neither configured machine nor caller-owned input is restored or mutated.
    const auto checkpoint=load_checkpoint_file(path,identity,configured,expected_file_sha256,expected_adapter);
    CheckpointInspection result;
    result.cpu=checkpoint.machine->cpu;
    result.host=checkpoint.host;
    result.checkpoint_sha256=checkpoint.sha256;
    result.core_sha256=checkpoint.payload_sha256;
    result.host_sha256=checkpoint_hash(encode_checkpoint_host(checkpoint.host));
    if(checkpoint.host.adapter)
        result.adapter_state_sha256=checkpoint_hash(checkpoint.host.adapter->state);
    auto projected=checkpoint.machine->cpu;
    projected.native_steps=0;projected.interpreter_steps=0;
    projected.native_block_steps=0;projected.interpreter_block_steps=0;
    result.tier_neutral_core_sha256=checkpoint_hash(encode_checkpoint(checkpoint.machine->bus,projected));
    result.frame=checkpoint.machine->bus.vdc.video.sequence();
    result.raster_frames=checkpoint.machine->bus.vdc.raster.frames;
    result.pending_pcm_frames=checkpoint.machine->bus.pcm.queued_frames();
    result.joypad_enabled=checkpoint.machine->bus.joypad.enabled;
    for(unsigned n=0;n<result.joypad_pressed.size();++n)
        result.joypad_pressed[n]=checkpoint.machine->bus.joypad.pads[n].pressed;
    return result;
}
} // namespace pce
