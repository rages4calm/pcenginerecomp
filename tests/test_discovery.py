"""Authored source-qualified ROM discovery and independent closure admission."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from pcerecomp import discovery


def seed(offset=0, size=1, *, pc=None, mpr=None, selector=0, offsets=None):
    return dict(pc=0xE000 + offset if pc is None else pc,
        mpr=[0] * 8 if mpr is None else list(mpr), selector=selector,
        rom_offsets=list(range(offset, offset + size)) if offsets is None else list(offsets))


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.image = self.root / 'authored.pce'
        self.seeds = self.root / 'seeds.json'
        self.profile = 'base'

    def inputs(self, code=b'\xEA\x80\xFD', roots=None, *, rom=None, profile='base', header='none', encoding='linear'):
        self.profile = profile
        if rom is None:
            rom = bytearray(b'\xEA' * (0x280000 if profile == 'sf2' else 8192))
            rom[:len(code)] = code
        self.image.write_bytes(rom)
        document = dict(format='pce-declared-roots-1', schema=1, kind='declared', execution_evidence=False,
            image=dict(sha256=hashlib.sha256(rom).hexdigest(), profile=profile, header=header, encoding=encoding),
            roots=[seed()] if roots is None else roots)
        self.seeds.write_text(json.dumps(document, indent=2) + '\n', encoding='utf-8', newline='\n')
        return document

    def run_discovery(self, *, ranges=((0, 3),), name='result', **options):
        return discovery.discover_roots(self.seeds, self.image, self.root / name,
                                       rom_ranges=list(ranges), **options)

    def pcs(self, admitted):
        return {item['pc'] for item in admitted.declarations.roots}

    def reasons(self, admitted):
        return {item['reason'] for item in admitted.report['unresolved']}

    def rewrite_report(self, admitted, mutate):
        report = admitted.report
        mutate(report)
        admitted.report_path.write_bytes(discovery._canonical(report, discovery.MAX_REPORT_BYTES))

    def test_simple_loop_exact_roots_source_binding_and_nonexecution_contract(self):
        self.inputs()
        original = self.seeds.read_bytes()
        admitted = self.run_discovery()
        self.assertEqual(self.pcs(admitted), {0xE000, 0xE001})
        self.assertEqual((self.root / 'result/seed-roots.json').read_bytes(), original)
        self.assertEqual(admitted.report['summary']['candidate_roots'], 2)
        self.assertEqual(admitted.report['summary']['source_identities'], 2)
        self.assertEqual(admitted.report['summary']['contexts'], 1)
        self.assertEqual(admitted.report['unresolved'], [])
        self.assertEqual({edge['kind'] for edge in admitted.report['edges']}, {'fallthrough', 'jump'})
        self.assertIs(admitted.report['execution_evidence'], False)
        self.assertIs(admitted.report['routine_closure'], False)
        self.assertEqual(admitted.report['static_reachability'], 'candidates_only')
        self.assertTrue(all('native_hits' not in item and 'interpreted_hits' not in item
                            for item in admitted.declarations.instructions))
        self.assertEqual(admitted.sha256, hashlib.sha256(admitted.report_path.read_bytes()).hexdigest())
        self.assertEqual(admitted.report['source']['image_sha256'], hashlib.sha256(self.image.read_bytes()).hexdigest())
        copy = admitted.report; copy['summary']['candidate_roots'] = 99
        self.assertEqual(admitted.report['summary']['candidate_roots'], 2)
        admitted.revalidate()
        self.assertEqual(discovery.load_discovery(admitted.report_path, self.image).sha256, admitted.sha256)

    def test_optimized_python_keeps_seed_offer_and_semantics(self):
        self.inputs()
        script = ('from pcerecomp.discovery import discover_roots; import json,sys; '
                  'x=discover_roots(sys.argv[1],sys.argv[2],sys.argv[3],rom_ranges=[(0,3)]); '
                  'print(json.dumps(x.report["summary"]))')
        result = subprocess.run([sys.executable, '-O', '-c', script, str(self.seeds), str(self.image),
                                 str(self.root / 'optimized')], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['candidate_roots'], 2)

    def test_direct_calls_follow_only_callee_and_never_guess_return_context(self):
        rom = bytearray(b'\xEA' * 8192); rom[:3] = bytes.fromhex('20 10 E0'); rom[16] = 0x60
        self.inputs(rom=rom, roots=[seed(size=3)])
        admitted = self.run_discovery(ranges=[(0, 3), (16, 1)])
        self.assertEqual(self.pcs(admitted), {0xE000, 0xE010})
        self.assertEqual(self.reasons(admitted), {'dynamic_return_site', 'dynamic_return'})
        self.assertEqual([item['resume_pc'] for item in admitted.report['unresolved'] if 'resume_pc' in item], [0xE003])
        self.assertNotIn(0xE003, self.pcs(admitted))
        rom[:2] = bytes.fromhex('44 0D'); rom[15] = 0x60
        self.inputs(rom=rom, roots=[seed(size=2)])
        relative = self.run_discovery(ranges=[(0, 2), (15, 1)], name='relative')
        self.assertEqual(self.pcs(relative), {0xE000, 0xE00F})

    def test_branches_jumps_and_data_references_do_not_linear_scan(self):
        cases = [(bytes.fromhex('80 03 EA EA EA 60'), 2, {0xE000, 0xE005}),
                 (bytes.fromhex('D0 03 4C 05 E0 60'), 2, {0xE000, 0xE002, 0xE005}),
                 (bytes.fromhex('AD 10 E0 60'), 3, {0xE000, 0xE003})]
        for index, (code, size, expected) in enumerate(cases):
            self.inputs(code, [seed(size=size)])
            admitted = self.run_discovery(ranges=[(0, len(code))], name='branch-' + str(index))
            self.assertEqual(self.pcs(admitted), expected)

    def test_unresolved_indirect_return_interrupt_reserved_and_unknown_tam_are_candidates(self):
        cases = [('6C 10 E0 60', 3, 'indirect_jump'), ('7C 10 E0 60', 3, 'indirect_jump'),
                 ('60 EA', 1, 'dynamic_return'), ('40 EA', 1, 'interrupt_return'),
                 ('00 EA 60', 2, 'interrupt_vector'), ('0B 60', 1, 'unassigned_opcode'),
                 ('53 80 60', 2, 'mapping_change')]
        for index, (text, size, reason) in enumerate(cases):
            code = bytes.fromhex(text); self.inputs(code, [seed(size=size)])
            admitted = self.run_discovery(ranges=[(0, len(code))], name='stop-' + str(index))
            self.assertEqual(self.pcs(admitted), {0xE000})
            self.assertEqual(self.reasons(admitted), {reason})

    def test_known_tam_full_mpr_view_and_zero_mask(self):
        self.inputs(bytes.fromhex('A9 08 53 80 60'), [seed(size=2)])
        admitted = self.run_discovery(ranges=[(0, 5)])
        self.assertEqual(self.pcs(admitted), {0xE000, 0xE002, 0xE004})
        last = next(item for item in admitted.declarations.roots if item['pc'] == 0xE004)
        self.assertEqual(last['mpr'], [0] * 7 + [8])
        self.assertEqual(admitted.report['summary']['contexts'], 2)
        self.assertIn('mapping_change', {edge['kind'] for edge in admitted.report['edges']})
        self.inputs(bytes.fromhex('53 00 60'), [seed(size=2)])
        no_mapping = self.run_discovery(ranges=[(0, 3)], name='zero')
        self.assertEqual(self.pcs(no_mapping), {0xE000, 0xE002})
        self.assertEqual(no_mapping.report['summary']['contexts'], 1)

    def test_register_restore_and_tma_latch_do_not_invent_known_a(self):
        self.inputs(bytes.fromhex('A9 08 48 68 53 80 60'), [seed(size=2)])
        restored = self.run_discovery(ranges=[(0, 7)])
        self.assertEqual(self.pcs(restored), {0xE000, 0xE002, 0xE003, 0xE004})
        self.assertIn('mapping_change', self.reasons(restored))
        mapping = [1, 0, 0, 0, 0, 0, 0, 2]
        self.inputs(bytes.fromhex('43 81 53 80 60'), [seed(pc=0x4000, size=2, mpr=mapping)])
        combined = self.run_discovery(ranges=[(0, 5)], name='combined')
        self.assertEqual(next(item['mpr'][7] for item in combined.declarations.roots if item['pc'] == 0x4004), 3)
        self.inputs(bytes.fromhex('43 00 53 80 60'), [seed(pc=0x4000, size=2, mpr=mapping)])
        unknown = self.run_discovery(ranges=[(0, 5)], name='latch')
        self.assertEqual(self.pcs(unknown), {0x4000, 0x4002})
        self.assertIn('mapping_change', self.reasons(unknown))

    def test_conflicting_facts_retract_optimistic_tam_descendants(self):
        self.inputs(bytes.fromhex('D0 04 A9 08 80 02 A9 09 53 80 60'), [seed(size=2)],)
        admitted = self.run_discovery(ranges=[(0, 11)])
        self.assertEqual(self.pcs(admitted), {0xE000, 0xE002, 0xE004, 0xE006, 0xE008})
        self.assertIn('mapping_change', self.reasons(admitted))
        tam = next(item for item in admitted.report['nodes'] if item['pc'] == 0xE008)
        self.assertIsNone(tam['register_facts']['a'])
        self.assertGreater(admitted.report['summary']['explored_states'], 5)
        self.assertEqual(admitted.report['summary']['contexts'], 1)

    def test_sf2_all_write_classes_use_typed_safe_modes_or_stop_barriers(self):
        cases = [('0E F3 1F 60', 3, True), ('8D F0 1F 60', 3, True),
                 ('0C FF 1F 60', 3, True), ('9D EF 1F 60', 3, True),
                 ('92 10 60', 2, True), ('81 10 60', 2, True), ('91 10 60', 2, True),
                 ('73 00 20 00 20 01 00 60', 7, True),
                 ('8D EF 1F 60', 3, False), ('07 F3 60', 2, False),
                 ('03 FF 60', 2, False), ('86 F3 60', 2, False), ('0A 60', 1, False)]
        for index, (text, size, barrier) in enumerate(cases):
            code = bytes.fromhex(text)
            self.inputs(code, [seed(pc=0x4000, size=size)], profile='sf2')
            admitted = self.run_discovery(ranges=[(0, len(code))], name='write-' + str(index))
            self.assertEqual('mapper_write_barrier' in self.reasons(admitted), barrier, text)
            self.assertEqual(len(admitted.declarations.roots), 1 if barrier else 2, text)

    def test_sf2_selector_aliases_keep_distinct_states_not_false_overlaps(self):
        self.inputs(roots=[seed(selector=0), seed(selector=4)], profile='sf2')
        admitted = self.run_discovery()
        self.assertEqual(len(admitted.declarations.roots), 4)
        self.assertEqual(len(admitted.declarations.instructions), 2)
        self.assertEqual(admitted.report['summary']['contexts'], 2)
        self.assertEqual(admitted.report['summary']['source_identities'], 2)
        self.assertEqual(admitted.report['overlaps'], [])

    def test_per_byte_range_validation_cross_page_tam_and_wrapped_fetch(self):
        rom = bytearray(b'\xEA' * 16384)
        rom[8189:8194] = bytes.fromhex('A9 00 53 80 60')
        mapping = [0, 0, 1, 0, 0, 0, 0, 7]
        self.inputs(rom=rom, roots=[seed(pc=0x3FFD, mpr=mapping, offsets=[8189, 8190])])
        admitted = self.run_discovery(ranges=[(8189, 5)])
        tam = next(item for item in admitted.declarations.roots if item['pc'] == 0x3FFF)
        self.assertEqual(tam['rom_offsets'], [8191, 8192])
        last = next(item for item in admitted.declarations.roots if item['pc'] == 0x4001)
        self.assertEqual(last['mpr'][7], 0)
        self.assertEqual(last['rom_offsets'], [8193])
        rom[-1] = 0xAD; rom[:3] = bytes.fromhex('34 12 60')
        mapping = [0] * 7 + [1]
        self.inputs(rom=rom, roots=[seed(pc=0xFFFF, mpr=mapping, offsets=[16383, 0, 1])])
        wrapped = self.run_discovery(ranges=[(16383, 1), (0, 3)], name='wrapped')
        self.assertEqual(self.pcs(wrapped), {0xFFFF, 2})
        initial = next(item for item in wrapped.declarations.roots if item['pc'] == 65535)
        self.assertEqual(initial['rom_offsets'], [16383, 0, 1])

    def test_ranges_use_decoded_offsets_after_header_and_byte_conversion(self):
        rom = b'\xEA\x80\xFD' + b'\xEA' * (8192 - 3)
        reversed_rom = bytes(int(f'{value:08b}'[::-1], 2) for value in rom)
        raw = b'authored header'.ljust(512, b'\0') + reversed_rom
        self.inputs(rom=raw, header='copier512', encoding='bit-reversed')
        admitted = self.run_discovery()
        self.assertEqual(self.pcs(admitted), {0xE000, 0xE001})
        self.assertEqual(admitted.report['source']['image_sha256'], hashlib.sha256(raw).hexdigest())
        self.assertEqual(admitted.report['source']['decoded_rom_sha256'], hashlib.sha256(rom).hexdigest())
        self.assertEqual([item['rom_offsets'] for item in admitted.declarations.roots], [[0], [1, 2]])

    def test_operand_boundary_does_not_publish_partial_instruction_and_seed_must_fit(self):
        self.inputs(bytes.fromhex('EA A9 2A 60'))
        admitted = self.run_discovery(ranges=[(0, 2)])
        self.assertEqual(self.pcs(admitted), {0xE000})
        self.assertEqual(self.reasons(admitted), {'allowed_rom_boundary'})
        self.inputs(bytes.fromhex('A9 2A 60'), [seed(size=2)])
        with self.assertRaisesRegex(ValueError, 'original seed'):
            self.run_discovery(ranges=[(0, 1)], name='bad-seed')
        self.assertFalse((self.root / 'bad-seed').exists())

    def test_non_rom_and_populous_ram_frontiers_are_explicit(self):
        rom = bytearray(b'\xEA' * 0x80000)
        rom[0x7FFF0:0x7FFF5] = bytes.fromhex('A9 40 53 04 60')
        mapping = [0, 0, 63, 0, 0, 0, 0, 0]
        self.inputs(rom=rom, profile='populous', roots=[seed(pc=0x5FF0, mpr=mapping, offsets=[0x7FFF0, 0x7FFF1])])
        admitted = self.run_discovery(ranges=[(0x7FFF0, 5)])
        self.assertEqual(self.pcs(admitted), {0x5FF0, 0x5FF2})
        self.assertEqual(self.reasons(admitted), {'non_rom_fetch'})
        self.inputs(bytes.fromhex('A9 F8 53 80 60'), [seed(size=2)])
        nonrom = self.run_discovery(ranges=[(0, 5)], name='ram')
        self.assertEqual(self.pcs(nonrom), {0xE000, 0xE002})
        self.assertEqual(self.reasons(nonrom), {'non_rom_fetch'})

    def test_conflicting_instruction_starts_report_overlap_without_conflating_alias_views(self):
        self.inputs(bytes.fromhex('A9 EA 60'), [seed(size=2), seed(offset=1)])
        admitted = self.run_discovery()
        self.assertEqual(self.pcs(admitted), {0xE000, 0xE001, 0xE002})
        self.assertEqual(admitted.report['overlaps'], [dict(left_id=0, right_id=1,
            logical_addresses=[0xE001], rom_offsets=[1])])
        self.inputs(roots=[seed(), seed(pc=0xC000)])
        mirrored = self.run_discovery(name='mirrored')
        self.assertEqual(self.pcs(mirrored), {0xC000, 0xC001, 0xE000, 0xE001})
        self.assertEqual(mirrored.report['overlaps'], [])
        self.inputs(roots=[seed(), seed(mpr=[0] * 6 + [7, 0])])
        contexts = self.run_discovery(name='contexts')
        self.assertEqual(len(contexts.declarations.roots), 4)
        self.assertEqual(contexts.report['overlaps'], [])

    def test_explicit_limits_report_frontiers_without_silent_seed_loss(self):
        self.inputs()
        limited = self.run_discovery(instruction_limit=1)
        self.assertEqual(self.pcs(limited), {0xE000})
        self.assertEqual(self.reasons(limited), {'instruction_limit'})
        self.assertIs(limited.report['summary']['limit_reached'], True)
        self.assertEqual(limited.report['summary']['explored_states'], 1)
        self.inputs(bytes.fromhex('A9 08 53 80 60'), [seed(size=2)])
        context = self.run_discovery(ranges=[(0, 5)], context_limit=1, name='context')
        self.assertEqual(self.pcs(context), {0xE000, 0xE002})
        self.assertEqual(self.reasons(context), {'context_limit'})
        self.inputs(roots=[seed(), seed(offset=1, size=2)])
        with self.assertRaisesRegex(ValueError, 'Seed instructions'):
            self.run_discovery(instruction_limit=1, name='seeds-too-many')
        self.inputs(roots=[seed(), seed(mpr=[0] * 6 + [1, 0])])
        with self.assertRaisesRegex(ValueError, 'Seed contexts'):
            self.run_discovery(context_limit=1, name='seed-contexts')

    def test_strict_options_and_serialized_bounds_refuse_before_output(self):
        self.inputs()
        variants = [dict(instruction_limit=value) for value in (0, True, 1.0, 1048577)]
        variants += [dict(context_limit=value) for value in (0, False, 1.0, 4097)]
        for index, options in enumerate(variants):
            destination = self.root / ('invalid-' + str(index))
            with self.subTest(options=options), self.assertRaises(ValueError):
                discovery.discover_roots(self.seeds, self.image, destination, rom_ranges=[(0, 3)], **options)
            self.assertFalse(destination.exists())
        for index, ranges in enumerate(([], [(0, 0)], [(True, 1)], [(0, 1.0)], [(8191, 2)], [(0, 1)] * 257)):
            with self.subTest(ranges=ranges), self.assertRaises(ValueError):
                self.run_discovery(ranges=ranges, name='ranges-' + str(index))
        with patch.object(discovery, 'MAX_REPORT_BYTES', 1):
            with self.assertRaisesRegex(ValueError, 'serialized'):
                self.run_discovery(name='report-bound')
        self.assertFalse((self.root / 'report-bound').exists())
        self.inputs(b'\xEA' * 8 + b'\x60')
        with patch.object(discovery, 'MAX_DECLARATION_BYTES', self.seeds.stat().st_size + 10):
            with self.assertRaisesRegex(ValueError, 'serialized'):
                self.run_discovery(ranges=[(0, 9)], name='roots-bound')
        self.assertFalse((self.root / 'roots-bound').exists())

    def test_range_order_merging_and_original_seed_order_are_deterministic(self):
        self.inputs(roots=[seed(offset=1, size=2), seed()])
        first = self.run_discovery(ranges=[(1, 2), (0, 1), (0, 3)])
        second = self.run_discovery(ranges=[(0, 3)], name='second')
        self.assertEqual(first.sha256, second.sha256)
        self.assertEqual(first.report['options']['rom_ranges'], [dict(start=0, length=3)])
        # The copied seed's original bytes intentionally remain part of provenance.
        value = json.loads(self.seeds.read_text()); value['roots'].reverse()
        self.seeds.write_text(json.dumps(value), encoding='utf-8')
        third = self.run_discovery(name='third')
        self.assertEqual(first.declarations.roots, third.declarations.roots)
        self.assertNotEqual(first.sha256, third.sha256)

    def test_closure_rederives_expansion_and_every_report_fact_not_only_transport_hashes(self):
        self.inputs()
        admitted = self.run_discovery()
        original_report = admitted.report_path.read_bytes()
        root_path = admitted.roots_path; original_roots = root_path.read_bytes()
        document = json.loads(original_roots); document['roots'].pop()
        root_path.write_bytes(discovery._canonical(document, discovery.MAX_DECLARATION_BYTES))
        self.rewrite_report(admitted, lambda report: report['artifacts'].__setitem__(discovery.ROOTS_NAME,
            dict(sha256=hashlib.sha256(root_path.read_bytes()).hexdigest(), size_bytes=root_path.stat().st_size)))
        with self.assertRaisesRegex(ValueError, 'Expanded numeric roots'):
            discovery.load_discovery(admitted.report_path, self.image)
        root_path.write_bytes(original_roots); admitted.report_path.write_bytes(original_report)
        for mutate in (lambda report: report['summary'].__setitem__('candidate_roots', 99),
                       lambda report: report['edges'].clear(),
                       lambda report: report['nodes'][0]['register_facts'].__setitem__('a', 42),
                       lambda report: report['source'].__setitem__('decoded_rom_sha256', '0' * 64)):
            self.rewrite_report(admitted, mutate)
            with self.assertRaisesRegex(ValueError, 'recomputed'):
                discovery.load_discovery(admitted.report_path, self.image)
            admitted.report_path.write_bytes(original_report)

    def test_missing_extra_links_duplicates_unknown_fields_and_noncanonical_report_refuse(self):
        self.inputs(); admitted = self.run_discovery(); original = admitted.report_path.read_bytes()
        extra = admitted.report_path.parent / 'scratch'; extra.write_bytes(b'not part of graph')
        with self.assertRaisesRegex(ValueError, 'unlisted'): admitted.revalidate()
        extra.unlink()
        for raw in (b'\xef\xbb\xbf' + original, b'{"schema":1,' + original[1:],
                    json.dumps(admitted.report, indent=2).encode(), original.replace(b'"schema":1', b'"schema":true')):
            admitted.report_path.write_bytes(raw)
            with self.assertRaises(ValueError): discovery.load_discovery(admitted.report_path, self.image)
        admitted.report_path.write_bytes(original)
        self.rewrite_report(admitted, lambda report: report.__setitem__('invented_hits', 0))
        with self.assertRaisesRegex(ValueError, 'fields'): discovery.load_discovery(admitted.report_path, self.image)
        admitted.report_path.write_bytes(original)
        missing = admitted.roots_path.read_bytes(); admitted.roots_path.unlink()
        with self.assertRaises(ValueError): discovery.load_discovery(admitted.report_path, self.image)
        admitted.roots_path.write_bytes(missing)
        hard = self.root / 'hard'; os.link(admitted.roots_path, hard)
        with self.assertRaises(ValueError): admitted.revalidate()
        hard.unlink()
        target = self.root / 'report-copy'; target.write_bytes(original)
        try:
            admitted.report_path.unlink(); os.symlink(target, admitted.report_path)
        except (OSError, NotImplementedError):
            admitted.report_path.write_bytes(original)
        else:
            with self.assertRaises(ValueError): discovery.load_discovery(admitted.report_path, self.image)

    def test_snapshot_changes_and_failed_publication_never_admit_partial_or_relabel_inputs(self):
        self.inputs(); admitted = self.run_discovery()
        before = self.image.stat(); raw = self.image.read_bytes()
        self.image.write_bytes(b'\x60' + raw[1:]); os.utime(self.image, ns=(before.st_atime_ns, before.st_mtime_ns))
        with self.assertRaises(ValueError): admitted.revalidate()
        self.image.write_bytes(raw)
        original_facts = discovery._register_facts
        def change_input(ins, facts, mpr):
            self.seeds.write_bytes(self.seeds.read_bytes() + b' ')
            return original_facts(ins, facts, mpr)
        with patch.object(discovery, '_register_facts', side_effect=change_input):
            with self.assertRaises(ValueError): self.run_discovery(name='mutated')
        self.assertFalse((self.root / 'mutated').exists())
        self.inputs()
        original_write = discovery._write_new
        def interrupted(path, data):
            if path.name == discovery.REPORT_NAME: raise OSError('authored interrupted publication')
            original_write(path, data)
        with patch.object(discovery, '_write_new', side_effect=interrupted):
            with self.assertRaises(OSError): self.run_discovery(name='partial')
        with self.assertRaises(ValueError): discovery.load_discovery(self.root / 'partial', self.image)
        # Closure uses the exact copied seed; its original external location is unnecessary.
        self.seeds.unlink()
        self.assertEqual(discovery.load_discovery(admitted.report_path, self.image).sha256, admitted.sha256)

    def test_output_collision_never_replaces_owner_files(self):
        self.inputs(); destination = self.root / 'owner'; destination.write_bytes(b'owner data')
        with self.assertRaisesRegex(ValueError, 'new directory'):
            self.run_discovery(name='owner')
        self.assertEqual(destination.read_bytes(), b'owner data')
        (self.root / 'directory').mkdir()
        with self.assertRaises(ValueError): self.run_discovery(name='directory')


if __name__ == '__main__':
    unittest.main()
