# Inventory reframe: catalog items vs. transient lots — proto-spec (SUPERSEDED)

**Status:** Superseded 2026-06-14 by
[`2026-06-14-inventory-catalog-vs-lots-spec.md`](./2026-06-14-inventory-catalog-vs-lots-spec.md),
which promotes this proto-spec to an agreed design + phased implementation plan
after the follow-up brainstorm.

The active spec resolves every open question this file raised — findability
(unified browsable list), where QOH lives (every lot is a first-class row),
earmarks (they *do* apply and get surfaced), lifecycle (delete-on-spend with an
earmark exception, no pruner), merge (explicit atomic endpoint), pricing (markup
config), and history (retire `InventoryAdjustment`, use `HistoryEntry`). See it
for the current design.
