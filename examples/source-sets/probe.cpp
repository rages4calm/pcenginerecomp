// Authored RAM-to-firmware calls; neither source is an observation capture.
#include "pce/runtime.hpp"
#include "pce/code_capture.hpp"
#include "cases.hpp"
#include <algorithm>
#include <array>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <iterator>
#include <memory>
#include <string>
#include <vector>
static void require(bool v,const char* text){if(!v)throw std::runtime_error(text);}
static auto path(const char* s){return std::filesystem::path(std::u8string(reinterpret_cast<const char8_t*>(s)));}
static auto read(const char* s){std::ifstream input(path(s),std::ios::binary);return std::vector<std::uint8_t>((std::istreambuf_iterator<char>(input)),{});}
int main(int argc,char** argv){try{
 require(argc==5,"usage: source-set-probe payload bios mode capture");const std::string mode=argv[3];
 const bool reference=mode=="reference",changed_payload=mode=="changed-payload",changed_bios=mode=="changed-bios",changed=changed_payload||changed_bios;
 require(reference||changed||mode=="native","invalid mode");const auto payload=read(argv[1]),bios=read(argv[2]);
 require(payload.size()==65536&&bios.size()==262144,"source size");
 pce::CodeCapture capture(path(argv[4]),16384);std::uint64_t native=0,interpreted=0,guards=0;
 for(unsigned n=0;n<(changed?1:case_count);++n){const auto& c=cases[n];auto bus=std::make_unique<pce::Bus>();pce::Cpu s;
  for(unsigned bank=0;bank<32;++bank)bus->kind[bank]=pce::BankKind::rom;
  for(unsigned bank=0x80;bank<=0x87;++bank)bus->kind[bank]=pce::BankKind::ram;
  bus->enable_work_ram_mirrors();bus->kind[0xFF]=pce::BankKind::io;bus->load(0,bios.data(),bios.size());bus->load(0x100000,payload.data(),payload.size());
  s.pc=c.pc;s.sp=255;s.clock_divisor=3;std::copy_n(c.initial,8,s.mpr.begin());const auto steps=changed_payload?5U:changed_bios?13U:c.steps;
  for(unsigned i=0;i<steps;++i){const auto before=capture.before(*bus,s);
   require(pce::step(*bus,s,100000,reference?pce::ExecutionPolicy::interpreter_only:pce::ExecutionPolicy::native_only)==pce::Exit::executed,"unexpected refusal");capture.after(before,s);
   const auto& e=c.cpu[i+1];require(s.pc==e.pc&&s.a==e.a&&s.x==e.x&&s.y==e.y&&s.sp==e.sp&&s.p==e.p,"literal CPU boundary");
   require(std::equal(s.mpr.begin(),s.mpr.end(),i>=4?c.final:c.initial),"literal MPR boundary");}
  if(changed){const std::uint8_t byte=0x43;const auto pa=(std::uint32_t(s.mpr[s.pc>>13])<<13)|(s.pc&8191);bus->load(pa+1,&byte,1);
   const auto old=s;const auto memory=std::make_unique<std::array<std::uint8_t,0x200000>>(*bus->bytes);const auto generations=bus->generation;
   require(pce::step(*bus,s,100000,pce::ExecutionPolicy::native_only)==pce::Exit::miss,"changed source accepted");
   require(s.pc==old.pc&&s.a==old.a&&s.x==old.x&&s.y==old.y&&s.sp==old.sp&&s.p==old.p&&s.mpr==old.mpr&&s.mpr_latch==old.mpr_latch&&s.cycles==old.cycles&&s.ticks==old.ticks,"guard CPU effects");
   require(*memory==*bus->bytes&&generations==bus->generation,"guard memory effects");
  }else{
   require(s.pc==c.end&&s.a==0x43&&s.x==3&&s.y==4&&s.sp==255&&s.p==4,"CPU endpoint");
   require(s.cycles==80&&s.ticks==942&&std::equal(s.mpr.begin(),s.mpr.end(),c.final),"clocks/mapping");
   for(unsigned i=0;i<8192;++i){const auto value=bus->peek(0x1F0000+i);require(value&&*value==(i==1?c.tag:expected_ram[i]),"literal full WRAM");}
   for(unsigned i=0;i<payload.size();++i){const auto value=bus->peek(0x100000+i);require(value&&*value==payload[i],"full CD RAM");}
  }
  require(s.native_steps==(reference?0U:steps)&&s.interpreter_steps==(reference?steps:0U)&&s.guard_misses==(changed?1U:0U),"tier counts");native+=s.native_steps;interpreted+=s.interpreter_steps;guards+=s.guard_misses;
 }
 capture.finish();std::cout<<"{\"passed\":true,\"cases\":"<<(changed?1:case_count)<<",\"native\":"<<native<<",\"interpreted\":"<<interpreted<<",\"guards\":"<<guards<<"}\n";
}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}}
