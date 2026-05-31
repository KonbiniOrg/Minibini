def floor_to_minute(dt):
    """Truncate a datetime to the whole minute (seconds+microseconds = 0). None-safe."""
    if dt is None:
        return None
    return dt.replace(second=0, microsecond=0)
