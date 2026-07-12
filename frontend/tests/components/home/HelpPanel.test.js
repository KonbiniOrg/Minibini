import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/svelte';
import HelpPanel from '@/components/home/HelpPanel.svelte';

describe('HelpPanel', () => {
  it('renders the tutorial sections', () => {
    const { getByRole } = render(HelpPanel);
    for (const heading of [
      'Finding your way around',
      'Estimating',
      'Doing the work',
      'Getting paid',
      'Who can do what',
    ]) {
      expect(getByRole('heading', { name: heading })).toBeInTheDocument();
    }
  });

  it('links into the app (hash routes via use:link)', () => {
    const { getAllByRole } = render(HelpPanel);
    const hrefs = getAllByRole('link').map((a) => a.getAttribute('href'));
    for (const target of ['#/jobs/board', '#/schedule', '#/catalog/service-items', '#/settings']) {
      expect(hrefs).toContain(target);
    }
  });
});
