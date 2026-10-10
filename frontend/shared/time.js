/**
 * FIT-RIDE Time Utilities (Team KNIGHT | PS 40)
 * Timezone: Asia/Kolkata (IST = UTC+05:30)
 * Handles ISO UTC conversions, human-friendly local displays, and slot increments.
 */

const FleetTime = {
  TIMEZONE: 'Asia/Kolkata',

  /**
   * Convert a local Date, or dateStr ('YYYY-MM-DD') and timeStr ('HH:MM')
   * into a UTC ISO-8601 string ('YYYY-MM-DDTHH:MM:SSZ').
   * Interprets input as Asia/Kolkata (+05:30) time.
   */
  toUtcIso(dateStr, timeStr) {
    if (!dateStr || !timeStr) return null;

    // Build ISO string with IST (+05:30) offset
    const cleanDate = dateStr.trim();
    const cleanTime = timeStr.trim().length === 5 ? `${timeStr.trim()}:00` : timeStr.trim();
    const istIso = `${cleanDate}T${cleanTime}+05:30`;

    const d = new Date(istIso);
    if (isNaN(d.getTime())) {
      // Fallback
      return new Date(`${cleanDate}T${cleanTime}`).toISOString();
    }
    return d.toISOString();
  },

  /**
   * Parse a UTC ISO string and format it for friendly local display in Asia/Kolkata.
   * Example: "Tomorrow, 10:30 AM" or "12 Oct 2026, 04:00 PM IST"
   */
  formatLocal(utcIsoStr, showSeconds = false) {
    if (!utcIsoStr) return '—';
    const d = new Date(utcIsoStr);
    if (isNaN(d.getTime())) return String(utcIsoStr);

    return d.toLocaleString('en-IN', {
      timeZone: this.TIMEZONE,
      day: '2-digit',
      month: 'short',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      second: showSeconds ? '2-digit' : undefined,
      hour12: true,
    });
  },

  /**
   * Alias for formatLocal for backwards compatibility.
   */
  formatIsoLocal(utcIsoStr, showSeconds = false) {
    return this.formatLocal(utcIsoStr, showSeconds);
  },

  /**
   * Format just the time part in Asia/Kolkata (e.g. "10:30 AM")
   */
  formatLocalTime(utcIsoStr) {
    if (!utcIsoStr) return '—';
    const d = new Date(utcIsoStr);
    if (isNaN(d.getTime())) return '';

    return d.toLocaleTimeString('en-IN', {
      timeZone: this.TIMEZONE,
      hour: '2-digit',
      minute: '2-digit',
      hour12: true,
    });
  },

  /**
   * Format just the date part in Asia/Kolkata (e.g. "12 Oct 2026")
   */
  formatLocalDate(utcIsoStr) {
    if (!utcIsoStr) return '—';
    const d = new Date(utcIsoStr);
    if (isNaN(d.getTime())) return '';

    return d.toLocaleDateString('en-IN', {
      timeZone: this.TIMEZONE,
      day: '2-digit',
      month: 'short',
      year: 'numeric',
    });
  },

  /**
   * Calculate human duration string between two UTC ISO strings (e.g. "2h 30m")
   */
  formatDuration(startUtcIso, endUtcIso) {
    if (!startUtcIso || !endUtcIso) return '—';
    const s = new Date(startUtcIso).getTime();
    const e = new Date(endUtcIso).getTime();
    if (isNaN(s) || isNaN(e) || e <= s) return '—';

    const diffMin = Math.round((e - s) / (1000 * 60));
    const hours = Math.floor(diffMin / 60);
    const mins = diffMin % 60;

    if (hours > 0 && mins > 0) return `${hours}h ${mins}m`;
    if (hours > 0) return `${hours}h`;
    return `${mins}m`;
  },

  /**
   * Calculate difference in minutes between two local HH:MM strings.
   * Handles next-day rollover if end < start.
   */
  diffMinutesLocal(startTimeStr, endTimeStr) {
    if (!startTimeStr || !endTimeStr) return 0;
    const [sh, sm] = startTimeStr.split(':').map(Number);
    const [eh, em] = endTimeStr.split(':').map(Number);
    let sMin = sh * 60 + sm;
    let eMin = eh * 60 + em;
    if (eMin < sMin) eMin += 24 * 60;
    return eMin - sMin;
  },

  /**
   * Return the current date and time in Asia/Kolkata broken down into
   * dateStr ('YYYY-MM-DD') and timeStr ('HH:MM') rounded up to next 30 minutes.
   * Handles midnight / date rollovers accurately by rounding timestamp first.
   */
  getNextAvailableSlot(minutesFromNow = 30) {
    const now = new Date();
    const targetMs = now.getTime() + minutesFromNow * 60 * 1000;
    const slotMs = 30 * 60 * 1000;
    const roundedMs = Math.ceil(targetMs / slotMs) * slotMs;
    const roundedDate = new Date(roundedMs);

    const formatter = new Intl.DateTimeFormat('en-CA', {
      timeZone: this.TIMEZONE,
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    });

    const parts = formatter.formatToParts(roundedDate);
    const map = {};
    for (const p of parts) map[p.type] = p.value;

    const hourStr = map.hour === '24' ? '00' : map.hour;
    return {
      dateStr: `${map.year}-${map.month}-${map.day}`,
      timeStr: `${hourStr}:${map.minute}`,
    };
  },

  /**
   * Add hours and minutes to a dateStr + timeStr in Asia/Kolkata
   * and return the ending dateStr and timeStr.
   */
  addDuration(dateStr, timeStr, durationMinutes) {
    const startUtc = this.toUtcIso(dateStr, timeStr);
    const startDate = new Date(startUtc);
    const endDate = new Date(startDate.getTime() + durationMinutes * 60 * 1000);

    const formatter = new Intl.DateTimeFormat('en-CA', {
      timeZone: this.TIMEZONE,
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    });

    const parts = formatter.formatToParts(endDate);
    const map = {};
    for (const p of parts) map[p.type] = p.value;

    const hourStr = map.hour === '24' ? '00' : map.hour;
    return {
      dateStr: `${map.year}-${map.month}-${map.day}`,
      timeStr: `${hourStr}:${map.minute}`,
      utcIso: endDate.toISOString(),
    };
  },

  /**
   * Robustly compute the end time UTC ISO string.
   * If endTimeStr <= startTimeStr, the trip crosses midnight into the next day.
   */
  calculateEndUtcIso(startDateStr, startTimeStr, endTimeStr, durationMinutes = null) {
    const startUtc = this.toUtcIso(startDateStr, startTimeStr);
    if (!startUtc) return null;

    if (endTimeStr && String(endTimeStr).trim()) {
      let endUtc = this.toUtcIso(startDateStr, endTimeStr);
      if (new Date(endUtc) <= new Date(startUtc)) {
        // Midnight crossing: end date is next calendar day (+24 hours)
        const nextDayStartDate = new Date(new Date(startUtc).getTime() + 24 * 60 * 60 * 1000);
        const formatter = new Intl.DateTimeFormat('en-CA', {
          timeZone: this.TIMEZONE,
          year: 'numeric',
          month: '2-digit',
          day: '2-digit',
        });
        const parts = formatter.formatToParts(nextDayStartDate);
        const map = {};
        for (const p of parts) map[p.type] = p.value;
        const nextDateStr = `${map.year}-${map.month}-${map.day}`;
        endUtc = this.toUtcIso(nextDateStr, endTimeStr);
      }
      return endUtc;
    }

    if (durationMinutes) {
      return this.addDuration(startDateStr, startTimeStr, durationMinutes).utcIso;
    }

    return null;
  },
};

window.FleetTime = FleetTime;
