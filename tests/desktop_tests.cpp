#include "host_pacer_support.hpp"
#include "pce/desktop.hpp"
#include "pce/desktop_input.hpp"
#include "pce/desktop_view.hpp"
#include "pce/runtime.hpp"
#include <SDL3/SDL.h>
#include <algorithm>
#include <array>
#include <chrono>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <sstream>
#include <string_view>

namespace {
void require(bool value,const char* why){if(!value)throw std::runtime_error(why);}
void window_event(pce::DesktopHost& host,SDL_EventType type) {
    SDL_Event event{};event.type=type;event.window.windowID=host.window_id();
    require(SDL_PushEvent(&event),"cannot push synthetic window event");
}
void key_event(pce::DesktopHost& host,SDL_Scancode code,bool down,bool repeat=false) {
    SDL_Event event{};event.type=down ? SDL_EVENT_KEY_DOWN:SDL_EVENT_KEY_UP;
    event.key.windowID=host.window_id();event.key.scancode=code;event.key.down=down;event.key.repeat=repeat;
    require(SDL_PushEvent(&event),"cannot push synthetic keyboard event");
}
std::array<std::uint8_t,3> pixel(const pce::VideoFrame& frame,unsigned x,unsigned y) {
    const auto off=(static_cast<std::size_t>(y)*frame.width+x)*3;
    return {frame.rgb.at(off),frame.rgb.at(off+1),frame.rgb.at(off+2)};
}
void completed_frames(pce::DesktopHost& host,unsigned count=2) {
    const pce::VideoFrame frame{1,1,{0,0,0}};
    while(count--)host.present(frame);
}
struct Capture {
    std::filesystem::path path=std::filesystem::temp_directory_path()/
        ("pce-authored-desktop-"+std::to_string(std::chrono::steady_clock::now().time_since_epoch().count())+".ppm");
    ~Capture(){std::error_code error;std::filesystem::remove(path,error);}
};

unsigned test_input_profiles() {
    unsigned checks=0;Capture profile;profile.path.replace_extension(".json");
    const auto put=[&](const std::string& value) {
        std::ofstream file(profile.path,std::ios::binary|std::ios::trunc);file<<value;file.close();
        require(static_cast<bool>(file),"cannot write authored input profile");
    };
    const auto wrapped=[](const std::string& slots) {
        return "{\"format\":\"pce-desktop-input-1\",\"schema\":1,\"slots\":"+slots+"}";
    };
    const auto refused=[&](const std::string& value) {
        put(value);bool bad=false;
        try{(void)pce::read_desktop_input_profile(profile.path.string());}catch(const pce::Fault&){bad=true;}
        require(bad,"malformed/conflicting desktop input profile accepted");++checks;
    };
    for(const auto& bad:std::array<std::string,16>{
        "{}","{\"format\":\"other\",\"schema\":1,\"slots\":[]}",
        "{\"format\":\"pce-desktop-input-1\",\"schema\":false,\"slots\":[]}",
        "{\"format\":\"pce-desktop-input-1\",\"schema\":2,\"slots\":[]}",
        "{\"format\":\"pce-desktop-input-1\",\"schema\":1.0,\"slots\":[]}",
        "{\"format\":\"pce-desktop-input-1\",\"schema\":1,\"slots\":[],\"extra\":0}",
        "{\"format\":\"pce-desktop-input-1\",\"schema\":1,\"schema\":1,\"slots\":[]}",
        wrapped("{}"),wrapped("[{\"port\":5,\"keyboard\":{}}]"),
        wrapped("[{\"port\":0,\"keyboard\":{}},{\"port\":0,\"keyboard\":{}}]"),
        wrapped("[{\"port\":0}]"),wrapped("[{\"port\":0,\"gamepad\":{}}]"),
        wrapped("[{\"port\":0,\"gamepad\":{\"index\":16}}]"),
        wrapped("[{\"port\":0,\"gamepad\":{\"index\":0,\"deadzone\":32768}}]"),
        wrapped("[{\"port\":0,\"gamepad\":{\"index\":0,\"buttons\":{\"i\":\"bad\"}}}]"),
        wrapped("[{\"port\":0,\"gamepad\":{\"index\":0,\"buttons\":{\"i\":\"south\",\"ii\":\"south\"}}}]")})refused(bad);
    for(const auto name:{"Escape","Space","F11","Not a key"})
        refused(wrapped(std::string("[{\"port\":0,\"keyboard\":{\"i\":[\"")+name+"\"]}}]"));
    for(const auto& bad:std::array<std::string,11>{
        wrapped("[{\"port\":0,\"keyboard\":{\"i\":[\"Q\",\"Q\"]}}]"),
        wrapped("[{\"port\":0,\"keyboard\":{\"i\":[\"Q\"]}},{\"port\":1,\"keyboard\":{\"i\":[\"Q\"]}}]"),
        wrapped("[{\"port\":0,\"keyboard\":{\"i\":[\"Q\",\"W\",\"E\",\"R\",\"T\"]}}]"),
        wrapped("[{\"port\":0,\"keyboard\":{\"unknown\":[\"Q\"]}}]"),
        wrapped("[{\"port\":0,\"gamepad\":{\"index\":0}},{\"port\":1,\"gamepad\":{\"index\":0}}]"),
        wrapped("[{\"port\":-1,\"keyboard\":{}}]"),wrapped("[{\"port\":0.0,\"keyboard\":{}}]"),
        wrapped("[{\"port\":00,\"keyboard\":{}}]"),wrapped("[{\"port\":0,\"keyboard\":{},} ]"),
        wrapped("[{\"port\":0,\"keyboard\":{\"i\":[\"\\u0000\"]}}]"),wrapped("[]")+"junk"})refused(bad);
    refused(std::string(16385,' '));
    put(wrapped("[{\"keyboard\":{\"i\":[\"\\u0051\"]},\"port\":4}]"));
    const auto escaped=pce::read_desktop_input_profile(profile.path.string());
    require(escaped.slots[4].keyboard[SDL_SCANCODE_Q]==1 && escaped.slots[0].keyboard[SDL_SCANCODE_Z]==0,
            "ASCII escape/reordered fields or explicit blank profile differs");++checks;
    // Five authored devices have deterministic initial instance-ID order. Their
    // slot assignments must survive another player's disconnect without theft.
    SDL_VirtualJoystickDesc descriptor{};SDL_INIT_INTERFACE(&descriptor);
    descriptor.type=SDL_JOYSTICK_TYPE_GAMEPAD;descriptor.vendor_id=0x1234;descriptor.product_id=0x5678;
    descriptor.naxes=SDL_GAMEPAD_AXIS_COUNT;descriptor.nbuttons=SDL_GAMEPAD_BUTTON_COUNT;
    descriptor.button_mask=(1u<<SDL_GAMEPAD_BUTTON_COUNT)-1;descriptor.axis_mask=(1u<<SDL_GAMEPAD_AXIS_COUNT)-1;
    descriptor.name="Authored profile controller";
    std::array<SDL_JoystickID,5> ids{};std::array<SDL_Joystick*,5> sticks{};
    for(unsigned n=0;n<ids.size();++n) {
        ids[n]=SDL_AttachVirtualJoystick(&descriptor);require(ids[n]!=0,"cannot attach profile controller");
        sticks[n]=SDL_OpenJoystick(ids[n]);require(sticks[n]!=nullptr,"cannot open profile controller");
    }
    std::ostringstream json;json<<'[';
    const std::array<char,5> keys={'Q','W','E','R','T'};
    const std::array<SDL_Scancode,5> scancodes={SDL_SCANCODE_Q,SDL_SCANCODE_W,SDL_SCANCODE_E,SDL_SCANCODE_R,SDL_SCANCODE_T};
    for(unsigned n=0;n<5;++n) {
        if(n)json<<',';
        json<<"{\"port\":"<<n<<",\"keyboard\":{\"i\":[\""<<keys[n]
            <<"\"]},\"gamepad\":{\"index\":"<<n<<",\"deadzone\":1000,\"buttons\":{\"ii\":\"north\"}}}";
    }
    json<<']';put(wrapped(json.str()));
    {
        pce::DesktopHost host({.title="Authored five-slot profiles",.scale=1,.hidden=true,.paced=false,.input_profile=profile.path.string()});
        host.poll();window_event(host,SDL_EVENT_WINDOW_FOCUS_GAINED);host.poll();
        require(host.stats().gamepad_connections==5,"not all five profile devices opened");++checks;
        for(unsigned slot=0;slot<5;++slot) {
            key_event(host,scancodes[slot],true);key_event(host,scancodes[slot],false);host.poll();
            for(unsigned n=0;n<5;++n)require(host.buttons(n)==(n==slot ? 1:0),"keyboard profile leaked across player slots");
            require(!host.checkpoint_input_quiescent(),"nonzero player-slot tap was treated as quiescent");
            host.redraw({1,1,{0,0,0}});require(host.buttons(slot)==1,"redraw aged profile tap");
            completed_frames(host,1);require(host.buttons(slot)==1,"profile tap did not span complete frame");
            completed_frames(host,1);require(host.buttons(slot)==0,"profile tap did not expire");
            require(SDL_SetJoystickVirtualButton(sticks[slot],SDL_GAMEPAD_BUTTON_NORTH,true),"cannot press mapped profile button");host.poll();
            for(unsigned n=0;n<5;++n)require(host.buttons(n)==(n==slot ? 2:0),"gamepad profile leaked across player slots");
            require(SDL_SetJoystickVirtualButton(sticks[slot],SDL_GAMEPAD_BUTTON_NORTH,false),"cannot release profile button");host.poll();completed_frames(host);
            for(const int value:{-1001,-1000,0,1000,1001}) {
                require(SDL_SetJoystickVirtualAxis(sticks[slot],SDL_GAMEPAD_AXIS_LEFTX,static_cast<Sint16>(value)),"cannot set profile axis");host.poll();
                require(host.buttons(slot)==(value < -1000 ? 128:value>1000 ? 32:0),"custom deadzone boundary differs");
            }
            require(SDL_SetJoystickVirtualAxis(sticks[slot],SDL_GAMEPAD_AXIS_LEFTX,0),"cannot reset profile axis");host.poll();
            checks+=11;
        }
        key_event(host,SDL_SCANCODE_T,true);key_event(host,SDL_SCANCODE_T,false);host.poll();host.reset_input();
        require(host.buttons(4)==0 && host.checkpoint_input_quiescent(),"input reset retained other-player tap");++checks;
        require(SDL_SetJoystickVirtualButton(sticks[4],SDL_GAMEPAD_BUTTON_NORTH,true),"cannot hold last profile controller");host.poll();completed_frames(host);
        SDL_CloseJoystick(sticks[0]);sticks[0]=nullptr;require(SDL_DetachVirtualJoystick(ids[0]),"cannot remove first profile controller");ids[0]=0;host.poll();
        require(host.buttons(0)==0 && host.buttons(4)==2,"disconnect stole a connected player's controller");++checks;
        window_event(host,SDL_EVENT_WINDOW_FOCUS_LOST);host.poll();
        for(unsigned n=0;n<5;++n)require(host.buttons(n)==0,"focus loss retained another player input");++checks;
        require(SDL_SetJoystickVirtualButton(sticks[4],SDL_GAMEPAD_BUTTON_NORTH,false),"cannot release profile controller");host.poll();
        bool bad=false;try{(void)host.buttons(5);}catch(const pce::Fault&){bad=true;}
        require(bad,"out-of-range desktop player accepted");++checks;
    }
    for(unsigned n=0;n<ids.size();++n)if(ids[n]){SDL_CloseJoystick(sticks[n]);require(SDL_DetachVirtualJoystick(ids[n]),"cannot clean profile controller");}
    return checks;
}

unsigned test_completed_frame_effects() {
    using namespace pce;
    unsigned checks=0;
    Bus timing_bus;timing_bus.enable_continuous_video();
    timing_bus.vdc.raster.master_ticks=123;timing_bus.vdc.video.frame_boundary(timing_bus.vdc);
    const DesktopFrameInput before(timing_bus,PortView::adaptive,{256,240},7,130);
    timing_bus.vdc.raster.master_ticks=137;
    const DesktopFrameInput partial(timing_bus,PortView::adaptive,{256,240},7,140);
    require(before.sequence==1 && partial.sequence==1 && before.completed_ticks==123 &&
        partial.completed_ticks==123 && before.guest_ticks==130 && partial.guest_ticks==140 &&
        partial.presentation_epoch==7,"current CPU ticks replaced completed-frame timestamp");++checks;
    DesktopHost host({.title="Authored software presentation effects",.scale=1,.hidden=true,
        .paced=false,.display_mode=DisplayMode::square,.effect_settings={0,50}});
    const VideoFrame white{256,240,std::vector<std::uint8_t>(256*240*3,100)};
    const VideoFrame black{256,240,std::vector<std::uint8_t>(256*240*3,0)};
    PresentationStamp stamp{.sequence=1,.ticks=100,.epoch=0,.width=256,.height=240};
    host.present(white,stamp);
    require(pixel(host.readback(),128,120)==std::array<std::uint8_t,3>{100,100,100},"first effect frame differs");++checks;
    stamp.sequence=2;stamp.ticks=200;host.present(black,stamp);
    require(pixel(host.readback(),128,120)==std::array<std::uint8_t,3>{50,50,50} && host.stats().effect_temporal,
            "persistence did not retain exactly one completed-frame half");++checks;
    const auto presented=host.stats().presented;
    host.redraw(black,stamp);
    const auto retained=host.readback();
    require(pixel(retained,128,120)==std::array<std::uint8_t,3>{50,50,50} &&
        host.readback().rgb==retained.rgb && host.stats().presented==presented &&
        !host.stats().effect_temporal && host.stats().effect_reason==PresentationBreak::repeated_frame,
        "redraw/readback decayed persistence or advanced completed-frame accounting");++checks;
    require(host.stats().presentation_ticks==200 && host.stats().presentation_sequence==2,
            "effect completed-frame metadata drifted");++checks;
    host.resize_window(512,480);host.poll();
    require(pixel(host.readback(),256,240)==std::array<std::uint8_t,3>{0,0,0} &&
        !host.stats().effect_temporal && host.stats().effect_reason==PresentationBreak::extent_change,
        "resized output reused a temporal trail");++checks;
    stamp.sequence=3;stamp.ticks=300;host.present(white,stamp);
    stamp.sequence=4;stamp.ticks=400;host.present(black,stamp);
    require(pixel(host.readback(),256,240)==std::array<std::uint8_t,3>{50,50,50},"new-frame effect did not resume after resize");++checks;
    ++stamp.epoch;host.redraw(black,stamp);
    require(pixel(host.readback(),256,240)==std::array<std::uint8_t,3>{0,0,0} &&
        host.stats().effect_reason==PresentationBreak::epoch_change && host.stats().presentation_epoch==1,
        "checkpoint epoch failed to clear temporal effect");++checks;
    bool rejected=false;try{host.present(white);}catch(const Fault&){rejected=true;}
    require(rejected && host.stats().presented==presented+2 &&
        pixel(host.readback(),256,240)==std::array<std::uint8_t,3>{0,0,0},
        "unstamped temporal call guessed guest cadence or changed prior output");++checks;
    rejected=false;try{host.set_effect_settings({101,0});}catch(const Fault&){rejected=true;}
    require(rejected && host.effect_settings()==PresentationEffectSettings{0,50},"invalid effect settings changed host policy");++checks;
    host.set_effect_settings({100,0});host.resize_window(256,240);host.poll();
    VideoFrame stripe=black;
    for(unsigned y=0;y<stripe.height;++y)for(unsigned c=0;c<3;++c)stripe.rgb[(y*256+128)*3+c]=100;
    host.present(stripe);const auto softened=host.readback();
    require(pixel(softened,127,120)==std::array<std::uint8_t,3>{25,25,25} &&
        pixel(softened,128,120)==std::array<std::uint8_t,3>{50,50,50} &&
        pixel(softened,129,120)==std::array<std::uint8_t,3>{25,25,25} &&
        host.stats().presentation_sequence==0,"legacy stateless softness differs or invented guest timing");++checks;
    rejected=false;try{host.set_effect_settings({0,50});}catch(const Fault&){rejected=true;}
    require(rejected && host.effect_settings()==PresentationEffectSettings{100,0},
        "legacy softness history was promoted to a guessed persistence clock");++checks;
    host.set_effect_settings({0,0});
    require(pixel(host.readback(),128,120)==std::array<std::uint8_t,3>{100,100,100} &&
        pixel(host.readback(),127,120)==std::array<std::uint8_t,3>{0,0,0},"disabling effects did not restore raw source");++checks;
    for(const auto settings:{PresentationEffectSettings{0,0},PresentationEffectSettings{100,0},PresentationEffectSettings{0,50}}) {
        DesktopHost guarded({.title="Authored presentation stamp refusal",.scale=1,.hidden=true,
            .paced=false,.display_mode=DisplayMode::square,.effect_settings=settings});
        // A first completed frame may legitimately use clock zero.
        PresentationStamp valid{.sequence=1,.ticks=0,.width=256,.height=240};
        guarded.present(white,valid);
        window_event(guarded,SDL_EVENT_WINDOW_FOCUS_GAINED);guarded.poll();
        key_event(guarded,SDL_SCANCODE_Z,true);key_event(guarded,SDL_SCANCODE_Z,false);guarded.poll();
        require((guarded.buttons()&1)!=0,"stamp refusal input fixture did not latch its pulse");
        auto invalid=std::array<PresentationStamp,7>{valid,valid,valid,valid,valid,valid,valid};
        invalid[0].sequence=0;invalid[1].width=0;invalid[2].height=0;
        invalid[3].width=8193;invalid[4].height=8193;
        invalid[5].width=8192;invalid[5].height=8192;
        invalid[6].width=std::numeric_limits<unsigned>::max();invalid[6].height=std::numeric_limits<unsigned>::max();
        for(const auto& bad:invalid) {
            bool refused=false;try{guarded.present(black,bad);}catch(const Fault&){refused=true;}
            require(refused && guarded.stats().presented==1 &&
                guarded.stats().presentation_sequence==1 && guarded.stats().presentation_ticks==0 &&
                (guarded.buttons()&1)!=0 && pixel(guarded.readback(),128,120)==std::array<std::uint8_t,3>{100,100,100},
                "invalid stamp changed publication, pixels, frame time or pending input");++checks;
        }
        ++valid.sequence;++valid.ticks;guarded.present(white,valid);
        require((guarded.buttons()&1)!=0,"refused stamps consumed first valid input boundary");++checks;
        ++valid.sequence;++valid.ticks;guarded.present(white,valid);
        require((guarded.buttons()&1)==0,"pending input survived two actual valid publications");++checks;
    }
    return checks;
}

int test_gpu_shader(std::string_view preset) {
    auto shader=pce::DisplayShader::off;
    if(preset=="sharp")shader=pce::DisplayShader::sharp;
    else if(preset=="crt")shader=pce::DisplayShader::crt;
    else if(preset=="smooth")shader=pce::DisplayShader::smooth;
    else if(preset=="lcd")shader=pce::DisplayShader::lcd;
    else if(preset=="mono")shader=pce::DisplayShader::mono;
    else if(preset=="crt-mask")shader=pce::DisplayShader::crt_mask;
    else require(preset=="off","unknown test shader");
    pce::VideoFrame pattern{4,2,std::vector<std::uint8_t>(4*2*3)};
    for(unsigned i=0;i<8;++i) {
        auto dest=pattern.rgb.begin()+i*3;
        std::fill_n(dest,3,i%4<2 ? 32:224);
        if(shader==pce::DisplayShader::mono) {
            dest[0]=255;dest[1]=0;dest[2]=0;
        }
    }
    pce::DesktopHost host({.title="Authored GPU shader test",.scale=1,.hidden=true,.paced=false,
        .display_mode=pce::DisplayMode::square,.display_filter=pce::DisplayFilter::linear,
        .display_shader=shader});
    auto* window=SDL_GetWindowFromID(host.window_id());
    host.present(pattern);
    const auto frame=host.readback();
    require(frame.width==256 && frame.height==240,"GPU readback geometry differs");
    require(pixel(frame,0,0)==std::array<std::uint8_t,3>{0,0,0},"GPU canvas border differs");
    const unsigned left=pixel(frame,120,120)[0], right=pixel(frame,135,120)[0];
    const unsigned edge=pixel(frame,240,120)[0];
    std::cout<<preset<<" samples "<<left<<", "<<right<<", "<<edge<<std::endl;
    if(shader==pce::DisplayShader::off)
        require(left>70 && right<190,"linear filter did not blend the source colors");
    else if(shader==pce::DisplayShader::sharp)
        require(left>=31 && left<=33 && right>=223 && right<=225,
                "sharp shader did not narrow the transition");
    else if(shader==pce::DisplayShader::crt)
        require(edge>160 && edge<224,"CRT shader vignette did not shade the edge");
    else if(shader==pce::DisplayShader::smooth)
        require(left>=86 && left<=100 && right>=155 && right<=174,
                "smooth shader did not ease the bilinear transition");
    else if(shader==pce::DisplayShader::lcd) {
        const unsigned seam=pixel(frame,192,88)[0], center=pixel(frame,224,88)[0];
        std::cout<<"LCD seam and center "<<seam<<", "<<center<<std::endl;
        require(seam>=165 && seam<=180 && center>=223 && center<=225,
                "LCD shader did not shade the grid boundary");
    } else if(shader==pce::DisplayShader::mono) {
        require(pixel(frame,192,88)==std::array<std::uint8_t,3>{76,76,76},
                "monochrome output differs from red luma");
    } else {
        for(unsigned channel=0;channel<3;++channel) {
            const auto stripe=pixel(frame,216+channel,88);
            std::cout<<"CRT stripe "<<channel<<": "<<unsigned(stripe[0])<<", "
                     <<unsigned(stripe[1])<<", "<<unsigned(stripe[2])<<std::endl;
            require(stripe[channel]>stripe[(channel+1)%3]+30 &&
                    stripe[(channel+1)%3]==stripe[(channel+2)%3],
                    "CRT phosphor stripes do not cycle over physical columns");
        }
    }
    for(const auto extent:{pce::DesktopExtent{1200,360},pce::DesktopExtent{840,360}}) {
        host.resize_window(extent.width,extent.height);
        host.poll();
        const auto logical_width=extent.width==1200 ? 512u:420u;
        host.redraw({logical_width,180,std::vector<std::uint8_t>(logical_width*180*3,96)});
        const auto resized=host.readback();
        const auto drawable=host.drawable_size();
        require(resized.width==drawable.width && resized.height==drawable.height,
                "GPU readback extent differs after resize");
    }
    host.resize_window(3840,2160);
    int width=0,height=0;
    require(SDL_GetWindowSizeInPixels(window,&width,&height) && width>=3840 && height>=2160,
            "UHD drawable was not created");
    host.poll();
    const pce::VideoFrame consumer_frame{1280,720,std::vector<std::uint8_t>(1280*720*3,96)};
    host.present(consumer_frame);
    std::cout<<"Shader pixels and UHD presentation passed\n";
    return 0;
}
}
int main(int argc,char** argv){try{
    if(argc==3 && std::string_view(argv[1])=="--gpu-shader")return test_gpu_shader(argv[2]);
    require(argc==1,"expected no arguments or --gpu-shader PRESET");
    {
        const pce::Bus bus;
        using pce::DesktopFrameInput;
        using pce::PortView;
        require(DesktopFrameInput(bus,PortView::twenty_one_nine).camera_width(180,240,512)==420,
                "fixed ultrawide camera width differs");
        require(DesktopFrameInput(bus,PortView::adaptive,{1680,720}).camera_width(180,240,512)==420,
                "high DPI changed adaptive aspect");
        require(DesktopFrameInput(bus,PortView::adaptive,{1200,360}).camera_width(180,240,512)==512 &&
                DesktopFrameInput(bus,PortView::adaptive,{600,800}).camera_width(180,240,512)==240,
                "adaptive camera did not respect scene bounds");
    }
    // No device/BIOS/retail dependency: SDL's software/dummy path exercises the
    // same upload/readback and host event code used by the optional desktop.
    SDL_SetHint(SDL_HINT_GAMECONTROLLER_IGNORE_DEVICES_EXCEPT,"0x1234/0x5678");
    // The dummy window has no OS focus; host focus is explicitly exercised by
    // injected events below, independently of SDL's device-update gate.
    SDL_SetHint(SDL_HINT_JOYSTICK_ALLOW_BACKGROUND_EVENTS,"1");
    pce::DesktopHost host({"Authored desktop integration test",1,true,false});
    unsigned checks=host_pacer_fixture::run();
    require(host.window_id()!=0,"desktop window has no ID");++checks;
    require(host.poll(),"new desktop unexpectedly quit");
    window_event(host,SDL_EVENT_WINDOW_FOCUS_GAINED);host.poll();
    key_event(host,SDL_SCANCODE_F12,true);key_event(host,SDL_SCANCODE_F12,true,true);key_event(host,SDL_SCANCODE_F12,false);host.poll();
    require(host.buttons()==0 && host.stats().unmapped_key_down==1 && host.stats().last_unmapped_scancode==SDL_SCANCODE_F12,
            "unmapped fresh key diagnostic omitted code or counted repeat/release");++checks;
    const std::array<SDL_Scancode,12> codes={SDL_SCANCODE_Z,SDL_SCANCODE_X,SDL_SCANCODE_LSHIFT,
        SDL_SCANCODE_RETURN,SDL_SCANCODE_UP,SDL_SCANCODE_RIGHT,SDL_SCANCODE_DOWN,SDL_SCANCODE_LEFT,
        SDL_SCANCODE_A,SDL_SCANCODE_S,SDL_SCANCODE_D,SDL_SCANCODE_F};
    for(unsigned n=0;n<codes.size();++n) {
        key_event(host,codes[n],true);host.poll();require(host.buttons()==(1u<<n),"keyboard button order differs from joypad contract");
        completed_frames(host);require(host.buttons()==(1u<<n),"held key did not outlast pending pulse");
        key_event(host,codes[n],false);host.poll();require(host.buttons()==0,"keyboard release stuck");checks+=2;
    }
    const std::array<SDL_Scancode,4> keypad={SDL_SCANCODE_KP_8,SDL_SCANCODE_KP_6,SDL_SCANCODE_KP_2,SDL_SCANCODE_KP_4};
    for(unsigned n=0;n<keypad.size();++n) {
        key_event(host,keypad[n],true);key_event(host,keypad[n],false);host.poll();
        require(host.buttons()==(16u<<n),"keypad direction alias or same-poll tap was lost");++checks;
        completed_frames(host,1);require(host.buttons()==(16u<<n),"keypad tap did not span a complete guest frame");++checks;
        completed_frames(host,1);require(host.buttons()==0,"keypad tap persisted beyond two frame boundaries");++checks;
    }
    key_event(host,SDL_SCANCODE_LSHIFT,true);key_event(host,SDL_SCANCODE_RSHIFT,true);host.poll();
    key_event(host,SDL_SCANCODE_LSHIFT,false);host.poll();require(host.buttons()==4,"left select release cleared held right select");++checks;
    key_event(host,SDL_SCANCODE_RSHIFT,false);host.poll();completed_frames(host);
    key_event(host,SDL_SCANCODE_RETURN,true);key_event(host,SDL_SCANCODE_RETURN,false);host.poll();
    require(host.buttons()==8,"same-poll keyboard tap was lost");++checks;
    (void)host.readback();require(host.buttons()==8,"host readback consumed a guest-frame input pulse");++checks;
    const auto frames_before_redraw=host.stats().presented;
    // Absence of a completed guest frame belongs to the caller; malformed
    // frames must never become successful presentations or consume input.
    for(const auto& malformed:{pce::VideoFrame{},pce::VideoFrame{0,1,{0,0,0}},
                               pce::VideoFrame{1,1,{0,0}}}) {
        bool refused=false;
        try{host.present(malformed);}catch(const pce::Fault&){refused=true;}
        require(refused && host.stats().presented==frames_before_redraw && host.buttons()==8,
                "malformed RGB frame was accepted or consumed host-frame state");++checks;
    }
    host.redraw({1,1,{12,34,56}});
    require(host.buttons()==8 && host.stats().presented==frames_before_redraw,
            "host redraw consumed guest-frame lifetime");++checks;
    completed_frames(host,1);require(host.buttons()==8,"keyboard pulse did not span a complete guest frame");++checks;
    completed_frames(host,1);require(host.buttons()==0,"keyboard tap persisted beyond two frame boundaries");++checks;
    for(const auto code:codes)key_event(host,code,true);
    host.poll();require(host.buttons()==4095,"simultaneous keyboard masks changed");++checks;
    window_event(host,SDL_EVENT_WINDOW_FOCUS_LOST);host.poll();
    require(host.buttons()==0 && host.stats().focus_losses==1,"focus loss did not release all host input");++checks;
    key_event(host,SDL_SCANCODE_Z,true);host.poll();require(host.buttons()==0,"background keyboard event changed guest input");++checks;
    window_event(host,SDL_EVENT_WINDOW_FOCUS_GAINED);host.poll();require(host.buttons()==0,"focus recovery resurrected stale keys");++checks;
    key_event(host,SDL_SCANCODE_SPACE,true);host.poll();require(host.paused() && host.buttons()==0,"pause action failed");++checks;
    key_event(host,SDL_SCANCODE_SPACE,true,true);host.poll();require(host.paused(),"key repeat toggled pause");++checks;
    key_event(host,SDL_SCANCODE_SPACE,false);key_event(host,SDL_SCANCODE_SPACE,true);host.poll();require(!host.paused(),"resume action failed");++checks;
    SDL_VirtualJoystickDesc descriptor{};SDL_INIT_INTERFACE(&descriptor);
    descriptor.type=SDL_JOYSTICK_TYPE_GAMEPAD;descriptor.vendor_id=0x1234;descriptor.product_id=0x5678;
    descriptor.naxes=SDL_GAMEPAD_AXIS_COUNT;descriptor.nbuttons=SDL_GAMEPAD_BUTTON_COUNT;
    descriptor.button_mask=(1u<<SDL_GAMEPAD_BUTTON_COUNT)-1;descriptor.axis_mask=(1u<<SDL_GAMEPAD_AXIS_COUNT)-1;
    descriptor.name="Authored PC Engine host test controller";
    const auto instance=SDL_AttachVirtualJoystick(&descriptor);
    require(instance!=0,"cannot attach authored virtual gamepad");host.poll();
    auto* joystick=SDL_OpenJoystick(instance);require(joystick!=nullptr,"cannot open virtual joystick source");
    require(host.stats().gamepad_connections==1,"gamepad hotplug was not opened");++checks;
    const std::array<SDL_GamepadButton,12> gamepad_buttons={SDL_GAMEPAD_BUTTON_SOUTH,SDL_GAMEPAD_BUTTON_EAST,
        SDL_GAMEPAD_BUTTON_BACK,SDL_GAMEPAD_BUTTON_START,SDL_GAMEPAD_BUTTON_DPAD_UP,SDL_GAMEPAD_BUTTON_DPAD_RIGHT,
        SDL_GAMEPAD_BUTTON_DPAD_DOWN,SDL_GAMEPAD_BUTTON_DPAD_LEFT,SDL_GAMEPAD_BUTTON_WEST,SDL_GAMEPAD_BUTTON_NORTH,
        SDL_GAMEPAD_BUTTON_LEFT_SHOULDER,SDL_GAMEPAD_BUTTON_RIGHT_SHOULDER};
    for(unsigned n=0;n<gamepad_buttons.size();++n) {
        require(SDL_SetJoystickVirtualButton(joystick,gamepad_buttons[n],true),"cannot press virtual gamepad button");
        host.poll();if(host.buttons()!=(1u<<n))throw std::runtime_error("gamepad button "+std::to_string(n)+" returned "+std::to_string(host.buttons()));
        completed_frames(host);require(host.buttons()==(1u<<n),"held gamepad did not outlast pending pulse");
        require(SDL_SetJoystickVirtualButton(joystick,gamepad_buttons[n],false),"cannot release virtual gamepad button");
        host.poll();require(host.buttons()==0,"gamepad release stuck");checks+=2;
    }
    SDL_Event tap{};tap.type=SDL_EVENT_GAMEPAD_BUTTON_DOWN;tap.gbutton.which=instance;tap.gbutton.button=SDL_GAMEPAD_BUTTON_START;tap.gbutton.down=true;
    require(SDL_PushEvent(&tap),"cannot queue authored gamepad press");
    tap.type=SDL_EVENT_GAMEPAD_BUTTON_UP;tap.gbutton.down=false;require(SDL_PushEvent(&tap),"cannot queue authored gamepad release");host.poll();
    require(host.buttons()==8,"same-poll gamepad tap was lost");++checks;
    completed_frames(host,1);require(host.buttons()==8,"gamepad pulse did not span a complete guest frame");++checks;
    completed_frames(host,1);require(host.buttons()==0,"gamepad tap persisted beyond two frame boundaries");++checks;
    for(const auto axis:{SDL_GAMEPAD_AXIS_LEFTX,SDL_GAMEPAD_AXIS_LEFTY}) {
        for(const int value:{-32768,-16001,-16000,0,16000,16001,32767}) {
            require(SDL_SetJoystickVirtualAxis(joystick,axis,static_cast<Sint16>(value)),"cannot set virtual gamepad axis");
            host.poll();
            const unsigned expected=axis==SDL_GAMEPAD_AXIS_LEFTX ? (value < -16000 ? 128:value>16000 ? 32:0):
                (value < -16000 ? 16:value>16000 ? 64:0);
            require(host.buttons()==expected,"gamepad deadzone/direction boundary changed");++checks;
        }
        require(SDL_SetJoystickVirtualAxis(joystick,axis,0),"cannot reset virtual gamepad axis");host.poll();
    }
    require(SDL_SetJoystickVirtualButton(joystick,SDL_GAMEPAD_BUTTON_SOUTH,true),"cannot hold virtual button");host.poll();
    key_event(host,SDL_SCANCODE_X,true);host.poll();require(host.buttons()==3,"keyboard/gamepad inputs did not combine");++checks;
    window_event(host,SDL_EVENT_WINDOW_FOCUS_LOST);host.poll();require(host.buttons()==0,"background gamepad input was not released");++checks;
    window_event(host,SDL_EVENT_WINDOW_FOCUS_GAINED);host.poll();require(host.buttons()==1,"focused gamepad did not resume live state");++checks;
    tap.type=SDL_EVENT_GAMEPAD_BUTTON_DOWN;tap.gbutton.down=true;require(SDL_PushEvent(&tap),"cannot queue pre-disconnect press");
    tap.type=SDL_EVENT_GAMEPAD_BUTTON_UP;tap.gbutton.down=false;require(SDL_PushEvent(&tap),"cannot queue pre-disconnect release");host.poll();
    require(host.buttons()==9,"pre-disconnect tap was not pending");++checks;
    SDL_CloseJoystick(joystick);require(SDL_DetachVirtualJoystick(instance),"cannot detach authored virtual gamepad");host.poll();
    require(host.buttons()==0,"gamepad disconnect retained held input");++checks;
    key_event(host,SDL_SCANCODE_RETURN,true);key_event(host,SDL_SCANCODE_RETURN,false);host.poll();
    window_event(host,SDL_EVENT_WINDOW_FOCUS_LOST);host.poll();window_event(host,SDL_EVENT_WINDOW_FOCUS_GAINED);host.poll();
    require(host.buttons()==0,"focus recovery resurrected pending tap");++checks;
    key_event(host,SDL_SCANCODE_RETURN,true);key_event(host,SDL_SCANCODE_RETURN,false);host.poll();
    key_event(host,SDL_SCANCODE_SPACE,true);host.poll();key_event(host,SDL_SCANCODE_SPACE,false);key_event(host,SDL_SCANCODE_SPACE,true);host.poll();
    require(!host.paused() && host.buttons()==0,"pause/resume resurrected pending tap");++checks;
    require(host.stats().keyboard_events>0 && host.stats().gamepad_events>=24 && host.stats().input_pulses>=26,"input source diagnostics did not record pulses");++checks;
    const auto frames_before=host.stats().presented;
    pce::VideoFrame frame{16,16,std::vector<std::uint8_t>(16*16*3)};
    for(unsigned n=0;n<16*16;++n)frame.rgb[n*3]=255;
    frame.rgb[0]=0;frame.rgb[2]=255;
    host.present(frame);
    auto read=host.readback();
    require(read.width==256 && read.height==240,"dummy window output geometry changed");++checks;
    require(pixel(read,0,0)==std::array<std::uint8_t,3>{0,0,0},"letterbox border is not black");++checks;
    require(pixel(read,8,0)==std::array<std::uint8_t,3>{0,0,255},"RGB texture conversion or integer origin changed");++checks;
    require(pixel(read,22,14)==std::array<std::uint8_t,3>{0,0,255},"nearest integer pixel replication changed");++checks;
    require(pixel(read,23,0)==std::array<std::uint8_t,3>{255,0,0},"RGB texture pixel boundary changed");++checks;
    frame.width=32;frame.height=8;frame.rgb.assign(32*8*3,0);
    for(unsigned n=0;n<32*8;++n)frame.rgb[n*3+1]=255;
    host.present(frame);read=host.readback();
    require(pixel(read,0,87)==std::array<std::uint8_t,3>{0,0,0} && pixel(read,0,88)==std::array<std::uint8_t,3>{0,255,0},
            "changed guest geometry did not replace texture/letterbox");++checks;
    require(host.stats().presented==frames_before+2,"presentation count includes readback redraws");++checks;
    auto* window=SDL_GetWindowFromID(host.window_id());require(window!=nullptr,"cannot find own test window");
    require(SDL_SetWindowSize(window,160,120),"cannot resize authored desktop window");host.poll();
    read=host.readback();require(read.width==160 && read.height==120,"resize did not change SDL target");++checks;
    require(pixel(read,0,39)==std::array<std::uint8_t,3>{0,0,0} && pixel(read,0,40)==std::array<std::uint8_t,3>{0,255,0},
            "resize did not preserve integer letterbox");++checks;
    key_event(host,SDL_SCANCODE_SPACE,true);host.poll();require(host.paused(),"pause before resize failed");
    require(SDL_SetWindowSize(window,256,240),"cannot resize paused window");
    window_event(host,SDL_EVENT_WINDOW_EXPOSED);host.poll();read=host.readback();
    require(read.width==256 && read.height==240 && host.stats().resize_events>0,"paused resize/expose did not redraw");++checks;
    key_event(host,SDL_SCANCODE_SPACE,false);key_event(host,SDL_SCANCODE_SPACE,true);host.poll();
    key_event(host,SDL_SCANCODE_F11,true);host.poll();
    require((SDL_GetWindowFlags(window)&SDL_WINDOW_FULLSCREEN)!=0,"F11 did not enter fullscreen");++checks;
    key_event(host,SDL_SCANCODE_F11,true,true);host.poll();
    require((SDL_GetWindowFlags(window)&SDL_WINDOW_FULLSCREEN)!=0,"key repeat left fullscreen");++checks;
    key_event(host,SDL_SCANCODE_F11,false);key_event(host,SDL_SCANCODE_F11,true);host.poll();
    require((SDL_GetWindowFlags(window)&SDL_WINDOW_FULLSCREEN)==0,"F11 did not leave fullscreen");++checks;
    require(host.stats().unmapped_key_down==1 && host.stats().last_unmapped_scancode==SDL_SCANCODE_F12,
            "pause/fullscreen host keys polluted unmapped input diagnostic");++checks;
    require(SDL_SetWindowSize(window,256,240),"cannot restore capture dimensions");host.poll();
    require(SDL_SetWindowSize(window,128,120),"cannot set small authored window");host.poll();
    pce::VideoFrame large{1024,512,std::vector<std::uint8_t>(1024*512*3,77)};
    host.present(large);read=host.readback();
    require(read.width==128 && read.height==120 && pixel(read,0,27)==std::array<std::uint8_t,3>{0,0,0} &&
            pixel(read,0,28)==std::array<std::uint8_t,3>{77,77,77} && pixel(read,127,91)==std::array<std::uint8_t,3>{77,77,77} &&
            pixel(read,127,92)==std::array<std::uint8_t,3>{0,0,0},"small-window nearest fit clipped instead of letterboxing");++checks;
    require(SDL_SetWindowSize(window,256,240),"cannot restore small-window capture dimensions");host.poll();host.present(frame);
    bool rejected=false;try{host.present({1,1,{}});}catch(const pce::Fault&){rejected=true;}
    require(rejected,"malformed host frame accepted");++checks;
    Capture capture;host.capture(capture.path.string());
    std::ifstream file(capture.path,std::ios::binary);std::string magic;std::getline(file,magic);
    require(magic=="P6" && std::filesystem::file_size(capture.path)>256*240*3,"actual SDL capture not written");++checks;
    file.close();const auto size=std::filesystem::file_size(capture.path);
    rejected=false;try{host.capture(capture.path.string());}catch(const pce::Fault&){rejected=true;}
    require(rejected && std::filesystem::file_size(capture.path)==size,"desktop capture overwrote existing output");++checks;
    window_event(host,SDL_EVENT_WINDOW_CLOSE_REQUESTED);require(!host.poll(),"close request did not end desktop loop");++checks;
    // Inspect actual SDL pixels for a 16:9 drawable and a 256x224 source.
    // Exact ratios in the drawable expose cropping, stretch and bad padding.
    const pce::VideoFrame green{256,224,std::vector<std::uint8_t>(256*224*3,77)};
    const std::array<std::uint8_t,3> fill{77,77,77}, black{0,0,0};
    for(const auto mode:{pce::DisplayMode::square,pce::DisplayMode::four_three,pce::DisplayMode::sixteen_nine}) {
        pce::DesktopHost display({.title="Authored display-mode test",.scale=1,.hidden=true,
            .paced=false,.display_mode=mode,.display_filter=pce::DisplayFilter::linear});
        auto* own_window=SDL_GetWindowFromID(display.window_id());
        require(SDL_SetWindowSize(own_window,640,360),"cannot resize display test window");
        display.poll();display.present(green);
        const auto pixels=display.readback();
        require(pixels.width==640 && pixels.height==360,"display target geometry differs");
        require(pixel(pixels,320,180)==fill && pixel(pixels,320,0)==fill,
                "fitted frame has incorrect vertical coverage");
        if(mode==pce::DisplayMode::square)
            require(pixel(pixels,110,180)==black && pixel(pixels,115,180)==fill,
                    "square pixels did not preserve frame aspect");
        else if(mode==pce::DisplayMode::four_three)
            require(pixel(pixels,79,180)==black && pixel(pixels,80,180)==fill &&
                    pixel(pixels,559,180)==fill && pixel(pixels,560,180)==black,
                    "4:3 viewport differs");
        else
            require(pixel(pixels,0,0)==fill && pixel(pixels,639,359)==fill,
                    "16:9 viewport did not fill drawable");
        ++checks;
    }
    {
        pce::DesktopHost fullscreen({.title="Authored fullscreen test",.scale=1,.hidden=true,
            .paced=false,.fullscreen=true});
        require(SDL_GetWindowFlags(SDL_GetWindowFromID(fullscreen.window_id()))&SDL_WINDOW_FULLSCREEN,
                "startup fullscreen flag was ignored");
        ++checks;
    }
    {
        pce::DesktopHost paced({"Authored paced host",1,true,true});
        paced.pace(0);const auto start=SDL_GetTicksNS();paced.pace(214773);
        require(SDL_GetTicksNS()-start>=9000000,"master-clock software pacer skipped requested wait");++checks;
        paced.pace(std::numeric_limits<std::uint64_t>::max());
        require(paced.stats().pacing_resets==1,"unbounded guest time jump did not reset host anchor");++checks;
        paced.pace(1);window_event(paced,SDL_EVENT_WINDOW_FOCUS_GAINED);paced.poll();
        key_event(paced,SDL_SCANCODE_ESCAPE,true);require(!paced.poll(),"Escape did not quit focused host");++checks;
    }
    checks+=test_completed_frame_effects();
    checks+=test_input_profiles();
    std::cout<<checks<<" desktop upload/readback/input/pause/output groups passed\n";return 0;
}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}}
