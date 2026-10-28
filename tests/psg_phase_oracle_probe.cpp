// Observer only: host-authored initial state, then one actual guest instruction.
// Toolkit output includes fixed /3 presentation headroom; original PSG is raw.
#include "pce/runtime.hpp"
#include "psg_phase_fixture.hpp"
#include <iostream>
#include <memory>
#include <string>
int main(int argc,char** argv){try{
 if(argc!=4)throw std::runtime_error("usage: probe CASE DIVISOR native|interpreted");
 const auto speed=std::stoul(argv[2]);if(speed!=3&&speed!=12)throw std::runtime_error("invalid divisor");
 const bool native=std::string(argv[3])=="native";if(!native&&std::string(argv[3])!="interpreted")throw std::runtime_error("invalid tier");
 const PhaseCase* item=nullptr;for(const auto& c:phase_cases)if(c.name==std::string(argv[1]))item=&c;if(!item)throw std::runtime_error("unknown authored case");const auto& c=*item;
 auto ptr=std::make_unique<pce::Bus>();auto& b=*ptr;pce::Cpu s;b.kind[0]=pce::BankKind::rom;b.kind[248]=pce::BankKind::ram;b.enable_psg();b.enable_audio_output();
 if(c.size==7&&c.data[2]==0)b.enable_vdc();
 s.mpr=phase_mpr;s.pc=c.pc;s.a=31;s.x=s.y=1;s.p=pce::I|pce::C;s.clock_divisor=speed;
 for(unsigned i=0;i<c.size;++i)(*b.bytes)[b.physical(s,c.pc+i)]=c.data[i];
 for(unsigned i=0;i<4;++i)(*b.bytes)[(248<<13)+0x200+i]=31;
 (*b.bytes)[(248<<13)+0x20]=6;(*b.bytes)[(248<<13)+0x21]=8;(*b.bytes)[(248<<13)+0x22]=5;(*b.bytes)[(248<<13)+0x23]=8;
 b.write(s,0x0800,0);b.write(s,0x0801,255);b.write(s,0x0804,223);b.write(s,0x0805,255);b.write(s,0x0806,c.old_dda);b.write(s,0x080a,31);
 const auto start=488-(c.size==7?19:4)*speed;s.ticks=start;b.sync(s);
 if((native?pce::generated_step(b,s,UINT64_MAX):pce::interpret_step(b,s,UINT64_MAX))!=pce::Exit::executed)throw std::runtime_error("guest instruction did not execute");
 const auto end=s.ticks;b.clock_cpu(s,unsigned((1200-s.ticks)/speed));
 auto samples=b.pcm.drain();std::cout<<"{\"case\":\""<<c.name<<"\",\"divisor\":"<<speed<<",\"pc\":"<<c.pc<<",\"mpr\":[";
 for(unsigned i=0;i<8;++i)std::cout<<(i?",":"")<<unsigned(s.mpr[i]);std::cout<<"],\"physical\":[";
 for(unsigned i=0;i<c.size;++i)std::cout<<(i?",":"")<<b.physical(s,c.pc+i);std::cout<<"],\"bytes\":[";
 for(unsigned i=0;i<c.size;++i)std::cout<<(i?",":"")<<unsigned(c.data[i]);
 std::cout<<"],\"start\":"<<start<<",\"end\":"<<end<<",\"final_pc\":"<<s.pc<<",\"dda\":"<<unsigned(b.psg.channels[0].dda)<<",\"native\":"<<s.native_steps<<",\"interpreted\":"<<s.interpreter_steps<<",\"pcm\":[";
 for(unsigned i=0;i<samples.size();++i)std::cout<<(i?",":"")<<samples[i];std::cout<<"]}\n";return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
