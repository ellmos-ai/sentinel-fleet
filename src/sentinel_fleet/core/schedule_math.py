"""Timezone-safe "next due" calculation for routine bindings.

Format and semantics are taken 1:1 from `ellmos_scheduler.schedules.next_after()` (interval /
daily / cron `kind` dicts, DST-safe via `zoneinfo`) - see the "Tasks & Routines" concept doc,
section C.1. The package itself is an internal module that is not published on PyPI and is not
installed in this environment, so this is a small, dependency-free vendor copy of just the
`next_after()` contract rather than an import of the package, per the concept's documented
fallback ("a vendor copy with an attribution note is equally acceptable"). It intentionally
does not import the scheduler's SQLite job store, lease/claim logic or tick loop - only the
pure date-math function this app actually needs to show and evaluate "next due".
"""

from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Hard stop for the cron/daily search loop, so a malformed expression cannot spin forever.
_MAX_LOOKAHEAD_MINUTES = 366 * 24 * 60


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        # A bad or missing tz database entry must degrade, not crash a fire cycle.
        return ZoneInfo("UTC")


def _first_valid_local(naive: datetime, tz: ZoneInfo) -> datetime:
    """Resolve a naive local time against a zone, stepping past a DST spring-forward gap.

    A wall-clock time that does not exist (e.g. 02:30 on the day clocks jump to 03:00) is
    nudged forward minute by minute until it lands on a real instant, instead of raising or
    silently picking an arbitrary UTC offset.
    """
    candidate = naive
    for _ in range(180):  # generous bound: DST gaps are at most a couple of hours
        aware = candidate.replace(tzinfo=tz)
        # zoneinfo never raises on an imaginary time; detect it by round-tripping through UTC.
        back = aware.astimezone(ZoneInfo("UTC")).astimezone(tz)
        if back.hour == aware.hour and back.minute == aware.minute:
            return aware
        candidate += timedelta(minutes=1)
    return naive.replace(tzinfo=tz)


def _matches_cron_field(value: int, field: str, max_value: int) -> bool:
    field = field.strip()
    if field == "*":
        return True
    for part in field.split(","):
        part = part.strip()
        if "/" in part:
            base, step = part.split("/", 1)
            step = int(step)
            if base in ("*", ""):
                lo = 0
            else:
                lo = int(base)
            if value >= lo and (value - lo) % step == 0:
                return True
        elif "-" in part:
            lo, hi = part.split("-", 1)
            if int(lo) <= value <= int(hi):
                return True
        elif part and int(part) == value:
            return True
    return False


def _cron_matches(moment: datetime, expression: str) -> bool:
    fields = expression.split()
    if len(fields) != 5:
        raise ValueError(f"Cron expression must have 5 fields, got {len(fields)!r}: {expression!r}")
    minute, hour, day, month, weekday = fields
    # Python's Monday=0 .. Sunday=6; cron's Sunday=0 (or 7) .. Saturday=6.
    cron_weekday = (moment.weekday() + 1) % 7
    return (
        _matches_cron_field(moment.minute, minute, 59)
        and _matches_cron_field(moment.hour, hour, 23)
        and _matches_cron_field(moment.day, day, 31)
        and _matches_cron_field(moment.month, month, 12)
        and _matches_cron_field(cron_weekday, weekday, 6)
    )


def next_after(spec: dict, after: datetime) -> Optional[datetime]:
    """Return the next timezone-aware fire time strictly after `after`, or None if unknown.

    `spec` mirrors the three ellmos-scheduler kinds used by RoutineBinding.schedule_spec:
      {"kind": "interval", "seconds": 3600}
      {"kind": "daily", "time": "04:00", "timezone": "Europe/Berlin"}
      {"kind": "cron", "expression": "*/15 * * * *", "timezone": "Europe/Berlin"}
    `after` may be naive (treated as UTC) or aware.
    """
    if after.tzinfo is None:
        after = after.replace(tzinfo=ZoneInfo("UTC"))

    kind = spec.get("kind")

    if kind == "interval":
        seconds = int(spec.get("seconds", 0))
        if seconds <= 0:
            return None
        return after + timedelta(seconds=seconds)

    if kind == "daily":
        tz = _zone(spec.get("timezone", "UTC"))
        hh, mm = (spec.get("time") or "00:00").split(":")
        local_after = after.astimezone(tz)
        candidate_naive = local_after.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
        candidate = _first_valid_local(candidate_naive.replace(tzinfo=None), tz)
        if candidate <= local_after:
            candidate_naive = candidate_naive + timedelta(days=1)
            candidate = _first_valid_local(candidate_naive.replace(tzinfo=None), tz)
        return candidate.astimezone(ZoneInfo("UTC"))

    if kind == "cron":
        tz = _zone(spec.get("timezone", "UTC"))
        expression = spec.get("expression", "")
        cursor = after.astimezone(tz).replace(second=0, microsecond=0) + timedelta(minutes=1)
        for _ in range(_MAX_LOOKAHEAD_MINUTES):
            if _cron_matches(cursor, expression):
                return cursor.astimezone(ZoneInfo("UTC"))
            cursor += timedelta(minutes=1)
        return None

    if kind == "idle_window":
        # Cloud Scheduler has no load signal to evaluate this against (concept doc, section
        # C.4) - Phase 3 territory. Reported honestly as "not computable yet" rather than
        # guessing a timestamp for a trigger this build cannot actually evaluate.
        return None

    return None
