#include "sector_internal.hpp"

#include <algorithm>
#include <cctype>
#include <filesystem>
#include <fstream>
#include <limits>
#include <set>
#include <sstream>
#include <vector>

namespace pce {
namespace {
namespace fs=std::filesystem;
constexpr std::uint64_t max_bytes=8ULL*1024*1024*1024;
constexpr std::size_t max_cue=1024*1024;
fs::path path_of(const std::string& text) {
    return fs::path(std::u8string(reinterpret_cast<const char8_t*>(text.data()),text.size()));
}
std::string utf8_path(const fs::path& path) {
    const auto bytes=path.generic_u8string();
    return std::string(reinterpret_cast<const char*>(bytes.data()),bytes.size());
}
std::string upper(std::string text) {
    for(auto& c:text) if(c>='a' && c<='z')c=static_cast<char>(c-'a'+'A');
    return text;
}
void valid_utf8(const std::string& bytes) {
    for(std::size_t i=0;i<bytes.size();) {
        const auto first=static_cast<unsigned char>(bytes[i++]);
        if(first<0x80) {
            if((first<32 && first!='\t' && first!='\r' && first!='\n') || first==127)
                throw Fault("CUE contains unsupported control characters");
            continue;
        }
        unsigned count=0,scalar=0,minimum=0;
        if(first>=0xC2 && first<=0xDF) {count=1;scalar=first&31;minimum=0x80;}
        else if(first>=0xE0 && first<=0xEF) {count=2;scalar=first&15;minimum=0x800;}
        else if(first>=0xF0 && first<=0xF4) {count=3;scalar=first&7;minimum=0x10000;}
        else throw Fault("CUE requires valid UTF-8 text");
        if(count>bytes.size()-i)throw Fault("Truncated CUE UTF-8 text");
        while(count--) {
            const auto next=static_cast<unsigned char>(bytes[i++]);
            if((next&0xC0)!=0x80)throw Fault("CUE requires valid UTF-8 text");
            scalar=(scalar<<6)|(next&63);
        }
        if(scalar<minimum || scalar>0x10FFFF || (scalar>=0xD800 && scalar<=0xDFFF))
            throw Fault("CUE requires valid UTF-8 text");
    }
}
struct Stamp {
    std::uintmax_t size;
    fs::file_time_type time;
    bool operator==(const Stamp&) const=default;
};
Stamp stamp(const fs::path& path) {
    std::error_code error;
    if(!fs::is_regular_file(path,error) || error)throw Fault("CUE source must be a regular file");
    const auto size=fs::file_size(path,error);
    if(error || size>max_bytes)throw Fault("CUE source exceeds the file size bound");
    const auto time=fs::last_write_time(path,error);
    if(error)throw Fault("Cannot inspect CUE source timestamp");
    return {size,time};
}
fs::path resolved(const fs::path& path) {
    std::error_code error;
    const auto result=fs::canonical(path,error);
    if(error)throw Fault("Cannot resolve CUE source path");
    return result;
}
bool within(const fs::path& path,const fs::path& parent) {
    const auto relative=path.lexically_relative(parent);
    if(relative.empty() || relative.is_absolute())return false;
    for(const auto& item:relative)if(item=="..")return false;
    return true;
}
std::string filename(std::string name) {
    std::replace(name.begin(),name.end(),'\\','/');
    if(name.empty() || name.front()=='/' || name.back()=='/')throw Fault("CUE FILE requires a relative filename");
    std::istringstream parts(name);
    std::string part;
    while(std::getline(parts,part,'/')) {
        if(part.empty() || part=="." || part==".." || part.back()=='.' || part.back()==' ')
            throw Fault("CUE FILE requires portable relative path components");
        for(const unsigned char c:part)
            if(c<32 || c==127 || std::string("<>:\"|?*").find(static_cast<char>(c))!=std::string::npos)
                throw Fault("CUE FILE requires a portable filename");
        const auto base=upper(part.substr(0,part.find('.')));
        if(base=="CON" || base=="PRN" || base=="AUX" || base=="NUL" ||
           (base.size()==4 && (base.starts_with("COM") || base.starts_with("LPT")) && base[3]>='1' && base[3]<='9'))
            throw Fault("CUE FILE uses a reserved device filename");
    }
    return name;
}
std::vector<std::string> tokens(const std::string& line) {
    std::vector<std::string> result;
    std::size_t i=0;
    while(i<line.size()) {
        while(i<line.size() && (line[i]==' ' || line[i]=='\t' || line[i]=='\r'))++i;
        if(i==line.size())break;
        std::string token;
        if(line[i]=='"') {
            const auto end=line.find('"',++i);
            if(end==std::string::npos)throw Fault("Unterminated CUE quoted token");
            token=line.substr(i,end-i);i=end+1;
            if(i<line.size() && line[i]!=' ' && line[i]!='\t' && line[i]!='\r')
                throw Fault("CUE quoted token must end at whitespace");
        } else {
            const auto begin=i;
            while(i<line.size() && line[i]!=' ' && line[i]!='\t' && line[i]!='\r')++i;
            token=line.substr(begin,i-begin);
            if(token.find('"')!=std::string::npos)throw Fault("Unexpected CUE quote");
        }
        result.push_back(std::move(token));
    }
    return result;
}
unsigned number(const std::string& value) {
    if(value.empty() || value.size()>2 || !std::all_of(value.begin(),value.end(),[](char c){return c>='0' && c<='9';}))
        throw Fault("Invalid CUE track/index number");
    unsigned result=0;
    for(char c:value)result=result*10+unsigned(c-'0');
    return result;
}
unsigned time(const std::string& value) {
    if(value.size()!=8 || value[2]!=':' || value[5]!=':')throw Fault("CUE time requires MM:SS:FF");
    const auto minute=number(value.substr(0,2)),second=number(value.substr(3,2)),frame=number(value.substr(6,2));
    if(second>=60 || frame>=75)throw Fault("CUE time is outside MSF range");
    return (minute*60+second)*75+frame;
}

class CueProvider final:public SectorProvider {
    struct Source {
        std::string name;
        fs::path declared,path;
        Stamp initial;
        unsigned width=0;
    };
    struct Track {
        unsigned file=0,index0=0,index1=0,pregap=0,start=0,count=0;
        bool has0=false,has1=false,has_pregap=false,audio=false,raw=false;
        unsigned segment() const {return has0?index0:index1;}
        unsigned stored() const {return has0?index1-index0:0;}
    };
    fs::path declared,path,base;
    Stamp initial;
    std::vector<Source> files;
    std::vector<Track> tracks;
    CdToc table;
    std::string digest;

