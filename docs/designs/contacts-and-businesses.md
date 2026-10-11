# Contacts and Businesses

The CRM layer: individual people (`Contact`) and the companies they work for
(`Business`), plus the shared `Tag` taxonomy and the stub `PaymentTerms`
model. Every Job, PurchaseOrder, and Invoice ultimately anchors to a
Contact (directly, or via a Business), so this is the identity substrate the
rest of the system builds on.

## What this doc owns

- The `Contact`, `Business`, `Tag`, and `PaymentTerms` models and their
  services (`apps/contacts/models.py`, `apps/contacts/services.py`).
- Duplicate-email / duplicate-business-name detection: the unique
  constraints, the pre-check services, the 409 contract, and the frontend
  "did you mean this one?" modals.
- The `ContactViewSet` / `BusinessViewSet` / `TagViewSet` /
  `PaymentTermsViewSet` API surface.
- The Contacts & Businesses frontend surface: the combined list page, the
  detail pages, the create/edit forms, and `ContactPicker` (the reusable
  contact search-picker used elsewhere in the app).

## What this doc does not own

- Service-layer conventions, mixin catalog, the two-phase delete pattern,
  the error-response contract, view-mode (`full`/`lite`), and the generic
  history/notes model+panel. See `docs/designs/architecture-and-conventions.md`
  §3 (API), §6 (view mode), §7 (history and notes) — this doc cross-references
  those rather than re-describing them.
- `Job.contact` — the FK itself, and the draft-only reassignment rule added
  on top of it. See `docs/designs/data-constraints.md` §1.8 and §1.5.
- `PurchaseOrder` contact and business FKs. See
  `docs/designs/materials-inventory-and-purchasing.md` (the Bill domain was
  retired to QBO 2026-07-23 — its §13; the vendor QBO push went with it,
  though `Business.qbo_vendor_id` remains).
- `Invoice`'s relationship to a business/contact (via its Job). See
  `docs/designs/invoicing-and-expenses.md`.
- QBO OAuth, `QBOSyncLog`, and the mechanics of `push_customer` /
  `push_contact_as_customer` / `push_vendor`. See
  `docs/designs/quickbooks-integration.md` — this doc only states the
  mutual-exclusivity rule the sync relies on.

---

## Contact

`apps/contacts/models.py` — `Contact`. `@history(exclude=[])` — every field
change is audit-tracked (see architecture doc §7).

### Fields

| Field | Type | Notes |
|---|---|---|
| `contact_id` | AutoField PK | |
| `first_name` / `last_name` | CharField(100) | Required. |
| `middle_initial` | CharField(10), blank | |
| `email` | EmailField, **unique** | Required, non-empty after `.strip()`. Normalized (not lowercased) in `clean()` so whitespace variants collide under the unique constraint. |
| `addr1`/`addr2`/`addr3`, `city`, `municipality`, `postal_code`, `country_code` | CharField, blank | |
| `mobile_number` / `work_number` / `home_number` | CharField(20), blank | At least one required. |
| `business` | FK Business (`SET_NULL`, nullable) | `related_name='contacts'`. |
| `qbo_customer_id` | CharField(50), null+blank | Only for individual contacts — see "QBO mutual exclusivity" below. |
| `tags` | M2M Tag, `db_table='contact_tags'` | |

`name` is a `@property` (`"{first} {middle} {last}"`, parts joined with
single spaces, empty parts skipped) — not a stored column. `phone()` returns
the highest-priority number (work > mobile > home). `address()` returns the
full address if `addr1`+`city`+`postal_code` are all present, else just
`addr1`, else `''`.

### `clean()`

1. Strips and requires `email` (`ValidationError('Email address is required.')`
   if empty after stripping).
2. Requires at least one of `work_number`/`mobile_number`/`home_number`.
3. **QBO mutual exclusivity:** if `business_id` and `qbo_customer_id` are both
   set, raises `ValidationError('A contact cannot have both a business and a
   direct QBO customer ID. Use the business's QBO customer ID instead.')`. A
   contact that belongs to a business always bills/syncs through the
   business's own `qbo_customer_id` (see `Business.qbo_customer_id` below);
   only a business-less individual contact carries its own.

### `save()` / `delete()` — default-contact upkeep

`Contact.save()` tracks the contact's business FK across the save and calls
`business.validate_and_fix_default_contact()` on both the new and (if
changed) the old business — self-healing if a business's `default_contact`
no longer points at one of its own contacts (see `Business` below).

`Contact.delete()` has its **own** sole-contact guard, independent of the
service-layer one (`ContactService.delete_contact`, next section): if this
contact is its business's `default_contact` and no other contact exists on
that business, it raises `PermissionDenied` (not `ValidationError`) rather
than delete. If another contact exists, it reassigns `default_contact`
before deleting. This means the guard fires even for a raw
`contact.delete()` call that bypasses the service — belt-and-suspenders, not
redundant plumbing to remove.

### `ContactService` (`apps/contacts/services.py`)

