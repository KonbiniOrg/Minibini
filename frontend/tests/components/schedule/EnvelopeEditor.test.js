import { describe, it, expect, vi } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import EnvelopeEditor from '@/components/schedule/EnvelopeEditor.svelte';

const WEEK = () => ({
  mon: [['08:00', '12:00'], ['12:30', '17:00']],
  tue: [['08:00', '17:00']],
  wed: [['08:00', '17:00']],
  thu: [['08:00', '17:00']],
  fri: [['08:00', '17:00']],
  sat: [],
  sun: [],
});

describe('EnvelopeEditor', () => {
  it('renders seven day rows with intervals and day-off markers', () => {
    const { getByText, getAllByText, container } = render(EnvelopeEditor, {
      props: { value: WEEK(), onchange: vi.fn() },
    });
    expect(getByText('Mon')).toBeInTheDocument();
    expect(getByText('Sun')).toBeInTheDocument();
    // Monday has two interval rows → 2 start inputs + 2 end inputs there.
    const monRow = getByText('Mon').closest('.env-day');
    expect(monRow.querySelectorAll('input[type="time"]')).toHaveLength(4);
    // Sat + Sun are days off.
    expect(getAllByText('Day off')).toHaveLength(2);
    expect(container.querySelectorAll('.env-day')).toHaveLength(7);
  });

  it('adds a default interval to an empty day', async () => {
    const onchange = vi.fn();
    const { getByText } = render(EnvelopeEditor, {
      props: { value: WEEK(), onchange },
    });
    const satRow = getByText('Sat').closest('.env-day');
    await fireEvent.click(satRow.querySelector('button.env-add'));
    expect(onchange).toHaveBeenCalledWith(
      expect.objectContaining({ sat: [['08:00', '17:00']] })
    );
  });

  it('removes an interval, emptying to day off', async () => {
    const onchange = vi.fn();
    const { getByText } = render(EnvelopeEditor, {
      props: { value: WEEK(), onchange },
    });
    const tueRow = getByText('Tue').closest('.env-day');
    await fireEvent.click(tueRow.querySelector('button.env-remove'));
    expect(onchange).toHaveBeenCalledWith(
      expect.objectContaining({ tue: [] })
    );
  });

  it('edits an interval time and reports the new value', async () => {
    const onchange = vi.fn();
    const { getByText } = render(EnvelopeEditor, {
      props: { value: WEEK(), onchange },
    });
    const wedRow = getByText('Wed').closest('.env-day');
    const startInput = wedRow.querySelector('input[type="time"]');
    await fireEvent.input(startInput, { target: { value: '07:00' } });
    expect(onchange).toHaveBeenCalledWith(
      expect.objectContaining({ wed: [['07:00', '17:00']] })
    );
  });

  it('with allowNull and a null value shows the default placeholder and Customize', async () => {
    const onchange = vi.fn();
    const { getByText, queryByText } = render(EnvelopeEditor, {
      props: { value: null, allowNull: true, onchange },
    });
    expect(getByText(/Using the shop schedule/)).toBeInTheDocument();
    expect(queryByText('Mon')).toBeNull();
    await fireEvent.click(getByText('Customize'));
    // Customizing seeds a standard editable week.
    expect(onchange).toHaveBeenCalledWith(
      expect.objectContaining({ mon: [['08:00', '17:00']], sun: [] })
    );
  });

  it('with allowNull and a value offers reset back to the shop default', async () => {
    const onchange = vi.fn();
    const { getByText } = render(EnvelopeEditor, {
      props: { value: WEEK(), allowNull: true, onchange },
    });
    await fireEvent.click(getByText('Use shop default'));
    expect(onchange).toHaveBeenCalledWith(null);
  });

  it('never shows the null affordances without allowNull', () => {
    const { queryByText } = render(EnvelopeEditor, {
      props: { value: WEEK(), onchange: vi.fn() },
    });
    expect(queryByText('Use shop default')).toBeNull();
  });
});
