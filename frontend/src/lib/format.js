export function formatQtyUnits(quantity, units) {
  if (quantity === null || quantity === undefined || quantity === '') {
    return '-';
  }
  if (!units || units === 'none') {
    return String(quantity);
  }
  return `${quantity} ${units}`;
}
