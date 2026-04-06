# Part 1 of the Task/Bundle/Material split refactor: create the new
# jobs-side schema (PlanBundle and PlanTask). The data move and removal
# of old columns live in jobs/0009_task_split_data_move.py, which depends
# on inventory/0006 so that the plan_materials table exists before the
# data move runs.
#
# See docs/plans/2026-04-05-task-split-plan1-model-refactor.md and
# docs/designs/2026-04-05-task-split-and-worksheet-to-workorder.md.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0010_alter_user_options'),
        ('estimates', '0005_remove_tasktemplate_parent_template'),
        ('jobs', '0007_alter_task_units'),
    ]

    operations = [
        migrations.CreateModel(
            name='PlanBundle',
            fields=[
                ('plan_bundle_id', models.AutoField(primary_key=True, serialize=False)),
                ('name', models.CharField(max_length=100)),
                ('description', models.TextField(blank=True)),
                ('sort_order', models.IntegerField(default=0)),
                ('accounting_category', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='core.accountingcategory')),
                ('est_worksheet', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='plan_bundles', to='estimates.estworksheet')),
                ('source_template_bundle', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='estimates.templatebundle')),
            ],
            options={
                'db_table': 'plan_bundles',
                'ordering': ['sort_order', 'name'],
            },
        ),
        migrations.CreateModel(
            name='PlanTask',
            fields=[
                ('name', models.CharField(max_length=255)),
                ('description', models.TextField(blank=True, default='')),
                ('sort_order', models.PositiveIntegerField(blank=True, null=True)),
                ('units', models.CharField(default='none', max_length=50)),
                ('rate', models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True)),
                ('est_qty', models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True)),
                ('plan_task_id', models.AutoField(primary_key=True, serialize=False)),
                ('mapping_strategy', models.CharField(choices=[('direct', 'Direct'), ('bundle', 'Bundle'), ('exclude', 'Exclude')], default='direct', max_length=20)),
                ('accounting_category', models.ForeignKey(blank=True, help_text='Type of line item this task produces when mapped directly', null=True, on_delete=django.db.models.deletion.PROTECT, to='core.accountingcategory')),
                ('bundle', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='plan_tasks', to='jobs.planbundle')),
                ('est_worksheet', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='plan_tasks', to='estimates.estworksheet')),
            ],
            options={
                'db_table': 'plan_tasks',
            },
        ),
    ]
