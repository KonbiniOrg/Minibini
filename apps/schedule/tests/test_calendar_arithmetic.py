from datetime import date, datetime, time, timedelta
from django.test import SimpleTestCase
from django.utils import timezone as dj_tz

from apps.schedule.calendar_arithmetic import (
    DAY_KEYS,
    WeekEnvelope,
    validate_week_envelope,
    _combine_local,
    add_work_time,
    day_segments_clamped,
    is_working_day,
    next_workable_moment,
    segments_for,
    shift_working_days,
    work_minutes_between,
)


def L(y, m, d, hh, mm):
    return _combine_local(date(y, m, d), time(hh, mm))



CANONICAL = {
    'mon': [['08:00', '12:00'], ['12:30', '17:00']],
    'tue': [['08:00', '17:00']],
    'wed': [['08:00', '17:00']],
    'thu': [['08:00', '17:00']],
    'fri': [['08:00', '17:00']],
    'sat': [],
    'sun': [],
}


def _week(**overrides):
    data = {k: [['08:00', '17:00']] for k in DAY_KEYS[:5]}
    data['sat'] = []
    data['sun'] = []
    data.update(overrides)
    return data


class WeekEnvelopeTest(SimpleTestCase):

    def test_default_is_mon_fri_8_to_5(self):
        env = WeekEnvelope.default()
        for weekday in range(5):
            self.assertEqual(env.days[weekday], ((time(8, 0), time(17, 0)),))
        self.assertEqual(env.days[5], ())
        self.assertEqual(env.days[6], ())

    def test_from_json_round_trips_to_json(self):
        env = WeekEnvelope.from_json(CANONICAL)
        self.assertEqual(env.to_json(), CANONICAL)

    def test_intervals_on_uses_weekday(self):
        env = WeekEnvelope.from_json(CANONICAL)
        # 2026-05-18 is a Monday
        self.assertEqual(
            env.intervals_on(date(2026, 5, 18)),
            ((time(8, 0), time(12, 0)), (time(12, 30), time(17, 0))),
        )

    def test_is_working_day(self):
        env = WeekEnvelope.from_json(CANONICAL)
        self.assertTrue(env.is_working_day(date(2026, 5, 18)))   # Mon
        self.assertFalse(env.is_working_day(date(2026, 5, 23)))  # Sat

    def test_from_json_rejects_invalid(self):
        with self.assertRaises(ValueError):
            WeekEnvelope.from_json({'mon': []})


class ValidateWeekEnvelopeTest(SimpleTestCase):

    def test_canonical_is_valid(self):
        self.assertEqual(validate_week_envelope(CANONICAL), [])

    def test_missing_key(self):
        data = dict(CANONICAL)
        del data['sun']
        self.assertTrue(validate_week_envelope(data))

    def test_extra_key(self):
        data = dict(CANONICAL)
        data['monday'] = []
        self.assertTrue(validate_week_envelope(data))

    def test_not_a_dict(self):
        self.assertTrue(validate_week_envelope(['08:00', '17:00']))

    def test_unpadded_hour_rejected(self):
        self.assertTrue(validate_week_envelope(_week(mon=[['8:00', '17:00']])))

    def test_out_of_range_hour_rejected(self):
        self.assertTrue(validate_week_envelope(_week(mon=[['25:00', '26:00']])))

    def test_zero_length_interval_rejected(self):
        self.assertTrue(validate_week_envelope(_week(mon=[['08:00', '08:00']])))

    def test_end_before_start_rejected(self):
        self.assertTrue(validate_week_envelope(_week(mon=[['17:00', '08:00']])))

    def test_overlapping_intervals_rejected(self):
        self.assertTrue(validate_week_envelope(
            _week(mon=[['08:00', '12:00'], ['11:00', '17:00']])))

    def test_touching_intervals_rejected(self):
        self.assertTrue(validate_week_envelope(
            _week(mon=[['08:00', '12:00'], ['12:00', '17:00']])))

    def test_unsorted_intervals_rejected(self):
        self.assertTrue(validate_week_envelope(
            _week(mon=[['13:00', '17:00'], ['08:00', '12:00']])))

    def test_non_list_day_rejected(self):
        self.assertTrue(validate_week_envelope(_week(mon='08:00-17:00')))

    def test_non_pair_interval_rejected(self):
        self.assertTrue(validate_week_envelope(_week(mon=[['08:00']])))

    def test_all_days_off_is_valid(self):
        data = {k: [] for k in DAY_KEYS}
        self.assertEqual(validate_week_envelope(data), [])



