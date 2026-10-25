#pragma once
#include <algorithm>
#include <array>
#include <cstdint>
#include <cstdlib>
#include <filesystem>
#include <stdexcept>
#include <string>
#include <vector>
#ifdef _WIN32
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#else
#include <cerrno>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>
#endif

namespace pce {
// Host-only raw snapshot, without formatting, guest reads or a save namespace.
// No output is opened until the caller has completed successful finalization.
inline void validate_bram_output(const std::filesystem::path& path) {
    const auto parent=path.has_parent_path() ? path.parent_path():std::filesystem::path(".");
    if(path.filename().empty() || !std::filesystem::is_directory(parent))
        throw std::runtime_error("BRAM export requires a file in an existing directory");
    const auto status=std::filesystem::symlink_status(path);
    if(status.type()!=std::filesystem::file_type::not_found)
        throw std::runtime_error("BRAM export exists; choose a new file");
}

inline void export_bram_new(const std::filesystem::path& path,
                            const std::array<std::uint8_t,2048>& bytes) {
    validate_bram_output(path);
#ifdef _WIN32
    // Rename the owned handle, not a name another process could have replaced.
    // ReplaceIfExists is false: the final name can never replace an input/save.
    HANDLE file=INVALID_HANDLE_VALUE;
    std::filesystem::path temporary;
    for(unsigned attempt=0;attempt<128 && file==INVALID_HANDLE_VALUE;++attempt) {
        temporary=path;
        temporary+=L".pce-bram-"+std::to_wstring(GetCurrentProcessId())+L"-"+
                   std::to_wstring(GetTickCount64())+L"-"+std::to_wstring(attempt);
        file=CreateFileW(temporary.c_str(),GENERIC_WRITE|DELETE,FILE_SHARE_READ,
                         nullptr,CREATE_NEW,FILE_ATTRIBUTE_NORMAL,nullptr);
        if(file==INVALID_HANDLE_VALUE && GetLastError()!=ERROR_FILE_EXISTS && GetLastError()!=ERROR_ALREADY_EXISTS)
            throw std::runtime_error("cannot create temporary BRAM export");
    }
    if(file==INVALID_HANDLE_VALUE) throw std::runtime_error("cannot reserve temporary BRAM export");
    try {
        DWORD written=0;
        if(!WriteFile(file,bytes.data(),static_cast<DWORD>(bytes.size()),&written,nullptr) ||
           written!=bytes.size() || !FlushFileBuffers(file))
            throw std::runtime_error("BRAM export write/flush failed");
        const auto absolute=std::filesystem::absolute(path).native();
        const auto name_bytes=absolute.size()*sizeof(wchar_t);
        std::vector<unsigned char> storage(sizeof(FILE_RENAME_INFO)+name_bytes);
        auto* rename=reinterpret_cast<FILE_RENAME_INFO*>(storage.data());
        rename->ReplaceIfExists=FALSE;
        rename->RootDirectory=nullptr;
        rename->FileNameLength=static_cast<DWORD>(name_bytes);
        std::copy(absolute.begin(),absolute.end(),rename->FileName);
        if(!SetFileInformationByHandle(file,FileRenameInfo,rename,static_cast<DWORD>(storage.size())))
            throw std::runtime_error("cannot publish new BRAM export");
        CloseHandle(file);
    } catch(...) {
        FILE_DISPOSITION_INFO remove{TRUE};
        SetFileInformationByHandle(file,FileDispositionInfo,&remove,sizeof(remove));
        CloseHandle(file);
        throw;
    }
#else
    std::string pattern=path.native()+".pce-bram-XXXXXX";
    std::vector<char> name(pattern.begin(),pattern.end());name.push_back('\0');
    const int file=mkstemp(name.data());
    if(file<0) throw std::runtime_error("cannot create temporary BRAM export");
    struct stat owned{};
    const bool identified=fstat(file,&owned)==0;
    const auto cleanup=[&] {
        struct stat current{};
        // Never remove a replacement name if someone changed the directory.
        if(identified && lstat(name.data(),&current)==0 &&
           current.st_dev==owned.st_dev && current.st_ino==owned.st_ino)
            unlink(name.data());
    };
    try {
        if(!identified) throw std::runtime_error("cannot identify temporary BRAM export");
        std::size_t done=0;
        while(done<bytes.size()) {
            const auto count=write(file,bytes.data()+done,bytes.size()-done);
            if(count<0 && errno==EINTR) continue;
            if(count<=0) throw std::runtime_error("BRAM export write failed");
            done+=static_cast<std::size_t>(count);
        }
        if(fsync(file)!=0) throw std::runtime_error("BRAM export flush failed");
        // A same-directory hard link publishes a complete file atomically and
        // refuses an existing destination, including a concurrent creator.
        if(link(name.data(),path.c_str())!=0)
            throw std::runtime_error("cannot publish new BRAM export");
        cleanup();close(file);
    } catch(...) {cleanup();close(file);throw;}
#endif
}
} // namespace pce
