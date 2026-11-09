#pragma once
// Authored observation declarations, force-included in PRIVATE GPL builds only.
// The independently compiled emulator retains its original CPU/memory bodies.
#include <cstdint>
extern void bus_reference_access(unsigned logical,unsigned physical,unsigned value,
                                 bool write,bool fixed,bool direct);
inline thread_local unsigned bus_reference_fetch_depth=0;
struct BusReferenceFetchScope {
    BusReferenceFetchScope(){++bus_reference_fetch_depth;}
    ~BusReferenceFetchScope(){--bus_reference_fetch_depth;}
};
#if defined(PCE_BUS_REFERENCE_OBSERVER)
#define BUS_REFERENCE_ACCESS(logical,physical,value,write,fixed,direct) \
    do {if(!bus_reference_fetch_depth)bus_reference_access(logical,physical,value,write,fixed,direct);}while(false)
#else
#define BUS_REFERENCE_ACCESS(logical,physical,value,write,fixed,direct) do {}while(false)
#endif