class IsWorkingDayTest(SimpleTestCase):

    def setUp(self):
        self.env = WeekEnvelope.default()

    def test_weekday_is_working(self):
        self.assertTrue(is_working_day(date(2026, 5, 18), self.env))  # Mon
        self.assertTrue(is_working_day(date(2026, 5, 22), self.env))  # Fri

    def test_weekend_not_working_by_default(self):
        self.assertFalse(is_working_day(date(2026, 5, 23), self.env))  # Sat
        self.assertFalse(is_working_day(date(2026, 5, 24), self.env))  # Sun

    def test_envelope_makes_saturday_working(self):
        env = WeekEnvelope.from_json(_week(sat=[['09:00', '13:00']]))
        self.assertTrue(is_working_day(date(2026, 5, 23), env))

    def test_envelope_makes_wednesday_off(self):
        env = WeekEnvelope.from_json(_week(wed=[]))
        self.assertFalse(is_working_day(date(2026, 5, 20), env))


class ShiftWorkingDaysTest(SimpleTestCase):

    def setUp(self):
        self.env = WeekEnvelope.default()

    def test_forward_skips_weekend(self):
        # Fri + 1 working day = Mon
        self.assertEqual(
            shift_working_days(date(2026, 5, 22), 1, self.env), date(2026, 5, 25))

    def test_backward_skips_weekend(self):
        # Mon - 1 working day = Fri
        self.assertEqual(
            shift_working_days(date(2026, 5, 25), -1, self.env), date(2026, 5, 22))

    def test_zero_is_identity(self):
        d = date(2026, 5, 23)
        self.assertEqual(shift_working_days(d, 0, self.env), d)

    def test_saturday_worker_counts_saturday(self):
        env = WeekEnvelope.from_json(_week(sat=[['09:00', '13:00']]))
        # Fri + 1 working day = Sat for this envelope
        self.assertEqual(
            shift_working_days(date(2026, 5, 22), 1, env), date(2026, 5, 23))

    def test_all_off_envelope_returns_input(self):
        env = WeekEnvelope.from_json({k: [] for k in DAY_KEYS})
        d = date(2026, 5, 20)
        self.assertEqual(shift_working_days(d, 3, env), d)


LUNCH = {'mon': [['08:00', '12:00'], ['12:30', '17:00']]}


