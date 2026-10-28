"""Independent phase/encoding/identity controls for authored scroll software."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from generate_vdc_scroll_fixture import definitions,fixture,generate,prefix,ticks,LINE,FRAME


class ScrollFixtureTests(unittest.TestCase):
    def test_finite_matrix_keeps_real_cpu_lattice(self):
        cases,roms,sources=fixture()
        self.assertEqual(len(cases),19)
        self.assertEqual({c['divider']for c in cases},{2,3,4})
        self.assertEqual(len(roms),38)
        for c in cases:
            for profile in ('runtime','gear'):
                self.assertEqual(c['sample_ticks'],c['frame']*FRAME+64*LINE+300)
                self.assertEqual(c['sample_ticks']%3,0)
                self.assertEqual(hashlib.sha256(roms[c[profile]['rom']]).hexdigest(),c[profile]['rom_sha256'])
                for a in c[profile]['actions']:self.assertEqual(a['effect_ticks']%3,0)
        self.assertTrue(sources)

    def test_source_plan_fetches_each_byte_through_full_mapping(self):
        cases,roms,sources=fixture()
        for source in sources:
            expected=[(source['mpr'][((source['pc']+i)&65535)>>13]<<13)|((source['pc']+i)&8191)for i in range(len(source['data']))]
            self.assertEqual(source['physical'],expected)
            self.assertTrue(any([rom[a]for a in expected]==source['data']for name,rom in roms.items()if name.endswith('-runtime.pce')))
        self.assertTrue(all(source['native_hits']==0 and source['interpreted_hits']==1 for source in sources))

    def test_original_csh_difference_remains_explicit_before_padding(self):
        for c in definitions():
            p=prefix(c)
            self.assertEqual(ticks(p,'runtime')-ticks(p,'gear'),18)

    def test_window_and_pair_literals_have_independent_boundaries(self):
        cases={c['id']:c for c in definitions()}
        self.assertEqual([cases['bxr-'+n]['x']for n in ('before','window','after')],[8,8,0])
        self.assertEqual([cases['byr-'+n]['y']for n in ('before','window','after')],[4,4,47])
        self.assertEqual(cases['byr-pair-exact-gap']['events'][-1][2]-cases['byr-pair-exact-gap']['events'][0][2],24)
        self.assertEqual((cases['byr-pair-valid']['y'],cases['byr-pair-valid']['counter']),(4,47))
        self.assertEqual(cases['byr-pair-expired-gap']['y'],47)
        self.assertEqual(cases['byr-bxr-inhibits']['y'],47)
        self.assertEqual(cases['byr-pair-outside-hsw']['y'],47)

    def test_repeated_generation_retains_exact_bytes_and_stamps(self):
        with tempfile.TemporaryDirectory()as temporary:
            out=Path(temporary)/'fixture';generate(out)
            files={str(p.relative_to(out)):(p.read_bytes(),p.stat().st_mtime_ns)for p in out.rglob('*')if p.is_file()}
            generate(out)
            self.assertEqual({str(p.relative_to(out)):(p.read_bytes(),p.stat().st_mtime_ns)for p in out.rglob('*')if p.is_file()},files)
            self.assertEqual(json.loads((out/'fixture.json').read_text())['schema'],1)


if __name__=='__main__':unittest.main()
