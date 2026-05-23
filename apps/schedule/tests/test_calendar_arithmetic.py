from datetime import date, datetime, time, timedelta
from django.test import SimpleTestCase
from django.utils import timezone as dj_tz

from apps.schedule.calendar_arithmetic import (
    DayShape,
    _combine_local,
    add_work_time,
    is_working_day,
    next_workable_moment,
    segments_for,
    work_minutes_between,
    workday_end_on,
    workday_start_on,
)


def L(y, m, d, hh, mm):
    return _combine_local(date(y, m, d), time(hh, mm))


class DayShapeTest(SimpleTestCase):

    def test_default_shape(self):
        shape = DayShape.default()
        self.assertEqual(shape.workday_start, time(8, 0))
        self.assertEqual(shape.workday_end, time(17, 0))
        self.assertEqual(shape.task_buffer_minutes, 10)


class IsWorkingDayTest(SimpleTestCase):

    def test_weekday_is_working(self):
        self.assertTrue(is_working_day(date(2026, 5, 18)))  # Mon
        self.assertTrue(is_working_day(date(2026, 5, 19)))  # Tue
        self.assertTrue(is_working_day(date(2026, 5, 22)))  # Fri

    def test_saturday_is_not_working(self):
        self.assertFalse(is_working_day(date(2026, 5, 23)))

    def test_sunday_is_not_working(self):
        self.assertFalse(is_working_day(date(2026, 5, 24)))


class WorkdayBoundsTest(SimpleTestCase):

    def test_workday_start_on(self):
        shape = DayShape.default()
        d = date(2026, 5, 19)
        result = workday_start_on(d, shape)
        self.assertEqual(result.date(), d)
        self.assertEqual(result.time(), time(8, 0))

    def test_workday_end_on(self):
        shape = DayShape.default()
        d = date(2026, 5, 19)
        result = workday_end_on(d, shape)
        self.assertEqual(result.date(), d)
        self.assertEqual(result.time(), time(17, 0))


class NextWorkableMomentTest(SimpleTestCase):

    def setUp(self):
        self.shape = DayShape.default()

    def test_mid_morning_unchanged(self):
        dt = L(2026, 5, 19, 9, 30)
        self.assertEqual(next_workable_moment(dt, self.shape), dt)

    def test_midday_is_workable(self):
        # The workday is continuous — noon is a normal working moment.
        dt = L(2026, 5, 19, 12, 30)
        self.assertEqual(next_workable_moment(dt, self.shape), dt)

    def test_after_workday_end_jumps_to_next_morning(self):
        dt = L(2026, 5, 19, 18, 0)
        self.assertEqual(next_workable_moment(dt, self.shape), L(2026, 5, 20, 8, 0))

    def test_friday_evening_jumps_to_monday(self):
        dt = L(2026, 5, 22, 18, 0)
        self.assertEqual(next_workable_moment(dt, self.shape), L(2026, 5, 25, 8, 0))

    def test_saturday_morning_jumps_to_monday(self):
        dt = L(2026, 5, 23, 9, 0)
        self.assertEqual(next_workable_moment(dt, self.shape), L(2026, 5, 25, 8, 0))

    def test_before_workday_start_clamps(self):
        dt = L(2026, 5, 19, 6, 0)
        self.assertEqual(next_workable_moment(dt, self.shape), L(2026, 5, 19, 8, 0))


