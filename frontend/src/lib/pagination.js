export const PAGE_SIZE = 25;

export function pageFromUrl(url) {
  const match = url?.match(/page=(\d+)/);
  return match ? parseInt(match[1]) : 1;
}

export function pageRange(paginatedData) {
  if (!paginatedData?.results?.length) return '';
  const page = paginatedData.next ? pageFromUrl(paginatedData.next) - 1
             : paginatedData.previous ? pageFromUrl(paginatedData.previous) + 1
             : 1;
  const min = (page - 1) * PAGE_SIZE + 1;
  const max = min + paginatedData.results.length - 1;
  return `${min}\u2013${max} of ${paginatedData.count}`;
}
