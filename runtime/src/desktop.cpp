#include "pce/desktop.hpp"
#include "pce/desktop_input.hpp"
#include "pce/runtime.hpp"
#include <SDL3/SDL.h>
#if SDL_VERSION_ATLEAST(3,4,0)
#include "pce/display_shader_data.hpp"
#endif
#include <algorithm>
#include <array>
#include <cstdio>
#include <filesystem>
#include <limits>
#include <memory>
#include <optional>

namespace pce {
namespace {
constexpr std::uint64_t MASTER_CLOCK=21477273, SECOND_NS=1000000000;
constexpr unsigned MAX_CAPTURE_PIXELS=4194304;
constexpr unsigned MAX_DISPLAY_PIXELS=16*1024*1024;
void checked(bool good,const char* operation) {
    if(!good) throw Fault(std::string(operation)+": "+SDL_GetError());
}
}
struct DesktopHost::Impl {
    SDL_Window* window=nullptr;
    SDL_Renderer* renderer=nullptr;
    SDL_Texture* texture=nullptr;
    std::array<SDL_Gamepad*,5> gamepads{};
    DesktopInputProfile input;
    unsigned width=0,height=0;
    bool initialized=false,quit=false,paused=false,focused=false,paced=true,anchor=false;
    std::array<bool,SDL_SCANCODE_COUNT> keys{};
    std::array<std::array<unsigned,12>,5> keyboard_pending{},gamepad_pending{};
    std::array<std::uint16_t,5> pressed{};
    std::uint64_t anchor_tick=0,anchor_ns=0;
    std::string title;
    DesktopStats stats;
    DisplayMode display_mode=DisplayMode::integer;
    SDL_ScaleMode filter=SDL_SCALEMODE_NEAREST;
    std::optional<DesktopSettings> display_backup;
    std::uint64_t display_deadline=0;
    ShaderParameters shader_parameters;
    DisplayShader effect=DisplayShader::off;
    std::array<bool,SDL_SCANCODE_COUNT> confirmation_keys{};
    DesktopExtent windowed_extent{256,240};
#if SDL_VERSION_ATLEAST(3,4,0)
    SDL_GPUDevice* gpu=nullptr;
    SDL_GPUShader* shader=nullptr;
    SDL_GPURenderState* shader_state=nullptr;
#endif
    void pulse(std::array<unsigned,12>& pending,std::uint16_t mask) {
        // An event can arrive just before a frame completes. Two boundaries
        // preserve one full subsequent frame even if down/up share this poll.
        for(unsigned n=0;n<pending.size();++n)if(mask&(1u<<n))pending[n]=2;
        if(mask)++stats.input_pulses;
    }
    std::uint16_t key_mask(unsigned slot,SDL_Scancode key) const {
        return key>=0 && static_cast<unsigned>(key)<input.slots[slot].keyboard.size() ? input.slots[slot].keyboard[key]:0;
    }
    void clear_pending() {for(auto* source:{&keyboard_pending,&gamepad_pending})for(auto& slot:*source)slot.fill(0);}
    void completed_frame() {
        for(auto* pending:{&keyboard_pending,&gamepad_pending})
            for(auto& slot:*pending)for(auto& frames:slot)if(frames)--frames;
    }
    std::uint16_t pulse_mask(unsigned slot) const {
        std::uint16_t value=0;
        for(unsigned n=0;n<keyboard_pending[slot].size();++n)
            if(keyboard_pending[slot][n] || gamepad_pending[slot][n])value|=1u<<n;
        return value;
    }
    ~Impl() {
        for(auto* gamepad:gamepads)if(gamepad)SDL_CloseGamepad(gamepad);
#if SDL_VERSION_ATLEAST(3,4,0)
        if(gpu && renderer) {
            SDL_FlushRenderer(renderer);
            SDL_WaitForGPUIdle(gpu);
        }
#endif
        if(texture)SDL_DestroyTexture(texture);
#if SDL_VERSION_ATLEAST(3,4,0)
        if(shader_state)SDL_DestroyGPURenderState(shader_state);
        if(shader)SDL_ReleaseGPUShader(gpu,shader);
#endif
        if(renderer)SDL_DestroyRenderer(renderer);
#if SDL_VERSION_ATLEAST(3,4,0)
        if(gpu)SDL_DestroyGPUDevice(gpu);
#endif
        if(window)SDL_DestroyWindow(window);
        if(initialized)SDL_QuitSubSystem(SDL_INIT_VIDEO|SDL_INIT_GAMEPAD);
    }
    void open_gamepad() {
        for(unsigned slot=0;slot<gamepads.size();++slot) {
            auto*& gamepad=gamepads[slot];
            if(gamepad && !SDL_GamepadConnected(gamepad)) {
                SDL_CloseGamepad(gamepad);gamepad=nullptr;gamepad_pending[slot].fill(0);
            }
        }
        int count=0;
        auto* ids=SDL_GetGamepads(&count);
        if(!ids)throw Fault(std::string("enumerate gamepads: ")+SDL_GetError());
        std::sort(ids,ids+count);
        for(unsigned slot=0;slot<gamepads.size();++slot) {
            const auto index=input.slots[slot].gamepad_index;
            if(gamepads[slot] || index<0 || index>=count)continue;
            const auto id=ids[index];bool assigned=false;
            for(auto* pad:gamepads)if(pad && SDL_GetGamepadID(pad)==id)assigned=true;
            if(assigned)continue;
            gamepads[slot]=SDL_OpenGamepad(id);
            if(!gamepads[slot]){SDL_free(ids);throw Fault(std::string("open selected gamepad: ")+SDL_GetError());}
            ++stats.gamepad_connections;
        }
        SDL_free(ids);
    }
    std::uint16_t gamepad_mask(unsigned slot) const {
        const auto* profile=&input.slots[slot];auto* gamepad=gamepads[slot];
        if(!gamepad || !SDL_GamepadConnected(gamepad))return 0;
        std::uint16_t value=0;
        for(unsigned n=0;n<SDL_GAMEPAD_BUTTON_COUNT;++n)
            if(SDL_GetGamepadButton(gamepad,static_cast<SDL_GamepadButton>(n)))value|=profile->gamepad_buttons[n];
        const auto deadzone=static_cast<int>(profile->deadzone);
        const int x=SDL_GetGamepadAxis(gamepad,SDL_GAMEPAD_AXIS_LEFTX);
        const int y=SDL_GetGamepadAxis(gamepad,SDL_GAMEPAD_AXIS_LEFTY);
        if(x>deadzone)value|=32;
        if(x<-deadzone)value|=128;
        if(y>deadzone)value|=64;
        if(y<-deadzone)value|=16;
        return value;
    }
    void draw() {
        if(texture) {
            int output_width=0,output_height=0;
            checked(SDL_GetRenderOutputSize(renderer,&output_width,&output_height),"query desktop output size");
            int logical_width=static_cast<int>(width), logical_height=static_cast<int>(height);
            auto mode=SDL_LOGICAL_PRESENTATION_LETTERBOX;
            switch(display_mode) {
            case DisplayMode::integer:
                if(output_width>=logical_width && output_height>=logical_height)
                    mode=SDL_LOGICAL_PRESENTATION_INTEGER_SCALE;
                break;
            case DisplayMode::square:break;
            case DisplayMode::four_three:logical_width=4;logical_height=3;break;
            case DisplayMode::sixteen_nine:logical_width=16;logical_height=9;break;
            }
            checked(SDL_SetRenderLogicalPresentation(renderer,logical_width,logical_height,mode),
                    "set desktop letterbox");
        }
        checked(SDL_SetRenderDrawColor(renderer,0,0,0,255),"set clear color");
        checked(SDL_RenderClear(renderer),"clear desktop target");
        if(!texture)return;
#if SDL_VERSION_ATLEAST(3,4,0)
        if(shader_state)checked(SDL_SetGPURenderState(renderer,shader_state),"bind display shader");
#endif
        checked(SDL_RenderTexture(renderer,texture,nullptr,nullptr),"draw desktop frame");
#if SDL_VERSION_ATLEAST(3,4,0)
        if(shader_state)checked(SDL_SetGPURenderState(renderer,nullptr),"unbind display shader");
#endif
    }
    void create_renderer(DisplayShader selected) {
        effect=selected;
        if(effect==DisplayShader::off) {
            renderer=SDL_CreateRenderer(window,nullptr);
            checked(renderer!=nullptr,"create desktop renderer");
            return;
        }
#if SDL_VERSION_ATLEAST(3,4,0)
        gpu=SDL_CreateGPUDevice(SDL_GPU_SHADERFORMAT_SPIRV|SDL_GPU_SHADERFORMAT_DXIL,false,nullptr);
        checked(gpu!=nullptr,"create display shader device");
        renderer=SDL_CreateGPURenderer(gpu,window);
        checked(renderer!=nullptr,"create display shader renderer");
        const bool spirv=(SDL_GetGPUShaderFormats(gpu)&SDL_GPU_SHADERFORMAT_SPIRV)!=0;
        SDL_GPUShaderCreateInfo description{};
        description.code=spirv ? display_shader::spirv:display_shader::dxil;
        description.code_size=spirv ? sizeof(display_shader::spirv):sizeof(display_shader::dxil);
        description.entrypoint="main";
        description.format=spirv ? SDL_GPU_SHADERFORMAT_SPIRV:SDL_GPU_SHADERFORMAT_DXIL;
        description.stage=SDL_GPU_SHADERSTAGE_FRAGMENT;
        description.num_samplers=1;
        description.num_uniform_buffers=1;
        shader=SDL_CreateGPUShader(gpu,&description);
        checked(shader!=nullptr,"create display shader");
        SDL_GPURenderStateCreateInfo state{};
        state.fragment_shader=shader;
        shader_state=SDL_CreateGPURenderState(renderer,&state);
        checked(shader_state!=nullptr,"create display shader state");
        update_shader_parameters();
        filter=SDL_SCALEMODE_LINEAR;
#else
        throw Fault("Display shaders require SDL 3.4 or newer");
#endif
    }
    void update_shader_parameters() {
#if SDL_VERSION_ATLEAST(3,4,0)
        if(!shader_state)return;
        const std::array<float,12> uniforms{
            (effect==DisplayShader::crt || effect==DisplayShader::crt_mask) ? 1.0f:0.0f,
            effect==DisplayShader::smooth ? 1.0f:0.0f,
            effect==DisplayShader::lcd ? 1.0f:0.0f,
            effect==DisplayShader::mono ? 1.0f:effect==DisplayShader::crt_mask ? 2.0f:0.0f,
            shader_parameters.scanline/100.0f,shader_parameters.mask/100.0f,
            shader_parameters.grid/100.0f,shader_parameters.vignette/100.0f,
            shader_parameters.brightness/100.0f,shader_parameters.saturation/100.0f,0.0f,0.0f,
        };
        checked(SDL_SetGPURenderStateFragmentUniforms(shader_state,0,uniforms.data(),sizeof(uniforms)),
                "set display shader uniforms");
#endif
    }
    DesktopSettings settings() const {
        int width=0,height=0;checked(SDL_GetWindowSize(window,&width,&height),"query display window size");
        const bool full=(SDL_GetWindowFlags(window)&SDL_WINDOW_FULLSCREEN)!=0;
        if(full){width=static_cast<int>(windowed_extent.width);height=static_cast<int>(windowed_extent.height);}
        return {static_cast<unsigned>(width),static_cast<unsigned>(height),
            full,display_mode,
            filter==SDL_SCALEMODE_LINEAR ? DisplayFilter::linear:DisplayFilter::nearest};
    }
    void apply_settings(const DesktopSettings& next) {
        const bool full=(SDL_GetWindowFlags(window)&SDL_WINDOW_FULLSCREEN)!=0;
        if(full!=next.fullscreen) {
            checked(SDL_SetWindowFullscreen(window,next.fullscreen),"request display fullscreen");
            checked(SDL_SyncWindow(window),"synchronize display fullscreen");
            if(((SDL_GetWindowFlags(window)&SDL_WINDOW_FULLSCREEN)!=0)!=next.fullscreen)
                throw Fault("window system refused fullscreen request");
        }
        if(!next.fullscreen) {
            if(SDL_GetWindowFlags(window)&SDL_WINDOW_MAXIMIZED) {
                checked(SDL_RestoreWindow(window),"restore maximized display window");
                checked(SDL_SyncWindow(window),"synchronize restored display window");
            }
            checked(SDL_SetWindowSize(window,static_cast<int>(next.width),static_cast<int>(next.height)),"request display size");
            checked(SDL_SyncWindow(window),"synchronize display size");
            int actual_width=0,actual_height=0;
            checked(SDL_GetWindowSize(window,&actual_width,&actual_height),"query applied display size");
            if(actual_width!=static_cast<int>(next.width) || actual_height!=static_cast<int>(next.height))
                throw Fault("window system refused display size request");
        }
        windowed_extent={next.width,next.height};
        display_mode=next.mode;
        filter=next.filter==DisplayFilter::linear ? SDL_SCALEMODE_LINEAR:SDL_SCALEMODE_NEAREST;
#if SDL_VERSION_ATLEAST(3,4,0)
        if(shader_state)filter=SDL_SCALEMODE_LINEAR;
#endif
        if(texture)checked(SDL_SetTextureScaleMode(texture,filter),"set display filter");
        draw();checked(SDL_RenderPresent(renderer),"redraw display settings");
    }
    void commit_display() {
        checked(SDL_SetWindowTitle(window,(title+(paused ? " [Paused]":"")).c_str()),"restore display title");
        display_backup.reset();display_deadline=0;
    }
};

DesktopHost::DesktopHost(const DesktopOptions& options):impl_(std::make_unique<Impl>()) {
    if(!options.shader_parameters.valid())throw Fault("shader percentage out of range");
    if(options.scale==0 || options.scale>6 || options.title.size()>256)
        throw Fault("desktop scale/title out of range");
    auto& p=*impl_;
    p.shader_parameters=options.shader_parameters;
    p.windowed_extent={256*options.scale,240*options.scale};
    p.input=options.input_profile.empty() ? default_desktop_input_profile():read_desktop_input_profile(options.input_profile);
    p.title=options.title;p.paced=options.paced;
    p.display_mode=options.display_mode;
    p.filter=options.display_filter==DisplayFilter::linear ? SDL_SCALEMODE_LINEAR:SDL_SCALEMODE_NEAREST;
    checked(SDL_InitSubSystem(SDL_INIT_VIDEO|SDL_INIT_GAMEPAD),"initialize SDL desktop");
    p.initialized=true;
    const SDL_WindowFlags flags=SDL_WINDOW_RESIZABLE|SDL_WINDOW_HIGH_PIXEL_DENSITY|
        (options.hidden ? SDL_WINDOW_HIDDEN:0)|(options.fullscreen ? SDL_WINDOW_FULLSCREEN:0);
    p.window=SDL_CreateWindow(p.title.c_str(),static_cast<int>(256*options.scale),static_cast<int>(240*options.scale),flags);
    checked(p.window!=nullptr,"create desktop window");
    p.create_renderer(options.display_shader);
    // Guest rate is paced from its master clock, never the monitor refresh.
    checked(SDL_SetRenderVSync(p.renderer,0),"disable renderer vsync");
    checked(SDL_SetWindowMinimumSize(p.window,128,120),"set minimum window size");
    p.focused=(SDL_GetWindowFlags(p.window)&SDL_WINDOW_INPUT_FOCUS)!=0;
    p.open_gamepad();
}
DesktopHost::~DesktopHost()=default;
bool DesktopHost::poll() {
    auto& p=*impl_;++p.stats.polls;
    bool display_prompt_seen=p.display_backup.has_value();
    if(p.display_backup && SDL_GetTicks()>=p.display_deadline)cancel_display();
    SDL_Event event;
    while(SDL_PollEvent(&event)) {
        if(event.type==SDL_EVENT_QUIT)p.quit=true;
        else if(event.type==SDL_EVENT_GAMEPAD_ADDED || event.type==SDL_EVENT_GAMEPAD_REMOVED)p.open_gamepad();
        else if(event.type==SDL_EVENT_GAMEPAD_BUTTON_DOWN || event.type==SDL_EVENT_GAMEPAD_BUTTON_UP) {
            for(unsigned slot=0;slot<p.gamepads.size();++slot) {
                if(!p.gamepads[slot] || event.gbutton.which!=SDL_GetGamepadID(p.gamepads[slot]))continue;
                ++p.stats.gamepad_events;
                if(event.type==SDL_EVENT_GAMEPAD_BUTTON_DOWN && p.focused && !p.paused &&
                   event.gbutton.button<SDL_GAMEPAD_BUTTON_COUNT)
                    p.pulse(p.gamepad_pending[slot],p.input.slots[slot].gamepad_buttons[event.gbutton.button]);
            }
        }
        else if(event.type==SDL_EVENT_WINDOW_CLOSE_REQUESTED && event.window.windowID==window_id())p.quit=true;
        else if(event.type==SDL_EVENT_WINDOW_FOCUS_LOST && event.window.windowID==window_id()) {
            if(p.display_backup)cancel_display();
            p.focused=false;p.keys.fill(false);p.pressed.fill(0);p.clear_pending();++p.stats.focus_losses;
        } else if(event.type==SDL_EVENT_WINDOW_FOCUS_GAINED && event.window.windowID==window_id())p.focused=true;
        else if((event.type==SDL_EVENT_WINDOW_PIXEL_SIZE_CHANGED || event.type==SDL_EVENT_WINDOW_EXPOSED) && event.window.windowID==window_id()) {
            if(event.type==SDL_EVENT_WINDOW_PIXEL_SIZE_CHANGED)++p.stats.resize_events;
            // Redraw the retained texture even when guest execution is paused.
            p.draw();checked(SDL_RenderPresent(p.renderer),"refresh desktop window");
        }
        else if((event.type==SDL_EVENT_KEY_DOWN || event.type==SDL_EVENT_KEY_UP) && event.key.windowID==window_id() && p.focused) {
            const auto code=event.key.scancode;
            if(code>=0 && code<SDL_SCANCODE_COUNT && p.confirmation_keys[code]) {
                if(event.type==SDL_EVENT_KEY_UP)p.confirmation_keys[code]=false;
                continue;
            }
            if((p.display_backup || display_prompt_seen) && (event.key.scancode==SDL_SCANCODE_RETURN || event.key.scancode==SDL_SCANCODE_ESCAPE)) {
                if(event.type==SDL_EVENT_KEY_DOWN && !event.key.repeat) {
                    p.confirmation_keys[event.key.scancode]=true;
                    if(p.display_backup) {
                        if(event.key.scancode==SDL_SCANCODE_RETURN && SDL_GetTicks()<p.display_deadline)p.commit_display();
                        else cancel_display();
                    }
                    reset_input();
                }
                continue;
            }
            ++p.stats.keyboard_events;
            const auto key=event.key.scancode;
            if(key>=0 && key<SDL_SCANCODE_COUNT)p.keys[static_cast<unsigned>(key)]=event.key.down;
            if(event.key.down && !event.key.repeat) {
                std::uint16_t mask=0;
                for(unsigned slot=0;slot<p.input.slots.size();++slot) {
                    const auto selected=p.key_mask(slot,key);mask|=selected;
                    if(!p.paused)p.pulse(p.keyboard_pending[slot],selected);
                }
                if(!mask && key!=SDL_SCANCODE_ESCAPE && key!=SDL_SCANCODE_SPACE && key!=SDL_SCANCODE_F11) {
                    ++p.stats.unmapped_key_down;
                    p.stats.last_unmapped_scancode=static_cast<std::uint32_t>(key);
                }
                if(key==SDL_SCANCODE_ESCAPE)p.quit=true;
                else if(key==SDL_SCANCODE_SPACE) {
                    p.paused=!p.paused;p.anchor=false;p.clear_pending();
                    checked(SDL_SetWindowTitle(p.window,(p.title+(p.paused ? " [Paused]":"")).c_str()),"update pause title");
                } else if(key==SDL_SCANCODE_F11) {
                    if(p.display_backup)cancel_display();
                    else {auto next=display_settings();next.fullscreen=!next.fullscreen;preview_display(next);display_prompt_seen=true;}
                }
            }
        }
    }
    p.pressed.fill(0);
    if(p.focused && !p.paused) {
        for(unsigned slot=0;slot<p.input.slots.size();++slot) {
            for(unsigned n=0;n<p.keys.size();++n)if(p.keys[n])p.pressed[slot]|=p.key_mask(slot,static_cast<SDL_Scancode>(n));
            p.pressed[slot]|=p.gamepad_mask(slot);
        }
    }
    if(p.paused)SDL_Delay(5);
    return !p.quit;
}
bool DesktopHost::paused() const{return impl_->paused;}
std::uint16_t DesktopHost::buttons(unsigned slot) const {
    const auto& p=*impl_;
    if(slot>=p.input.slots.size())throw Fault("desktop input slot out of range");
    return p.focused && !p.paused ? p.pressed[slot]|p.pulse_mask(slot):0;
}
void DesktopHost::reset_input() {
    auto& p=*impl_;p.keys.fill(false);p.pressed.fill(0);p.clear_pending();
}
bool DesktopHost::checkpoint_input_quiescent() const {
    const auto& p=*impl_;
    for(unsigned slot=0;slot<p.input.slots.size();++slot) {
        if(p.pulse_mask(slot) || p.gamepad_mask(slot))return false;
        for(unsigned n=0;n<p.keys.size();++n)if(p.keys[n] && p.key_mask(slot,static_cast<SDL_Scancode>(n)))return false;
    }
    return true;
}
void DesktopHost::present(const VideoFrame& frame) {
    redraw(frame);
    ++impl_->stats.presented;
    impl_->completed_frame();
}
void DesktopHost::redraw(const VideoFrame& frame) {
    const auto pixels=static_cast<std::uint64_t>(frame.width)*frame.height;
    if(!pixels || pixels>MAX_DISPLAY_PIXELS || frame.width>8192 || frame.height>8192 ||
       frame.rgb.size()!=pixels*3)
        throw Fault("invalid desktop RGB frame");
    auto& p=*impl_;
    if(frame.width!=p.width || frame.height!=p.height) {
        if(p.texture){SDL_DestroyTexture(p.texture);p.texture=nullptr;}
        p.texture=SDL_CreateTexture(p.renderer,SDL_PIXELFORMAT_RGB24,SDL_TEXTUREACCESS_STREAMING,
                                   static_cast<int>(frame.width),static_cast<int>(frame.height));
        checked(p.texture!=nullptr,"create desktop streaming texture");
        checked(SDL_SetTextureScaleMode(p.texture,p.filter),"select display texture filter");
        checked(SDL_SetTextureBlendMode(p.texture,SDL_BLENDMODE_NONE),"disable texture blending");
        p.width=frame.width;p.height=frame.height;
    }
    checked(SDL_UpdateTexture(p.texture,nullptr,frame.rgb.data(),static_cast<int>(frame.width*3)),"upload desktop frame");
    p.draw();checked(SDL_RenderPresent(p.renderer),"present desktop frame");
}
DesktopExtent DesktopHost::drawable_size() const {
    int width=0,height=0;
    checked(SDL_GetRenderOutputSize(impl_->renderer,&width,&height),"query desktop drawable size");
    return {static_cast<unsigned>(std::max(width,0)),static_cast<unsigned>(std::max(height,0))};
}
void DesktopHost::resize_window(unsigned width,unsigned height) {
    if(impl_->display_backup)throw Fault("confirm or cancel the pending display change before resizing");
    if(width<128 || height<120 || width>4096 || height>4096)
        throw Fault("desktop window size must be within 128x120 and 4096x4096");
    auto* window=impl_->window;
    if(SDL_GetWindowFlags(window)&(SDL_WINDOW_FULLSCREEN|SDL_WINDOW_MAXIMIZED))
        throw Fault("window resize requires a non-maximized window");
    checked(SDL_SetWindowSize(window,static_cast<int>(width),static_cast<int>(height)),"request desktop window size");
    checked(SDL_SyncWindow(window),"synchronize desktop window size");
}
DesktopSettings DesktopHost::display_settings() const {return impl_->settings();}
bool DesktopHost::display_change_pending() const {return impl_->display_backup.has_value();}
void DesktopHost::preview_display(const DesktopSettings& next,unsigned timeout_ms) {
    auto& p=*impl_;
    if(p.display_backup)throw Fault("a display confirmation is already pending");
    if(next.width<128 || next.height<120 || next.width>4096 || next.height>4096 ||
       !timeout_ms || timeout_ms>30000 ||
       (next.mode!=DisplayMode::integer && next.mode!=DisplayMode::square && next.mode!=DisplayMode::four_three && next.mode!=DisplayMode::sixteen_nine) ||
       (next.filter!=DisplayFilter::nearest && next.filter!=DisplayFilter::linear))
        throw Fault("invalid display settings preview");
    if(SDL_GetWindowFlags(p.window)&SDL_WINDOW_MAXIMIZED)throw Fault("display preview requires a non-maximized window");
    p.display_backup=p.settings();
    // Confirmation keys cannot retain a guest Run binding during the prompt.
    if(p.keys[SDL_SCANCODE_RETURN])p.confirmation_keys[SDL_SCANCODE_RETURN]=true;
    p.keys[SDL_SCANCODE_RETURN]=false;
    for(unsigned slot=0;slot<5;++slot) {
        const auto mask=p.key_mask(slot,SDL_SCANCODE_RETURN);
        p.pressed[slot]&=static_cast<std::uint16_t>(~mask);
        for(unsigned n=0;n<12;++n)if(mask&(1u<<n))p.keyboard_pending[slot][n]=0;
    }
    p.display_deadline=SDL_GetTicks()+timeout_ms;
    try {
        p.apply_settings(next);
        checked(SDL_SetWindowTitle(p.window,(p.title+" [Keep display? Enter confirms, Esc reverts]").c_str()),"set display confirmation title");
    } catch(...) {
        cancel_display();throw;
    }
}
void DesktopHost::confirm_display() {
    auto& p=*impl_;
    if(!p.display_backup)throw Fault("no display confirmation is pending");
    // A caller cannot confirm an expired preview between event polls.
    if(SDL_GetTicks()>=p.display_deadline) {cancel_display();throw Fault("display confirmation expired");}
    p.commit_display();
}
void DesktopHost::cancel_display() {
    auto& p=*impl_;
    if(!p.display_backup)throw Fault("no display confirmation is pending");
    p.apply_settings(*p.display_backup);
    p.display_backup.reset();p.display_deadline=0;
    checked(SDL_SetWindowTitle(p.window,(p.title+(p.paused ? " [Paused]":"")).c_str()),"restore display title");
}
std::string DesktopHost::renderer_backend() const {
#if SDL_VERSION_ATLEAST(3,4,0)
    if(impl_->gpu)return SDL_GetGPUDeviceDriver(impl_->gpu);
#endif
    const auto* name=SDL_GetRendererName(impl_->renderer);
    return name ? name:"";
}
void DesktopHost::set_shader_parameters(const ShaderParameters& parameters) {
    if(!parameters.valid())throw Fault("shader percentage out of range");
    auto& p=*impl_;const auto previous=p.shader_parameters;
    p.shader_parameters=parameters;
    try{p.update_shader_parameters();}
    catch(...){p.shader_parameters=previous;throw;}
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
    // A hidden GPU swapchain can retain its old backbuffer extent after
    // resize. Compose into a target that matches the current drawable.
    using Texture=std::unique_ptr<SDL_Texture,decltype(&SDL_DestroyTexture)>;
    Texture capture(SDL_CreateTexture(p.renderer,SDL_PIXELFORMAT_RGBA32,
                                     SDL_TEXTUREACCESS_TARGET,width,height),SDL_DestroyTexture);
#if SDL_VERSION_ATLEAST(3,4,0)
    if(p.gpu)checked(capture!=nullptr,"create desktop GPU capture target");
#endif
    if(capture)checked(SDL_SetRenderTarget(p.renderer,capture.get()),"bind desktop capture target");
    using Surface=std::unique_ptr<SDL_Surface,decltype(&SDL_DestroySurface)>;
    Surface raw(nullptr,SDL_DestroySurface);
    try {
        p.draw();
        // Include the complete viewport and any letterbox bars.
        checked(SDL_SetRenderLogicalPresentation(p.renderer,0,0,SDL_LOGICAL_PRESENTATION_DISABLED),
                "select full desktop capture viewport");
        raw.reset(SDL_RenderReadPixels(p.renderer,nullptr));
        checked(raw!=nullptr,"read desktop target");
    } catch(...) {
        if(capture)SDL_SetRenderTarget(p.renderer,nullptr);
        throw;
    }
    if(capture)checked(SDL_SetRenderTarget(p.renderer,nullptr),"restore desktop window target");
    else checked(SDL_RenderPresent(p.renderer),"present captured desktop frame");
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
