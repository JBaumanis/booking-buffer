# Booking.com Prep-Time Buffer

Automatically blocks 1 night before and 1 night after every Booking.com
reservation, guaranteeing a 1-night gap between guests for cleaning/prep.

## How it works

1. Every 30 minutes, a GitHub Actions workflow fetches your Booking.com
   calendar export (the URL is stored as a repository secret).
2. `generate_buffer.py` finds every reservation and generates `buffer.ics`
   containing only the prep-time block days.
3. Booking.com imports `buffer.ics` (via its raw file URL) and shows those
   days as unavailable.

Buffers around back-to-back bookings overlap, so the minimum gap is always
exactly 1 night — never 2.

## Configuration

Edit `.github/workflows/update-buffer.yml`:

- `BUFFER_BEFORE` — nights blocked before each check-in (default `"1"`)
- `BUFFER_AFTER`  — nights blocked after each check-out (default `"1"`,
  set `"0"` to allow same-day turnover after a stay)
- the `cron` line — how often it runs

The Booking.com export URL lives in **Settings → Secrets and variables →
Actions → BOOKING_ICS_URL**. If Booking.com ever regenerates your export
link, update the secret there.

## Notes

- iCal sync is not instant: Booking.com refreshes imported calendars every
  few hours. Setting a 1-day minimum advance reservation in the extranet
  closes most of the remaining risk window.
- When creating the Booking.com export link, choose to sync **bookings
  only** (not closed dates), otherwise the buffer days would feed back
  into the source and grow each cycle.
- The workflow only commits when the calendar actually changes, plus a
  weekly keep-alive commit so GitHub doesn't disable the schedule after
  60 days of inactivity.
