#include "pce/desktop_input.hpp"
#include "pce/runtime.hpp"
#include <SDL3/SDL.h>
#include <algorithm>
#include <array>
#include <charconv>
#include <filesystem>
#include <fstream>
#include <set>
#include <string_view>

namespace pce {
namespace {
constexpr std::array<std::string_view,12> actions={
    "i","ii","select","run","up","right","down","left","iii","iv","v","vi"};
constexpr std::array<SDL_GamepadButton,12> buttons={
    SDL_GAMEPAD_BUTTON_SOUTH,SDL_GAMEPAD_BUTTON_EAST,SDL_GAMEPAD_BUTTON_BACK,
    SDL_GAMEPAD_BUTTON_START,SDL_GAMEPAD_BUTTON_DPAD_UP,SDL_GAMEPAD_BUTTON_DPAD_RIGHT,
    SDL_GAMEPAD_BUTTON_DPAD_DOWN,SDL_GAMEPAD_BUTTON_DPAD_LEFT,
    SDL_GAMEPAD_BUTTON_WEST,SDL_GAMEPAD_BUTTON_NORTH,SDL_GAMEPAD_BUTTON_LEFT_SHOULDER,
    SDL_GAMEPAD_BUTTON_RIGHT_SHOULDER};
static_assert(SDL_SCANCODE_COUNT<=512 && SDL_GAMEPAD_BUTTON_COUNT<=32);
void default_buttons(DesktopInputSlot& slot) {
    for(unsigned n=0;n<buttons.size();++n)slot.gamepad_buttons[buttons[n]]=1u<<n;
}
std::uint16_t action(std::string_view name) {
    const auto found=std::find(actions.begin(),actions.end(),name);
    if(found==actions.end())throw Fault("unknown desktop input action");
    return static_cast<std::uint16_t>(1u<<(found-actions.begin()));
}
bool reserved(SDL_Scancode key) {
    return key==SDL_SCANCODE_ESCAPE || key==SDL_SCANCODE_SPACE || key==SDL_SCANCODE_F11;
}
SDL_GamepadButton named_button(const std::string& name) {
    // SDL mapping strings retain a/b/x/y spellings. Expose SDL3's positional
    // names too, which stay clear across Nintendo/Xbox/PlayStation labels.
    if(name=="south")return SDL_GAMEPAD_BUTTON_SOUTH;
    if(name=="east")return SDL_GAMEPAD_BUTTON_EAST;
    if(name=="west")return SDL_GAMEPAD_BUTTON_WEST;
    if(name=="north")return SDL_GAMEPAD_BUTTON_NORTH;
    return SDL_GetGamepadButtonFromString(name.c_str());
}
// This intentionally parses only the documented schema, with bounded strings,
// collections, exact unsigned integers, duplicate detection and no recursion.
struct Parser {
    std::string_view text;
    std::size_t pos=0;
    DesktopInputProfile result;
    std::set<unsigned> ports;
    std::set<unsigned> assigned_keys;
    std::set<unsigned> assigned_gamepads;
    [[noreturn]] void invalid() const {throw Fault("invalid desktop input profile JSON");}
    void ws() {while(pos<text.size() && (text[pos]==' ' || text[pos]=='\t' || text[pos]=='\r' || text[pos]=='\n'))++pos;}
    bool maybe(char c) {ws();if(pos==text.size() || text[pos]!=c)return false;++pos;return true;}
    void take(char c) {if(!maybe(c))invalid();}
    std::string str() {
        take('"');std::string value;
        while(pos<text.size()) {
            auto c=static_cast<unsigned char>(text[pos++]);
            if(c=='"')return value;
            if(c<32 || c>=127)invalid();
            if(c=='\\') {
                if(pos==text.size())invalid();
                c=static_cast<unsigned char>(text[pos++]);
                if(c=='u') {
                    unsigned code=0;
                    for(unsigned n=0;n<4;++n) {
                        if(pos==text.size())invalid();
                        const auto digit=text[pos++];
                        const unsigned hex=digit>='0' && digit<='9' ? digit-'0':
                            digit>='a' && digit<='f' ? digit-'a'+10:digit>='A' && digit<='F' ? digit-'A'+10:16;
                        if(hex==16)invalid();code=code*16+hex;
                    }
                    if(code<32 || code>=127)invalid();c=static_cast<unsigned char>(code);
                } else if(c!='"' && c!='\\' && c!='/')invalid();
            }
            if(value.size()==64)throw Fault("desktop input profile string exceeds64 bytes");
            value.push_back(static_cast<char>(c));
        }
        invalid();
    }
    unsigned number(unsigned maximum) {
        ws();const auto start=pos;
        while(pos<text.size() && text[pos]>='0' && text[pos]<='9')++pos;
        if(start==pos || (pos-start>1 && text[start]=='0'))invalid();
        unsigned value=0;
        const auto parsed=std::from_chars(text.data()+start,text.data()+pos,value);
        if(parsed.ec!=std::errc{} || value>maximum)throw Fault("desktop input profile integer out of range");
        return value;
    }
    template<class Function> void object(Function visit) {
        take('{');std::set<std::string> fields;
        if(maybe('}'))return;
        for(;;) {
            const auto key=str();
            if(!fields.insert(key).second)throw Fault("duplicate desktop input profile field");
            take(':');visit(key);
            if(maybe('}'))return;
            take(',');
        }
    }
    void keyboard(DesktopInputSlot& slot) {
        object([&](const std::string& name) {
            const auto mask=action(name);take('[');unsigned count=0;
            if(maybe(']'))return;
            for(;;) {
                if(++count>4)throw Fault("at most4 keyboard aliases per desktop action");
                const auto name=str();const auto key=SDL_GetScancodeFromName(name.c_str());
                if(key==SDL_SCANCODE_UNKNOWN || reserved(key))throw Fault("unknown or reserved desktop input key");
                if(!assigned_keys.insert(static_cast<unsigned>(key)).second)throw Fault("conflicting desktop keyboard binding");
                slot.keyboard[key]=mask;
                if(maybe(']'))return;
                take(',');
            }
        });
    }
    void gamepad(DesktopInputSlot& slot) {
        bool index=false,custom_buttons=false;
        object([&](const std::string& name) {
            if(name=="index") {
                const auto value=number(15);
                if(!assigned_gamepads.insert(value).second)throw Fault("conflicting desktop gamepad index");
                slot.gamepad_index=static_cast<int>(value);index=true;
            } else if(name=="deadzone")slot.deadzone=number(32767);
            else if(name=="buttons") {
                custom_buttons=true;
                object([&](const std::string& key) {
                    const auto mask=action(key);const auto button_name=str();
                    const auto button=named_button(button_name);
                    if(button<0 || button>=SDL_GAMEPAD_BUTTON_COUNT)throw Fault("unknown desktop gamepad button");
                    if(slot.gamepad_buttons[button])throw Fault("conflicting desktop gamepad binding");
                    slot.gamepad_buttons[button]=mask;
                });
            } else throw Fault("unknown desktop gamepad field");
        });
        if(!index)throw Fault("desktop gamepad requires explicit index");
        if(!custom_buttons)default_buttons(slot);
    }
    void slot() {
        DesktopInputSlot slot;bool has_port=false,has_keyboard=false,has_gamepad=false;unsigned port=0;
        object([&](const std::string& name) {
            if(name=="port") {port=number(4);has_port=true;}
            else if(name=="keyboard") {keyboard(slot);has_keyboard=true;}
            else if(name=="gamepad") {gamepad(slot);has_gamepad=true;}
            else throw Fault("unknown desktop input slot field");
        });
        if(!has_port || (!has_keyboard && !has_gamepad))throw Fault("desktop input slot requires port and keyboard or gamepad");
        if(!ports.insert(port).second)throw Fault("duplicate desktop input port");
        result.slots[port]=slot;
    }
    DesktopInputProfile parse() {
        bool format=false,schema=false,slots=false;
        object([&](const std::string& name) {
            if(name=="format") {if(str()!="pce-desktop-input-1")throw Fault("unsupported desktop input format");format=true;}
            else if(name=="schema") {if(number(1)!=1)throw Fault("unsupported desktop input schema");schema=true;}
            else if(name=="slots") {
                slots=true;take('[');
                if(maybe(']'))return;
                for(unsigned count=0;;++count) {
                    if(count==5)throw Fault("desktop input supports five slots");
                    slot();if(maybe(']'))return;take(',');
                }
            } else throw Fault("unknown desktop input profile field");
        });
        ws();if(pos!=text.size() || !format || !schema || !slots)invalid();
        return result;
    }
};
} // namespace
DesktopInputProfile default_desktop_input_profile() {
    DesktopInputProfile profile;auto& slot=profile.slots[0];slot.gamepad_index=0;
    default_buttons(slot);
    constexpr std::array<SDL_Scancode,12> keys={SDL_SCANCODE_Z,SDL_SCANCODE_X,SDL_SCANCODE_LSHIFT,
        SDL_SCANCODE_RETURN,SDL_SCANCODE_UP,SDL_SCANCODE_RIGHT,SDL_SCANCODE_DOWN,SDL_SCANCODE_LEFT,
        SDL_SCANCODE_A,SDL_SCANCODE_S,SDL_SCANCODE_D,SDL_SCANCODE_F};
    for(unsigned n=0;n<keys.size();++n)slot.keyboard[keys[n]]=1u<<n;
    slot.keyboard[SDL_SCANCODE_RSHIFT]=4;
    slot.keyboard[SDL_SCANCODE_KP_8]=16;slot.keyboard[SDL_SCANCODE_KP_6]=32;
    slot.keyboard[SDL_SCANCODE_KP_2]=64;slot.keyboard[SDL_SCANCODE_KP_4]=128;
    return profile;
}
DesktopInputProfile read_desktop_input_profile(const std::string& path) {
    const auto file_path=std::filesystem::path(std::u8string(reinterpret_cast<const char8_t*>(path.c_str())));
    std::ifstream file(file_path,std::ios::binary);
    if(!file)throw Fault("cannot open desktop input profile");
    std::string contents;char ch;
    while(file.get(ch)) {
        if(contents.size()==16384)throw Fault("desktop input profile exceeds16 KiB");
        contents.push_back(ch);
    }
    if(!file.eof())throw Fault("cannot read desktop input profile");
    return Parser{contents}.parse();
}
} // namespace pce
