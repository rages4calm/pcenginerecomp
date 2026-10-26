// Authored adapter for the toolkit; the independent full core is separate.
#define main cd_decode_unit_main
#include "cd_decode_tests.cpp"
#undef main
#include <fstream>
static std::vector<std::uint64_t> decode_record(const pce::Bus& b,const pce::Cpu& c,unsigned profile){
    std::vector<std::uint64_t> row{c.pc,c.a,c.x,c.y,c.sp,c.p,c.clock_divisor,c.ticks};for(auto m:c.mpr)row.push_back(m);
    row.insert(row.end(),{c.mpr_latch,b.io_latch});if(profile!=2)row.insert(row.end(),{unsigned(b.cd.bram_unlocked),b.cd.reset,b.cd.interrupt_enable,b.cd.interrupt_active,b.cd.scsi.phase,b.cd.scsi.signals,b.cd.scsi.latch,b.cd.audio.fader});return row;
}
int main(int argc,char**argv){try{
    if(argc!=5)throw std::runtime_error("cd-decode-probe PLAN native|interpreter NEW_CAPTURE NEW_REPORT");
    const std::string tier=argv[2];if(tier!="native"&&tier!="interpreter")throw std::runtime_error("Explicit tier required");
    if(std::filesystem::exists(argv[4]))throw std::runtime_error("New report required");
    std::ifstream plan(argv[1]);if(!plan)throw std::runtime_error("Plan missing");pce::CodeCapture capture(argv[3],1024);
    std::unique_ptr<pce::Bus> bus;pce::Cpu c;unsigned profile=0,alias=0;std::uint64_t n=0,i=0,records=0,cases=0;bool first=true;std::string op;std::cout<<'[';
    while(plan>>op){if(op=="r"){
        unsigned fast;if(!(plan>>profile>>fast>>alias)||profile>2||fast>1||alias>1)throw std::runtime_error("Reset bounds");
        bus=decode_setup(profile,true);bus->power_on_cpu(c,0,0);c.mpr=cd_decode_mpr;c.clock_divisor=fast?3:12;++cases;
    }else{if(!bus)throw std::runtime_error("Operation before setup");if(op=="s"){
        const auto before=decode_record(*bus,c,profile);reset_probe::record(first,"cpu",before);++records;
        std::vector<std::uint64_t> hashes{reset_probe::hash(bus->bytes->data()+0x1F0000,8192)};if(profile!=2)hashes.push_back(reset_probe::hash(bus->bytes->data()+0x1EE000,2048));reset_probe::record(first,"memory",hashes);++records;
        require_decode(decode_record(*bus,c,profile)==before,"Inspection changed CPU/device state");
    }else if(op=="w"||op=="q"){
        unsigned offset,value=0;if(!(plan>>offset)||offset>8191||(op=="w"&&(!(plan>>value)||value>255)))throw std::runtime_error("Port bounds");
        decode_pointer(*bus,offset,alias);c.pc=op=="q"?cd_decode_read_pc:cd_decode_write_pc;if(op=="w")c.a=value;
        const auto pending=capture.before(*bus,c);decode_step(*bus,c,tier=="native");capture.after(pending,c);
        if(tier=="native")++n;else ++i;reset_probe::record(first,"cpu",decode_record(*bus,c,profile));++records;
    }else throw std::runtime_error("Unknown plan operation");}}
    capture.finish();std::cout<<"]\n";decode_refusals();
    std::ofstream report(argv[4]);if(!report)throw std::runtime_error("Report creation failed");
    report<<"{\"schema\":1,\"native_steps\":"<<n<<",\"interpreted_steps\":"<<i<<",\"pure_guards\":"<<decode_guards<<",\"records\":"<<records<<",\"cases\":"<<cases<<",\"literal_checks\":"<<decode_checks<<",\"scope\":\"Authored synthetic initial state and real indirect CPU bus operations; no hardware-reset claim\"}\n";
    return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
