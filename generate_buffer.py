#!/usr/bin/env python3
"""
Prep-time buffer generator for Booking.com (or any iCal source).

Reads a source iCal feed containing reservations, and writes buffer.ics
containing "prep time" block events around each reservation:

  - BUFFER_BEFORE nights blocked immediately before each check-in
  - BUFFER_AFTER  nights blocked immediately after each check-out

The output feed contains ONLY the buffer blocks (never the reservations
themselves), so it is safe to import back into Booking.com.

Configuration is via environment variables (set in the GitHub Actions
workflow file):

  BOOKING_ICS_URL   (required)  URL of the Booking.com "Export calendar" link
  BUFFER_BEFORE     (optional)  nights to block before check-in  (default: 1)
  BUFFER_AFTER      (optional)  nights to block after check-out  (default: 1)

No third-party libraries required - Python 3 standard library only.
"""

import hashlib
import os
import sys
import urllib.request
from datetime import date, datetime, timedelta

OUTPUT_FILE = "buffer.ics"
HORIZON_PAST_DAYS = 7      # ignore reservations that ended more than a week ago
HORIZON_FUTURE_DAYS = 730  # ignore anything more than ~2 years out


def unfold(text: str):
    """Unfold RFC 5545 folded lines (continuation lines start with space/tab)."""
    lines = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw.startswith((" ", "\t")) and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    return lines


def parse_ics_date(value: str):
    """Parse an iCal DTSTART/DTEND value ('20260801' or '20260801T140000Z')."""
    value = value.strip()
    if len(value) < 8:
        return None
    try:
        return date(int(value[0:4]), int(value[4:6]), int(value[6:8]))
    except ValueError:
        return None


def extract_reservations(ics_text: str):
    """Return a list of (checkin_date, checkout_date) tuples from VEVENTs.

    In iCal all-day events, DTEND is exclusive - which matches hotel
    semantics: DTSTART = check-in date, DTEND = check-out date, and the
    occupied nights are [DTSTART, DTEND).
    """
    reservations = []
    in_event = False
    dtstart = dtend = None

    for line in unfold(ics_text):
        upper = line.upper()
        if upper.startswith("BEGIN:VEVENT"):
            in_event, dtstart, dtend = True, None, None
        elif upper.startswith("END:VEVENT"):
            if in_event and dtstart:
                if dtend is None or dtend <= dtstart:
                    dtend = dtstart + timedelta(days=1)
                reservations.append((dtstart, dtend))
            in_event = False
        elif in_event:
            if upper.startswith("DTSTART"):
                dtstart = parse_ics_date(line.split(":", 1)[-1])
            elif upper.startswith("DTEND"):
                dtend = parse_ics_date(line.split(":", 1)[-1])

    return reservations


def build_buffer_nights(reservations, buffer_before: int, buffer_after: int):
    """Compute the set of individual nights to block.

    A night is represented by its calendar date. Nights that are already
    occupied by a reservation are excluded (blocking them again is
    pointless and could feed back into the source calendar).
    """
    occupied = set()
    for checkin, checkout in reservations:
        night = checkin
        while night < checkout:
            occupied.add(night)
            night += timedelta(days=1)

    today = date.today()
    lo = today - timedelta(days=HORIZON_PAST_DAYS)
    hi = today + timedelta(days=HORIZON_FUTURE_DAYS)

    buffer_nights = set()
    for checkin, checkout in reservations:
        for i in range(1, buffer_before + 1):
            buffer_nights.add(checkin - timedelta(days=i))
        for i in range(0, buffer_after):
            buffer_nights.add(checkout + timedelta(days=i))

    return sorted(
        n for n in buffer_nights
        if n not in occupied and lo <= n <= hi
    )


def group_into_ranges(nights):
    """Merge consecutive nights into (start, end_exclusive) ranges."""
    ranges = []
    for night in nights:
        if ranges and ranges[-1][1] == night:
            ranges[-1][1] = night + timedelta(days=1)
        else:
            ranges.append([night, night + timedelta(days=1)])
    return [(a, b) for a, b in ranges]


def render_ics(ranges):
    """Render the buffer ranges as a VCALENDAR string (deterministic output)."""
    out = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//prep-buffer-generator//EN",
        "CALSCALE:GREGORIAN",
    ]
    for start, end in ranges:
        uid_seed = f"{start.isoformat()}_{end.isoformat()}"
        uid = hashlib.md5(uid_seed.encode()).hexdigest()[:16]
        out += [
            "BEGIN:VEVENT",
            f"UID:prep-{uid}@buffer-generator",
            f"DTSTAMP:{start.strftime('%Y%m%d')}T000000Z",
            f"DTSTART;VALUE=DATE:{start.strftime('%Y%m%d')}",
            f"DTEND;VALUE=DATE:{end.strftime('%Y%m%d')}",
            "SUMMARY:Prep time (auto-generated)",
            "TRANSP:OPAQUE",
            "END:VEVENT",
        ]
    out.append("END:VCALENDAR")
    return "\r\n".join(out) + "\r\n"


def main():
    url = os.environ.get("BOOKING_ICS_URL", "").strip()
    if not url:
        print("ERROR: BOOKING_ICS_URL environment variable is not set.", file=sys.stderr)
        sys.exit(1)

    buffer_before = int(os.environ.get("BUFFER_BEFORE", "1"))
    buffer_after = int(os.environ.get("BUFFER_AFTER", "1"))

    req = urllib.request.Request(url, headers={"User-Agent": "prep-buffer-generator/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        ics_text = resp.read().decode("utf-8", errors="replace")

    if "BEGIN:VCALENDAR" not in ics_text.upper():
        print("ERROR: The fetched URL does not look like an iCal feed.", file=sys.stderr)
        sys.exit(1)

    reservations = extract_reservations(ics_text)
    nights = build_buffer_nights(reservations, buffer_before, buffer_after)
    ranges = group_into_ranges(nights)

    with open(OUTPUT_FILE, "w", newline="") as f:
        f.write(render_ics(ranges))

    print(f"Source reservations found : {len(reservations)}")
    print(f"Buffer nights generated   : {len(nights)}")
    print(f"Written to                : {OUTPUT_FILE}")
    for start, end in ranges:
        print(f"  blocked: {start} -> {end - timedelta(days=1)} (inclusive)")


if __name__ == "__main__":
    main()
