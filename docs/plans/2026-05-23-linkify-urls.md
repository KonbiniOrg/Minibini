# Linkify URLs in descriptions & line items

**Status:** approved, implementing. Disposable plan (see `docs/designs/` for durable reference).

## Problem

Long URLs pasted into free-text fields (Job/Task descriptions, line items) are
one unbreakable token. In the Job-overview midband (`grid-template-columns:
1fr 1fr 320px`), a grid track won't shrink below its content's min-width, so a
long URL forces the description column wide and shoves Deliverables/History
off-screen. `white-space: pre-wrap` (the `.preserve-breaks` convention) wraps at
spaces/newlines but not inside a spaceless token.

## Two layers

1. **Layout fix (applies regardless):**
   - Add `overflow-wrap: anywhere` to the global `.preserve-breaks` rule
     (`frontend/src/css/app.css`, `templates/base.html`, and the standalone
     `templates/purchasing/purchase_order_pdf.html`) so long tokens break/wrap.
   - Add `.midband > :global(*) { min-width: 0; }` in `JobDetail.svelte` so the
     `1fr` columns can shrink below content (belt-and-suspenders with
     overflow-wrap).

2. **Linkify (SPA):** detect URLs in displayed text and render them as clickable
   links.

## URL matching rule

**Scheme required + dotted host required + www optional.** A token links iff it
starts with `http://`/`https://` AND its host contains a dot.

| Token | Result |
|---|---|
| `https://example.com/x`, `http://example.com`, `https://www.example.com` | link |
| `http://intra/wiki`, `http://localhost:8000` | plain (no dot in host) |
| `example.com`, `www.example.com` (no scheme) | plain |
| `drawing.pdf`, `rev 2.0` | plain |

No TLD allowlist needed (the required scheme keeps false positives near zero).
Trailing sentence punctuation (`.,;:!?)]}'"`) is trimmed back out of the match.

## Components

- **`frontend/src/lib/linkify.js`** — pure `linkify(text)` → array of segments
  `{type:'text', value}` | `{type:'url', value, href, display}`. Module-level
  regex `https?:\/\/[^\s/]*\.[^\s/]+(?:[/?#]\S*)?`, trailing-punct trim. No deps.
  Also exports `truncateUrl(url)` → compact display text: scheme dropped, full
  host + up to 8 chars of the path/query, then `…` only if there's more
  (`example.com/files/r…`, `example.com/x`, `example.com`).
- **`frontend/src/components/LinkifiedText.svelte`** — prop `{ text }`. Renders
  segments inline (no wrapper): text → auto-escaped `{value}`; url →
  `<a href title={full-url} target="_blank" rel="noopener noreferrer">{display}</a>`
  — the visible text is the truncated form, the full URL is in `href` + `title`
  (hover). No `{@html}` → XSS-safe like `.preserve-breaks`. Dropped *inside*
  existing `.preserve-breaks` wrappers so it inherits newline preservation + wrap.

## Usage sites

`<p class="preserve-breaks"><LinkifiedText text={...} /></p>` at:
- Job description (`JobDetail.svelte`)
- Task description (`TaskDetailPage.svelte`)
- PlanTask description (`PlanTaskDetailPage.svelte`)
- Line-item descriptions: `LineItemTable.svelte` (shared by estimate/invoice/PO
  detail views), `JobDetail.svelte` (invoice + PO line items),
  `PurchaseOrderDetail.svelte` (line-item cell + change-job dialog)

Out of scope: truncated/sliced cells, pickers, the print packing list, and other
free-text fields (notes, addresses, material descriptions) — they still get the
CSS wrap fix but aren't linkified for now.

## Testing

No JS test runner in the repo (only `vite build`); the tokenizer is a small pure
function verified via build + manual check. Adding Vitest was deemed out of scope.
