#pragma once

#include "pce/sector.hpp"
#include <string_view>

namespace pce::detail {
// Internal composition helpers; these do not alter the guest/runtime ABI.
std::string file_sha256(const std::string& path);
std::string text_sha256(std::string_view bytes);
std::string cue_sha256(const std::string& path);
std::shared_ptr<SectorProvider> open_cue_provider(const std::string& path);
}
