export function formatQtyUnits(quantity, units) {
  if (quantity === null || quantity === undefined || quantity === '') {
    return '-';
  }
  if (!units || units === 'none') {
    return String(quantity);
  }
  return `${quantity} ${units}`;
}

// Parse user duration input to an ISO 8601 duration string ("PT1H30M").
// Accepts "HH:MM" (e.g. "1:30") or decimal hours (e.g. "1.5").
// Returns null for empty input, false for unparseable input.
export function parseDurationToISO(input) {
  if (input === '' || input === null || input === undefined) return null;
  const trimmed = String(input).trim();
  if (trimmed === '') return null;
  const colon = trimmed.match(/^(\d+):(\d+)$/);
  if (colon) {
    return `PT${parseInt(colon[1], 10)}H${parseInt(colon[2], 10)}M`;
  }
  const decimal = trimmed.match(/^(\d+\.?\d*|\.\d+)$/);
  if (decimal) {
    const totalMinutes = Math.round(parseFloat(decimal[1]) * 60);
    return `PT${Math.floor(totalMinutes / 60)}H${totalMinutes % 60}M`;
  }
  return false;
}

// Format a DRF DurationField string ("[D ]H:MM:SS[.ffffff]") as "1h 30m".
export function formatDuration(raw) {
  if (!raw) return '-';
  let days = 0;
  let timePart = String(raw);
  if (timePart.includes(' ')) {
    const [d, t] = timePart.split(' ');
    days = parseInt(d, 10) || 0;
    timePart = t;
  }
  const [h, m] = timePart.split(':');
  const hours = days * 24 + (parseInt(h, 10) || 0);
  const minutes = parseInt(m, 10) || 0;
  return hours > 0 ? `${hours}h ${minutes}m` : `${minutes}m`;
}

// Session/timestamp display, app-wide convention: day name + 12-hour time
// within the last 7 days ("Sat 2:05 PM"); calendar date beyond that
// ("Mar 1, 2:05 PM" — day names are ambiguous past a week); year appended
// when it isn't the current year ("Dec 30 2025, 9:30 AM"). Timestamps are
// rounded to the nearest minute.
const DOW = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const WEEK_MS = 7 * 24 * 60 * 60 * 1000;

export function formatSessionDateTime(iso) {
  if (!iso) return '—';
  const d = new Date(Math.round(new Date(iso).getTime() / 60000) * 60000);
  let h = d.getHours();
  const ampm = h >= 12 ? 'PM' : 'AM';
  h = h % 12 || 12;
  const time = `${h}:${String(d.getMinutes()).padStart(2, '0')} ${ampm}`;
  const now = new Date();
  if (now.getTime() - d.getTime() < WEEK_MS) {
    return `${DOW[d.getDay()]} ${time}`;
  }
  const md = `${MONTHS[d.getMonth()]} ${d.getDate()}`;
  const year = d.getFullYear() === now.getFullYear() ? '' : ` ${d.getFullYear()}`;
  return `${md}${year}, ${time}`;
}
