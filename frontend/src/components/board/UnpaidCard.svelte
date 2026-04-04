<script>
  let { job } = $props();

  function formatAmount(amount) {
    if (amount == null) return '$0.00';
    return Number(amount).toLocaleString('en-US', { style: 'currency', currency: 'USD' });
  }

  function formatDate(isoDate) {
    if (!isoDate) return '';
    return new Date(isoDate).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  }

  function hasOverdue() {
    return job.invoices?.some(inv => {
      if (inv.status === 'paid') return false;
      if (!inv.sent_date) return false;
      return inv.status === 'open' || inv.status === 'partly-paid';
    }) || false;
  }

  function invoiceStatusPill(inv) {
    if (inv.status === 'paid') return { label: 'Paid', cls: 'paid' };
    if (inv.status === 'partly-paid') return { label: 'Partly Paid', cls: 'partly' };
    if (inv.status === 'open') return { label: 'Unpaid', cls: 'open' };
    return { label: inv.status, cls: '' };
  }

  function amountClass(inv) {
    if (inv.status === 'paid') return 'amt-paid';
    return 'amt-owing';
  }

  function paymentRows(inv) {
    if (!inv.amount_paid || Number(inv.amount_paid) === 0) return [];
    return [{
      date: inv.closed_date || inv.sent_date,
      amount: inv.amount_paid,
    }];
  }

  let totalDue = $derived(() => {
    if (!job.invoices) return 0;
    return job.invoices.reduce((sum, inv) => {
      if (inv.status === 'paid' || inv.status === 'cancelled') return sum;
      const total = Number(inv.total) || 0;
      const paid = Number(inv.amount_paid) || 0;
      return sum + total - paid;
    }, 0);
  });

  let invoiceCount = $derived(job.invoices?.length || 0);
  let paymentCount = $derived(job.invoices?.filter(i => i.amount_paid && Number(i.amount_paid) > 0).length || 0);
</script>

<div class="unpaid-card" class:has-overdue={hasOverdue()} class:needs-inv={job.sub_status === 'needs-invoice'}>
  <div class="card-head">
    <div class="card-head-top">
      <span class="job-name">{job.name}</span>
      <span class="profit">
        Billed <span class="val">{formatAmount(job.billed)}</span>
        Spent <span class="val">{formatAmount(job.spent)}</span>
        Profit <span class="val" class:green={Number(job.profit) >= 0} class:red={Number(job.profit) < 0}>{formatAmount(job.profit)}</span>
      </span>
    </div>
    <div class="card-head-sub">
      <a class="customer" href="#/contacts/{job.contact_id}">{job.contact_name || 'No contact'}</a>
      <span class="job-num">{job.job_number}</span>
    </div>
  </div>
  {#if job.sub_status === 'needs-invoice'}
    <div class="needs-invoice">
      <span class="pill needs-inv">Needs Invoice</span>
      <span class="needs-inv-text">Work order complete — no invoice created yet</span>
    </div>
  {:else}
    <table class="line-table">
      {#each job.invoices || [] as inv}
        {@const pill = invoiceStatusPill(inv)}
        <tr>
          <td class="col-num">{inv.invoice_number}</td>
          <td class="col-status"><span class="pill {pill.cls}">{pill.label}</span></td>
          <td class="col-date">{inv.sent_date ? `Sent ${formatDate(inv.sent_date)}` : ''}</td>
          <td class="col-amt {amountClass(inv)}">{formatAmount(inv.total)}</td>
        </tr>
        {#each paymentRows(inv) as pmt}
          <tr class="payment-row">
            <td class="col-num"></td>
            <td class="col-status"><span class="pill payment">Payment</span></td>
            <td class="col-date">Paid {formatDate(pmt.date)}</td>
            <td class="col-amt amt-payment">-{formatAmount(pmt.amount)}</td>
          </tr>
        {/each}
      {/each}
    </table>
    <div class="card-foot">
      <span>{invoiceCount} invoice{invoiceCount !== 1 ? 's' : ''}{paymentCount > 0 ? ` · ${paymentCount} payment${paymentCount !== 1 ? 's' : ''}` : ''}</span>
      <span class="spacer"></span>
      <span class="total">{formatAmount(totalDue())} due</span>
    </div>
  {/if}
</div>

<style>
  .unpaid-card {
    background: #fff; border-radius: 10px; overflow: hidden;
    box-shadow: 0 1px 3px rgba(0,0,0,0.06);
    border-left: 4px solid #f59e0b;
  }
  .unpaid-card.has-overdue { border-left-color: #dc2626; }
  .unpaid-card.needs-inv { border-left-color: #64748b; }

  .needs-invoice {
    padding: 10px 12px; display: flex; align-items: center; gap: 8px;
    background: #f8f9fb; border-top: 1px solid #f0f0f0;
  }
  .needs-inv-text { font-size: 11px; color: #888; }
  .pill.needs-inv { background: #f1f5f9; color: #64748b; }

  .card-head { padding: 8px 10px 6px; border-bottom: 1px solid #f0f0f0; }
  .card-head-top { display: flex; align-items: baseline; gap: 6px; }
  .job-name { font-size: 13px; font-weight: 600; }
  .profit { margin-left: auto; display: flex; gap: 8px; font-size: 10px; color: #888; }
  .val { font-weight: 600; font-family: 'SF Mono', 'Fira Code', monospace; }
  .val.green { color: #15803d; }
  .val.red { color: #dc2626; }
  .card-head-sub { display: flex; align-items: baseline; gap: 6px; margin-top: 2px; }
  .customer { font-size: 11px; color: #2563eb; text-decoration: none; }
  .customer:hover { text-decoration: underline; }
  .job-num { font-size: 10px; color: #999; font-family: 'SF Mono', 'Fira Code', monospace; }

  .line-table { width: 100%; border-collapse: collapse; font-size: 11px; }
  .line-table td { padding: 4px 6px; white-space: nowrap; }
  .line-table tr { border-bottom: 1px solid #f8f8f8; }
  .line-table tr:last-child { border-bottom: none; }
  .line-table tr.payment-row { background: #f9fdf9; }
  .col-num { font-family: 'SF Mono', 'Fira Code', monospace; color: #888; font-size: 10px; width: 68px; }
  .col-status { width: 72px; }
  .col-date { color: #888; font-size: 10px; }
  .col-amt { text-align: right; font-weight: 600; font-family: 'SF Mono', 'Fira Code', monospace; font-size: 11px; }
  .amt-paid { color: #15803d; }
  .amt-owing { color: #b45309; }
  .amt-payment { color: #15803d; }

  .pill { font-size: 9px; padding: 1px 6px; border-radius: 8px; font-weight: 600; display: inline-block; }
  .pill.open { background: #fef3c7; color: #b45309; }
  .pill.paid { background: #dcfce7; color: #15803d; }
  .pill.partly { background: #e0e7ff; color: #4338ca; }
  .pill.payment { background: #dcfce7; color: #15803d; }

  .card-foot {
    display: flex; align-items: center; padding: 5px 10px; background: #f8f9fa;
    font-size: 10px; color: #888; gap: 8px; border-top: 1px solid #f0f0f0;
  }
  .spacer { flex: 1; }
  .total { font-weight: 700; font-size: 11px; font-family: 'SF Mono', 'Fira Code', monospace; color: #b45309; }
</style>
