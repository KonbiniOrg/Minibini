# History & Notes Design

## Overview

Audit trail and user notes for significant business objects. All changes to tracked models generate immutable history entries with timestamp, user, and field-level diffs. Users can also add free-text notes to top-level objects.

## HistoryEntry Model

Location: `apps/core/models.py`

```python
class HistoryEntry(models.Model):
    ENTRY_TYPES = [
        ('audit', 'Audit'),      # automatic change tracking
        ('action', 'Action'),    # system-generated with reason (signal side effects)
        ('note', 'Note'),        # user-written note
    ]

    entry_type = models.CharField(max_length=10, choices=ENTRY_TYPES)
    object_type = models.CharField(max_length=50)   # e.g., 'estimate', 'job'
    object_id = models.IntegerField()
    user = models.ForeignKey('core.User', null=True, blank=True, on_delete=models.SET_NULL)
    timestamp = models.DateTimeField(auto_now_add=True)
    changes = models.JSONField(null=True, blank=True)  # {"status": {"old": "draft", "new": "open"}}
    text = models.TextField(blank=True)                 # reason or note text

    class Meta:
        db_table = 'history'
        ordering = ['-timestamp']
```

Entry type usage:
- **audit**: `changes` has the field diff, `text` is empty
- **action**: `changes` has the field diff, `text` has the reason
- **note**: `changes` is null, `text` has the note

Uses `object_type` + `object_id` (not Django GenericForeignKey) for simplicity.

## Tracked Models

Decorated with `@history(exclude=[...])`:

- Job
- Estimate
- EstWorksheet
- WorkOrder
- Invoice
- PurchaseOrder
- Bill
- Contact
- Business

Not tracked: Task, Configuration, PriceListItem (can be added later).

## @history Decorator

Location: `apps/core/history.py`

```python
def history(exclude=None):
    """Mark a model for automatic history tracking."""
    def decorator(cls):
        cls._history_tracked = True
        cls._history_exclude = set(exclude or [])
        return cls
    return decorator
```

The decorator marks the model class and specifies fields to exclude from tracking. Excluded fields:
- Do not appear in the `changes` JSON
- If they are the only fields that changed, no history entry is created

## Change Detection

Uses `post_init` and `pre_save` Django signals (no `save()` overrides).

**`post_init`**: When a tracked model instance is loaded from the database, snapshot its field values onto `instance._history_original`.

**`pre_save`**: Compare current field values to `_history_original`, filter out excluded fields. If anything changed, append the diff to the request-scoped pending changes list (via `contextvars`).

**Middleware (after view)**: Read the pending changes list, create HistoryEntry records with `request.user`. Skip if the request errored/transaction rolled back.

### contextvars Usage

The middleware stores a pending changes list and `request.user` in a `contextvars.ContextVar` at request start. The `pre_save` signal handler appends change diffs to this list. The middleware reads the list after the view completes and creates all HistoryEntries. This is the only use of contextvars in the system.

### Signal-Created Entries

Signal handlers that cause side-effect changes (e.g., estimate accepted -> job status change) create action-type HistoryEntries directly, with user=System and an explicit reason. These bypass the middleware's pending list.

Example: `update_job_status` signal creates an action entry with reason "Estimate EST-2025-0001 accepted".

## Important: No QuerySet.update()

Never use `QuerySet.update()` on tracked models. Always load the instance and call `.save()` so that `post_init`/`pre_save` fire and history is captured. This is an existing codebase convention (custom `delete()` methods require the same discipline) now extended to all tracked models.

## Notes

Notes are immutable — no edit or delete. A new note can textually reference an old one if needed.

Notes can be added to three top-level object types only:
- Job
- Contact
- Business

## API Endpoints

### History Feeds

- `GET /api/jobs/{id}/history/` — aggregated feed: job + all related estimates, worksheets, work orders, invoices, POs, bills. Paginated, newest first.
- `GET /api/businesses/{id}/history/` — aggregated feed: business + all its contacts. Paginated, newest first.
- `GET /api/contacts/{id}/history/` — single object history. Paginated, newest first.

### Notes

- `POST /api/jobs/{id}/notes/` — add a note to a job
- `POST /api/contacts/{id}/notes/` — add a note to a contact
- `POST /api/businesses/{id}/notes/` — add a note to a business

No PATCH or DELETE endpoints (notes are immutable).

## Frontend

### History Section

Added to Job, Contact, and Business detail pages. Displays below existing content.

- Most recent entries at the top
- Each entry shows: timestamp, user, entry type badge, object type, changes or note text
- Non-note entries (audit, action) rendered in smaller font
- Note input (text field + submit button) at the top of the history section

### View Mode Behavior

- **Full view**: shows all history entries (audit, action, note)
- **Lite view**: shows notes only
