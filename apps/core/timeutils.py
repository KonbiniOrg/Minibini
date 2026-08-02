from decimal import Decimal

SECONDS_PER_HOUR = Decimal('3600')


def floor_to_minute(dt):
    """Truncate a datetime to the whole minute (seconds+microseconds = 0). None-safe."""
    if dt is None:
        return None
    return dt.replace(second=0, microsecond=0)


def timedelta_to_hours(td):
    """timedelta → Decimal hours, unquantized (callers pick their rounding).

    None-safe: None → None. The single seconds/3600 conversion — billing
    (RateScheme.get_actual_qty), cost (financials), progress (overview) and
    the task serializer all route here so they can't drift.
    """
    if td is None:
        return None
    return Decimal(str(td.total_seconds())) / SECONDS_PER_HOUR
