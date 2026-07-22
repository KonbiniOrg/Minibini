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

  function borderColor() {
    // Gray: work done, no invoice created yet
    if (job.sub_status === 'needs-invoice') return '#64748b';
    // Amber: invoice drafted but not sent yet
    if (job.sub_status === 'invoice-prepped') return '#f59e0b';
    // TODO: Red (#dc2626) for overdue invoices, once Invoice has
    // a due_date field or PaymentTerms has net_days to compute it.
    // Default: invoice sent, awaiting payment
    return '#3b82f6';
  }

  function invoiceStatusPill(inv) {
    if (inv.status === 'paid') return { label: 'Paid', cls: 'paid' };
    if (inv.status === 'partly-paid') return { label: 'Partly Paid', cls: 'partly' };
    if (inv.status === 'open') return { label: 'Sent', cls: 'open' };
    if (inv.status === 'draft') return { label: 'Draft', cls: 'draft' };
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

<div class="unpaid-card">
  <div class="card-border" style="background: {borderColor()};">
    <span class="border-num">{job.job_number}</span>
  </div>
  <div class="card-main">
    <div class="card-head">
      <div class="card-head-top">
        <div class="card-left">
          <div class="job-name">{job.name}</div>
          <div class="card-sub">
            <a class="customer" href="#/contacts/{job.contact_id}">{job.contact_name || 'No contact'}</a>
          </div>
          {#if job.project_manager_name}
            <div class="pm-line">PM: {job.project_manager_name}</div>
          {/if}
        </div>
        <div class="card-right">
          <div class="pr-line"><span class="pr-label">Invoiced</span> <span class="pr-val">{formatAmount(job.billed)}</span></div>
          <div class="pr-line"><span class="pr-label">Spent</span> <span class="pr-val">{formatAmount(job.spent)}</span></div>
          <div class="pr-line"><span class="pr-label">Profit</span> <span class="pr-val" class:green={Number(job.profit) >= 0} class:red={Number(job.profit) < 0}>{formatAmount(job.profit)}</span></div>
        </div>
      </div>
    </div>
    {#if job.sub_status === 'needs-invoice'}
      <div class="needs-invoice">
        <span class="pill needs-inv">Needs Invoice</span>
        <span class="needs-inv-text">Work complete — no invoice created yet</span>
      </div>
    {:else}
      <table class="line-table">
        <tbody>
          {#each job.invoices || [] as inv}
            {@const pill = invoiceStatusPill(inv)}
            <tr>
              <td class="col-num">{inv.display_number}</td>
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
        </tbody>
      </table>
      <div class="card-foot">
        <span>{invoiceCount} invoice{invoiceCount !== 1 ? 's' : ''}{paymentCount > 0 ? ` · ${paymentCount} payment${paymentCount !== 1 ? 's' : ''}` : ''}</span>
        <span class="spacer"></span>
        <span class="total">{formatAmount(totalDue())} due</span>
      </div>
    {/if}
  </div>
</div>

<style>
  .unpaid-card {
    background: #fff; border-radius: 10px; overflow: hidden;
    box-shadow: 0 1px 3px rgba(0,0,0,0.06);
    display: flex;
  }

  .card-border {
    width: 18px; flex-shrink: 0; position: relative;
    display: flex; align-items: center; justify-content: center;
    border-radius: 10px 0 0 10px;
  }
  .border-num {
    writing-mode: vertical-rl; text-orientation: mixed;
    transform: rotate(180deg);
    font-size: 8px; font-weight: 600; font-family: 'SF Mono', 'Fira Code', monospace;
    letter-spacing: 0.3px; white-space: nowrap; user-select: none;
    color: #fff; opacity: 0.85;
  }

  .card-main { flex: 1; min-width: 0; }

  .card-head { padding: 8px 10px 6px; border-bottom: 1px solid #f0f0f0; }
  .card-head-top { display: flex; align-items: flex-start; gap: 8px; }
  .card-left { flex: 1; min-width: 0; }
  .job-name { font-size: 13px; font-weight: 600; line-height: 1.3; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .card-sub { display: flex; align-items: baseline; gap: 6px; margin-top: 2px; }
  .customer { font-size: 11px; color: #2563eb; text-decoration: none; }
  .customer:hover { text-decoration: underline; }
  .pm-line { font-size: 10px; color: #888; margin-top: 1px; }

  .card-right { flex-shrink: 0; text-align: right; font-size: 10px; color: #888; line-height: 1.5; }
  .pr-line { display: flex; justify-content: flex-end; gap: 3px; }
  .pr-label { color: #aaa; }
  .pr-val { font-weight: 600; font-family: 'SF Mono', 'Fira Code', monospace; min-width: 52px; text-align: right; }
  .pr-val.green { color: #15803d; }
  .pr-val.red { color: #dc2626; }

  .needs-invoice {
    padding: 10px 12px; display: flex; align-items: center; gap: 8px;
    background: #f8f9fb; border-top: 1px solid #f0f0f0;
  }
  .needs-inv-text { font-size: 11px; color: #888; }

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
  .pill.draft { background: #f1f5f9; color: #64748b; }
  .pill.needs-inv { background: #f1f5f9; color: #64748b; }

  .card-foot {
    display: flex; align-items: center; padding: 5px 10px; background: #f8f9fa;
    font-size: 10px; color: #888; gap: 8px; border-top: 1px solid #f0f0f0;
  }
  .spacer { flex: 1; }
  .total { font-weight: 700; font-size: 11px; font-family: 'SF Mono', 'Fira Code', monospace; color: #b45309; }
</style>