| Method | Behavior |
|---|---|
| `create_contact(*, business_pk=None, **kwargs)` | Pre-checks for a duplicate email (see "Duplicate detection" below) before constructing the instance. Resolves `business_pk` to a `Business` (raises `NotFoundError` if missing). Calls `full_clean()` + `save()`. |
| `update_contact(pk, *, business_pk=_sentinel, **kwargs)` | Generic `setattr` loop. `business_pk` is a sentinel-defaulted kwarg so `None` (clear the business) is distinguishable from "not passed." **Does not** pre-check duplicate email — an email collision on update surfaces only as a plain `full_clean()` validation error (a field-level 400, not the rich 409); this is a deliberate narrower scope, not a gap — see "Duplicate detection" below. |
| `delete_contact(pk, new_default_contact_pk=None)` | Raises `ValidationError` if the contact has any `Job` or `Bill` (the Bill check remains for legacy rows — the retired-but-retained schema, materials doc §13). If it's a business's sole contact, raises `ValidationError` (a friendlier message than the model's own `PermissionDenied` path, since the service checks it explicitly first via `other_contacts.exists()`). If it's the default contact with siblings, reassigns to `new_default_contact_pk` (validated as belonging to the same business) or the first sibling, then deletes. |

---

## Business

`apps/contacts/models.py` — `Business`. `@history(exclude=['business_id'])`.

### Fields

| Field | Type | Notes |
|---|---|---|
| `business_id` | AutoField PK | |
| `our_reference_code` | CharField(50), blank, **unique** | Auto-generated as `BUS-{N:04d}` on save if blank — see below. |
| `business_name` | CharField(255), **unique** | Required, stripped in `clean()`. |
| `business_address` | TextField, blank | |
| `business_phone` | CharField(50), blank | |
| `tax_exemption_number` | CharField(50), blank | |
| `website` | URLField(200), blank | |
| `terms` | FK PaymentTerms (`SET_NULL`, nullable) | See "PaymentTerms" below — currently a stub model. |
| `default_contact` | FK Contact (`PROTECT`, required) | Must be one of this business's own contacts (self-healed — see below). `PROTECT` blocks deleting a Contact that is currently some business's default without going through the reassignment paths above. |
| `tax_multiplier` | Decimal(3,2), nullable | `null`/`1.0` = full rate, `0` = exempt, `0.5` = half rate. |
| `qbo_customer_id` / `qbo_vendor_id` | CharField(50), null+blank | Both `blank=True` (required so `ContactService` can call `full_clean()` without tripping on them). |
| `tags` | M2M Tag, `db_table='business_tags'` | |

### `clean()`

Strips `business_name` and requires it non-empty (mirrors `Contact.email`'s
normalize-then-require pattern, so whitespace variants collide under the
unique constraint).

### Reference code generation

`Business.save()` only touches `our_reference_code` when it's blank on
create. It generates `BUS-{next_id:04d}` from `(latest business_id) + 1`,
checks for a pre-existing collision (`while ... .exists(): next_id += 1`),
then saves inside `transaction.atomic()`. On `IntegrityError` mentioning
`our_reference_code` it retries (up to 10 attempts, incrementing the probe
each time) — a race-condition safety net for concurrent creates. Any other
`IntegrityError` re-raises immediately.

### `default_contact` self-healing

`Business.validate_and_fix_default_contact()`: if the business has no
contacts, no-ops (can't fix — a business without any contact cannot satisfy
the required FK, which is an inconsistent state the model doesn't actively
prevent from arising via `SET_NULL` moves). If the current
`default_contact` is one of the business's own contacts, no-ops. Otherwise
reassigns to the contact with the lowest `contact_id`. Called from
`Contact.save()`/`Contact.delete()` (both the business the contact is
joining/leaving), so `default_contact` drift is corrected automatically as
contacts move between businesses — no dedicated management command needed.

### Circular-dependency creation order

Business requires a `default_contact`, and `Contact.business` is optional —
so creating a business "from scratch" is a three-step dance (see
`docs/designs/data-constraints.md` §1.5): create the Contact first with
`business=None`, create the Business with `default_contact` pointing at it,
then set the Contact's `business` FK. `ContactService.create_business_for_contact`
and the frontend's `BusinessFormModal` create flow (below) both follow this
order.

### `ContactService` — Business methods

| Method | Behavior |
|---|---|
| `create_business(contacts_data, **kwargs)` | Multi-contact creation: pre-checks duplicate name, then in one transaction creates the first contact (business-less), creates the Business with it as `default_contact`, links it back, then creates any remaining contacts directly on the business. **Not currently wired to any API endpoint** — exercised only by `tests/test_contacts_services.py`; `BusinessViewSet` uses `create_business_for_contact` instead. |
| `create_business_for_contact(contact_pk, **kwargs)` | The live path (`BusinessViewSet.perform_create`). Pre-checks duplicate name, then in one transaction creates the Business with the given existing contact as `default_contact` and points that contact's `business` FK at it. |
| `update_business(pk, **kwargs)` | Generic `setattr` loop + `full_clean()` + `save()`. No duplicate-name pre-check on update (same asymmetry as `update_contact` — see below). |
| `set_default_contact(business_pk, contact_pk)` | Validates the contact belongs to the business, then sets `default_contact` and saves with `update_fields=['default_contact']`. |
| `delete_business(pk, po_actions=None, bill_actions=None, contact_actions=None, job_actions=None)` | Rich cascading delete — see below. |

### `delete_business` cascade

(Bill-related branches below remain for **legacy rows only** — the Bill
domain was retired 2026-07-23 with schema retained; see the materials doc
§13.)

Four optional dicts key by object pk → `(action, target)`:

- `po_actions` / `bill_actions`: `'delete'` or `'reassign'` (to another
  `Business`, clearing `contact`).
- `contact_actions`: `'unlink'` (clear `business`), `'delete'`, or
  `'reassign'` (to another `Business`).
- `job_actions`: `'delete'` or `'reassign'` (to another `Contact` — jobs
  don't reassign business directly, only contact).

Inside one `transaction.atomic()`: process POs, then Bills, then Jobs (for
contacts marked for deletion), then clear any *other* businesses' PO/Bill
`contact` references that point at a contact being deleted, then
unlink/reassign the surviving contacts, then delete the Business itself,
then delete the contacts that were marked `'delete'`.

**This cascade is currently richer than any UI can drive.**
`BusinessViewSet.perform_confirmed_destroy` calls `delete_business(business.pk)`
with **all four dicts defaulted to `{}`** — i.e. no explicit action for any
related object. In practice this means:
- Any existing PO or Bill referencing the business causes the unconditional
  `business.delete()` to raise `ProtectedError` (caught and surfaced as "Cannot
  delete this business — it is still referenced by purchase orders or
  bills."). The rich reassign/delete-per-PO machinery is unreachable from
  the SPA today.
- Contacts are not explicitly acted on either — they fall back to
  `Contact.business`'s `on_delete=SET_NULL`, so they survive as
  business-less contacts rather than being unlinked/reassigned/deleted per
  any explicit choice.

The frontend confirmation (`BusinessDetailPage.svelte`) is a **blunt
count-only** two-phase confirm (see "Two-phase delete" below) — it shows
`{jobs, purchase_orders, bills, contacts}` counts and a single "Yes,
delete"/"Cancel" pair, not a per-item action picker. If you need the
granular cascade, it has to be added to the frontend — the service already
supports it.

---

## Duplicate detection (email / business name)

Both `Contact.email` and `Business.business_name` carry a DB-level
`unique=True` constraint (added in migration `contacts/0008`). Detecting and
surfacing a collision *before* the DB rejects it is handled the same way on
both sides — added for Contact first, then mirrored onto Business in a
later pass so the same UX ("this looks like a duplicate — go look at the
existing one, or go back and edit") applies to both create flows.

### Why the serializer declares the field explicitly

`ContactSerializer.email` and `BusinessSerializer.business_name` are both
declared as **explicit** serializer fields (`serializers.EmailField()` /
`serializers.CharField(max_length=255)`) rather than left to
`ModelSerializer`'s auto-generation. This is load-bearing: DRF's
`ModelSerializer` auto-attaches a `UniqueValidator` to any field backed by a
`unique=True` model column, and that validator runs during
`serializer.is_valid()` — *before* `perform_create` (and therefore before
the service-layer duplicate check) ever executes. Left auto-generated, a
duplicate would short-circuit as a bare `{'email': ['contact with this
email already exists.']}` 400, and the service's richer 409 (below) would
never fire. (This was confirmed the hard way for `business_name`: adding
`unique=True` to the model without the matching serializer override made
the API test expecting a 409 actually receive a 400.)

### Service-layer pre-check

`ContactService._check_duplicate_business_name` /
`create_contact`'s inline email check both do the same shape of thing:
case-insensitive lookup (`__iexact`) for an existing row, and if found,
raise:

```python
raise ValidationError(
    'A contact with this email address already exists.',  # or business name
    code='duplicate_email',            # or 'duplicate_business_name'
    params={'contact_id': existing.pk},  # or {'business_id': existing.pk}
)
```

`ContactService.find_business_by_name(name)` is the extracted, non-raising
lookup — shared by the pre-check above and by the `check-name` endpoint
(below).

### 409 contract

`ContactViewSet.create()` and `BusinessViewSet.create()` both override the
default `ModelViewSet.create()` (not just `perform_create`) so they can
catch this specific `ValidationError` by its `code` and reshape it:

```json
// duplicate_email — POST /api/contacts/
{"detail": "A contact with this email address already exists.",
 "code": "duplicate_email",
 "existing_contact": { /* full ContactSerializer payload */ }}

// duplicate_business_name — POST /api/businesses/
{"detail": "A business with this name already exists.",
 "code": "duplicate_business_name",
 "existing_business": { /* full BusinessSerializer payload */ }}
```

Both at `HTTP 409 Conflict`. Any other `ValidationError` (a different
`code`, or none) is re-raised and falls through to the standard error
contract (`docs/designs/architecture-and-conventions.md` §3.9).

### `check-name` — pre-flight, no-side-effect probe

`GET /api/businesses/check-name/?name=<name>` (`BusinessViewSet.check_name`)
returns `{'exists': bool, 'business': {...}|null}` — a read of
`find_business_by_name` with no create attempt. It exists because creating
a *new* Business always requires creating its `default_contact` first (see
"Circular-dependency creation order" above): if the frontend only relied on
the 409-on-create, a duplicate business name would be caught only *after*
that contact was already committed, leaving it permanently orphaned
(business-less, since the Business creation that would have linked it never
completes). `BusinessFormModal`'s create flow calls this endpoint first and
shows the duplicate-business notice (its in-modal sub-state) immediately — without ever POSTing the contact —
if it comes back `exists: true`. There's no equivalent gap on the Contact
side, since a Contact create has no such "must create something else
first" step.

There is no `check-name` equivalent for Contact/email, since the contact
*is* the thing being created — the 409-on-create is sufficient there.

### Race window

Both the pre-check and `check-name` are check-then-act, not atomic with the
eventual insert. A concurrent double-submit of the identical email/name can
still slip past both checks and hit the DB unique constraint on `save()` —
which raises a raw `IntegrityError`, not a `ValidationError`, and
`apps/api/exceptions.py`'s central handler does not special-case
`IntegrityError` ("anything else is a programming error — let it 500
loudly"). This is a narrow, low-likelihood window (not currently mitigated
by a `select_for_update` or similar), left as-is rather than engineered
around — the DB constraint is still the true backstop; the service check
and 409 are purely a UX improvement over the raw 500 in the common
(non-racing) case.

### Update path is intentionally narrower

Neither `update_contact` nor `update_business` runs the pre-check — editing
an existing row's email/name to collide with another only surfaces via
`full_clean()`'s plain field-level `ValidationError` (a normal 400 rendered
under the input, not the 409/modal flow). The frontend's edit forms
(`isEdit` in `ContactFormModal.svelte` / `BusinessFormModal.svelte`)
only check for the 409 codes on the **create** path — this is deliberate,
not an oversight, since a same-collision-on-edit is rarer and the plain
field error is adequate.

### Frontend

`DuplicateContactNotice.svelte` / `DuplicateBusinessNotice.svelte`
(`frontend/src/components/contacts/`) are near-identical plain fragments
(no `<Modal>` of their own): "View Existing Contact/Business" (navigates
to its detail page) and "Go Back and Edit" (returns to the form). Since
2026-10-10 the create forms are themselves modals, so duplicate detection
is an **in-modal sub-state** rather than a stacked modal: the host keeps
its form mounted but `hidden`, renders the notice in its place, and its
`onCancel` backs out one level (notice → form → closed) — the
`Modal.svelte` sub-state convention (`frontend/README.md` → Modals).
`DuplicateContactModal.svelte` / `DuplicateBusinessModal.svelte` survive
only as thin `<Modal>` wrappers for `EmailCreatePOPage.svelte` (PO work is
parked); they are Esc-only (no `onSave`) since both actions are navigation.

Wired into: `ContactFormModal.svelte`, `BusinessFormModal.svelte` (both
create-only — see above), and the email-to-Job modal
(`EmailCreateJobModal.svelte`; `EmailCreatePOPage.svelte` still uses the
wrappers; `EmailCreateBillPage` was deleted with the 2026-07-23 bill
retirement), which create a Contact via
`resolveSenderToContact` (`frontend/src/lib/email.js`) and need the same
409 handling since that helper POSTs to `/api/contacts/` directly. All four
check both `e.data?.code === 'duplicate_email'` and
`'duplicate_business_name'` before falling through to normal error triage.

`resolveSenderToContact` can also create a **Business** (its
`businessMode === 'new'` branch). It follows the same "check before you
create anything" order as `BusinessFormModal`: it calls `check-name` first,
and if a match exists, throws a synthetic `{status: 409, data: {code:
'duplicate_business_name', existing_business}}` error *before* the contact
POST — so, like the form modal, a collision here never orphans a contact.
The email create-job modal renders `DuplicateBusinessNotice` for this error
the same way it does `DuplicateContactNotice`.

---

## Tag

`apps/contacts/models.py` — `Tag`. Minimal: `tag_id` PK, `name`
(CharField(100), **unique**), ordered by `name`, `db_table='tags'`.

Shared M2M taxonomy between Contact (`contact_tags` through-table) and
Business (`business_tags` through-table) — the same `Tag` row can be
attached to both contacts and businesses.

`TagService` (`apps/contacts/services.py`):

```python
TagService.attach(obj, name)   # get_or_create(name=name), obj.tags.add(tag)
TagService.detach(obj, tag_id) # obj.tags.remove(tag_id)
```

`get_or_create` keeps the global tag list deduplicated by name — attaching
"Rush" to two different contacts reuses the same `Tag` row.

### API

`TagViewSet` (`IsAuthenticated`, standard pagination, `?search=` by
`name__icontains`) for the flat tag list. Per-object attach/detach is via
`POST /api/contacts/{id}/add-tag/` / `remove-tag/` and the Business
equivalents (body: `{name}` / `{tag_id}`) — thin wrappers calling
`TagService` and returning the object's fresh tag list. Both
`ContactViewSet.get_queryset()` and `BusinessViewSet.get_queryset()`
`prefetch_related('tags')` so list/retrieve don't N+1 on the nested
`TagSerializer`.

`DELETE /api/tags/{id}/` removes a tag globally — from every contact and
business it's applied to in one call (deleting the `Tag` row cascades the
`contact_tags`/`business_tags` through-table rows) — via the standard
`ConfirmDeleteMixin` two-phase confirm: first call returns
`{'confirm_required': True, 'impact': {'contacts': N, 'businesses': M}}`,
`?confirm=true` executes. Gated `IsAuthenticated` + `CanManageJobs`
(matching the per-object add-tag/remove-tag write gate); all other
`TagViewSet` actions stay `IsAuthenticated` only.

### Frontend

`TagEditor.svelte` (`frontend/src/components/`) is generic — mounted with
an `endpoint` prop (`/api/contacts/{id}` or `/api/businesses/{id}`) and
`initialTags`, POSTing to `{endpoint}/add-tag/` / `{endpoint}/remove-tag/`.
Used identically on `ContactDetail.svelte` and `BusinessDetail.svelte`
(read-only when the viewer lacks `can_manage_jobs`) — this is the
per-object removal path (one contact/business at a time).

The combined list page (`ContactListPage.svelte`, below) also fetches the
full tag list (`/api/tags/?page_size=200`) to render filter chips —
`?tag=<id>` (repeatable) on both `/api/contacts/` and `/api/businesses/`.
When the viewer has `can_manage_jobs`, each chip gets a small "×" that
calls `DELETE /api/tags/{id}/` (global removal, not per-object) and shows
an inline impact-count confirm panel before the real delete, mirroring the
delete-confirm pattern on `ContactDetailPage.svelte`.

---

## PaymentTerms

`apps/contacts/models.py` — `PaymentTerms`, `db_table='terms'`. Fields
(real since 2026-07-23; previously a `term_id`-only stub): `term_id`
(AutoField PK), `name` (CharField 100, blank-allowed at the model),
`days` (nullable positive int), `qbo_id` (QBO Term mirror, '' = not
imported). `__str__` = name.

**Management UI (2026-07-23): Settings → Business tab.** A flat list
(name, days, a green "QBO" badge on mirrored rows, in-use business
count) with modal create/edit (`PaymentTermsManager.svelte`, standard
`Modal.svelte` keyboard contract) and a two-phase confirm delete — the
FK is `SET_NULL`, so the confirm quotes "used by N businesses — their
terms will be cleared". Directly above it sits the terms QBO import
panel (`TermsImportPanel`, area `terms`, own pull button + sticky
dismissal — see quickbooks-integration.md). No individual term page.

**API**: `PaymentTermsViewSet` is a full ModelViewSet +
`ConfirmDeleteMixin`, unpaginated, ordered by name. Reads are
`IsAuthenticated` (the BusinessForm assignment select); writes require
`can_manage_config` (the Settings surface's atom — deliberately NOT
`can_manage_jobs`). The serializer enforces what the model doesn't:
`name` required and case-insensitively unique (the model stays
permissive so QBO-import merges can't trip), `qbo_id` read-only,
annotated `business_count`.

**QBO-mirror policy**: rows with a `qbo_id` are editable (badge visible);
local edits surface as `changed` on the next terms pull and the import
panel arbitrates. Deleting a mirrored term is allowed — it re-appears as
`new` after the next pull.

---

## API layer

`apps/api/contacts/{views.py,serializers.py}`. Router registrations
(`apps/api/urls.py`): `contacts`, `businesses`, `payment-terms`, `tags`.

### Serializers

| Serializer | Notes |
|---|---|
| `ContactSerializer` | `name` read-only (the model `@property`). `email` explicit (see "Duplicate detection"). `business` nested read-only (`BusinessSummarySerializer`); `business_id` write-only PK field (`source='business'`). `tags` nested read-only. |
| `ContactSummarySerializer` | `contact_id`, `name`, `email`, `mobile_number`, `work_number` (added 2026-10-10 so the business page's Contacts table can fall back to the work number) — used wherever a contact is nested inside another object (e.g. `BusinessDetailSerializer.contacts`). |
| `ContactDetailSerializer(ContactSerializer)` | Adds `jobs` (`SerializerMethodField`, `Job.objects.filter(contact=obj)` via `JobSummarySerializer` — since 2026-10-10 each row carries `contact`, `contact_name`, `start_date`, `created_date` and `estimated_amount`, the last computed per job through `compute_job_financials` and memoized per serializer instance) and nests full `BusinessSerializer` (not just the summary) for `business`. Used only for `retrieve`. |
| `BusinessSerializer` | `business_name` explicit (see "Duplicate detection"). `default_contact` nested read-only full `ContactSerializer`; `default_contact_id` write-only PK field. `qbo_customer_id`/`qbo_vendor_id`/`business_id`/`our_reference_code` all read-only. Also exposes read-only `terms_name` (2026-10-10): `terms` itself serializes as the PaymentTerms pk the form writes, and the detail page's Billing panel shows the name. |
| `BusinessSummarySerializer` | `business_id`, `business_name`, `our_reference_code`, `default_contact` — nested elsewhere (e.g. `ContactSerializer.business`). |
| `BusinessDetailSerializer(BusinessSerializer)` | Adds `contacts` (`ContactSummarySerializer`, many) and `jobs` (`SerializerMethodField`, `Job.objects.filter(contact__business=obj)`). Used only for `retrieve`. |
| `TagSerializer` | `tag_id`, `name`. |
| `PaymentTermsSerializer` | `fields = '__all__'` — currently just `term_id` (see above). |

### `get_queryset` filters

Both `ContactViewSet` and `BusinessViewSet` support:

| Param | Behavior |
|---|---|
| `?business=<id>` | Contact only — `business_id=<id>`. |
| `?starts_with=<letter>` | `first_name__istartswith` (Contact) / `business_name__istartswith` (Business). Special value `'0-9'` matches a leading digit via regex (`^[0-9]`). |
| `?tag=<id>` (repeatable) | `tags__tag_id=<id>`, ANDed per repetition (each call narrows further). |
| `?search=<text>` | Contact: `icontains` across first/last name, email, business name, **plus** phone-digit-stripped matching (`re.sub` strips spaces/dashes/dots/parens from both the query and each phone field via a chained `Replace` annotation, so "555-1234" matches a differently-punctuated stored number). Business: `icontains` across name, reference code, phone, address. |

### Permissions

`get_permissions()` on both viewsets:

| Action | Permission |
|---|---|
| `list`, `retrieve`, `history`, `notes`, `financials` | `IsAuthenticated` |
| everything else (create, update, delete, add-tag, remove-tag, set-default-contact, check-name) | `IsAuthenticated` + `CanManageJobs` |

`TagViewSet` is `IsAuthenticated` only (read + the flat CRUD DRF gives it by
default — nothing in this domain currently restricts *creating* a bare tag
by name beyond that, though in practice tags are only ever created via
`get_or_create` inside `add-tag`). `PaymentTermsViewSet` is
`ReadOnlyModelViewSet`, no explicit `get_permissions` override (defaults
apply).

### Endpoints

| Method | URL | Notes |
|---|---|---|
| `GET/POST` | `/api/contacts/`, `/api/businesses/` | List/create. `create()` overridden on both for the 409 duplicate contract. |
| `GET/PATCH/DELETE` | `/api/contacts/{id}/`, `/api/businesses/{id}/` | Retrieve uses the `*DetailSerializer`. DELETE is two-phase (below). |
| `GET` | `/api/{contacts,businesses}/{id}/history/` | `CrmHistory` rows for the object. **Business's version also unions in its contacts' history** — `Q(object_type='business', object_id=business.pk) | Q(object_type='contact', object_id__in=<business's contact pks>)` — so a business's history feed shows its contacts' changes inline, not just the business row's own. Contact's `history` action has no such union (plain per-object filter). |
| `POST` | `/api/{contacts,businesses}/{id}/notes/` | Body `{text}`; creates a `note`-type `CrmHistory` entry via `record_history`. |
| `GET` | `/api/{contacts,businesses}/{id}/financials/` | See "Financials rollup" below. |
| `POST` | `/api/{contacts,businesses}/{id}/add-tag/`, `remove-tag/` | Body `{name}` / `{tag_id}`. |
| `GET` | `/api/businesses/check-name/` | See "Duplicate detection" above. |
| `POST` | `/api/businesses/{id}/set-default-contact/` | Body `{contact_id}`; validates the contact belongs to the business. |
| CRUD | `/api/tags/` | Standard `ModelViewSet`, `?search=`. |
| `GET` | `/api/payment-terms/` | Read-only, unpaginated. |

### Two-phase delete

Standard `ConfirmDeleteMixin` pattern (architecture doc §3.7): first `DELETE`
returns `{'confirm_required': true, 'impact': {...}}`, second with
`?confirm=true` executes.

`ContactViewSet.get_deletion_impact` → `{'jobs': <count>}`.
`BusinessViewSet.get_deletion_impact` → `{'jobs', 'purchase_orders', 'bills',
'contacts'}` counts (Jobs counted via `contact__business=business`, i.e.
jobs belonging to any of the business's contacts; the `bills` count covers
legacy rows only — retired schema, 2026-07-23).

`perform_confirmed_destroy` on both catches `ProtectedError` (→ 400,
"still referenced by other records") and `ServiceError`/`ValidationError`
(→ 400 with the service's message) around the `ContactService.delete_contact`
/ `delete_business` call. See "delete_business cascade" above for why the
Business path's rich per-item actions are currently unreachable.

### Error contract

Both viewsets follow the standard two-shape contract
(`docs/designs/architecture-and-conventions.md` §3.9) for everything except
the 409 duplicate responses described above, which are a deliberate,
documented exception (extra `code` + `existing_*` keys) — not a contract
violation.

---

## Financials rollup

`ContactViewSet.financials` / `BusinessViewSet.financials` both hand the
relevant Jobs (`contact.job_set.all()`, or
`Job.objects.filter(contact__business=business)`) to
`compute_customer_financials(jobs)` (`apps/jobs/financials.py`, 2026-10-10),
which returns:

| key | meaning |
|---|---|
| `invoiced`, `profit` | sums of the per-job `compute_job_financials` figures (a plain per-job loop, as before — fine at current volumes, an N × query-cost pattern to know about) |
| `open_jobs` | count of jobs not completed / rejected / cancelled |
| `outstanding` | Σ (line-item total − `qbo_amount_paid`) over invoices in `Invoice.UNPAID_STATUSES` (open / partly-paid / defaulted — the constant moved onto the model so the A/R serializer and this rollup share one set) |
| `first_job_date` | earliest `created_date`, as a local ISO date, or null |
| `last_job_start` | latest of each job's `start_date` (falling back to `created_date`), local ISO date or null |

The viewsets serialize money as 2-dp strings, counts as ints, dates as ISO
strings or null (`_financials_payload` in `apps/api/contacts/views.py`).

`CustomerHeader.svelte` (frontend) is the shared banner component rendering
this rollup on both detail pages: a facts line ("Customer since Mar 2024 ·
Last job started Sep 26, 2026 · Net 30"; "Contact since …" on contact
pages; null facts omitted) over a numbers box of Open jobs / Outstanding
(amber) / Invoiced (green) / Profit (green or red). It also renders the
name, the counterpart link (business's default contact ↔ contact's
business, or "(individual)" when a contact has none), the "default
contact" chip, and the page-supplied `actions` snippet — see "Detail
pages" below.

---

## Search integration

`apps/search/services.py`'s `SearchService` registers `CATEGORY_CONTACTS`
and `CATEGORY_BUSINESSES` among its cross-entity categories.
`search_contacts(query)` matches `icontains` across first/middle/last name,
email, and all three phone fields. `search_businesses(query)` matches
`icontains` across `business_name`, `our_reference_code`,
`business_address`, `business_phone`. Both are plain `icontains` OR-chains —
no phone-digit-stripping here (unlike `ContactViewSet.get_queryset`'s
dedicated search param, which does strip punctuation for phone matching).
See `apps/search/` for the category registry and result-hydration mechanics
generally — not duplicated here.

---

## QBO touchpoints

`Contact.qbo_customer_id`, `Business.qbo_customer_id`, and
`Business.qbo_vendor_id` are all set by `apps/qbo/services.py`:
`push_customer(business)`, `push_contact_as_customer(contact)` (only called
for a business-less contact), and `push_vendor(business)` respectively. The
**mutual exclusivity** rule — a contact with a `business` must not carry
its own `qbo_customer_id` — is enforced in `Contact.clean()` (see above),
not in the QBO service layer; the sync code relies on that invariant
already holding rather than re-checking it. Full OAuth/sync mechanics:
`docs/designs/quickbooks-integration.md`.

---

## Frontend

### Routes

| Path | Component | Notes |
|---|---|---|
| `/contacts` | `ContactListPage.svelte` | **The primary nav entry** (`Sidebar.svelte` links here, labeled "Contacts") — despite the name, this is a **combined** Contacts + Businesses list (see below). |
| `/contacts/new`, `/contacts/:id/edit` | `RedirectTo` stub | Retired 2026-10-10: the form is `ContactFormModal.svelte`, opened from the list's **New Contact** button, the detail page's **Edit**, or a business page's **New Contact** (pre-attached via `defaultBusinessId`). The stub bounces stale links to `/contacts` / `/contacts/:id`. |
| `/contacts/:id` | `ContactDetailPage.svelte` | |
| `/businesses` | `BusinessListPage.svelte` | A separate, plain-paginated, **Business-only** list with no letter/tag filters (thin wrapper over `BusinessList.svelte`). Not in the sidebar nav and (since the 2026-10-10 detail-page redesign dropped "Back to list") reachable only by URL. Effectively a secondary surface; `/contacts` is where users land day to day. |
| `/businesses/new`, `/businesses/:id/edit` | `RedirectTo` stub | Retired 2026-10-10: the form is `BusinessFormModal.svelte`, opened from the lists' **New Business** buttons or the detail page's **Edit**. |
| `/businesses/:id` | `BusinessDetailPage.svelte` | |

### `ContactListPage.svelte` — the combined list

Fetches `/api/contacts/` and `/api/businesses/` **in parallel** with the
same query params (`page_size=100`, `starts_with`, `search`, repeated
`tag`), tags each result row with `_type: 'contact'|'business'`, and merges
them into one client-side-paginated table (`PAGE_SIZE=25` of the up-to-100
fetched). Filter UI: A–Z letter buttons (`LETTERS`) mapped to
`starts_with`, a free-text search box, a tag-chip filter (fetched once from
`/api/tags/?page_size=200`), and `showContacts`/`showBusinesses` toggles
that filter the already-merged client-side list without refetching.
"New Contact" / "New Business" are `<button>`s here (gated `can_manage_jobs`) that open `ContactFormModal` / `BusinessFormModal` over the list.

### Detail pages

Redesigned 2026-10-10 (spec: `docs/plans/2026-10-10-contacts-ui-redesign.md`,
disposable). `ContactDetailPage.svelte` / `BusinessDetailPage.svelte` are
near-mirrors: load the object, then in parallel its invoices
(`?contact=`/`?business=` + `summary=true&page_size=100`), purchase orders
(`page_size=100`), financials and history. The lists are fetched **whole**
(no pager; 100 is the documented ceiling — if a customer outgrows it the
answer is a Job History tab, not pagination here). The contact page also
fetches its business's **detail** payload (`/api/businesses/{id}/`) so the
"Also here" list can show sibling job counts from `contacts[]` × `jobs[]`
without a new endpoint.

**Banner** — `CustomerHeader` (see "Financials rollup") with an `actions`
snippet the page fills, gated `can_manage_jobs`: **New Job** (the one real
button; business page → the default contact, contact page → this contact;
the modal still lets the user change the contact), **Edit** (the form
modal), and either **Delete…** or **Deactivate**:

- `canDeleteBusiness` / `canDeleteContact` (`lib/customerActivity.js`)
  mirror `ContactService`'s guards from data already loaded — a business is
  deletable with no jobs, no POs and at most one contact; a contact with no
  jobs that is not the only contact of its business.
- Deletable → **Delete…** opens a `Modal` ("Delete business" / "Delete
  contact") listing the first-phase DELETE's impact counts (the business
  payload's retired `bills` count is no longer rendered); confirming runs
  `?confirm=true` and navigates to `/contacts`.
- Otherwise → **Deactivate**, a *disabled placeholder* (`title="Not
  available yet"`). The feature — an active flag on Business and Contact,
  pickers and lists skipping inactive rows, a Reactivate path — is tracked
  in the external issue tracker, not `LATER.md`.

The banner's quiet links share `.edit-link` with the job header; that rule
grew to 14px / 0.75 opacity on 2026-10-10 so both banners match.

**Body** — a two-column grid (`300px minmax(0,1fr)`, stacking at
`PHONE_MAX_WIDTH`) inside `.page-body`:

- Left, identity `.panel`s. Business: **Contact** (phone, website as a
  link, address), **Billing** (ref code, `terms_name`, tax exemption or
  "Not exempt", multiplier or "full rate"), **Tags** (`TagEditor`).
  Contact: **Contact** (email as `mailto:` + a copy button, Mobile/Work/Home
  as `tel:` links with blank ones omitted, address block), **Business**
  (omitted for individuals: name link, "{phone} · {terms} · tax exempt"
  line, and **Also here** — the business's other contacts with job counts),
  **Tags**. The old Name / Reference Code rows and the full-mode "Business
  Details" dump are gone; the banner says the name.
- Right, `CustomerActivity.svelte` (one component for both pages):
  **Contacts** (business pages only; always visible) → **Recent Jobs** →
  **Open Invoices** → **Purchase orders** → **History** (`HistoryPanel`
  inside a `.panel`; it keeps its own lite/full rule). Each list section
  hides its closed rows behind a **show N completed / paid / closed** link
  (jobs: completed + rejected + cancelled; invoices: paid + cancelled +
  superseded; POs: received_in_full + cancelled) that extends the table in
  place and toggles to "hide N …"; the link is absent when N is 0. A
  section with no rows at all renders as a dashed one-line **collapsed
  section** ("Purchase orders · none") carrying its action (New purchase
  order, `can_manage_financials`); populated sections precede collapsed
  ones. Sections are stamped `data-section="contacts|jobs|invoices|pos|history"`.
  Contacts rows: name link + yellow "default" chip, `mailto:` email,
  mobile-else-work phone, and (managers) **New job** for that contact and
  **Set as default** (`PATCH /api/businesses/{id}/ {default_contact_id}`
  then reload; no confirm — it is reversible; disabled on the current
  default). The section head carries **New contact** (`ContactFormModal`
  with `defaultBusinessId`). Recent Jobs columns: Job # (`JOB-` prefix
  stripped), Name, Contact (business page only), Status pill, Started
  (`start_date` else `created_date`), Estimate. Open Invoices: Invoice #,
  Job, Status, Sent, Total, Paid, Balance. POs: PO #, Status, Issued.
- The pure rules (closed sets, labels, ordering, delete rule, facts line,
  siblings) live in `frontend/src/lib/customerActivity.js`.

Density: these pages are **FULL-only for now** (RM 2026-10-10) — they no
longer read `$viewMode` or use `<FullOnly>`; the show-N toggle replaced the
lite closed-row hiding. A LITE trimming pass is a later, separate piece.

### Forms (modals)

`ContactFormModal.svelte` / `BusinessFormModal.svelte`
(`components/contacts/`, 2026-10-10 — they replaced the `/new` + `/:id/edit`
pages) — shared conventions: props `{ open, contact|business = null,
onSaved, onClose }` (null → create, object → edit); the inner
`ContactForm` / `BusinessForm` components are unchanged. Both wire
duplicate detection as an in-modal sub-state on create only (see
"Duplicate detection" above). **Create navigates** to the new record's
detail page (`push`), **edit calls `onSaved`** and the host detail page
reloads in place, **cancel stays**. `ContactFormModal` takes
`defaultBusinessId` (the business page's New Contact). `BusinessFormModal`
loads `/api/payment-terms/` on open and runs the three-step create from
"Circular-dependency creation order": `check-name` → create Contact →
create Business with `default_contact_id`.

### `ContactPicker.svelte`

`frontend/src/components/ContactPicker.svelte` — a generic
`SearchPicker`-based contact search field (`bind:value` = `contact_id`),
searching `/api/contacts/?search=`. Reused outside this domain wherever a
contact needs to be picked without a full form — e.g. `DuplicateJobModal.svelte`,
and the Job-edit contact reassignment (draft-only — see
`docs/designs/data-constraints.md` §1.8).
