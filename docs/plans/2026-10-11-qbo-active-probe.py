"""QBO Customer/Vendor Active-flag probe (disposable; deleted with the plan).

Run by RM ONLY, against the SANDBOX company ONLY (QBO_ENVIRONMENT=sandbox in
.env, never production), with the sandbox connected in Settings -> QuickBooks:

    python manage.py shell < docs/plans/2026-10-11-qbo-active-probe.py

READ-ONLY for the konbini DB; writes only to the QBO sandbox (creates a probe
customer and a probe vendor, toggles their Active flag).
"""
from quickbooks.objects.customer import Customer
from quickbooks.objects.vendor import Vendor
from apps.qbo.services import QBOService
client = QBOService.get_client(); assert client, 'connect the sandbox first (Settings → QuickBooks)'

c = Customer(); c.DisplayName = 'konbini probe customer'; c.save(qb=client)
print('created', c.Id, c.DisplayName, c.Active)
c = Customer.get(c.Id, qb=client); c.Active = False; c.save(qb=client)
c = Customer.get(c.Id, qb=client); print('after deactivate:', c.DisplayName, c.Active)
c.Active = True; c.save(qb=client)
c = Customer.get(c.Id, qb=client); print('after reactivate:', c.DisplayName, c.Active)
print('visible to default filter?', bool(Customer.filter(DisplayName='konbini probe customer', qb=client)))
print('visible to Active=False filter?', bool(Customer.filter(Active=False, DisplayName='konbini probe customer (deleted)', qb=client)))
v = Vendor(); v.DisplayName = 'konbini probe vendor'; v.save(qb=client)
v = Vendor.get(v.Id, qb=client); v.Active = False; v.save(qb=client)
print('vendor after deactivate:', Vendor.get(v.Id, qb=client).DisplayName)

print('NEXT (manual, sandbox UI): create an UNPAID invoice for "konbini probe customer" and an UNPAID bill for '
      '"konbini probe vendor", then re-run ONLY the deactivate lines for each and record whether QBO refuses (exact error text).')
