// Authored declared-only routine; real native execution, no fabricated hits.
#include "pce/runtime.hpp"
#include "pce/code_capture.hpp"
#include <array>
#include <fstream>
#include <iostream>
#include <iterator>
#include <memory>
#include <vector>

static void require(bool ok,const char* message) {if(!ok)throw std::runtime_error(message);}
int main(int argc,char** argv) {
 try {
  require(argc==4,"usage: declared-probe card normal|guard new-capture");
  const bool guard=std::string(argv[2])=="guard";
  require(guard || std::string(argv[2])=="normal","unknown mode");
  std::ifstream input(argv[1],std::ios::binary);
  std::vector<std::uint8_t> image((std::istreambuf_iterator<char>(input)),{});
  require(image.size()==8192,"authored image size");
  if(guard)image[0x41]=43; // Separate host-assisted negative, original file unchanged.
  auto bus=std::make_unique<pce::Bus>();pce::Cpu cpu;
  bus->configure_hucard(pce::HuCardProfile::base,image);bus->power_on_cpu(cpu);
  auto capture=std::make_unique<pce::CodeCapture>(argv[3],64);
  auto retire=[&] {
   const auto pending=capture->before(*bus,cpu);
   require(pce::step(*bus,cpu,100000,pce::ExecutionPolicy::native_only)==pce::Exit::executed,
           "native instruction did not retire");
   capture->after(pending,cpu);
  };
  for(unsigned i=0;i<100;++i)retire();
  require(cpu.pc==0xE00B && cpu.a==0 && cpu.x==255 && cpu.y==0 && cpu.sp==255 && cpu.p==6,
          "literal unexecuted-routine prefix registers");
  require(cpu.cycles==442 && cpu.ticks==1407 && cpu.native_steps==100 && cpu.interpreter_steps==0 && cpu.guard_misses==0,
          "literal prefix clocks/tiers");
  for(unsigned i=0;i<8192;++i)require(bus->peek(0x1F0000+i)==0,"initial whole WRAM");
  const auto before=cpu.ticks;
  bus->write(cpu,0x2000,1); // Developer-assisted trigger, not a guest retirement.
  require(cpu.ticks==before && cpu.native_steps==100,"host trigger changed clocks/retirements");
  for(unsigned i=0;i<(guard?4U:10U);++i)retire();
  if(guard) {
   require(cpu.pc==0xE040 && cpu.native_steps==104 && cpu.cycles==460 && cpu.ticks==1461,
           "guard entry literal boundary");
   const auto ticks=cpu.ticks,cycles=cpu.cycles,retired=cpu.native_steps;
   require(pce::step(*bus,cpu,100000,pce::ExecutionPolicy::native_only)==pce::Exit::miss,
           "changed declared ROM operand accepted");
   require(cpu.pc==0xE040 && cpu.ticks==ticks && cpu.cycles==cycles && cpu.native_steps==retired &&
           cpu.interpreter_steps==0 && cpu.guard_misses==1,"guard miss changed retired state");
  } else {
   require(cpu.pc==0xE00B && cpu.a==0 && cpu.x==255 && cpu.sp==255 && cpu.p==6 && cpu.cycles==488 && cpu.ticks==1545 &&
           cpu.native_steps==110 && cpu.interpreter_steps==0 && cpu.guard_misses==0,"literal suffix endpoint");
   std::array<std::uint8_t,8192> expected{};expected[1]=42;expected[0x1FE]=0x0F;expected[0x1FF]=0xE0;
   for(unsigned i=0;i<expected.size();++i)require(bus->peek(0x1F0000+i)==expected[i],"literal final whole WRAM");
  }
  capture->finish();
  std::cout<<"{\"passed\":true,\"mode\":\""<<(guard?"guard":"normal")<<"\",\"native\":"<<cpu.native_steps
           <<",\"interpreted\":"<<cpu.interpreter_steps<<",\"guards\":"<<cpu.guard_misses
           <<",\"cycles\":"<<cpu.cycles<<",\"ticks\":"<<cpu.ticks<<"}\n";
 }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
