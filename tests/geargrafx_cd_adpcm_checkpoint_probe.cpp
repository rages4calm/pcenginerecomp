// Original register/device core only; no guest CPU calls or imported state.
#define main prior_authored_sense_main
#define Adapter BaseCdAdapter
#include "geargrafx_sense_probe.cpp"
#undef Adapter
#undef main
#include "cd_adpcm_checkpoint_support.hpp"
struct DmaCycles {using type=s32 Adpcm::*;friend type observe(DmaCycles);};
struct WriteCycles {using type=s32 Adpcm::*;friend type observe(WriteCycles);};
struct AckCycles {using type=s32 ScsiController::*;friend type observe(AckCycles);};
template<class Tag,typename Tag::type Member>struct ObserveMember {friend typename Tag::type observe(Tag){return Member;}};
template struct ObserveMember<DmaCycles,&Adpcm::m_dma_cycles>;
template struct ObserveMember<WriteCycles,&Adpcm::m_write_cycles>;
template struct ObserveMember<AckCycles,&ScsiController::m_auto_ack_cycles>;
struct Adapter:BaseCdAdapter {
 unsigned divisor;std::uint64_t single_calls=0,coarse_calls=0,single_ticks=0,coarse_ticks=0;std::vector<dma_checkpoint::Mark> journal;
 Adapter(const std::vector<std::uint8_t>& image,const char* cue,unsigned div):BaseCdAdapter{nullptr,image,cue},divisor(div){reset(1);core->GetMedia()->SetCDROMType(GG_CDROM_STANDARD);dma_checkpoint::require(core->LoadBiosFromBuffer(image.data(),int(image.size()),true)&&core->LoadMedia(cue,false)&&core->GetMedia()->IsCDROMHardwareEnabled(),"original CD hardware setup");}
 void tick(unsigned n,bool single){if(single){++single_calls;single_ticks+=n;}else{++coarse_calls;coarse_ticks+=n;}BaseCdAdapter::advance(n);}
 void advance(unsigned n){if((dma()&3)||write_remaining()){for(unsigned i=0;i<n;++i)tick(1,true);}else tick(n,false);}
 void advance_safe(unsigned n){dma_checkpoint::require(!request()&&(!(dma()&3)||!dma_remaining())&&!write_remaining(),"unsafe original coarse wait");const auto before=dma_remaining(),len=length(),address=write_address(),head=core->GetCDROMMedia()->GetCurrentSector();const auto bytes=ram();tick(n,false);dma_checkpoint::require(ram()==bytes&&length()==len&&write_address()==address&&core->GetCDROMMedia()->GetCurrentSector()==head,"coarse original wait transferred data");if(!(dma()&3))dma_checkpoint::require(dma_remaining()==before,"coarse original wait changed frozen DMA residual");}
 void write(unsigned address,unsigned value){core->GetCDROM()->WriteRegister(address,value);advance(5*divisor);}
 unsigned read(unsigned address){auto value=core->GetCDROM()->ReadRegister(address);advance(5*divisor);return value;}
 unsigned load_wait()const{auto value=*core->GetScsiController()->GetState()->NEXT_LOAD_CYCLES;dma_checkpoint::require(value>0&&value<10000000,"pending original load");return value;}
 bool ack()const{return core->GetScsiController()->IsSignalSet(ScsiController::SCSI_SIGNAL_ACK);}
 unsigned dma()const{return *core->GetAdpcm()->GetState()->DMA;}
 unsigned dma_remaining()const{return std::max(0,core->GetAdpcm()->*observe(DmaCycles{}));}
 unsigned write_remaining()const{return std::max(0,core->GetAdpcm()->*observe(WriteCycles{}));}
 unsigned write_address()const{return *core->GetAdpcm()->GetState()->WRITE_ADDRESS;}
 unsigned length()const{return *core->GetAdpcm()->GetState()->LENGTH;}
 unsigned half()const{return *core->GetAdpcm()->GetState()->HALF_IRQ;}
 unsigned end()const{return *core->GetAdpcm()->GetState()->END_IRQ;}
 unsigned irq()const{auto*s=core->GetCDROM()->GetState();return (*s->ENABLED_IRQS&*s->ACTIVE_IRQS)!=0;}
 std::string error_state()const{return "original register-driven observer";}
 std::vector<unsigned> ram()const{auto*data=core->GetAdpcm()->GetRAM();return {data,data+65536};}
 std::vector<std::uint64_t> snapshot()const{auto*c=core->GetCDROM()->GetState();return {core->GetMasterClockCycles(),signals(),dma(),dma_remaining(),write_remaining(),write_address(),length(),half(),end(),irq(),*c->ACTIVE_IRQS,*c->ENABLED_IRQS,static_cast<unsigned>(std::max(0,core->GetScsiController()->*observe(AckCycles{})))};}
};
int main(int argc,char**argv){try{dma_checkpoint::require(argc==4,"PLAN ROM CUE");auto p=dma_checkpoint::plan(argv[1]);auto image=reset_probe::rom(argv[2]);Adapter a(image,argv[3],p.divisor);dma_checkpoint::prefix(a,p);auto cut=a.snapshot();auto reply=dma_checkpoint::suffix(a,p);
 std::cout<<"{\"cut\":";dma_checkpoint::vector_json(cut);std::cout<<",\"prefix\":[],\"reply\":";dma_checkpoint::reply_json(reply);std::cout<<",\"guest_cpu_calls\":0,\"single_clock_calls\":"<<a.single_calls<<",\"single_clock_ticks\":"<<a.single_ticks<<",\"coarse_clock_calls\":"<<a.coarse_calls<<",\"coarse_clock_ticks\":"<<a.coarse_ticks<<",\"final_ticks\":"<<a.core->GetMasterClockCycles()<<",\"journal\":";dma_checkpoint::journal_json(a.journal);std::cout<<"}\n";return 0;
 }catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
