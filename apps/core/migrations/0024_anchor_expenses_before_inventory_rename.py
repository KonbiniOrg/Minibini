# Ordering anchor (no schema operations).
#
# expenses.0003 adds Expense.stock_pli as an FK to the PRE-RENAME model
# `inventory.pricelistitem`, but it never declared a dependency forcing it to
# run before inventory.0026 (RenameModel PriceListItem -> InventoryItem). On a
# fresh build the historical topological sort placed the expenses chain before
# inventory.0026 only because the inventory chain was appended late (by the
# `inventory` per-app leaf, which sorts after the `expenses` leaf).
#
# The Task 4.2b plan-layer deletion migration estimates.0038 (DeleteModel
# EstWorksheet) must run after inventory.0030 (DeleteModel PlanMaterial), so it
# now transitively pulls the whole inventory chain — including inventory.0026 —
# into the `estimates` leaf's subtree. Because the `estimates` leaf sorts BEFORE
# the `expenses` leaf, inventory.0026 began being appended ahead of
# expenses.0003, and the fresh migrate then crashed resolving
# `inventory.pricelistitem`.
#
# We cannot edit the existing expenses.0003 / inventory.0026 files. This empty
# migration lives in `core` (whose leaf sorts before `estimates`) and depends on
# the expenses leaf, so the expenses chain is appended early — before
# estimates.0038 pulls in inventory.0026 — restoring the required ordering.
#
# Forward-dependencies only (no `run_before`): nothing already applied depends
# on this migration, so it does NOT trip check_consistent_history on an existing
# database the way a run_before pin would. No cycle: expenses depends only on
# core migrations <= 0023, never on this 0024.
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0023_expenseshistory'),
        ('expenses', '0007_expense_qbo_pending_op_reimbursement_qbo_pending_op'),
    ]

    operations = []
