# Generated manually

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0004_create_default_line_item_types'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='lineitemtype',
            name='default_units',
        ),
    ]
