// Authored wiring of the unchanged separately compiled GPL reference core.
#define Adapter GearGapAdapterBase
#define main previous_authored_gap_sense_main
#include "geargrafx_sense_probe.cpp"
#undef main
#undef Adapter
struct GapSeekStart {using type=u32 CdRomAudio::*;friend type member(GapSeekStart);};
template struct Access<GapSeekStart,&CdRomAudio::m_seek_start_lba>;
#define PCE_CDDA_GAP_GEAR
#include "cdda_gap_probe.cpp"
