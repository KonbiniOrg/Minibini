// User-facing setup hint text, one entry per gated area.
// Edit freely — the dev server hot-reloads this file, so changes appear
// in the browser on save. Shown in the sidebar's floating callouts and the
// Home "Finish setting up" checklist. Areas missing here fall back to the
// backend's /api/setup/status/ message.
export const setupHints = {
  email:
    'Minibini needs a mailbox to fetch from and send as. ' +
    'Add your email service configuration on the Settings → Email tab.',
  catalog:
    'The catalog needs at least one accounting category and one rate ' +
    'scheme. Create them in Settings — or connect QuickBooks there and ' +
    'pull your existing setup.',
  jobs:
    'Jobs belong to customers. Add a contact — or import your QBO ' +
    'customers from the Contacts area — and this unlocks.',
  estimates:
    'Estimates live on jobs, and jobs need a customer contact first.',
  invoices:
    'Invoices live on jobs, and jobs need a customer contact first.',
  purchasing:
    'Purchase orders go to vendors. Add a vendor business — or import ' +
    'your QBO vendors from the Contacts area.',
};

export function setupHint(area, fallback = '') {
  return setupHints[area] || fallback;
}