class NextWorkableMomentTest(SimpleTestCase):

    def setUp(self):
        self.env = WeekEnvelope.default()

    def test_mid_morning_unchanged(self):
        dt = L(2026, 5, 19, 9, 30)
        self.assertEqual(next_workable_moment(dt, self.env), dt)

    def test_midday_is_workable_without_gap(self):
        dt = L(2026, 5, 19, 12, 30)
        self.assertEqual(next_workable_moment(dt, self.env), dt)

    def test_after_workday_end_jumps_to_next_morning(self):
        dt = L(2026, 5, 19, 18, 0)
        self.assertEqual(next_workable_moment(dt, self.env), L(2026, 5, 20, 8, 0))

    def test_friday_evening_jumps_to_monday(self):
        dt = L(2026, 5, 22, 18, 0)
        self.assertEqual(next_workable_moment(dt, self.env), L(2026, 5, 25, 8, 0))

    def test_saturday_morning_jumps_to_monday(self):
        dt = L(2026, 5, 23, 9, 0)
        self.assertEqual(next_workable_moment(dt, self.env), L(2026, 5, 25, 8, 0))

    def test_before_workday_start_clamps(self):
        dt = L(2026, 5, 19, 6, 0)
        self.assertEqual(next_workable_moment(dt, self.env), L(2026, 5, 19, 8, 0))

    def test_inside_lunch_gap_jumps_to_after_lunch(self):
        env = WeekEnvelope.from_json(_week(**LUNCH))
        # 2026-05-18 is a Monday
        dt = L(2026, 5, 18, 12, 10)
        self.assertEqual(next_workable_moment(dt, env), L(2026, 5, 18, 12, 30))

    def test_exactly_at_gap_start_jumps(self):
        env = WeekEnvelope.from_json(_week(**LUNCH))
        dt = L(2026, 5, 18, 12, 0)
        self.assertEqual(next_workable_moment(dt, env), L(2026, 5, 18, 12, 30))

    def test_day_off_jumps_to_next_working_day(self):
        env = WeekEnvelope.from_json(_week(wed=[]))
        dt = L(2026, 5, 20, 10, 0)  # Wednesday off
        self.assertEqual(next_workable_moment(dt, env), L(2026, 5, 21, 8, 0))

    def test_all_off_envelope_raises(self):
        env = WeekEnvelope.from_json({k: [] for k in DAY_KEYS})
        with self.assertRaises(ValueError):
            next_workable_moment(L(2026, 5, 19, 9, 0), env)


class AddWorkTimeTest(SimpleTestCase):

    def setUp(self):
        self.env = WeekEnvelope.default()

    def test_fits_within_day(self):
        self.assertEqual(
            add_work_time(L(2026, 5, 19, 9, 0), timedelta(hours=2), self.env),
            L(2026, 5, 19, 11, 0),
        )

    def test_spans_midday_no_gap(self):
        self.assertEqual(
            add_work_time(L(2026, 5, 19, 11, 0), timedelta(hours=2), self.env),
            L(2026, 5, 19, 13, 0),
        )

    def test_spans_lunch_gap(self):
        env = WeekEnvelope.from_json(_week(**LUNCH))
        # Mon 11:00 + 2h: 1h to 12:00, gap, 1h from 12:30 = 13:30
        self.assertEqual(
            add_work_time(L(2026, 5, 18, 11, 0), timedelta(hours=2), env),
            L(2026, 5, 18, 13, 30),
        )

    def test_crosses_overnight(self):
        self.assertEqual(
            add_work_time(L(2026, 5, 19, 15, 0), timedelta(hours=3), self.env),
            L(2026, 5, 20, 9, 0),
        )

    def test_crosses_overnight_from_midday(self):
        self.assertEqual(
            add_work_time(L(2026, 5, 19, 11, 0), timedelta(hours=8), self.env),
            L(2026, 5, 20, 10, 0),
        )

    def test_crosses_weekend(self):
        self.assertEqual(
            add_work_time(L(2026, 5, 22, 15, 0), timedelta(hours=3), self.env),
            L(2026, 5, 25, 9, 0),
        )

    def test_crosses_day_off(self):
        env = WeekEnvelope.from_json(_week(wed=[]))
        # Tue 16:00 + 2h: 1h to 17:00, Wed off, 1h Thu from 08:00 = Thu 09:00
        self.assertEqual(
            add_work_time(L(2026, 5, 19, 16, 0), timedelta(hours=2), env),
            L(2026, 5, 21, 9, 0),
        )

    def test_starts_after_workday_end(self):
        self.assertEqual(
            add_work_time(L(2026, 5, 19, 18, 0), timedelta(hours=1), self.env),
            L(2026, 5, 20, 9, 0),
        )

    def test_starts_before_workday_start(self):
        self.assertEqual(
            add_work_time(L(2026, 5, 19, 6, 0), timedelta(hours=1), self.env),
            L(2026, 5, 19, 9, 0),
        )

    def test_starts_inside_gap(self):
        env = WeekEnvelope.from_json(_week(**LUNCH))
        self.assertEqual(
            add_work_time(L(2026, 5, 18, 12, 10), timedelta(hours=1), env),
            L(2026, 5, 18, 13, 30),
        )

    def test_zero_duration(self):
        start = L(2026, 5, 19, 9, 0)
        self.assertEqual(add_work_time(start, timedelta(0), self.env), start)

    def test_multi_day_long_span(self):
        # Mon 09:00 + 20h: Mon 9→17 = 8h, Tue 8→17 = 9h (17h), Wed 8 + 3h = 11:00.
        self.assertEqual(
            add_work_time(L(2026, 5, 18, 9, 0), timedelta(hours=20), self.env),
            L(2026, 5, 20, 11, 0),
        )

    def test_split_shift_evening(self):
        env = WeekEnvelope.from_json(
            _week(mon=[['08:00', '12:00'], ['18:00', '22:00']]))
        # Mon 11:00 + 3h: 1h to 12:00, then 2h from 18:00 = 20:00
        self.assertEqual(
            add_work_time(L(2026, 5, 18, 11, 0), timedelta(hours=3), env),
            L(2026, 5, 18, 20, 0),
        )


