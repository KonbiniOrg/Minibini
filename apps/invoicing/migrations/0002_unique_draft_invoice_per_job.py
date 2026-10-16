"""DB-level one-draft-invoice-per-job enforcement for MySQL.

Invoice.Meta declares a conditional UniqueConstraint (job, status='draft'),
but MySQL has no partial indexes, so Django skips it there (models.W036).
This stored generated column + unique index is the real enforcement: the
column equals job_id for drafts and NULL otherwise, and MySQL excludes NULLs
from unique indexes, so non-draft invoices never conflict.

Hand-authored survivor of the 2026-10 migration consolidation (formerly
invoicing/0008). Invisible in models.py — do not drop on a future squash.
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('invoicing', '0001_initial'),
    ]

    operations = [
        migrations.RunSQL(
            sql=[
                """
                ALTER TABLE invoices
                ADD COLUMN draft_job_id INT GENERATED ALWAYS AS
                    (CASE WHEN status = 'draft' THEN job_id END) STORED
                """,
                """
                CREATE UNIQUE INDEX unique_draft_invoice_per_job
                ON invoices (draft_job_id)
                """,
            ],
            reverse_sql=[
                "DROP INDEX unique_draft_invoice_per_job ON invoices",
                "ALTER TABLE invoices DROP COLUMN draft_job_id",
            ],
        ),
    ]
