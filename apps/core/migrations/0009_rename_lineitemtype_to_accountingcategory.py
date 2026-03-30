from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0008_lineitemtype_qbo_expense_account_id_and_more'),
        # Cross-app deps — all apps with FKs to LineItemType
        ('jobs', '0004_migrate_draft_workorders'),
        ('estimates', '0002_initial'),
        ('inventory', '0002_alter_pricelistitem_code'),
        ('invoicing', '0001_initial'),
        ('purchasing', '0001_initial'),
    ]

    operations = [
        migrations.RenameModel(
            old_name='LineItemType',
            new_name='AccountingCategory',
        ),
        migrations.AlterModelTable(
            name='AccountingCategory',
            table='accounting_categories',
        ),
        migrations.AlterModelOptions(
            name='AccountingCategory',
            options={
                'ordering': ['name'],
                'verbose_name_plural': 'accounting categories',
            },
        ),
    ]