class SegmentsForTest(SimpleTestCase):

    def setUp(self):
        self.env = WeekEnvelope.default()

    def test_no_cross(self):
        s, e = L(2026, 5, 19, 9, 0), L(2026, 5, 19, 11, 0)
        self.assertEqual(segments_for(s, e, self.env), [(s, e)])

    def test_spans_midday_single_segment(self):
        s = L(2026, 5, 19, 11, 0)
        e = L(2026, 5, 19, 14, 0)
        self.assertEqual(segments_for(s, e, self.env), [(s, e)])

    def test_splits_at_lunch_gap(self):
        env = WeekEnvelope.from_json(_week(**LUNCH))
        s = L(2026, 5, 18, 11, 0)
        e = L(2026, 5, 18, 13, 30)
        self.assertEqual(segments_for(s, e, env), [
            (s, L(2026, 5, 18, 12, 0)),
            (L(2026, 5, 18, 12, 30), e),
        ])

    def test_crosses_overnight_only(self):
        s = L(2026, 5, 19, 15, 0)
        e = L(2026, 5, 20, 10, 0)
        self.assertEqual(segments_for(s, e, self.env), [
            (s, L(2026, 5, 19, 17, 0)),
            (L(2026, 5, 20, 8, 0), e),
        ])

    def test_crosses_weekend(self):
        s = L(2026, 5, 22, 15, 0)  # Fri
        e = L(2026, 5, 25, 10, 0)  # Mon
        self.assertEqual(segments_for(s, e, self.env), [
            (s, L(2026, 5, 22, 17, 0)),
            (L(2026, 5, 25, 8, 0), e),
        ])

    def test_crosses_day_off(self):
        env = WeekEnvelope.from_json(_week(wed=[]))
        s = L(2026, 5, 19, 16, 0)  # Tue
        e = L(2026, 5, 21, 9, 0)   # Thu
        self.assertEqual(segments_for(s, e, env), [
            (s, L(2026, 5, 19, 17, 0)),
            (L(2026, 5, 21, 8, 0), e),
        ])


