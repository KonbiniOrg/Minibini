export function formatQtyUnits(quantity, units) {
  if (quantity === null || quantity === undefined || quantity === '') {
    return '-';
  }
  if (!units || units === 'none') {
    return String(quantity);
  }
  return `${quantity} ${units}`;
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
