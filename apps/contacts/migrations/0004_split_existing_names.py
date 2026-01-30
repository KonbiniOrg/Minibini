# Generated manually

from django.db import migrations


def split_names(apps, schema_editor):
    """Split existing name field into first_name, middle_initial, last_name"""
    Contact = apps.get_model('contacts', 'Contact')

    for contact in Contact.objects.all():
        if not contact.name:
            # Handle empty names
            contact.first_name = ''
            contact.last_name = ''
            contact.middle_initial = ''
        else:
            # Split the name by spaces
            name_parts = contact.name.strip().split()

            if len(name_parts) == 1:
                # Only one name part - use as first name
                contact.first_name = name_parts[0]
                contact.last_name = ''
                contact.middle_initial = ''
            elif len(name_parts) == 2:
                # Two parts - first and last name
                contact.first_name = name_parts[0]
                contact.last_name = name_parts[1]
                contact.middle_initial = ''
            else:
                # Three or more parts
                contact.first_name = name_parts[0]
                contact.last_name = name_parts[-1]

                # Middle parts - check if it looks like a middle initial
                middle_parts = name_parts[1:-1]
                middle_text = ' '.join(middle_parts)

                # If middle part is short (1-2 chars) or ends with a period, treat as initial
                if len(middle_text) <= 2 or middle_text.endswith('.'):
                    contact.middle_initial = middle_text.rstrip('.')
                else:
                    # Multiple middle names - join them
                    contact.middle_initial = middle_text

        contact.save()


def reverse_split_names(apps, schema_editor):
    """Reverse migration - combine name fields back into name"""
    Contact = apps.get_model('contacts', 'Contact')

    for contact in Contact.objects.all():
        parts = []
        if contact.first_name:
            parts.append(contact.first_name)
        if contact.middle_initial:
            parts.append(contact.middle_initial)
        if contact.last_name:
            parts.append(contact.last_name)

        contact.name = ' '.join(parts) if parts else ''
        contact.save()


class Migration(migrations.Migration):

    dependencies = [
        ('contacts', '0003_add_name_fields'),
    ]

    operations = [
        migrations.RunPython(split_names, reverse_split_names),
    ]
