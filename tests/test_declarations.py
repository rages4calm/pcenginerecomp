"""Authored numeric ROM declarations, board mapping, evidence and snapshot closure."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pcerecomp import declarations, history


def root(pc=0x4000, mpr=None, selector=0, offsets=None):
    return dict(pc=pc, mpr=[0] * 8 if mpr is None else list(mpr), selector=selector,
                rom_offsets=[0, 1] if offsets is None else list(offsets))


class DeclarationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.image = self.directory / 'authored.pce'
        rom = bytearray(b'\xEA' * 8192)
        rom[:2] = bytes.fromhex('A9 2A')
        self.image.write_bytes(rom)
        self.path = self.directory / 'declared-roots.json'

    def document(self, roots=None, **image_options):
        return dict(format=declarations.FORMAT, schema=1, execution_evidence=False,
                    kind='declared', image=dict(sha256=hashlib.sha256(self.image.read_bytes()).hexdigest(),
                    profile='base', header='none', encoding='linear', **image_options),
                    roots=[root()] if roots is None else roots)

    def write(self, document=None):
        value = self.document() if document is None else document
        self.path.write_bytes((json.dumps(value, indent=2) + '\n').encode('utf-8'))
        return self.path

    def admit(self, document=None):
        return declarations.load_declarations(self.write(document), self.image)

    def test_exact_source_metadata_no_fabricated_execution_and_detached_views(self):
        admitted = self.admit()
        instruction = admitted.instructions[0]
        self.assertEqual((instruction['pc'], instruction['physical'], instruction['data']),
                         (0x4000, (0, 1), (0xA9, 42)))
        self.assertEqual(instruction['mpr'], (0,) * 8)
        self.assertEqual(instruction['mnemonic'], 'LDA')
        self.assertNotIn('native_hits', instruction)
        self.assertNotIn('interpreted_hits', instruction)
        self.assertEqual(admitted.sha256, hashlib.sha256(self.path.read_bytes()).hexdigest())
        source = admitted.source_metadata
        self.assertEqual(source, dict(image_sha256=hashlib.sha256(self.image.read_bytes()).hexdigest(),
            decoded_rom_sha256=hashlib.sha256(self.image.read_bytes()).hexdigest(),
            profile='base', header='none', encoding='linear', file_bytes=8192, rom_bytes=8192))
        self.assertEqual(set(admitted.artifact_bindings), {'declarations', 'source_image'})
        for binding in admitted.artifact_bindings.values():
            self.assertTrue(binding['path'].is_absolute())
            self.assertEqual(binding['size_bytes'], binding['path'].stat().st_size)
        changed = admitted.roots; changed[0]['mpr'][0] = 255
        instruction['mpr'] = (255,) * 8
        source['profile'] = 'sf2'
        self.assertEqual(admitted.instructions[0]['mpr'], (0,) * 8)
        self.assertEqual(admitted.roots[0]['mpr'], [0] * 8)
        self.assertEqual(admitted.source_metadata['profile'], 'base')
        self.assertEqual(admitted.static_reachability, 'not_inferred')
        admitted.revalidate()

    def test_unused_mpr_variants_and_input_order_keep_full_identity(self):
        alternate = [0] * 7 + [248]
        admitted = self.admit(self.document([root(mpr=alternate), root()]))
        self.assertEqual(len(admitted.instructions), 2)
        self.assertEqual(admitted.instructions[0]['mpr'], (0,) * 8)
        self.assertEqual(admitted.instructions[1]['mpr'], tuple(alternate))
        before = admitted.sha256
        reordered = self.admit(self.document([root(), root(mpr=alternate)]))
        self.assertEqual(admitted.instructions, reordered.instructions)
        self.assertNotEqual(before, reordered.sha256)

    def test_sf2_selector_window_aliases_retained_but_compiled_keys_deduplicate(self):
        rom = bytearray(b'\xEA' * 0x280000)
        rom[0x80000:0x80002] = bytes.fromhex('A9 2A')
        rom[0x100000:0x100002] = bytes.fromhex('A9 2B')
        rom[0x200000:0x200002] = bytes.fromhex('A9 2C')
        self.image.write_bytes(rom)
        mapping = [0, 0, 64, 0, 0, 0, 0, 0]
        document = self.document([
            root(mpr=mapping, selector=4, offsets=[0x80000, 0x80001]),
            root(mpr=mapping, selector=0, offsets=[0x80000, 0x80001]),
            root(mpr=mapping, selector=1, offsets=[0x100000, 0x100001]),
            root(mpr=mapping, selector=15, offsets=[0x200000, 0x200001])])
        document['image']['profile'] = 'sf2'
        admitted = self.admit(document)
        self.assertEqual(len(admitted.roots), 4)
        self.assertEqual([item['selector'] for item in admitted.roots], [0, 1, 4, 15])
        self.assertEqual(len(admitted.instructions), 3)
        self.assertEqual({item['data'] for item in admitted.instructions}, {(0xA9, 42), (0xA9, 43), (0xA9, 44)})
        self.assertTrue(all(item['physical'] == (0x80000, 0x80001) for item in admitted.instructions))
        compiled = declarations.load_compilation(self.path, self.image)
        self.assertEqual(compiled.counts()['declared_roots_count'], 4)
        self.assertEqual(compiled.counts()['declared_instructions'], 3)
        self.assertEqual(compiled.counts()['source_identity_count'], 3)
        self.assertEqual(compiled.counts()['observed_instructions'], 0)

    def test_each_fetched_byte_uses_mapping_at_page_crossing_and_logical_wrap(self):
        rom = bytearray(b'\xEA' * 16384)
        rom[8191:8193] = bytes.fromhex('A9 2A')
        self.image.write_bytes(rom)
        mapping = [0, 0, 1, 0, 0, 0, 0, 0]
        admitted = self.admit(self.document([root(0x3FFF, mapping, offsets=[8191, 8192])]))
        self.assertEqual(admitted.instructions[0]['physical'], (8191, 8192))
        rom[-1] = 0xAD; rom[:2] = bytes.fromhex('34 12')
        self.image.write_bytes(rom)
        mapping = [0] * 7 + [1]
        wrapped = self.admit(self.document([root(0xFFFF, mapping, offsets=[16383, 0, 1])]))
        self.assertEqual(wrapped.instructions[0]['physical'], (16383, 0, 1))
        self.assertEqual(wrapped.instructions[0]['data'], (0xAD, 0x34, 0x12))
        self.assertEqual(wrapped.instructions[0]['pc'], 65535)

    def test_sf2_crossing_uses_selector_for_operand_not_only_opcode(self):
        rom = bytearray(b'\xEA' * 0x280000)
        rom[0x7FFFF] = 0xA9
        rom[0x100000] = 42
        self.image.write_bytes(rom)
        mapping = [0, 63, 64, 0, 0, 0, 0, 0]
        document = self.document([root(0x3FFF, mapping, selector=1, offsets=[0x7FFFF, 0x100000])])
        document['image']['profile'] = 'sf2'
        admitted = self.admit(document)
        self.assertEqual(admitted.instructions[0]['data'], (0xA9, 42))
        self.assertEqual(admitted.instructions[0]['physical'], (0x7FFFF, 0x80000))
        document['roots'][0]['rom_offsets'][1] = 0x80000
        with self.assertRaisesRegex(ValueError, 'offsets disagree'):
            self.admit(document)

    def test_non_rom_fetches_populous_ram_and_crossing_into_ram_refuse(self):
        for bank in (128, 248, 255):
            mapping = [0, 0, bank, 0, 0, 0, 0, 0]
            with self.subTest(bank=bank), self.assertRaisesRegex(ValueError, 'not driven'):
                self.admit(self.document([root(mpr=mapping)]))
        rom = bytearray(b'\xEA' * 0x80000); rom[-1] = 0xA9
        self.image.write_bytes(rom)
        for candidate in (root(mpr=[0, 0, 64, 0, 0, 0, 0, 0], offsets=[0]),
                          root(0x3FFF, [0, 63, 64, 0, 0, 0, 0, 0], offsets=[0x7FFFF, 0])):
            document = self.document([candidate]); document['image']['profile'] = 'populous'
            with self.assertRaisesRegex(ValueError, 'not driven'):
                self.admit(document)
        good = self.document([root(mpr=[0, 0, 96, 0, 0, 0, 0, 0], offsets=[0x40000])])
        good['image']['profile'] = 'populous'
        self.assertEqual(self.admit(good).instructions[0]['data'], (0xEA,))

    def test_header_bit_encoding_offsets_are_decoded_but_hash_is_original(self):
        decoded = self.image.read_bytes()
        reversed_bytes = bytes(int(f'{value:08b}'[::-1], 2) for value in decoded)
        raw = b'authored header'.ljust(512, b'\0') + reversed_bytes
        self.image.write_bytes(raw)
        document = self.document(); document['image'].update(header='copier512', encoding='bit-reversed')
        admitted = self.admit(document)
        self.assertEqual(admitted.instructions[0]['data'], (0xA9, 42))
        self.assertEqual(admitted.source_metadata['decoded_rom_sha256'], hashlib.sha256(decoded).hexdigest())
        self.assertEqual(admitted.source_metadata['image_sha256'], hashlib.sha256(raw).hexdigest())
        self.assertEqual(admitted.source_metadata['file_bytes'], 8704)
        self.assertEqual(admitted.source_metadata['rom_bytes'], 8192)
        document['roots'][0]['rom_offsets'] = [512, 513]
        with self.assertRaises(ValueError):
            self.admit(document)

    def test_unknown_fields_invented_hits_paths_and_duplicate_roots_refuse(self):
        variants = []
        for key, value in (('native_hits', 0), ('checkpoint_origin', {}), ('path', 'other.pce')):
            candidate = self.document(); candidate[key] = value; variants.append(candidate)
        candidate = self.document(); candidate['roots'][0]['data'] = [0xA9, 42]; variants.append(candidate)
        candidate = self.document(); candidate['image']['path'] = 'other.pce'; variants.append(candidate)
        candidate = self.document(); candidate['roots'] *= 2; variants.append(candidate)
        for candidate in variants:
            with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                self.admit(candidate)

    def test_strict_types_lengths_digest_selection_and_offsets(self):
        variants = []
        for key, value in (('schema', True), ('schema', 1.0), ('execution_evidence', 0), ('kind', 'observed')):
            candidate = self.document(); candidate[key] = value; variants.append(candidate)
        for key, value in (('pc', True), ('pc', 16384.0), ('pc', 65536), ('selector', True),
                           ('selector', 16), ('selector', 1), ('mpr', [0] * 7),
                           ('mpr', [0] * 7 + [False]), ('rom_offsets', []),
                           ('rom_offsets', [0]), ('rom_offsets', [0, 1, 2]),
                           ('rom_offsets', [0, True]), ('rom_offsets', [0, 8192])):
            candidate = self.document(); candidate['roots'][0][key] = value; variants.append(candidate)
        for key, value in (('sha256', 'A' * 64), ('sha256', '0' * 64), ('profile', 'auto'),
                           ('header', 'auto'), ('encoding', 'auto')):
            candidate = self.document(); candidate['image'][key] = value; variants.append(candidate)
        for candidate in variants:
            with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                self.admit(candidate)

    def test_json_encoding_duplicates_nonfinite_missing_files_and_bounds(self):
        raw = json.dumps(self.document()).encode()
        for invalid in (b'\xef\xbb\xbf' + raw, raw.decode().encode('utf-16'),
                        raw.replace(b'"schema": 1', b'"schema": 1e999'),
                        b'{"schema":1,' + raw[1:], b'{'):
            self.path.write_bytes(invalid)
            with self.subTest(raw=invalid[:30]), self.assertRaises(ValueError):
                declarations.load_declarations(self.path, self.image)
        self.write()
        with patch.object(declarations, 'MAX_DECLARATION_BYTES', 1):
            with self.assertRaises(ValueError): declarations.load_declarations(self.path, self.image)
        with patch.object(declarations, 'MAX_ROOTS', 1):
            with self.assertRaises(ValueError): self.admit(self.document([root(), root(0x4002, offsets=[2])]))
        with patch.object(declarations, 'MAX_IMAGE_BYTES', 1):
            with self.assertRaises(ValueError): declarations.load_declarations(self.path, self.image)
        with self.assertRaises(ValueError): declarations.load_declarations(self.directory / 'absent', self.image)
        with self.assertRaises(ValueError): declarations.load_declarations(self.path, self.directory)

    def test_links_and_hardlinks_are_refused_without_following_them(self):
        self.write()
        linked = self.directory / 'hard-link.pce'
        os.link(self.image, linked)
        with self.assertRaisesRegex(ValueError, 'single-link'):
            declarations.load_declarations(self.path, self.image)
        linked.unlink()
        link = self.directory / 'linked.pce'
        try:
            os.symlink(self.image, link)
        except (OSError, NotImplementedError):
            return  # Hard-link refusal above remains exercised on restricted hosts.
        with self.assertRaisesRegex(ValueError, 'links'):
            declarations.load_declarations(self.path, link)
        directory_link = self.directory / 'alias'
        os.symlink(self.directory, directory_link, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'links'):
            declarations.load_declarations(directory_link / self.path.name, self.image)

    def test_revalidation_hashes_same_timestamp_changes_in_both_originals(self):
        for target in (self.image, self.path):
            admitted = self.admit()
            before = target.stat(); raw = target.read_bytes()
            changed = raw.replace(b'16384', b'16385', 1) if target == self.path else b'\xEA' + raw[1:]
            target.write_bytes(changed)
            os.utime(target, ns=(before.st_atime_ns, before.st_mtime_ns))
            with self.assertRaises(ValueError): admitted.revalidate()
            target.write_bytes(raw)

    def test_changes_during_derivation_refuse_before_an_admitted_object_escapes(self):
        original_decode = declarations.decode_rom
        for target in (self.image, self.path):
            self.write()
            original = target.read_bytes()
            def change_then_decode(raw, header, encoding, profile):
                target.write_bytes((b'\xEA' + original[1:]) if target == self.image else original + b' ')
                return original_decode(raw, header, encoding, profile)
            with patch.object(declarations, 'decode_rom', side_effect=change_then_decode):
                with self.assertRaises(ValueError):
                    declarations.load_declarations(self.path, self.image)
            target.write_bytes(original)

    def test_control_and_mapping_diagnostics_do_not_expand_roots(self):
        rom = bytearray(self.image.read_bytes()); rom[:7] = bytes.fromhex('53 80 20 20 40 40 0B')
        self.image.write_bytes(rom)
        admitted = self.admit(self.document([root(offsets=[0, 1]), root(0x4002, offsets=[2, 3, 4]),
            root(0x4005, offsets=[5]), root(0x4006, offsets=[6])]))
        self.assertEqual(len(admitted.roots), 4)
        self.assertEqual(len(admitted.instructions), 4)
        self.assertEqual({item['pc'] for item in admitted.instructions}, {0x4000, 0x4002, 0x4005, 0x4006})
        reasons = {item['reason'] for item in admitted.diagnostics}
        self.assertEqual(reasons, {'dynamic_mpr_mapping', 'call_target_and_return_continuation_not_traversed',
                                  'dynamic_return_target', 'unsupported_instruction'})
        self.assertTrue(all(item['static_reachability'] == 'not_inferred' for item in admitted.diagnostics))

    def _mixed(self, version=1):
        rom = bytearray(self.image.read_bytes()); rom[3] = 0x0B; self.image.write_bytes(rom)
        self.write(self.document([root(), root(0x4002, offsets=[2]), root(0x4003, offsets=[3])]))
        observations = [dict(pc=0x4000, mpr=[0] * 8, physical=[0, 1], data=[0xA9, 42],
                             native_hits=2, interpreted_hits=3),
                        dict(pc=0x4004, mpr=[0] * 8, physical=[4], data=[0xEA],
                             native_hits=1, interpreted_hits=4)]
        capture = dict(schema=1, runtime_abi=18, capacity=65536, complete=True,
            dropped_instructions=0, unreadable_instructions=0, retired_instructions=10, observations=observations)
        path = self.directory / 'capture.json'; path.write_text(json.dumps(capture), encoding='utf-8')
        observed = history.compose_history([path], self.directory / ('history-' + str(version)), history_version=version)
        return observed, declarations.load_compilation(self.path, self.image, observation_history=observed)

    def test_mixed_history_preserves_actual_tier_rows_and_historical_accounting(self):
        for version in (1, 2):
            observed, compiled = self._mixed(version)
            self.assertEqual(compiled.accounting, observed.accounting)
            self.assertEqual(compiled.accounting['historical_totals']['retired_instructions'], 10)
            rows = {declarations.instruction_key(item): item for item in compiled.instructions}
            for item in observed.instructions:
                self.assertEqual(rows[declarations.instruction_key(item)], item)
            declared_only = [item for key, item in rows.items() if key not in compiled.observed_keys]
            self.assertTrue(all('native_hits' not in item and 'interpreted_hits' not in item for item in declared_only))
            counts = compiled.counts()
            self.assertEqual(counts, dict(observed_instructions=2, declared_instructions=3, declared_roots_count=3,
                source_identity_count=4, declared_only=2, observed_only=1, declared_observed_overlap=1,
                emitted_instructions=3, excluded_observations=0, excluded_declarations=0,
                excluded_retired_hits=0, unsupported_observations=0, unsupported_declarations=1))
            self.assertEqual(compiled.provenance['observation_history_schema'], version)
            self.assertEqual(compiled.provenance['observation_inputs'], observed.input_metadata)
            self.assertEqual(compiled.provenance['declared_roots_sha256'], compiled.declarations.sha256)
            compiled.revalidate()

    def test_declared_only_has_no_history_counters_and_excludes_by_any_fetch_byte(self):
        self.write()
        compiled = declarations.load_compilation(self.path, self.image)
        self.assertEqual(compiled.accounting, {})
        self.assertEqual(set(compiled.provenance), {'declared_roots_sha256', 'declared_roots_schema',
                         'declared_roots_format', 'declared_roots_source'})
        selection = compiled.selection([(1, 1), (1, 1)])
        self.assertEqual(selection['instructions'], [])
        self.assertEqual(selection['exclusions'], [dict(start=1, length=1)])
        self.assertEqual(selection['counts']['excluded_observations'], 0)
        self.assertEqual(selection['counts']['excluded_declarations'], 1)
        self.assertEqual(selection['counts']['excluded_retired_hits'], 0)

    def test_mixed_exclusion_overlap_and_unsupported_counts_do_not_invent_hits(self):
        observed, compiled = self._mixed()
        counts = compiled.counts([(1, 1)])
        self.assertEqual(counts['excluded_observations'], 1)
        self.assertEqual(counts['excluded_declarations'], 1)
        self.assertEqual(counts['excluded_retired_hits'], 5)
        self.assertEqual(counts['emitted_instructions'], 2)
        self.assertEqual(counts['unsupported_observations'], 0)
        self.assertEqual(counts['unsupported_declarations'], 1)
        self.assertEqual(compiled.accounting, observed.accounting)
        for invalid in ([(True, 1)], [(0, False)], [(0x1FFFFF, 2)], [(0, 0)], [(0, 1)] * 257):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError): compiled.counts(invalid)
        with patch.object(declarations, 'MAX_COMPILATION_IDENTITIES', 3):
            with self.assertRaisesRegex(ValueError, 'union exceeds'):
                declarations.load_compilation(self.path, self.image, observation_history=observed.index_path)
        shard = next(value['path'] for key, value in observed.artifact_bindings.items() if key.startswith('captures/'))
        shard.write_bytes(shard.read_bytes().replace(b'42', b'43'))
        with self.assertRaises(ValueError): compiled.revalidate()


if __name__ == '__main__':
    unittest.main()
