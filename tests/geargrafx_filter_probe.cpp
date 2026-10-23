// Authored API-only wrapper around external, unmodified GPL Geargrafx sources.
// This executable is built privately, separately from the MIT runtime. It uses
// actual Sample/EndFrame output, never a reimplementation of reference filters.
#include "huc6280_psg.h"
#include "adpcm.h"
#include "cdrom.h"
#include "geargrafx_core.h"
#include <algorithm>
#include <cstring>
#include <fstream>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>

bool g_mcp_stdio_mode=true;
int main(int argc,char** argv) {
    try {
        if(argc!=4)throw std::runtime_error("usage: gear-filter-probe psg|adpcm PLAN CHUNK");
        const bool mode=std::string(argv[1])=="adpcm";
        if(!mode && std::string(argv[1])!="psg")throw std::runtime_error("unknown source");
        const auto chunk=std::stoul(argv[3]);if(!chunk || chunk>512)throw std::runtime_error("invalid chunk");
        std::ifstream input(argv[2]);if(!input)throw std::runtime_error("cannot open plan");
        HuC6280PSG p;p.Init();GeargrafxCore core;
        Adpcm* adpcm=nullptr;CdRom* cd=nullptr;
        if(mode) {core.Init(nullptr);adpcm=core.GetAdpcm();cd=core.GetCDROM();}
        bool first=true;unsigned buffered=0;int a=0,b=0;std::string op;
        std::cout<<'[';
        const auto flush=[&] {
            if(!buffered)return;
            s16 data[GG_AUDIO_BUFFER_SIZE];const auto count=p.EndFrame(data);
            if(count!=int(buffered*2))throw std::runtime_error("reference PSG output length changed");
            for(int i=0;i<count;i+=2){if(!first)std::cout<<',';first=false;std::cout<<'['<<data[i]<<','<<data[i+1]<<']';}
            buffered=0;
        };
        const auto adpcm_input=[&](unsigned value,unsigned gain) {
            // Only the authored predictor input changes. SaveState/LoadState
            // retain reference filter history; no private object access or
            // reference source mutation is used. Layout is pinned by adapter.
            std::ostringstream saved(std::ios::binary);adpcm->SaveState(saved);auto bytes=saved.str();
            if(bytes.size()!=65599)throw std::runtime_error("reference ADPCM v44 layout changed");
            const u16 decoder=static_cast<u16>(value);std::memcpy(bytes.data()+65572,&decoder,2);
            std::istringstream restore(bytes,std::ios::binary);adpcm->LoadState(restore,44);
            // A valid initialized CD object supplies the real fader API. At
            // zero master time a zero-duration enabled fader has target zero;
            // disabled fader has target one. No firmware or transport is run.
            std::ostringstream cd_saved(std::ios::binary);cd->SaveState(cd_saved);auto cd_bytes=cd_saved.str();
            if(cd_bytes.size()!=35)throw std::runtime_error("reference CD v44 layout changed");
            cd_bytes[16]=gain ? 0:1;cd_bytes[17]=1;
            std::fill(cd_bytes.begin()+19,cd_bytes.end(),0);
            std::istringstream cd_restore(cd_bytes,std::ios::binary);cd->LoadState(cd_restore,44);
            adpcm->Sample();s16 data[GG_AUDIO_BUFFER_SIZE];const auto count=adpcm->EndFrame(data);
            if(count!=2)throw std::runtime_error("reference ADPCM output length changed");
            if(!first)std::cout<<',';first=false;std::cout<<'['<<data[0]<<','<<data[1]<<']';
        };
        while(input>>op) {
            if(op=="r" && input>>a && a>=0 && a<=1) {
                flush();p.Reset();p.EnableHuC6280A(a!=0);if(mode)adpcm->Reset();
            } else if(!mode && op=="w" && input>>a>>b && a>=0 && a<=15 && b>=0 && b<=255) {
                p.Write(static_cast<u16>(a),static_cast<u8>(b));
            } else if(!mode && op=="s" && input>>a && a>0 && a<=10000000) {
                p.Clock(static_cast<u32>(a));p.Sample();if(++buffered==chunk)flush();
            } else if(!mode && op=="x" && input>>a>>b && a>=-196608 && a<=196602 && b>=-196608 && b<=196602) {
                p.Clock(1);p.Sample();auto* channels=p.GetState()->CHANNELS;
                int values[2]={a,b};
                for(unsigned channel=0;channel<6;++channel)for(unsigned side=0;side<2;++side) {
                    const auto part=std::clamp(values[side],-32768,32767);values[side]-=part;
                    channels[channel].output[buffered*2+side]=static_cast<s16>(part);
                }
                if(++buffered==chunk)flush();
            } else if(mode && op=="a" && input>>a>>b && a>=0 && a<=4095 && b>=0 && b<=1) {
                adpcm_input(static_cast<unsigned>(a),static_cast<unsigned>(b));
            } else if(mode && op=="v" && input>>a && a>=0 && a<=15) {
                adpcm->Write(0x0e,static_cast<u8>(a));
            } else throw std::runtime_error("invalid authored filter plan");
        }
        if(!input.eof())throw std::runtime_error("truncated filter plan");flush();std::cout<<"]\n";
    } catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