class AddWorkTimeTest(SimpleTestCase):

    def setUp(self):
        self.shape = DayShape.default()

    def test_fits_within_day(self):
        self.assertEqual(
            add_work_time(L(2026, 5, 19, 9, 0), timedelta(hours=2), self.shape),
            L(2026, 5, 19, 11, 0),
        )

    def test_spans_midday_no_lunch(self):
        # Continuous workday: 11:00 + 2h = 13:00 (no lunch skip).
        self.assertEqual(
            add_work_time(L(2026, 5, 19, 11, 0), timedelta(hours=2), self.shape),
            L(2026, 5, 19, 13, 0),
        )

    def test_crosses_overnight(self):
        # Tue 15:00 + 3h work = Tue 17:00 (2h) then Wed 08:00 + 1h = Wed 09:00
        self.assertEqual(
            add_work_time(L(2026, 5, 19, 15, 0), timedelta(hours=3), self.shape),
            L(2026, 5, 20, 9, 0),
        )

    def test_crosses_overnight_from_midday(self):
        # Tue 11:00 + 8h: 6h to EOD (17:00), 2h on Wed = Wed 10:00
        self.assertEqual(
            add_work_time(L(2026, 5, 19, 11, 0), timedelta(hours=8), self.shape),
            L(2026, 5, 20, 10, 0),
        )

    def test_crosses_weekend(self):
        # Fri 15:00 + 3h = Fri 17:00 (2h) then Mon 08:00 + 1h = Mon 09:00
        self.assertEqual(
            add_work_time(L(2026, 5, 22, 15, 0), timedelta(hours=3), self.shape),
            L(2026, 5, 25, 9, 0),
        )

    def test_starts_after_workday_end(self):
        # 18:00 Tue → next morning 08:00 + 1h = Wed 09:00
        self.assertEqual(
            add_work_time(L(2026, 5, 19, 18, 0), timedelta(hours=1), self.shape),
            L(2026, 5, 20, 9, 0),
        )

    def test_starts_before_workday_start(self):
        # 06:00 → clamps to 08:00, + 1h = 09:00
        self.assertEqual(
            add_work_time(L(2026, 5, 19, 6, 0), timedelta(hours=1), self.shape),
            L(2026, 5, 19, 9, 0),
        )

    def test_zero_duration(self):
        start = L(2026, 5, 19, 9, 0)
        self.assertEqual(add_work_time(start, timedelta(0), self.shape), start)

    def test_multi_day_long_span(self):
        # Mon 09:00 + 20h: Mon 9→17 = 8h, Tue 8→17 = 9h (17h), Wed 8 + 3h = 11:00.
        self.assertEqual(
            add_work_time(L(2026, 5, 18, 9, 0), timedelta(hours=20), self.shape),
            L(2026, 5, 20, 11, 0),
        )


class SegmentsForTest(SimpleTestCase):

    def setUp(self):
        self.shape = DayShape.default()

    def test_no_cross(self):
        s, e = L(2026, 5, 19, 9, 0), L(2026, 5, 19, 11, 0)
        self.assertEqual(segments_for(s, e, self.shape), [(s, e)])

    def test_spans_midday_single_segment(self):
        # Continuous workday — no lunch split.
        s = L(2026, 5, 19, 11, 0)
        e = L(2026, 5, 19, 14, 0)
        self.assertEqual(segments_for(s, e, self.shape), [(s, e)])

    def test_crosses_overnight_only(self):
        s = L(2026, 5, 19, 15, 0)
        e = L(2026, 5, 20, 10, 0)
        self.assertEqual(segments_for(s, e, self.shape), [
            (s, L(2026, 5, 19, 17, 0)),
            (L(2026, 5, 20, 8, 0), e),
        ])

    def test_crosses_overnight_from_midday(self):
        s = L(2026, 5, 19, 11, 0)
        e = L(2026, 5, 20, 10, 0)
        self.assertEqual(segments_for(s, e, self.shape), [
            (s, L(2026, 5, 19, 17, 0)),
            (L(2026, 5, 20, 8, 0), e),
        ])

    def test_crosses_weekend(self):
        s = L(2026, 5, 22, 15, 0)  # Fri
        e = L(2026, 5, 25, 10, 0)  # Mon
        self.assertEqual(segments_for(s, e, self.shape), [
            (s, L(2026, 5, 22, 17, 0)),
            (L(2026, 5, 25, 8, 0), e),
        ])


class WorkMinutesBetweenTest(SimpleTestCase):

    def setUp(self):
        self.shape = DayShape.default()

    def test_within_day(self):
        self.assertEqual(
            work_minutes_between(L(2026, 5, 19, 9, 0), L(2026, 5, 19, 11, 0), self.shape),
            120,
        )

    def test_spans_midday_counts_continuously(self):
        # 11:00→14:00 with no lunch = 180 minutes.
        self.assertEqual(
            work_minutes_between(L(2026, 5, 19, 11, 0), L(2026, 5, 19, 14, 0), self.shape),
            180,
        )

    def test_crosses_overnight(self):
        self.assertEqual(
            work_minutes_between(L(2026, 5, 19, 16, 0), L(2026, 5, 20, 9, 0), self.shape),
            120,
        )

    def test_b_before_a_is_zero(self):
        self.assertEqual(
            work_minutes_between(L(2026, 5, 19, 11, 0), L(2026, 5, 19, 10, 0), self.shape),
            0,
        )
