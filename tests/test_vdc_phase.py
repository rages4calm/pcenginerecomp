"""Independent arithmetic expectations for the narrow blank VDC diagnostic."""
import unittest

from scripts.vdc_phase import PROFILE, predict_blank_dma_read_wait


def facts(**changes):
    # Starting at horizontal tick200, thirty ticks contain15 VCE2 dots.
    # A127-word DMA therefore has508-15=493 dots left at target entry.
    result = dict(profile=PROFILE, access='high', cpu_divisor=3, vce_divider=2,
                  dma_words=127, launch_tick=0, launch_hclock=200,
                  target_tick=30, target_hclock=230, pending_dma_dots=493,
                  transfer_delay=0, queue_carry=0, read_pending=True,
                  write_pending=False, satb_pending_dots=0, display_control=0,
                  burst=True, sprite_count=0, selected_register=2,
                  hsw_excluded=True)
    result.update(changes)
    return result


class BlankVdcPhaseTests(unittest.TestCase):
    def test_cpu_prefix_and_whole_block_do_not_change_grant_phase(self):
        # Final DMA dot is at1016. The first eligible fast callback starts1017;
        # horizontal1217 is even dot608. Queue clears at callback end1020.
        for access, divisor, prefix, wait in (('high', 3, 3, 987),
                                              ('tai2', 3, 48, 942),
                                              ('high', 12, 12, 978),
                                              ('tai2', 12, 192, 798)):
            with self.subTest(access=access, divisor=divisor):
                result = predict_blank_dma_read_wait(**facts(access=access, cpu_divisor=divisor))
                self.assertEqual(result['predicted_completion_tick'], 1016)
                self.assertEqual(result['predicted_grant_start_tick'], 1017)
                self.assertEqual(result['predicted_grant_hclock'], 1217)
                self.assertEqual(result['prefix_ticks'], prefix)
                self.assertEqual(result['predicted_wait_ticks'], wait)

    def test_line_tail_and_vce_speed_are_distinct_from_cpu_speed(self):
        # VCE4 has341 dots per1365-tick line: one tail tick is not a dot.
        # The final ordinal558 is line1 dot217, at1365+868, minus origin200.
        result = predict_blank_dma_read_wait(**facts(vce_divider=4, pending_dma_dots=501))
        self.assertEqual(result['predicted_completion_tick'], 2033)
        self.assertEqual(result['predicted_grant_start_tick'], 2037)
        self.assertEqual(result['predicted_wait_ticks'], 2007)
        # At VCE3, ordinal574 is line1 dot119:1365+357-origin200=1522.
        result = predict_blank_dma_read_wait(**facts(vce_divider=3, pending_dma_dots=498))
        self.assertEqual(result['predicted_completion_tick'], 1522)
        self.assertEqual(result['predicted_grant_start_tick'], 1527)
        self.assertEqual(result['predicted_wait_ticks'], 1497)

    def test_three_tick_callback_checks_before_advancing_raster(self):
        # Four dots complete at8. The callback starting6 cannot grant on the
        # completion that it clocks; eligibility is checked again at9.
        result = predict_blank_dma_read_wait(**facts(dma_words=1, target_tick=0,
                                                    target_hclock=200, pending_dma_dots=4))
        self.assertEqual(result['predicted_completion_tick'], 8)
        self.assertEqual(result['predicted_grant_start_tick'], 9)
        self.assertEqual(result['predicted_wait_ticks'], 9)

    def test_queue_delay_is_an_independent_barrier_and_may_finish_in_prefix(self):
        for carry in (0, 1, 2):
            options = facts(dma_words=1, target_tick=0, target_hclock=200,
                            pending_dma_dots=4, transfer_delay=15, queue_carry=carry)
            result = predict_blank_dma_read_wait(**options)
            self.assertEqual(result['queue_delay_first_eligible_tick'], 12)
            self.assertEqual(result['predicted_grant_start_tick'], 12)
            self.assertEqual(result['predicted_wait_ticks'], 12)
            self.assertEqual(result['queue_carry_at_target'], carry)
            self.assertEqual(result['queue_carry_after_grant'], 0)
            result = predict_blank_dma_read_wait(**dict(options, access='tai2'))
            self.assertEqual(result['predicted_wait_ticks'], 0)

    def test_phase_facts_explain_six_tick_difference_without_clock_alignment(self):
        # Same source/count and114-tick setup, different observed line phase.
        # 1365 is odd, so crossing its tail changes the final even-dot lattice.
        gear = predict_blank_dma_read_wait(**facts(dma_words=4096,
            launch_hclock=678, target_tick=114, target_hclock=792, pending_dma_dots=16327))
        tool = predict_blank_dma_read_wait(**facts(dma_words=4096,
            launch_hclock=696, target_tick=114, target_hclock=810, pending_dma_dots=16327))
        self.assertEqual(gear['predicted_wait_ticks'], 32685)
        self.assertEqual(tool['predicted_wait_ticks'], 32679)
        self.assertEqual(tool['predicted_wait_ticks'] - gear['predicted_wait_ticks'], -6)

    def test_phase_and_one_remaining_dot_explain_three_tick_difference(self):
        gear = predict_blank_dma_read_wait(**facts(dma_words=4096, cpu_divisor=12, vce_divider=4,
            launch_hclock=1176, target_tick=456, target_hclock=267, pending_dma_dots=16271))
        tool = predict_blank_dma_read_wait(**facts(dma_words=4096, cpu_divisor=12, vce_divider=4,
            launch_hclock=396, target_tick=456, target_hclock=852, pending_dma_dots=16270))
        self.assertEqual(gear['predicted_wait_ticks'], 65121)
        self.assertEqual(tool['predicted_wait_ticks'], 65124)
        self.assertEqual(tool['predicted_wait_ticks'] - gear['predicted_wait_ticks'], 3)

    def test_absolute_time_translation_preserves_the_observed_phase_prediction(self):
        old = predict_blank_dma_read_wait(**facts())
        moved = predict_blank_dma_read_wait(**facts(launch_tick=100003, target_tick=100033))
        self.assertEqual(moved['predicted_wait_ticks'], old['predicted_wait_ticks'])
        for key in ('predicted_completion_tick', 'predicted_grant_start_tick', 'queue_delay_first_eligible_tick'):
            self.assertEqual(moved[key], old[key] + 100003)
        self.assertEqual(moved['search_bound_callbacks'], 455)
        self.assertLessEqual(moved['examined_callbacks'], 455)

    def test_observed_countdown_and_phase_are_required_not_inferred_from_wait(self):
        for change in (dict(pending_dma_dots=492), dict(target_hclock=231),
                       dict(target_tick=29), dict(launch_tick=31)):
            with self.subTest(change=change), self.assertRaises(ValueError):
                predict_blank_dma_read_wait(**facts(**change))

    def test_unsupported_hsw_and_device_interference_are_refused(self):
        # Two words from hclock1340 at VCE4 finish at next-line tick8. Early
        # position alone is not HSW: accept when its gate is actually excluded.
        options = facts(dma_words=2, vce_divider=4, launch_hclock=1340,
                        target_tick=0, target_hclock=1340, pending_dma_dots=8)
        result = predict_blank_dma_read_wait(**options)
        self.assertEqual(result['predicted_completion_tick'], 33)
        self.assertEqual(result['predicted_grant_start_tick'], 33)
        self.assertEqual(result['predicted_grant_hclock'], 8)
        self.assertEqual(result['predicted_wait_ticks'], 33)
        with self.assertRaisesRegex(ValueError, 'hsw_excluded'):
            predict_blank_dma_read_wait(**dict(options, hsw_excluded=False))
        for change in (dict(profile='active-vram'), dict(access='write'),
                       dict(read_pending=False), dict(write_pending=True),
                       dict(satb_pending_dots=1), dict(display_control=128),
                       dict(burst=False), dict(sprite_count=1), dict(selected_register=1),
                       dict(hsw_excluded=False)):
            with self.subTest(change=change), self.assertRaises(ValueError):
                predict_blank_dma_read_wait(**facts(**change))

    def test_strict_integer_bool_range_and_partial_tail_refusals(self):
        for change in (dict(cpu_divisor=True), dict(vce_divider=2.0),
                       dict(cpu_divisor=6), dict(vce_divider=5), dict(dma_words=0),
                       dict(dma_words=65537), dict(launch_hclock=1365),
                       dict(queue_carry=3), dict(transfer_delay=1),
                       dict(transfer_delay=18), dict(read_pending=1), dict(burst=1),
                       dict(hsw_excluded=1)):
            with self.subTest(change=change), self.assertRaises(ValueError):
                predict_blank_dma_read_wait(**facts(**change))

    def test_clock_overflow_is_explicit(self):
        offset = (1 << 64) - 100
        with self.assertRaisesRegex(ValueError, 'overflows'):
            predict_blank_dma_read_wait(**facts(launch_tick=offset, target_tick=offset + 30))


if __name__ == '__main__':
    unittest.main()
