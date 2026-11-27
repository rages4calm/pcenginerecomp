#include "pce/desktop.hpp"
#include "pce/runtime.hpp"
#include <SDL3/SDL.h>
#include <iostream>

namespace {
unsigned checks=0;
void require(bool good,const char* message) {++checks;if(!good)throw pce::Fault(message);}
template<class F>void refuses(F operation) {
    ++checks;try{operation();}catch(const pce::Fault&){return;}throw pce::Fault("expected settings refusal");
}
void event(pce::DesktopHost& host,SDL_EventType type) {
    SDL_Event value{};value.type=type;value.window.windowID=host.window_id();
    require(SDL_PushEvent(&value),"push window event");
}
void key(pce::DesktopHost& host,bool down,bool repeat=false) {
    SDL_Event value{};value.type=down ? SDL_EVENT_KEY_DOWN:SDL_EVENT_KEY_UP;
    value.key.windowID=host.window_id();value.key.scancode=SDL_SCANCODE_RETURN;
    value.key.down=down;value.key.repeat=repeat;
    require(SDL_PushEvent(&value),"push confirmation key");
}
}
int main() {
    pce::ShaderParameters params;
    require(params.valid(),"default shader settings invalid");
    const auto uniforms=params.uniforms();
    require(uniforms[0]==0.24f && uniforms[1]==0.22f && uniforms[2]==0.26f && uniforms[3]==0.08f &&
            uniforms[4]==1.0f && uniforms[5]==1.0f,"default uniform values differ");
    for(auto member:{&pce::ShaderParameters::scanline,&pce::ShaderParameters::mask,
                    &pce::ShaderParameters::grid,&pce::ShaderParameters::vignette}) {
        auto bounded=params;bounded.*member=100;require(bounded.valid(),"effect boundary rejected");
        bounded.*member=101;require(!bounded.valid(),"effect overflow admitted");
    }
    for(auto member:{&pce::ShaderParameters::brightness,&pce::ShaderParameters::saturation}) {
        auto bounded=params;bounded.*member=200;require(bounded.valid(),"color boundary rejected");
        bounded.*member=201;require(!bounded.valid(),"color overflow admitted");
    }
    params.brightness=201;
    refuses([&]{pce::DesktopHost invalid({.shader_parameters=params});});
    pce::DesktopHost host({.hidden=true,.paced=false});
    host.present({2,2,{255,0,0,0,255,0,0,0,255,255,255,255}});
    host.poll();
    const auto original=host.display_settings();
    auto next=original;next.width=512;next.height=384;next.mode=pce::DisplayMode::square;next.filter=pce::DisplayFilter::linear;
    const auto frames=host.stats().presented;
    host.preview_display(next,1000);
    require(host.display_change_pending() && host.display_settings()==next,"preview not applied");
    refuses([&]{host.preview_display(original);});
    refuses([&]{host.resize_window(256,240);});
    host.cancel_display();
    require(!host.display_change_pending() && host.display_settings()==original,"cancel did not restore settings");
    refuses([&]{host.confirm_display();});refuses([&]{host.cancel_display();});
    host.preview_display(next,1000);host.confirm_display();
    require(!host.display_change_pending() && host.display_settings()==next,"confirmed settings lost");
    host.preview_display(original,5);SDL_Delay(12);host.poll();
    require(!host.display_change_pending() && host.display_settings()==next,"timer did not rollback while paused");
    host.preview_display(original,5);SDL_Delay(12);refuses([&]{host.confirm_display();});
    require(host.display_settings()==next,"expired confirmation committed");
    host.preview_display(original,1000);event(host,SDL_EVENT_WINDOW_FOCUS_LOST);host.poll();
    require(!host.display_change_pending() && host.display_settings()==next,"focus loss did not rollback");
    event(host,SDL_EVENT_WINDOW_FOCUS_GAINED);host.poll();
    host.preview_display(original,1000);key(host,true);host.poll();
    require(!host.display_change_pending() && host.buttons()==0,"confirmation leaked guest input");
    key(host,true,true);host.poll();
    for(unsigned slot=0;slot<5;++slot)require(host.buttons(slot)==0,"confirmation repeat leaked to guest");
    key(host,false);host.poll();
    key(host,true);host.poll();require(host.buttons()==8,"released Run binding did not recover");
    host.preview_display(next,1000);
    require(host.buttons()==0,"held Run persisted into display prompt");
    key(host,false);host.poll();host.cancel_display();
    host.preview_display(next,5);SDL_Delay(12);key(host,true);host.poll();
    require(!host.display_change_pending() && host.buttons()==0,"expired prompt leaked queued confirmation");
    key(host,false);host.poll();
    host.preview_display(next,1000);host.confirm_display();
    for(const unsigned timeout:{0u,30001u})refuses([&]{host.preview_display(original,timeout);});
    auto bad=next;bad.width=127;refuses([&]{host.preview_display(bad);});
    bad=next;bad.mode=static_cast<pce::DisplayMode>(99);refuses([&]{host.preview_display(bad);});
    require(host.stats().presented==frames,"settings aged guest publication/input pulses");
    require(host.renderer_backend()=="software","dummy test used unexpected renderer");
    refuses([&]{host.set_shader_parameters(params);});
    host.set_shader_parameters({.brightness=0});
    require(host.display_settings()==next,"shader parameters changed window settings");
    std::cout<<checks<<" authored display confirmation/rollback/shader-bound checks passed\n";
}
