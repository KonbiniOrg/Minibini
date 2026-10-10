import { readable } from 'svelte/store';

// Layout axis of the view-mode design (docs/designs/architecture-and-conventions.md
// §6): a DEVICE FACT — is there room for a sidebar and a wide table? — as
// opposed to `viewMode` (lite/full), which is a USER PREFERENCE about data
// density. The two are independent: nothing may read one to infer the other.
//
// 'phone' when the viewport is at most PHONE_MAX_WIDTH px wide, else
// 'desktop'. CSS that needs the same threshold uses `@media (max-width: 720px)`
// or the `body[data-layout]` attribute main.js mirrors this store onto.
export const PHONE_MAX_WIDTH = 720;

const QUERY = `(max-width: ${PHONE_MAX_WIDTH}px)`;

export const layout = readable('desktop', (set) => {
  // jsdom and very old browsers have no matchMedia: stay 'desktop', no throw.
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
    return undefined;
  }
  const mq = window.matchMedia(QUERY);
  const apply = () => set(mq.matches ? 'phone' : 'desktop');
  apply();
  mq.addEventListener('change', apply);
  return () => mq.removeEventListener('change', apply);
});