class WorkMinutesBetweenTest(SimpleTestCase):

    def setUp(self):
        self.env = WeekEnvelope.default()

    def test_within_day(self):
        self.assertEqual(
            work_minutes_between(L(2026, 5, 19, 9, 0), L(2026, 5, 19, 11, 0), self.env),
            120,
        )

    def test_spans_midday_counts_continuously(self):
        self.assertEqual(
            work_minutes_between(L(2026, 5, 19, 11, 0), L(2026, 5, 19, 14, 0), self.env),
            180,
        )

    def test_gap_time_not_counted(self):
        env = WeekEnvelope.from_json(_week(**LUNCH))
        self.assertEqual(
            work_minutes_between(L(2026, 5, 18, 11, 0), L(2026, 5, 18, 13, 30), env),
            120,
        )

    def test_crosses_overnight(self):
        self.assertEqual(
            work_minutes_between(L(2026, 5, 19, 16, 0), L(2026, 5, 20, 9, 0), self.env),
            120,
        )

    def test_b_before_a_is_zero(self):
        self.assertEqual(
            work_minutes_between(L(2026, 5, 19, 11, 0), L(2026, 5, 19, 10, 0), self.env),
            0,
        )


class DaySegmentsClampedTest(SimpleTestCase):
    """Actual-bar segmentation: split ONLY at local midnight, clamp to the
    display axis hours, flag what got cut. Never envelope-aware — logged work
    draws over breaks."""

    AXIS = (time(8, 0), time(20, 0))

    def _clamped(self, s, e):
        return day_segments_clamped(s, e, *self.AXIS)

    def test_same_day_within_axis_single_unclipped(self):
        s, e = L(2026, 5, 19, 9, 0), L(2026, 5, 19, 11, 0)
        self.assertEqual(self._clamped(s, e), [
            {'start': s, 'end': e, 'clipped_left': False, 'clipped_right': False},
        ])

    def test_spans_envelope_gap_stays_whole(self):
        # No envelope in sight — a blep through lunch is one piece.
        s, e = L(2026, 5, 18, 11, 0), L(2026, 5, 18, 14, 0)
        self.assertEqual(self._clamped(s, e), [
            {'start': s, 'end': e, 'clipped_left': False, 'clipped_right': False},
        ])

    def test_crosses_midnight_splits_and_clips(self):
        s = L(2026, 5, 19, 19, 0)
        e = L(2026, 5, 20, 9, 0)
        result = self._clamped(s, e)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['start'], s)
        self.assertEqual(result[0]['end'], L(2026, 5, 19, 20, 0))
        self.assertTrue(result[0]['clipped_right'])
        self.assertEqual(result[1]['start'], L(2026, 5, 20, 8, 0))
        self.assertEqual(result[1]['end'], e)
        self.assertTrue(result[1]['clipped_left'])

    def test_end_past_axis_clips_right(self):
        s = L(2026, 5, 19, 18, 0)
        e = L(2026, 5, 19, 22, 0)
        result = self._clamped(s, e)
        self.assertEqual(result, [
            {'start': s, 'end': L(2026, 5, 19, 20, 0),
             'clipped_left': False, 'clipped_right': True},
        ])

    def test_fully_after_axis_yields_sliver_at_axis_end(self):
        s = L(2026, 5, 19, 22, 0)
        e = L(2026, 5, 19, 23, 30)
        result = self._clamped(s, e)
        self.assertEqual(result, [
            {'start': L(2026, 5, 19, 19, 59), 'end': L(2026, 5, 19, 20, 0),
             'clipped_left': False, 'clipped_right': True},
        ])

    def test_fully_before_axis_yields_sliver_at_axis_start(self):
        s = L(2026, 5, 19, 5, 0)
        e = L(2026, 5, 19, 6, 0)
        result = self._clamped(s, e)
        self.assertEqual(result, [
            {'start': L(2026, 5, 19, 8, 0), 'end': L(2026, 5, 19, 8, 1),
             'clipped_left': True, 'clipped_right': False},
        ])

    def test_zero_width_within_axis_yields_sliver_at_start(self):
        s = L(2026, 5, 19, 10, 0)
        result = self._clamped(s, s)
        self.assertEqual(result, [
            {'start': s, 'end': L(2026, 5, 19, 10, 1),
             'clipped_left': False, 'clipped_right': False},
        ])
