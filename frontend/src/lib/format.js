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
