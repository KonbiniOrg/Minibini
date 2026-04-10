from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('invoicing', '0007_invoicelineitemsource'),
    ]

    operations = [
        migrations.RunSQL(
            sql=[
                # Stored generated column: equals job_id for drafts, NULL otherwise.
                # MySQL excludes NULLs from unique indexes (each NULL is distinct),
                # so non-draft invoices don't conflict.
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
