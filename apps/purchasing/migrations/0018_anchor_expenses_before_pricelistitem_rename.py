# Ordering anchor (no schema operations) — first link in a sequential chain
# (0018-0024) that core.0029_singular_units routes through.
#
# core.0029 needs the current latest migration of core, estimates,
# purchasing, invoicing, inventory, deliverables, and jobs all applied
# before it runs. Declaring several of those as direct sibling dependencies
# on one node is unsafe on a fresh build: MigrationGraph.iterative_dfs
# visits a node's parents in *reverse* sorted (app_label, name) order, and
# several existing renames in this history (PriceListItem -> InventoryItem,
# RateScheme -> ServicePrice -> ServiceItem -> RateScheme) only resolve
# correctly if the apps holding pre-rename FK references are walked before
# the app doing the rename — an ordering the existing migration graph gets
# "for free" only because of which top-level leaf happens to reach each
# region first during a fresh `migrate`; a new node depending on several of
# these leaves directly can walk into the same regions in the wrong order.
#
# This link: 'expenses' before 'inventory' touches the PriceListItem rename.
# expenses.0003 adds Expense.stock_pli as an FK to the pre-rename model
# 'inventory.pricelistitem' but its actual dependencies are
# ('expenses', '0002_expense_job') and
# ('inventory', '0025_pricelistitem_price_list_qty_on_hand_non_negative') —
# the migration immediately BEFORE the rename; nothing forces it to run
# before inventory.0026 (RenameModel PriceListItem -> InventoryItem). See
# core/migrations/0024_anchor_expenses_before_inventory_rename.py, which
# already anchors this for the *existing* graph's own leaf-vs-leaf race —
# this link re-establishes the same ordering from within this new chain,
# since this chain reaches 'inventory' via a different path than the one
# 0024 was built for.
#
# We cannot edit the existing expenses.0003 / inventory.0026 files (same
# constraint 0024 documents), and a `run_before` pin from a new migration
# would target an already-applied migration on every existing DB, tripping
# check_consistent_history there.
#
# Forward-dependencies only (no run_before): nothing already applied
# depends on this migration, so it does NOT trip check_consistent_history
# on an existing database.
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('purchasing', '0017_remove_billlineitem_tax_rate_override_and_more'),
        ('expenses', '0007_expense_qbo_pending_op_reimbursement_qbo_pending_op'),
    ]

    operations = []
