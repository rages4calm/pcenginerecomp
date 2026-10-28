// Authored adapter only; original reference sources are compiled unchanged.
#define Adapter GearGapAdapterBase
#define main previous_authored_end_sense_main
#include "geargrafx_sense_probe.cpp"
#undef main
#undef Adapter
struct GapSeekStart {using type=u32 CdRomAudio::*;friend type member(GapSeekStart);};
struct EndSampleClock {using type=u64 Audio::*;friend type member(EndSampleClock);};
template struct Access<GapSeekStart,&CdRomAudio::m_seek_start_lba>;
template struct Access<EndSampleClock,&Audio::m_sample_clock_counter>;
#define PCE_CDDA_GAP_GEAR
#include "cdda_end_probe.cpp"
