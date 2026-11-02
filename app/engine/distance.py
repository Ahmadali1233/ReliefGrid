"""Straight-line distance between two coordinates (haversine formula)."""

import math

EARTH_RADIUS_KM = 6371.0


def km_between(lat1, lon1, lat2, lon2):
    """Kilometres between two points, or None if either point has no coordinates."""
    if None in (lat1, lon1, lat2, lon2):
        return None
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))