    void unchanged() const {
        if(resolved(declared)!=path || !(stamp(path)==initial))throw Fault("CUE source changed after identity verification");
        for(const auto& source:files)
            if(resolved(source.declared)!=source.path || !(stamp(source.path)==source.initial))
                throw Fault("CUE component changed after identity verification");
    }
    void parse(const std::string& text) {
        int file=-1;
        Track* current=nullptr;
        std::set<std::string> names;
        std::set<fs::path> paths;
        std::istringstream lines(text);
        std::string line;
        while(std::getline(lines,line)) {
            if(!line.empty() && line.back()=='\r')line.pop_back();
            if(line.find('\r')!=std::string::npos)throw Fault("CUE contains an embedded carriage return");
            // REM has an opaque comment body, including unmatched quotation.
            const auto first=line.find_first_not_of(" \t\r");
            if(first==std::string::npos)continue;
            const auto end=line.find_first_of(" \t\r",first);
            const auto directive=upper(line.substr(first,end==std::string::npos?end:end-first));
            if(directive=="REM")continue;
            const auto args=tokens(line);
            if(directive=="TITLE" || directive=="PERFORMER" || directive=="SONGWRITER" || directive=="CATALOG" || directive=="ISRC") {
                if(args.size()<2)throw Fault("CUE text metadata requires a value");
                continue;
            }
            if(directive=="FILE") {
                if(args.size()!=3 || upper(args[2])!="BINARY" || files.size()==99)
                    throw Fault("CUE supports at most 99 BINARY FILE declarations");
                if(file>=0 && (tracks.empty() || tracks.back().file!=static_cast<unsigned>(file)))
                    throw Fault("CUE FILE contains no TRACK");
                auto name=filename(args[1]);
                const auto lexical=base/path_of(name),canonical=resolved(lexical);
                if(!within(canonical,base) || canonical==path)throw Fault("CUE FILE escapes its cue directory or aliases the descriptor");
                if(!names.insert(upper(name)).second || !paths.insert(canonical).second)
                    throw Fault("Duplicate CUE FILE source");
                files.push_back({name,lexical,canonical,stamp(canonical),0});
                file=static_cast<int>(files.size()-1);current=nullptr;
            } else if(directive=="TRACK") {
                if(args.size()!=3 || file<0 || tracks.size()==99 || number(args[1])!=tracks.size()+1)
                    throw Fault("CUE TRACK numbers must be sequential from 01");
                const auto mode=upper(args[2]);
                if(mode!="AUDIO" && mode!="MODE1/2048" && mode!="MODE1/2352")
                    throw Fault("Unsupported CUE TRACK mode");
                const unsigned width=mode=="MODE1/2048"?2048:2352;
                auto& source=files[static_cast<unsigned>(file)];
                if(source.width && source.width!=width)throw Fault("Mixed CUE sector widths within one FILE are unsupported");
                source.width=width;
                tracks.push_back({});current=&tracks.back();
                current->file=static_cast<unsigned>(file);current->audio=mode=="AUDIO";current->raw=mode=="MODE1/2352";
            } else if(directive=="INDEX") {
                if(args.size()!=3 || !current)throw Fault("CUE INDEX requires a TRACK");
                const auto index=number(args[1]),frame=time(args[2]);
                if(index==0 && !current->has0 && !current->has1) {current->has0=true;current->index0=frame;}
                else if(index==1 && !current->has1) {current->has1=true;current->index1=frame;}
                else throw Fault("CUE supports one INDEX 00 before one INDEX 01 only");
            } else if(directive=="PREGAP") {
                if(args.size()!=2 || !current || current->has_pregap || current->has0 || current->has1)
                    throw Fault("CUE PREGAP must occur once before INDEX");
                current->has_pregap=true;current->pregap=time(args[1]);
            } else throw Fault("Unsupported CUE command: "+directive);
        }
        if(tracks.empty() || files.empty() || tracks.back().file!=files.size()-1)
            throw Fault("CUE requires nonempty FILE/TRACK declarations");
        std::uint64_t total=0;
        for(const auto& source:files) {
            if(!source.width || !source.initial.size || source.initial.size%source.width)
                throw Fault("CUE FILE requires complete nonempty sectors");
            total+=source.initial.size;
            if(total>max_bytes)throw Fault("Combined CUE sources exceed 8 GiB");
        }
        std::uint64_t cursor=0;
        for(std::size_t i=0;i<tracks.size();++i) {
            auto& track=tracks[i];
            if(!track.has1 || (track.has0 && track.index0>track.index1))throw Fault("CUE TRACK requires an ordered INDEX 01");
            if(track.pregap && track.stored())throw Fault("Combined virtual and stored CUE pregap is unsupported");
            if(i==0 && (track.index1 || track.pregap))throw Fault("First CUE track must start at file/disc frame zero");
            if((i==0 || tracks[i-1].file!=track.file) && track.segment()!=0)
                throw Fault("First CUE segment in each FILE must begin at zero");
            const auto& source=files[track.file];
            const auto frames=source.initial.size/source.width;
            const auto end=i+1<tracks.size() && tracks[i+1].file==track.file ? tracks[i+1].segment():frames;
            if(end>frames || track.index1>=end)throw Fault("CUE track data is empty, unordered or outside FILE");
            track.count=static_cast<unsigned>(end-track.index1);
            cursor+=track.pregap+track.stored();
            track.start=static_cast<unsigned>(cursor);
            cursor+=track.count;
            if(cursor>449849)throw Fault("CUE leadout exceeds the supported CD range");
            table.tracks[i]={track.start,static_cast<std::uint8_t>(track.audio?0:4)};
        }
        table.track_count=static_cast<unsigned>(tracks.size());table.leadout_lba=static_cast<std::uint32_t>(cursor);
        table.validate();
    }
    const Track& locate(unsigned lba,bool audio) const {
        for(const auto& track:tracks) {
            const bool payload=lba>=track.start && lba-track.start<track.count;
            const bool stored=audio && track.audio && lba<track.start && track.start-lba<=track.stored();
            if(payload || stored) {
                if(track.audio!=audio)throw Fault("CUE sector type does not match requested data/audio read");
                return track;
            }
        }
        throw Fault("CUE LBA falls in a gap or outside disc");
    }
    void frame(const Track& track,unsigned lba,std::uint8_t* output,std::size_t size,unsigned offset=0) const {
        const auto& source=files[track.file];
        const auto number=lba>=track.start ? std::uint64_t(track.index1)+(lba-track.start):std::uint64_t(track.index1)-(track.start-lba);
        std::ifstream stream(source.path,std::ios::binary);
        if(!stream)throw Fault("Cannot open CUE component for read");
        stream.seekg(static_cast<std::streamoff>(number*source.width+offset));
        stream.read(reinterpret_cast<char*>(output),static_cast<std::streamsize>(size));
        if(static_cast<std::size_t>(stream.gcount())!=size)throw Fault("Short CUE sector read");
    }
public:
    explicit CueProvider(const std::string& image) {
        std::error_code error;
        declared=fs::absolute(path_of(image),error);
        if(error)throw Fault("Cannot resolve CUE path");
        path=resolved(declared);base=resolved(declared.parent_path());
        if(!within(path,base))throw Fault("CUE source escapes its declared directory");
        initial=stamp(path);
        if(!initial.size || initial.size>max_cue)throw Fault("CUE text must contain 1..1048576 bytes");
        std::ifstream stream(path,std::ios::binary);
        std::string text(static_cast<std::size_t>(initial.size),'\0');
        stream.read(text.data(),static_cast<std::streamsize>(text.size()));
        if(static_cast<std::size_t>(stream.gcount())!=text.size())throw Fault("Short CUE text read");
        valid_utf8(text);
        if(text.starts_with("\xEF\xBB\xBF"))text.erase(0,3);
        parse(text);unchanged();
        std::string identity="PCE-CUE-1\ncue\t"+std::to_string(initial.size)+"\t"+detail::file_sha256(utf8_path(path))+"\n";
        for(const auto& source:files)
            identity+="file\t"+source.name+"\t"+std::to_string(source.initial.size)+"\t"+detail::file_sha256(utf8_path(source.path))+"\n";
        unchanged();digest=detail::text_sha256(identity);table.image_sha256=digest;
    }
    const CdToc& toc() const override {return table;}
    bool audio_playable(std::uint32_t lba) const override {
        unchanged();
        bool result=false;
        for(std::size_t i=0;i<tracks.size();++i) {
            const auto& track=tracks[i];
            if(track.audio && ((lba>=track.start && lba-track.start<track.count) ||
               (i && tracks[i-1].audio && lba<track.start && track.start-lba<=track.stored()))) {result=true;break;}
        }
        unchanged();return result;
    }
    Sector read(std::uint32_t lba) override {
        unchanged();const auto& track=locate(lba,false);Sector result{};
        if(track.raw) {
            std::array<std::uint8_t,2352> bytes{};frame(track,lba,bytes.data(),bytes.size());
            if(bytes[0] || bytes[11] || bytes[15]!=1 || !std::all_of(bytes.begin()+1,bytes.begin()+11,[](auto v){return v==255;}))
                throw Fault("Invalid CUE MODE1 raw sector header");
            std::copy_n(bytes.begin()+16,result.size(),result.begin());
        } else frame(track,lba,result.data(),result.size());
        unchanged();return result;
    }
    AudioSector read_audio(std::uint32_t lba) override {
        unchanged();const auto& track=locate(lba,true);
        std::array<std::uint8_t,2352> bytes{};frame(track,lba,bytes.data(),bytes.size());
        AudioSector result{};
        for(unsigned i=0;i<result.size();++i) {
            const unsigned value=unsigned(bytes[i*2])|(unsigned(bytes[i*2+1])<<8);
            result[i]=static_cast<std::int16_t>(value<32768?int(value):int(value)-65536);
        }
        unchanged();return result;
    }
    const std::string& identity() const {return digest;}
};
}
std::shared_ptr<SectorProvider> detail::open_cue_provider(const std::string& image) {
    return std::make_shared<CueProvider>(image);
}
std::string detail::cue_sha256(const std::string& image) {return CueProvider(image).identity();}
}
