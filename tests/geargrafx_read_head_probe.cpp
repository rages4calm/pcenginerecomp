// Reuse authored full-core wiring; no third-party CPU or device body is copied.
#define Adapter GearHeadAdapter
#define main previous_authored_sense_main
#include "geargrafx_sense_probe.cpp"
#undef main
#undef Adapter
#define PCE_READ_HEAD_GEAR
#include "read_head_probe.cpp"
