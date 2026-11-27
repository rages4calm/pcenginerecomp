// Small authored renderer probe. No ROM, guest execution or fullscreen changes.
#include "pce/desktop.hpp"
#include "pce/runtime.hpp"
#include <SDL3/SDL.h>
#include <filesystem>
#include <iostream>
#include <string>

int main(int argc,char** argv) {
    try {
        std::string backend,shader_name,path;
        for(int i=1;i<argc;i+=2) {
            if(i+1==argc)throw pce::Fault("missing probe option value");
            const std::string name=argv[i];
            auto* dest=name=="--backend" ? &backend:name=="--shader" ? &shader_name:name=="--out" ? &path:nullptr;
            if(!dest || !dest->empty())throw pce::Fault("unknown or repeated probe option");
            *dest=argv[i+1];
        }
        if((backend!="software" && backend!="direct3d12" && backend!="vulkan") ||
           path.empty() || std::filesystem::exists(std::filesystem::u8path(path)))
            throw pce::Fault("probe requires explicit backend and new output path");
        auto shader=pce::DisplayShader::off;
        if(shader_name=="sharp")shader=pce::DisplayShader::sharp;
        else if(shader_name=="crt")shader=pce::DisplayShader::crt;
        else if(shader_name=="smooth")shader=pce::DisplayShader::smooth;
        else if(shader_name=="lcd")shader=pce::DisplayShader::lcd;
        else if(shader_name=="mono")shader=pce::DisplayShader::mono;
        else if(shader_name=="crt-mask")shader=pce::DisplayShader::crt_mask;
        else if(shader_name!="off")throw pce::Fault("unknown probe shader");
        if(backend=="software" && shader!=pce::DisplayShader::off)
            throw pce::Fault("software SDL probe requires shader off");
        // Explicit backend selection with no renderer fallback.
        SDL_SetHintWithPriority(SDL_HINT_RENDER_DRIVER,backend.c_str(),SDL_HINT_OVERRIDE);
        SDL_SetHintWithPriority(SDL_HINT_GPU_DRIVER,backend.c_str(),SDL_HINT_OVERRIDE);
        pce::DesktopHost host({.title="Bounded authored display probe",.scale=1,.hidden=true,.paced=false,
            .display_mode=pce::DisplayMode::square,.display_shader=shader});
        if(host.renderer_backend()!=backend)throw pce::Fault("probe selected an unexpected renderer");
        pce::VideoFrame frame{64,64,std::vector<std::uint8_t>(64*64*3)};
        for(unsigned y=0;y<64;++y)for(unsigned x=0;x<64;++x) {
            const auto offset=(y*64+x)*3;
            frame.rgb[offset]=static_cast<std::uint8_t>(x*4);
            frame.rgb[offset+1]=static_cast<std::uint8_t>(y*4);
            frame.rgb[offset+2]=((x/8+y/8)&1) ? 224:32;
        }
        for(unsigned n=0;n<2;++n) {
            if(!host.poll())throw pce::Fault("probe window closed");
            host.present(frame);
        }
        const auto output=host.readback();
        if(output.width!=256 || output.height!=240 || output.rgb.size()!=256*240*3)
            throw pce::Fault("probe readback extent differs");
        pce::write_ppm(output,path);
        // A literal zero-brightness expectation also tests uniform updates.
        if(shader!=pce::DisplayShader::off) {
            pce::ShaderParameters dark;dark.brightness=0;
            host.set_shader_parameters(dark);host.redraw(frame);
            const auto black=host.readback();
            for(const auto byte:black.rgb)if(byte)throw pce::Fault("zero brightness readback was not black");
        }
        std::cout<<"{\"backend\":\""<<backend<<"\",\"shader\":\""<<shader_name
                 <<"\",\"frames\":2,\"width\":256,\"height\":240}\n";
        return 0;
    } catch(const std::exception& error) {
        std::cerr<<error.what()<<'\n';return 2;
    }
}
