#include "pce/checkpoint_file.hpp"
#include "pce/checkpoint_archive.hpp"
#include "sector_internal.hpp"
#include <cstdio>
#include <fstream>

namespace pce {
namespace {
constexpr std::array<std::uint8_t,8> magic{'P','C','E','D','E','V','C','P'};
constexpr std::size_t maximum_file=checkpoint::maximum_bytes;
void host_fields(auto& archive,auto& state) {
    archive(state.scripted,state.remote,state.input_applied,state.memory_requests,state.memory_changes,state.source_wav_frames,state.next_poll);
}
void validate_host(const CheckpointHostState& state) {
    for(auto mask:state.scripted) if(mask>4095) throw Fault("invalid checkpoint scripted input");
    for(auto mask:state.remote) if(mask>4095) throw Fault("invalid checkpoint remote input");
}
}
bool checkpoint_hex_identity(const std::string& value) {
    return value.size()==64 && std::all_of(value.begin(),value.end(),[](char c){return (c>='0'&&c<='9')||(c>='a'&&c<='f');});
}
std::string checkpoint_hash(std::span<const std::uint8_t> bytes) {
    return detail::text_sha256(std::string_view(reinterpret_cast<const char*>(bytes.data()),bytes.size()));
}
std::filesystem::path checkpoint_path(const std::filesystem::path& directory,const std::string& name) {
    // Socket callers choose only a portable new basename inside a startup-owned
    // directory. Disallow alternate streams, traversal, reserved names and links.
    if(name.empty() || name.size()>96 || name.front()=='.' || name.find("..")!=std::string::npos ||
       !std::all_of(name.begin(),name.end(),[](char c){return (c>='a'&&c<='z')||(c>='A'&&c<='Z')||(c>='0'&&c<='9')||c=='_'||c=='-'||c=='.';}) ||
       !name.ends_with(".pcec")) throw Fault("checkpoint requires a portable .pcec basename");
    auto stem=name.substr(0,name.find('.'));
    std::transform(stem.begin(),stem.end(),stem.begin(),[](unsigned char c){return char(std::toupper(c));});
    if(stem=="CON"||stem=="PRN"||stem=="AUX"||stem=="NUL"||
       (stem.size()==4&&(stem.starts_with("COM")||stem.starts_with("LPT"))&&stem[3]>='0'&&stem[3]<='9'))
        throw Fault("reserved checkpoint basename");
    if(!std::filesystem::is_directory(directory) || std::filesystem::is_symlink(directory)) throw Fault("checkpoint directory must be an existing ordinary directory");
    auto path=directory/name;
    if(std::filesystem::is_symlink(path)) throw Fault("checkpoint links are not supported");
    return path;
}
CheckpointFile save_checkpoint_file(const std::filesystem::path& path,const std::string& identity,
                                    const Bus& bus,const Cpu& cpu,const CheckpointHostState& host) {
    if(!checkpoint_hex_identity(identity)) throw Fault("invalid checkpoint identity");
    validate_host(host);
    auto payload=encode_checkpoint(bus,cpu);
    checkpoint::Writer body;
    auto copy=host;host_fields(body,copy);body.append(payload);
    const auto payload_hash=checkpoint_hash(payload),body_hash=checkpoint_hash(body.data);
    checkpoint::Writer file;
    file(magic,std::uint32_t(1),std::uint32_t(abi_version));file.string(identity,64);file.string(body_hash,64);
    file(std::uint64_t(body.data.size()));file.append(body.data);
#ifdef _WIN32
    auto* output=_wfopen(path.c_str(),L"wbx");
#else
    auto* output=std::fopen(path.c_str(),"wbx");
#endif
    if(!output) throw Fault("cannot exclusively create checkpoint; choose a new file");
    const bool written=std::fwrite(file.data.data(),1,file.data.size(),output)==file.data.size();
    const bool flushed=std::fflush(output)==0;
    const bool closed=std::fclose(output)==0;
    // Preserve a failed partial artifact as evidence; never replace any file.
    if(!written||!flushed||!closed) throw Fault("checkpoint write failed; incomplete new file retained");
    return {nullptr,host,checkpoint_hash(file.data),payload_hash};
}
CheckpointFile load_checkpoint_file(const std::filesystem::path& path,const std::string& identity,const Bus& configured) {
    if(!checkpoint_hex_identity(identity)) throw Fault("invalid checkpoint identity");
    std::ifstream stream(path,std::ios::binary|std::ios::ate);
    if(!stream) throw Fault("cannot open checkpoint");
    const auto size=stream.tellg();
    if(size<=0 || static_cast<std::uint64_t>(size)>maximum_file) throw Fault("checkpoint file exceeds bounds");
    std::vector<std::uint8_t> bytes(static_cast<std::size_t>(size));stream.seekg(0);
    stream.read(reinterpret_cast<char*>(bytes.data()),static_cast<std::streamsize>(bytes.size()));
    if(!stream || stream.peek()!=std::ifstream::traits_type::eof()) throw Fault("checkpoint changed during read");
    checkpoint::Reader file(bytes);
    std::array<std::uint8_t,8> read_magic{};std::uint32_t schema=0,abi=0;std::uint64_t length=0;std::string stored,digest;
    file(read_magic,schema,abi);file.string(stored,64);file.string(digest,64);file(length);
    if(read_magic!=magic||schema!=1||abi!=abi_version) throw Fault("unsupported developer checkpoint format or ABI");
    if(stored!=identity) throw Fault("checkpoint binary/module/source/media/profile identity mismatch");
    if(length!=file.remaining()) throw Fault("checkpoint body length mismatch");
    const auto body=file.take(static_cast<std::size_t>(length));file.finish();
    if(!checkpoint_hex_identity(digest)||checkpoint_hash(body)!=digest) throw Fault("checkpoint digest mismatch");
    checkpoint::Reader reader(body);CheckpointHostState host;host_fields(reader,host);validate_host(host);
    const auto payload=reader.take(reader.remaining());
    auto machine=decode_checkpoint(payload,configured);
    if(host.source_wav_frames>machine->bus.pcm.frames)throw Fault("checkpoint WAV cursor exceeds produced PCM");
    if(host.next_poll>machine->cpu.ticks && host.next_poll-machine->cpu.ticks>20000)
        throw Fault("checkpoint host polling cursor exceeds cadence");
    return {std::move(machine),host,checkpoint_hash(bytes),checkpoint_hash(payload)};
}
} // namespace pce
