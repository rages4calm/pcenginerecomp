"""Independent authored DD program/gap expectations and evidence rejection."""
import copy
from pathlib import Path
import tempfile
import unittest

from scripts import cd_position_reference as reference


class CdPositionReferenceTests(unittest.TestCase):
    def test_gap_reply_does_not_inherit_preceding_data_control_or_relative_time(self):
        layout=reference.geometry('virtual',4,True)
        self.assertEqual(reference.position(3,layout),[1,65,1,1,0,0,3,0,2,3])
        self.assertEqual(reference.position(4,layout),[1,1,0,1,0,0,0,0,2,4])
        self.assertEqual(reference.position(5,layout),[1,1,0,1,0,0,0,0,2,5])
        self.assertEqual(reference.position(6,layout),[1,1,2,1,0,0,0,0,2,6])
        self.assertEqual(reference.position(8,layout),[1,1,2,1,0,0,2,0,2,8])
        self.assertEqual(reference.position(10,layout),[1,1,0,1,0,0,0,0,2,0x10])

    def test_no_gap_track_boundary_is_still_program_data(self):
        layout=reference.geometry('plain',4,False)
        self.assertEqual(reference.position(4,layout),[1,65,2,1,0,0,0,0,2,4])
        self.assertEqual(reference.position(7,layout),[1,65,2,1,0,0,3,0,2,7])

    def test_BCD_second_rollover_has_independent_literals(self):
        self.assertEqual(reference.position(74,reference.geometry('virtual',74,True)),[1,1,0,1,0,0,0,0,2,0x74])
        self.assertEqual(reference.position(75,reference.geometry('stored',75,False)),[1,1,0,1,0,0,0,0,3,0])
        self.assertEqual(reference.position(77,reference.geometry('stored',75,False)),[1,65,2,1,0,0,0,0,3,2])

    def test_successful_READ_establishes_gap_head_without_host_seed(self):
        layout=reference.geometry('virtual',4,False)
        cases=reference.plans(layout,0)
        rows=reference.expected([cases[2]],layout)
        self.assertEqual(rows[0]['cdb'],[8,0,0,3,1,0])
        self.assertEqual(len(rows[0]['data']),2048)
        self.assertEqual(rows[1],dict(kind='head',values=[4]))
        self.assertEqual(rows[2]['data'],[1,1,0,1,0,0,0,0,2,4])
        self.assertEqual(rows[3],dict(kind='head',values=[4]))

    def test_program_last_sector_head_clamps_without_repeating_payload(self):
        layout=reference.geometry('virtual',4,False)
        rows=reference.expected([reference.plans(layout,1)[-1]],layout)
        self.assertEqual(rows[0]['cdb'],[8,0,0,9,1,0])
        self.assertEqual(rows[1],dict(kind='head',values=[9]))
        self.assertEqual(rows[2]['data'],[1,65,2,1,0,0,3,0,2,9])

    def test_distinct_ACK_paths_have_exact_authored_source_work(self):
        for automatic in(0,1):
            layout=reference.geometry('virtual',4,False)
            cases=reference.plans(layout,automatic)[2:3]
            hits=reference.expected_hits(cases,reference.expected(cases,layout))
            self.assertEqual(sum(hits.values()),6236)
            self.assertEqual(len(hits),4 if automatic==0 else 6)

    def test_all_fixture_geometries_and_original_case_counts(self):
        with tempfile.TemporaryDirectory()as tmp:
            rom,layouts=reference.fixtures(Path(tmp))
            self.assertEqual(rom.stat().st_size,262144)
            self.assertEqual(len(layouts),18)
            self.assertEqual(sum(len(reference.plans(layout,ack))for layout,_ in layouts for ack in(0,1)),144)
            for layout,cue in layouts:
                text=cue.read_text()
                self.assertEqual('INDEX 00'in text,layout['kind']=='stored')
                self.assertEqual('PREGAP'in text,layout['kind']=='virtual')
                self.assertNotIn('POSTGAP',text)

    def test_original_counterexample_and_missing_bytes_are_rejected(self):
        layout=reference.geometry('virtual',4,False)
        expected=reference.expected(reference.plans(layout,0)[2:3],layout)
        self.assertGreater(reference.shared.validate_rows(expected,expected),2048)
        for mutation in('preceding-track','relative','absolute','truncate','status'):
            actual=copy.deepcopy(expected)
            if mutation=='preceding-track':actual[2]['data']=[1,65,1,1,0,0,4,0,2,4]
            elif mutation=='relative':actual[2]['data'][6]=4
            elif mutation=='absolute':actual[2]['data'][9]=5
            elif mutation=='truncate':actual[2]['data'].pop()
            else:actual[2]['status']=2
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):
                reference.shared.validate_rows(actual,expected)

    def test_unauthored_geometry_and_operations_refused(self):
        for args in(('unknown',4,False),('plain',5,False),('plain',4,0)):
            with self.subTest(args=args),self.assertRaises(ValueError):reference.geometry(*args)
        layout=reference.geometry('virtual',4,False)
        with self.assertRaises(ValueError):reference.plans(layout,True)
        with self.assertRaises(ValueError):reference.expected([dict(operations=[('seed-head',4)])],layout)


if __name__=='__main__':unittest.main()
