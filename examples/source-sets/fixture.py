"""Authored RAM program calling independently declared sandbox BIOS routines."""
import importlib.util
from pathlib import Path
spec=importlib.util.spec_from_file_location('source_set_boot_fixture',Path(__file__).parents[1]/'boot-sources/fixture.py')
boot=importlib.util.module_from_spec(spec);spec.loader.exec_module(boot)


def case(bank=128,firmware_bank=0):
    c=boot.case('cd-ram',bank);c['firmware_bank']=firmware_bank
    c['initial_mpr']=tuple(firmware_bank if i==7 else v for i,v in enumerate(c['initial_mpr']))
    c['final_mpr']=tuple(firmware_bank if i==7 else v for i,v in enumerate(c['final_mpr']))
    for i,row in enumerate(c['plan']):
        row['mpr']=c['initial_mpr'] if i<5 else c['final_mpr']
        if i==12:row['code']=bytes.fromhex('20 00 E3')
        if 13<=i<=16:row['pc']=0xE300+row['pc']-(0x4000+64)
    c['tag']=9+firmware_bank;c['plan'][13]['code']=bytes((0xA9,c['tag']))
    return c


def fixture():
    payload=bytearray(65536);bios=bytearray(262144)
    cases=[case(bank,firmware) for bank in range(128,136) for firmware in range(32)]
    for c in cases:
        for i,row in enumerate(c['plan']):
            address=row['mpr'][row['pc']//8192]*8192+(row['pc']&8191)
            target=bios if 13<=i<=16 else payload;offset=address if 13<=i<=16 else address-0x100000
            target[offset:offset+len(row['code'])]=row['code']
    return bytes(payload),bytes(bios),cases


def cpu_states(c):return boot.cpu_states(c)
def expected_ram(c):return boot.expected_ram('cd-ram',c)
