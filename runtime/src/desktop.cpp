#include "pce/desktop.hpp"
#include "pce/runtime.hpp"
#include <SDL3/SDL.h>
#include <algorithm>
#include <array>
#include <cstdio>
#include <filesystem>
#include <limits>
#include <memory>

namespace pce {
namespace {
constexpr std::uint64_t MASTER_CLOCK=21477273, SECOND_NS=1000000000;
constexpr unsigned MAX_CAPTURE_PIXELS=4194304;
void checked(bool good,const char* operation) {
    if(!good) throw Fault(std::string(operation)+": "+SDL_GetError());
}
std::uint16_t key_mask(SDL_Scancode key) {
    switch(key) {
    case SDL_SCANCODE_Z:return 1;
    case SDL_SCANCODE_X:return 2;
    case SDL_SCANCODE_LSHIFT:case SDL_SCANCODE_RSHIFT:return 4;
    case SDL_SCANCODE_RETURN:return 8;
    case SDL_SCANCODE_UP:case SDL_SCANCODE_KP_8:return 16;
    case SDL_SCANCODE_RIGHT:case SDL_SCANCODE_KP_6:return 32;
    case SDL_SCANCODE_DOWN:case SDL_SCANCODE_KP_2:return 64;
    case SDL_SCANCODE_LEFT:case SDL_SCANCODE_KP_4:return 128;
    case SDL_SCANCODE_A:return 256;
    case SDL_SCANCODE_S:return 512;
    case SDL_SCANCODE_D:return 1024;
    case SDL_SCANCODE_F:return 2048;
    default:return 0;
    }
}
constexpr std::array<SDL_GamepadButton,12> GAMEPAD_BUTTONS={
    SDL_GAMEPAD_BUTTON_SOUTH,SDL_GAMEPAD_BUTTON_EAST,SDL_GAMEPAD_BUTTON_BACK,
    SDL_GAMEPAD_BUTTON_START,SDL_GAMEPAD_BUTTON_DPAD_UP,SDL_GAMEPAD_BUTTON_DPAD_RIGHT,
    SDL_GAMEPAD_BUTTON_DPAD_DOWN,SDL_GAMEPAD_BUTTON_DPAD_LEFT,
    SDL_GAMEPAD_BUTTON_WEST,SDL_GAMEPAD_BUTTON_NORTH,SDL_GAMEPAD_BUTTON_LEFT_SHOULDER,
    SDL_GAMEPAD_BUTTON_RIGHT_SHOULDER};
std::uint16_t gamepad_button_mask(SDL_GamepadButton button) {
    for(unsigned n=0;n<GAMEPAD_BUTTONS.size();++n)if(button==GAMEPAD_BUTTONS[n])return 1u<<n;
    return 0;
}
}
struct DesktopHost::Impl {
    SDL_Window* window=nullptr;
    SDL_Renderer* renderer=nullptr;
    SDL_Texture* texture=nullptr;
    SDL_Gamepad* gamepad=nullptr;
    unsigned width=0,height=0;
    bool initialized=false,quit=false,paused=false,focused=false,paced=true,anchor=false;
    std::array<bool,SDL_SCANCODE_COUNT> keys{};
    std::array<unsigned,12> keyboard_pending{},gamepad_pending{};
    std::uint16_t pressed=0;
    std::uint64_t anchor_tick=0,anchor_ns=0;
    std::string title;
    DesktopStats stats;
    void pulse(std::array<unsigned,12>& pending,std::uint16_t mask) {
        // An event can arrive just before a frame completes. Two boundaries
        // preserve one full subsequent frame even if down/up share this poll.
        for(unsigned n=0;n<pending.size();++n)if(mask&(1u<<n))pending[n]=2;
        if(mask)++stats.input_pulses;
    }
    void clear_pending() {keyboard_pending.fill(0);gamepad_pending.fill(0);}
    void completed_frame() {
        for(auto* pending:{&keyboard_pending,&gamepad_pending})
            for(auto& frames:*pending)if(frames)--frames;
    }
    std::uint16_t pulse_mask() const {
        std::uint16_t value=0;
        for(unsigned n=0;n<keyboard_pending.size();++n)
            if(keyboard_pending[n] || gamepad_pending[n])value|=1u<<n;
        return value;
    }
    ~Impl() {
        if(gamepad)SDL_CloseGamepad(gamepad);
        if(texture)SDL_DestroyTexture(texture);
        if(renderer)SDL_DestroyRenderer(renderer);
        if(window)SDL_DestroyWindow(window);
        if(initialized)SDL_QuitSubSystem(SDL_INIT_VIDEO|SDL_INIT_GAMEPAD);
    }
    void open_gamepad() {
        if(gamepad && SDL_GamepadConnected(gamepad))return;
        if(gamepad){SDL_CloseGamepad(gamepad);gamepad=nullptr;gamepad_pending.fill(0);}
        int count=0;
        auto* ids=SDL_GetGamepads(&count);
        if(!ids)throw Fault(std::string("enumerate gamepads: ")+SDL_GetError());
        for(int n=0;n<count && !gamepad;++n)gamepad=SDL_OpenGamepad(ids[n]);
        SDL_free(ids);
        if(gamepad)++stats.gamepad_connections;
    }
    std::uint16_t gamepad_mask() const {
        if(!gamepad || !SDL_GamepadConnected(gamepad))return 0;
        std::uint16_t value=0;
        for(unsigned n=0;n<GAMEPAD_BUTTONS.size();++n)if(SDL_GetGamepadButton(gamepad,GAMEPAD_BUTTONS[n]))value|=1u<<n;
        constexpr int DEADZONE=16000;
        const int x=SDL_GetGamepadAxis(gamepad,SDL_GAMEPAD_AXIS_LEFTX);
        const int y=SDL_GetGamepadAxis(gamepad,SDL_GAMEPAD_AXIS_LEFTY);
        if(x>DEADZONE)value|=32;
        if(x<-DEADZONE)value|=128;
        if(y>DEADZONE)value|=64;
        if(y<-DEADZONE)value|=16;
        return value;
    }
    void draw() {
        if(texture) {
            int output_width=0,output_height=0;
            checked(SDL_GetRenderOutputSize(renderer,&output_width,&output_height),"query desktop output size");
            const auto mode=output_width<static_cast<int>(width) || output_height<static_cast<int>(height) ?
                SDL_LOGICAL_PRESENTATION_LETTERBOX:SDL_LOGICAL_PRESENTATION_INTEGER_SCALE;
            checked(SDL_SetRenderLogicalPresentation(renderer,static_cast<int>(width),static_cast<int>(height),mode),
                    "set desktop letterbox");
        }
        checked(SDL_SetRenderDrawColor(renderer,0,0,0,255),"set clear color");
        checked(SDL_RenderClear(renderer),"clear desktop target");
        if(texture)checked(SDL_RenderTexture(renderer,texture,nullptr,nullptr),"draw desktop frame");
    }
};

DesktopHost::DesktopHost(const DesktopOptions& options):impl_(std::make_unique<Impl>()) {
    if(options.scale==0 || options.scale>6 || options.title.size()>256)
        throw Fault("desktop scale/title out of range");
    auto& p=*impl_;
    p.title=options.title;p.paced=options.paced;
    checked(SDL_InitSubSystem(SDL_INIT_VIDEO|SDL_INIT_GAMEPAD),"initialize SDL desktop");
    p.initialized=true;
    const SDL_WindowFlags flags=SDL_WINDOW_RESIZABLE|SDL_WINDOW_HIGH_PIXEL_DENSITY|
        (options.hidden ? SDL_WINDOW_HIDDEN:0);
    p.window=SDL_CreateWindow(p.title.c_str(),static_cast<int>(256*options.scale),static_cast<int>(240*options.scale),flags);
    checked(p.window!=nullptr,"create desktop window");
    p.renderer=SDL_CreateRenderer(p.window,nullptr);
    checked(p.renderer!=nullptr,"create desktop renderer");
    // Guest rate is paced from its master clock, never the monitor refresh.
    checked(SDL_SetRenderVSync(p.renderer,0),"disable renderer vsync");
    checked(SDL_SetWindowMinimumSize(p.window,128,120),"set minimum window size");
    p.focused=(SDL_GetWindowFlags(p.window)&SDL_WINDOW_INPUT_FOCUS)!=0;
    p.open_gamepad();
}
DesktopHost::~DesktopHost()=default;
bool DesktopHost::poll() {
    auto& p=*impl_;++p.stats.polls;
    SDL_Event event;
    while(SDL_PollEvent(&event)) {
        if(event.type==SDL_EVENT_QUIT)p.quit=true;
        else if(event.type==SDL_EVENT_GAMEPAD_ADDED || event.type==SDL_EVENT_GAMEPAD_REMOVED)p.open_gamepad();
        else if((event.type==SDL_EVENT_GAMEPAD_BUTTON_DOWN || event.type==SDL_EVENT_GAMEPAD_BUTTON_UP) &&
                p.gamepad && event.gbutton.which==SDL_GetGamepadID(p.gamepad)) {
            ++p.stats.gamepad_events;
            if(event.type==SDL_EVENT_GAMEPAD_BUTTON_DOWN && p.focused && !p.paused)
                p.pulse(p.gamepad_pending,gamepad_button_mask(static_cast<SDL_GamepadButton>(event.gbutton.button)));
        }
        else if(event.type==SDL_EVENT_WINDOW_CLOSE_REQUESTED && event.window.windowID==window_id())p.quit=true;
        else if(event.type==SDL_EVENT_WINDOW_FOCUS_LOST && event.window.windowID==window_id()) {
            p.focused=false;p.keys.fill(false);p.pressed=0;p.clear_pending();++p.stats.focus_losses;
        } else if(event.type==SDL_EVENT_WINDOW_FOCUS_GAINED && event.window.windowID==window_id())p.focused=true;
        else if((event.type==SDL_EVENT_WINDOW_PIXEL_SIZE_CHANGED || event.type==SDL_EVENT_WINDOW_EXPOSED) && event.window.windowID==window_id()) {
            if(event.type==SDL_EVENT_WINDOW_PIXEL_SIZE_CHANGED)++p.stats.resize_events;
            // Redraw the retained texture even when guest execution is paused.
            p.draw();checked(SDL_RenderPresent(p.renderer),"refresh desktop window");
        }
        else if((event.type==SDL_EVENT_KEY_DOWN || event.type==SDL_EVENT_KEY_UP) && event.key.windowID==window_id() && p.focused) {
            ++p.stats.keyboard_events;
            const auto key=event.key.scancode;
            if(key>=0 && key<SDL_SCANCODE_COUNT)p.keys[static_cast<unsigned>(key)]=event.key.down;
            if(event.key.down && !event.key.repeat) {
                const auto mask=key_mask(key);
                if(!p.paused)p.pulse(p.keyboard_pending,mask);
                if(!mask && key!=SDL_SCANCODE_ESCAPE && key!=SDL_SCANCODE_SPACE && key!=SDL_SCANCODE_F11) {
                    ++p.stats.unmapped_key_down;
                    p.stats.last_unmapped_scancode=static_cast<std::uint32_t>(key);
                }
                if(key==SDL_SCANCODE_ESCAPE)p.quit=true;
                else if(key==SDL_SCANCODE_SPACE) {
                    p.paused=!p.paused;p.anchor=false;p.clear_pending();
                    checked(SDL_SetWindowTitle(p.window,(p.title+(p.paused ? " [Paused]":"")).c_str()),"update pause title");
                } else if(key==SDL_SCANCODE_F11) {
                    const bool full=(SDL_GetWindowFlags(p.window)&SDL_WINDOW_FULLSCREEN)!=0;
                    checked(SDL_SetWindowFullscreen(p.window,!full),"toggle fullscreen");
                }
            }
        }
    }
    p.pressed=0;
    if(p.focused && !p.paused) {
        for(unsigned n=0;n<p.keys.size();++n)if(p.keys[n])p.pressed|=key_mask(static_cast<SDL_Scancode>(n));
        p.pressed|=p.gamepad_mask();
    }
    if(p.paused)SDL_Delay(5);
    return !p.quit;
}
bool DesktopHost::paused() const{return impl_->paused;}
std::uint16_t DesktopHost::buttons() const {
    const auto& p=*impl_;
    return p.focused && !p.paused ? p.pressed|p.pulse_mask():0;
}
bool DesktopHost::checkpoint_input_quiescent() const {
    const auto& p=*impl_;
    if(p.pulse_mask() || p.gamepad_mask())return false;
    for(unsigned n=0;n<p.keys.size();++n)if(p.keys[n] && key_mask(static_cast<SDL_Scancode>(n)))return false;
    return true;
}
void DesktopHost::present(const VideoFrame& frame) {
    if(frame.width==0 || frame.width>1024 || frame.height==0 || frame.height>512 ||
       frame.rgb.size()!=static_cast<std::size_t>(frame.width)*frame.height*3)
        throw Fault("invalid desktop RGB frame");
    auto& p=*impl_;
    if(frame.width!=p.width || frame.height!=p.height) {
        if(p.texture){SDL_DestroyTexture(p.texture);p.texture=nullptr;}
        p.texture=SDL_CreateTexture(p.renderer,SDL_PIXELFORMAT_RGB24,SDL_TEXTUREACCESS_STREAMING,
                                   static_cast<int>(frame.width),static_cast<int>(frame.height));
        checked(p.texture!=nullptr,"create desktop streaming texture");
        checked(SDL_SetTextureScaleMode(p.texture,SDL_SCALEMODE_NEAREST),"select nearest pixels");
        checked(SDL_SetTextureBlendMode(p.texture,SDL_BLENDMODE_NONE),"disable texture blending");
        checked(SDL_SetRenderLogicalPresentation(p.renderer,static_cast<int>(frame.width),static_cast<int>(frame.height),
                                                SDL_LOGICAL_PRESENTATION_INTEGER_SCALE),"set integer letterbox");
        p.width=frame.width;p.height=frame.height;
    }
    checked(SDL_UpdateTexture(p.texture,nullptr,frame.rgb.data(),static_cast<int>(frame.width*3)),"upload desktop frame");
    p.draw();checked(SDL_RenderPresent(p.renderer),"present desktop frame");++p.stats.presented;
    p.completed_frame();
}
void DesktopHost::reset_pacing() {impl_->anchor=false;}
void DesktopHost::pace(std::uint64_t ticks) {
    auto& p=*impl_;
    if(!p.paced)return;
    const auto now=SDL_GetTicksNS();
    if(!p.anchor || ticks<p.anchor_tick || p.paused) {
        p.anchor=true;p.anchor_tick=ticks;p.anchor_ns=now;return;
    }
    const auto delta=ticks-p.anchor_tick;
    // Rebase after a long debugger stop/host stall or impossible caller jump.
    if(delta/MASTER_CLOCK>3600) {
        p.anchor_tick=ticks;p.anchor_ns=now;++p.stats.pacing_resets;return;
    }
    const auto elapsed=(delta/MASTER_CLOCK)*SECOND_NS+(delta%MASTER_CLOCK)*SECOND_NS/MASTER_CLOCK;
    const auto target=p.anchor_ns+elapsed;
    if(now>target && now-target>SECOND_NS/4) {
        p.anchor_tick=ticks;p.anchor_ns=now;++p.stats.pacing_resets;
    } else if(target>now)SDL_DelayNS(std::min<std::uint64_t>(target-now,SECOND_NS/10));
}
VideoFrame DesktopHost::readback() {
    auto& p=*impl_;
    int width=0,height=0;
    checked(SDL_GetRenderOutputSize(p.renderer,&width,&height),"query desktop output size");
    if(width<=0 || height<=0 || static_cast<std::uint64_t>(width)*height>MAX_CAPTURE_PIXELS)
        throw Fault("desktop capture exceeds four-million-pixel limit");
    p.draw();
    // SDL readback clips to the current logical viewport. Disable coordinates
    // after drawing so the capture includes the complete window/black bars.
    checked(SDL_SetRenderLogicalPresentation(p.renderer,0,0,SDL_LOGICAL_PRESENTATION_DISABLED),
            "select full desktop capture viewport");
    using Surface=std::unique_ptr<SDL_Surface,decltype(&SDL_DestroySurface)>;
    Surface raw(SDL_RenderReadPixels(p.renderer,nullptr),SDL_DestroySurface);
    checked(raw!=nullptr,"read desktop target");
    Surface rgb(SDL_ConvertSurface(raw.get(),SDL_PIXELFORMAT_RGB24),SDL_DestroySurface);
    checked(rgb!=nullptr,"convert desktop capture");
    if(rgb->w<=0 || rgb->h<=0 || static_cast<std::uint64_t>(rgb->w)*rgb->h>MAX_CAPTURE_PIXELS)
        throw Fault("invalid desktop readback dimensions");
    VideoFrame result{static_cast<unsigned>(rgb->w),static_cast<unsigned>(rgb->h),{}};
    result.rgb.resize(static_cast<std::size_t>(result.width)*result.height*3);
    checked(SDL_LockSurface(rgb.get()),"lock desktop capture");
    for(unsigned y=0;y<result.height;++y)
        std::copy_n(static_cast<const std::uint8_t*>(rgb->pixels)+static_cast<std::size_t>(y)*rgb->pitch,
                    result.width*3,result.rgb.data()+static_cast<std::size_t>(y)*result.width*3);
    SDL_UnlockSurface(rgb.get());
    checked(SDL_RenderPresent(p.renderer),"present captured desktop frame");
    return result;
}
void DesktopHost::capture(const std::string& path) {
    const auto frame=readback();
    const auto file_path=std::filesystem::path(std::u8string(reinterpret_cast<const char8_t*>(path.c_str())));
    // C11 exclusive creation rejects an existing file, including a race after
    // CLI validation. No supplied input or previous capture is overwritten.
#ifdef _WIN32
    auto* file=_wfopen(file_path.c_str(),L"wbx");
#else
    auto* file=std::fopen(file_path.c_str(),"wbx");
#endif
    if(!file)throw Fault("cannot create new desktop capture");
    const auto written=std::fprintf(file,"P6\n%u %u\n255\n",frame.width,frame.height);
    const bool good=written>0 && std::fwrite(frame.rgb.data(),1,frame.rgb.size(),file)==frame.rgb.size();
    const bool closed=std::fclose(file)==0;
    if(!good || !closed)throw Fault("cannot write desktop capture");
}
std::uint32_t DesktopHost::window_id() const{return SDL_GetWindowID(impl_->window);}
const DesktopStats& DesktopHost::stats() const{return impl_->stats;}
} // namespace pce
