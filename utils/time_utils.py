# 📌 utils/time_utils.py

import re
import logging

# 📌 Set up a logger for this module.
logger = logging.getLogger("utils.time_utils")
logger.setLevel(logging.DEBUG)

def convert_time(duration: str) -> int:
    """
    📌 Convert a time string (e.g., "1h", "30m", "45s") into seconds.
    📌 The input must match exactly: one or more digits followed by an optional space and a single unit [s, m, h, d, y].
    📌 Returns the total seconds as an integer or None if the format is invalid.
    """
    # 📌 Remove extra whitespace.
    duration = duration.strip()
    # 📌 Use start (^) and end ($) anchors to force an exact match.
    match = re.match(r"^(\d+)\s*([smhdy])$", duration.lower())
    if match:
        value = int(match.group(1))
        unit = match.group(2)
        time_units = {
            "s": 1,        # Seconds
            "m": 60,       # Minutes
            "h": 3600,     # Hours
            "d": 86400,    # Days
            "y": 31536000  # Years
        }
        result = value * time_units.get(unit, 0)
        logger.debug(f"convert_time: '{duration}' -> {result} seconds")
        return result
    logger.debug(f"convert_time: '{duration}' did not match expected pattern")
    return None
