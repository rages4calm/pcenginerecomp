#pragma once

namespace pce {
struct Bus;
namespace checkpoint {
class Writer;
class Reader;
// The destination is a fresh, configured machine with its read-only provider
// already attached. No media reads or guest clock advances occur here.
void write_audio(Writer&,const Bus&);
void read_audio(Reader&,Bus&);
void validate_audio(const Bus&);
void validate_audio_configuration(const Bus& decoded,const Bus& configured);
} // namespace checkpoint
} // namespace pce
