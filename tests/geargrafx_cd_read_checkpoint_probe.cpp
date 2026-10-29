// Original core transport, driven through registers; zero guest CPU calls.
#define main old_authored_sense_main
#define Adapter OriginalCdAdapter
#include "geargrafx_sense_probe.cpp"
#undef main
#undef Adapter
#include "cd_read_checkpoint_support.hpp"
struct Adapter:OriginalCdAdapter {
    unsigned divisor;
    Adapter(const std::vector<std::uint8_t>& rom,const char* cue,unsigned speed):OriginalCdAdapter{nullptr,rom,cue},divisor(speed){reset(1);}
    void select(){OriginalCdAdapter::select();advance(5*divisor);}
    void write_data(unsigned v){OriginalCdAdapter::write_data(v);advance(5*divisor);}
    void ack(bool v){OriginalCdAdapter::ack(v);advance(5*divisor);}
    unsigned read_data(bool automatic){const auto value=OriginalCdAdapter::read_data(automatic);advance(5*divisor);return value;}
    void reset_line(bool v){core->GetCDROM()->WriteRegister(0x1804,v?2:0);advance(5*divisor);}
    unsigned load_wait()const{const auto n=*core->GetScsiController()->GetState()->NEXT_LOAD_CYCLES;if(n<=0||n>10000000)throw std::runtime_error("bounded pending original load required");return static_cast<unsigned>(n);}
};
int main(int argc,char** argv) {
    try {
        if(argc!=4)throw std::runtime_error("PLAN ROM CUE");const auto p=cd_checkpoint::plan(argv[1]);
        const auto rom=reset_probe::rom(argv[2]);Adapter a(rom,argv[3],p.divisor);
        const auto prefix=cd_checkpoint::prefix(a,p);const auto* state=a.core->GetScsiController()->GetState();
        const std::vector<unsigned> cut{static_cast<unsigned>(*state->PHASE),unsigned(*state->SIGNALS),unsigned(a.core->GetScsiController()->IsSignalSet(ScsiController::SCSI_SIGNAL_ACK)),*state->LOAD_SECTOR,*state->LOAD_SECTOR_COUNT,a.core->GetCDROMMedia()->GetCurrentSector()};
        const auto reply=cd_checkpoint::suffix(a,p);
        std::cout<<"{\"cut\":";cd_checkpoint::vector_json(cut);std::cout<<",\"prefix\":";cd_checkpoint::vector_json(prefix);std::cout<<",\"reply\":";cd_checkpoint::reply_json(reply);
        std::cout<<",\"guest_cpu_calls\":0}\n";return 0;
    }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
