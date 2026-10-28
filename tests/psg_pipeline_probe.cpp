// Authored one-instruction CPU fixture followed by device-clock continuation.
// The first audio edge occurs inside the instruction; no source observer hook
// exists there. Only subsequent held sums are directly observed by this probe.
#include "pce/runtime.hpp"
#include "psg_phase_fixture.hpp"
#include <iostream>
#include <memory>
#include <string>
#include <vector>
namespace {
constexpr unsigned frames=2048,partition=512;
constexpr std::uint64_t master=21477273,rate=44100;
std::uint64_t edge(unsigned frame){return (std::uint64_t(frame)*master+rate-1)/rate;}
template<class T>void array(const T& values){std::cout<<'[';bool comma=false;for(auto v:values){std::cout<<(comma?",":"")<<+v;comma=true;}std::cout<<']';}
template<class T>void rows(const T& values){std::cout<<'[';bool comma=false;for(auto v:values){std::cout<<(comma?",":"");array(v);comma=true;}std::cout<<']';}
}
int main(int argc,char** argv){try{
 if(argc!=5)throw std::runtime_error("usage: probe CASE DIVISOR native|interpreted raw|filtered");
 const auto speed=std::stoul(argv[2]);if(speed!=3&&speed!=12)throw std::runtime_error("invalid divisor");
 const bool native=std::string(argv[3])=="native";if(!native&&std::string(argv[3])!="interpreted")throw std::runtime_error("invalid tier");
 const bool filtered=std::string(argv[4])=="filtered";if(!filtered&&std::string(argv[4])!="raw")throw std::runtime_error("invalid profile");
 const PhaseCase* item=nullptr;for(const auto& c:phase_cases)if(c.name==std::string(argv[1]))item=&c;if(!item)throw std::runtime_error("unknown authored case");const auto& c=*item;
 auto ptr=std::make_unique<pce::Bus>();auto& b=*ptr;pce::Cpu s;b.kind[0]=pce::BankKind::rom;b.kind[248]=pce::BankKind::ram;b.enable_psg();b.enable_audio_output(filtered?pce::AudioProfile::filtered:pce::AudioProfile::raw,44100,pce::AudioTiming::gear);
 if(c.size==7&&c.data[2]==0)b.enable_vdc();
 s.mpr=phase_mpr;s.pc=c.pc;s.a=31;s.x=s.y=1;s.p=pce::I|pce::C;s.clock_divisor=speed;
 for(unsigned i=0;i<c.size;++i)(*b.bytes)[b.physical(s,c.pc+i)]=c.data[i];
 for(unsigned i=0;i<4;++i)(*b.bytes)[(248<<13)+0x200+i]=31;
 (*b.bytes)[(248<<13)+0x20]=6;(*b.bytes)[(248<<13)+0x21]=8;(*b.bytes)[(248<<13)+0x22]=5;(*b.bytes)[(248<<13)+0x23]=8;
 b.write(s,0x0800,0);b.write(s,0x0801,255);b.write(s,0x0804,223);b.write(s,0x0805,255);b.write(s,0x0806,c.old_dda);b.write(s,0x080a,31);
 const auto start=488-(c.size==7?19:4)*speed;s.ticks=start;b.sync(s);
 if((native?pce::generated_step(b,s,UINT64_MAX):pce::interpret_step(b,s,UINT64_MAX))!=pce::Exit::executed)throw std::runtime_error("guest instruction did not execute");
 const auto end=s.ticks;
 std::vector<std::array<std::int32_t,2>> sums;
 std::vector<std::array<std::int16_t,2>> samples;
 std::vector<unsigned> drains;
 for(unsigned frame=2;frame<=frames;++frame){
  const auto target=edge(frame);b.clock_cpu(s,unsigned((target-s.ticks+speed-1)/speed));
  sums.push_back(b.psg.held_sum());
  if(frame%partition==0){auto part=b.pcm.drain();if(part.size()!=partition*2)throw std::runtime_error("partition count differs");for(unsigned i=0;i<part.size();i+=2)samples.push_back({part[i],part[i+1]});drains.push_back(frame);}
 }
 std::cout<<"{\"case\":\""<<c.name<<"\",\"divisor\":"<<speed<<",\"pc\":"<<c.pc<<",\"mpr\":";array(s.mpr);std::cout<<",\"physical\":[";
 for(unsigned i=0;i<c.size;++i)std::cout<<(i?",":"")<<b.physical(s,c.pc+i);std::cout<<"],\"bytes\":[";
 for(unsigned i=0;i<c.size;++i)std::cout<<(i?",":"")<<unsigned(c.data[i]);
 std::cout<<"],\"start\":"<<start<<",\"end\":"<<end<<",\"final_pc\":"<<s.pc<<",\"dda\":"<<unsigned(b.psg.channels[0].dda)<<",\"native\":"<<s.native_steps<<",\"interpreted\":"<<s.interpreter_steps<<",\"profile\":\""<<argv[4]<<"\",\"rate\":44100,\"frames\":"<<b.pcm.frames<<",\"continuation_end\":"<<s.ticks<<",\"partition_end_frames\":";array(drains);
 std::cout<<",\"source_ticks\":[";for(unsigned frame=1;frame<=frames;++frame)std::cout<<(frame>1?",":"")<<edge(frame);std::cout<<"],\"observed_source_first_frame\":2,\"observed_source_sums\":";rows(sums);std::cout<<",\"pcm\":";rows(samples);std::cout<<"}\n";
 return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
