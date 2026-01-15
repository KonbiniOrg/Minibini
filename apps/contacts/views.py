from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from .models import Contact, Business

def contact_list(request):
    contacts = Contact.objects.all().order_by('last_name', 'first_name')
    return render(request, 'contacts/contact_list.html', {'contacts': contacts})

def contact_detail(request, contact_id):
    contact = get_object_or_404(Contact, contact_id=contact_id)
    return render(request, 'contacts/contact_detail.html', {'contact': contact})

def business_list(request):
    businesses = Business.objects.all().order_by('business_name')
    return render(request, 'contacts/business_list.html', {'businesses': businesses})

def business_detail(request, business_id):
    business = get_object_or_404(Business, business_id=business_id)
    contacts = Contact.objects.filter(business=business).order_by('last_name', 'first_name')
    return render(request, 'contacts/business_detail.html', {'business': business, 'contacts': contacts})

def add_contact(request):
    if request.method == 'POST':
        from django.db import transaction

        # Contact fields
        first_name = request.POST.get('first_name')
        middle_initial = request.POST.get('middle_initial')
        last_name = request.POST.get('last_name')
        email = request.POST.get('email')
        work_number = request.POST.get('work_number')
        mobile_number = request.POST.get('mobile_number')
        home_number = request.POST.get('home_number')
        address = request.POST.get('address')
        city = request.POST.get('city')
        postal_code = request.POST.get('postal_code')

        # Business fields
        business_name = request.POST.get('business_name')
        business_phone = request.POST.get('business_phone')
        business_address = request.POST.get('business_address')
        tax_exemption_number = request.POST.get('tax_exemption_number')
        website = request.POST.get('website')

        if first_name and last_name:
            # Validate email is provided
            if not email or not email.strip():
                messages.error(request, 'Email address is required.')
                return render(request, 'contacts/add_contact.html')

            # Validate at least one phone number is provided
            if not any([work_number, mobile_number, home_number]):
                messages.error(request, 'At least one phone number (work, mobile, or home) is required.')
                return render(request, 'contacts/add_contact.html')

            with transaction.atomic():
                # Create contact first (without business association)
                contact = Contact.objects.create(
                    first_name=first_name,
                    middle_initial=middle_initial or '',
                    last_name=last_name,
                    email=email.strip(),
                    work_number=work_number or '',
                    mobile_number=mobile_number or '',
                    home_number=home_number or '',
                    addr1=address or '',
                    city=city or '',
                    postal_code=postal_code or '',
                    business=None
                )

                business = None
                # Create business only if business name is provided and not just whitespace
                if business_name and business_name.strip():
                    business = Business.objects.create(
                        business_name=business_name.strip(),
                        business_phone=business_phone.strip() if business_phone else '',
                        business_address=business_address.strip() if business_address else '',
                        tax_exemption_number=tax_exemption_number.strip() if tax_exemption_number else '',
                        website=website.strip() if website else '',
                        default_contact=contact
                    )
                    # Associate contact with business
                    contact.business = business
                    contact.save()

            success_msg = f'Contact "{contact}" has been added successfully.'
            if business:
                success_msg += f' Associated with business "{business_name}".'
            messages.success(request, success_msg)
            return redirect('contacts:contact_list')
        else:
            messages.error(request, 'First name and last name are required.')

    return render(request, 'contacts/add_contact.html')

def add_business_contact(request, business_id):
    business = get_object_or_404(Business, business_id=business_id)

    if request.method == 'POST':
        first_name = request.POST.get('first_name')
        middle_initial = request.POST.get('middle_initial')
        last_name = request.POST.get('last_name')
        email = request.POST.get('email')
        work_number = request.POST.get('work_number')
        mobile_number = request.POST.get('mobile_number')
        home_number = request.POST.get('home_number')
        address = request.POST.get('address')
        city = request.POST.get('city')
        postal_code = request.POST.get('postal_code')
        set_as_default = request.POST.get('set_as_default') == 'true'

        if first_name and last_name:
            # Validate email is provided
            if not email or not email.strip():
                messages.error(request, 'Email address is required.')
                return render(request, 'contacts/add_business_contact.html', {'business': business})

            # Validate at least one phone number is provided
            if not any([work_number, mobile_number, home_number]):
                messages.error(request, 'At least one phone number (work, mobile, or home) is required.')
                return render(request, 'contacts/add_business_contact.html', {'business': business})

            contact = Contact.objects.create(
                first_name=first_name,
                middle_initial=middle_initial or '',
                last_name=last_name,
                email=email.strip(),
                work_number=work_number or '',
                mobile_number=mobile_number or '',
                home_number=home_number or '',
                addr1=address or '',
                city=city or '',
                postal_code=postal_code or '',
                business=business
            )

            # Set as default contact if checkbox was checked
            if set_as_default:
                business.default_contact = contact
                business.save(update_fields=['default_contact'])
                messages.success(request, f'Contact "{contact}" has been added to {business.business_name} and set as the default contact.')
            else:
                messages.success(request, f'Contact "{contact}" has been added to {business.business_name}.')

            return redirect('contacts:business_detail', business_id=business.business_id)
        else:
            messages.error(request, 'First name and last name are required.')

    return render(request, 'contacts/add_business_contact.html', {'business': business})

def add_business(request):
    if request.method == 'POST':
        # Business fields
        business_name = request.POST.get('business_name')
        business_phone = request.POST.get('business_phone')
        business_address = request.POST.get('business_address')
        tax_exemption_number = request.POST.get('tax_exemption_number')
        website = request.POST.get('website')

        # Get number of contacts
        contact_count = int(request.POST.get('contact_count', 1))

        # Collect contact data
        contacts_data = []
        for i in range(contact_count):
            contact_data = {
                'first_name': request.POST.get(f'contact_{i}_first_name'),
                'middle_initial': request.POST.get(f'contact_{i}_middle_initial'),
                'last_name': request.POST.get(f'contact_{i}_last_name'),
                'email': request.POST.get(f'contact_{i}_email'),
                'work_number': request.POST.get(f'contact_{i}_work_number'),
                'mobile_number': request.POST.get(f'contact_{i}_mobile_number'),
                'home_number': request.POST.get(f'contact_{i}_home_number'),
                'address': request.POST.get(f'contact_{i}_address'),
                'city': request.POST.get(f'contact_{i}_city'),
                'postal_code': request.POST.get(f'contact_{i}_postal_code')
            }
            # Only add contact if first and last name are provided
            if contact_data['first_name'] and contact_data['first_name'].strip() and contact_data['last_name'] and contact_data['last_name'].strip():
                contacts_data.append(contact_data)

        # Validate: business name and at least one contact required
        if not business_name or not business_name.strip():
            messages.error(request, 'Business name is required.')
        elif not contacts_data:
            messages.error(request, 'At least one contact with first and last name is required.')
        else:
            # Validate all contacts first
            for i, contact_data in enumerate(contacts_data):
                # Validate email
                if not contact_data['email'] or not contact_data['email'].strip():
                    messages.error(request, f'Email address is required for contact {i + 1}.')
                    return render(request, 'contacts/add_business.html')

                # Validate at least one phone number
                if not any([contact_data['work_number'], contact_data['mobile_number'], contact_data['home_number']]):
                    messages.error(request, f'At least one phone number is required for contact {i + 1}.')
                    return render(request, 'contacts/add_business.html')

            from django.db import transaction

            with transaction.atomic():
                # Create the first contact (without business association yet)
                first_contact_data = contacts_data[0]
                first_contact = Contact.objects.create(
                    first_name=first_contact_data['first_name'].strip(),
                    middle_initial=first_contact_data['middle_initial'].strip() if first_contact_data['middle_initial'] else '',
                    last_name=first_contact_data['last_name'].strip(),
                    email=first_contact_data['email'].strip(),
                    work_number=first_contact_data['work_number'].strip() if first_contact_data['work_number'] else '',
                    mobile_number=first_contact_data['mobile_number'].strip() if first_contact_data['mobile_number'] else '',
                    home_number=first_contact_data['home_number'].strip() if first_contact_data['home_number'] else '',
                    addr1=first_contact_data['address'].strip() if first_contact_data['address'] else '',
                    city=first_contact_data['city'].strip() if first_contact_data['city'] else '',
                    postal_code=first_contact_data['postal_code'].strip() if first_contact_data['postal_code'] else '',
                    business=None
                )

                # Create business with first contact as default
                business = Business.objects.create(
                    business_name=business_name.strip(),
                    business_phone=business_phone.strip() if business_phone else '',
                    business_address=business_address.strip() if business_address else '',
                    tax_exemption_number=tax_exemption_number.strip() if tax_exemption_number else '',
                    website=website.strip() if website else '',
                    default_contact=first_contact
                )

                # Update first contact to associate with business
                first_contact.business = business
                first_contact.save()

                created_contacts = [first_contact]

                # Create remaining contacts
                for i in range(1, len(contacts_data)):
                    contact_data = contacts_data[i]
                    contact = Contact.objects.create(
                        first_name=contact_data['first_name'].strip(),
                        middle_initial=contact_data['middle_initial'].strip() if contact_data['middle_initial'] else '',
                        last_name=contact_data['last_name'].strip(),
                        email=contact_data['email'].strip(),
                        work_number=contact_data['work_number'].strip() if contact_data['work_number'] else '',
                        mobile_number=contact_data['mobile_number'].strip() if contact_data['mobile_number'] else '',
                        home_number=contact_data['home_number'].strip() if contact_data['home_number'] else '',
                        addr1=contact_data['address'].strip() if contact_data['address'] else '',
                        city=contact_data['city'].strip() if contact_data['city'] else '',
                        postal_code=contact_data['postal_code'].strip() if contact_data['postal_code'] else '',
                        business=business
                    )
                    created_contacts.append(contact)

            success_msg = f'Business "{business_name}" has been created with {len(created_contacts)} contact(s): {", ".join(str(c) for c in created_contacts)}.'
            messages.success(request, success_msg)
            return redirect('contacts:business_list')

    return render(request, 'contacts/add_business.html')

def edit_contact(request, contact_id):
    contact = get_object_or_404(Contact, contact_id=contact_id)

    if request.method == 'POST':
        # Contact fields
        first_name = request.POST.get('first_name')
        middle_initial = request.POST.get('middle_initial')
        last_name = request.POST.get('last_name')
        email = request.POST.get('email')
        work_number = request.POST.get('work_number')
        mobile_number = request.POST.get('mobile_number')
        home_number = request.POST.get('home_number')
        address = request.POST.get('address')
        city = request.POST.get('city')
        postal_code = request.POST.get('postal_code')

        # Business fields
        business_selection_mode = request.POST.get('business_selection_mode')
        existing_business_id = request.POST.get('existing_business_id')
        business_name = request.POST.get('business_name')
        business_phone = request.POST.get('business_phone')
        business_address = request.POST.get('business_address')
        tax_exemption_number = request.POST.get('tax_exemption_number')
        website = request.POST.get('website')

        if first_name and last_name:
            # Validate email is provided
            if not email or not email.strip():
                messages.error(request, 'Email address is required.')
                existing_businesses = Business.objects.all().order_by('business_name')
                return render(request, 'contacts/edit_contact.html', {
                    'contact': contact,
                    'existing_businesses': existing_businesses
                })

            # Validate at least one phone number is provided
            if not any([work_number, mobile_number, home_number]):
                messages.error(request, 'At least one phone number (work, mobile, or home) is required.')
                existing_businesses = Business.objects.all().order_by('business_name')
                return render(request, 'contacts/edit_contact.html', {
                    'contact': contact,
                    'existing_businesses': existing_businesses
                })

            # Check if contact has open jobs before allowing business change
            from apps.jobs.models import Job

            # Business association is changing if:
            # 1. Contact currently has no business but will be assigned one
            # 2. Contact currently has a business but will be changed to a different one or none
            current_business_id = contact.business.business_id if contact.business else None
            new_business_id = None

            if business_selection_mode == 'existing' and existing_business_id:
                new_business_id = int(existing_business_id)
            elif business_selection_mode == 'new' and business_name and business_name.strip():
                # For new business, we'll check if it's actually creating a new business later
                # For now, we know it's changing
                pass
            elif business_selection_mode == 'name_search' and business_name and business_name.strip():
                from django.db.models import Q
                existing_business = Business.objects.filter(business_name__iexact=business_name.strip()).first()
                if existing_business:
                    new_business_id = existing_business.business_id

            # Check if business is actually changing
            business_changing = (
                (current_business_id is None and (new_business_id is not None or
                 (business_selection_mode == 'new' and business_name and business_name.strip()))) or
                (current_business_id is not None and (new_business_id != current_business_id or
                 business_selection_mode is None or business_selection_mode == '' or
                 (business_selection_mode == 'new' and business_name and business_name.strip())))
            )

            if business_changing:
                # Check for open jobs (not completed, rejected, or cancelled)
                open_jobs = Job.objects.filter(
                    contact=contact
                ).exclude(
                    status__in=['completed', 'rejected', 'cancelled']
                )

                if open_jobs.exists():
                    job_numbers = list(open_jobs.values_list('job_number', flat=True))
                    messages.error(
                        request,
                        f'Cannot change business association for "{contact}" because they have open jobs: {", ".join(job_numbers)}. '
                        'Complete or reject these jobs before changing the business association.'
                    )
                    existing_businesses = Business.objects.all().order_by('business_name')
                    return render(request, 'contacts/edit_contact.html', {
                        'contact': contact,
                        'existing_businesses': existing_businesses
                    })

            # Handle business association based on selection mode
            business = None

            if business_selection_mode == 'existing' and existing_business_id:
                # Associate with existing business - NO MODIFICATION ALLOWED
                try:
                    business = Business.objects.get(business_id=existing_business_id)
                    # Existing business is used as-is, no fields are updated
                except Business.DoesNotExist:
                    messages.error(request, 'Selected business no longer exists.')
                    existing_businesses = Business.objects.all().order_by('business_name')
                    return render(request, 'contacts/edit_contact.html', {
                        'contact': contact,
                        'existing_businesses': existing_businesses
                    })

            elif business_selection_mode == 'new' and business_name and business_name.strip():
                # Create new business - this will dissociate from current business
                # First, note the current business for messaging
                old_business_name = contact.business.business_name if contact.business else None

                # Check if business with this name already exists
                existing_business = Business.objects.filter(business_name__iexact=business_name.strip()).first()
                if existing_business:
                    # Use existing business instead of creating duplicate
                    business = existing_business
                    if old_business_name:
                        messages.info(request, f'Contact removed from "{old_business_name}" and associated with existing business "{existing_business.business_name}".')
                    else:
                        messages.info(request, f'Contact associated with existing business "{existing_business.business_name}".')
                else:
                    # Create new business (contact will be dissociated from old business)
                    business = Business.objects.create(
                        business_name=business_name.strip(),
                        business_phone=business_phone.strip() if business_phone else '',
                        business_address=business_address.strip() if business_address else '',
                        tax_exemption_number=tax_exemption_number.strip() if tax_exemption_number else '',
                        website=website.strip() if website else ''
                    )
                    if old_business_name:
                        messages.success(request, f'Contact removed from "{old_business_name}" and associated with new business "{business_name.strip()}".')
                    else:
                        messages.success(request, f'Contact associated with new business "{business_name.strip()}".')

            elif business_selection_mode == 'name_search' and business_name and business_name.strip():
                # Search for existing business by name - NO MODIFICATION ALLOWED
                existing_business = Business.objects.filter(business_name__iexact=business_name.strip()).first()
                if existing_business:
                    business = existing_business
                    # Existing business is used as-is, no fields are updated
                    messages.info(request, f'Contact associated with existing business "{existing_business.business_name}".')
                else:
                    messages.error(request, f'No business found with name "{business_name.strip()}". Please select from existing businesses or create a new one.')
                    existing_businesses = Business.objects.all().order_by('business_name')
                    return render(request, 'contacts/edit_contact.html', {
                        'contact': contact,
                        'existing_businesses': existing_businesses
                    })

            # business remains None if no selection mode or empty fields

            # Update contact
            contact.first_name = first_name
            contact.middle_initial = middle_initial or ''
            contact.last_name = last_name
            contact.email = email.strip()
            contact.work_number = work_number or ''
            contact.mobile_number = mobile_number or ''
            contact.home_number = home_number or ''
            contact.addr1 = address or ''
            contact.city = city or ''
            contact.postal_code = postal_code or ''

            # Only update business association if a radio button was selected
            # If no selection mode, preserve existing business association
            if business_selection_mode:
                contact.business = business

            contact.save()

            messages.success(request, f'Contact "{contact}" has been updated successfully.')
            return redirect('contacts:contact_detail', contact_id=contact.contact_id)
        else:
            messages.error(request, 'First name and last name are required.')

    existing_businesses = Business.objects.all().order_by('business_name')
    return render(request, 'contacts/edit_contact.html', {
        'contact': contact,
        'existing_businesses': existing_businesses
    })

def set_default_contact(request, contact_id):
    """Set a contact as the default contact for their business"""
    contact = get_object_or_404(Contact, contact_id=contact_id)

    if request.method == 'POST':
        if not contact.business:
            messages.error(request, 'This contact is not associated with any business.')
        else:
            business = contact.business
            business.default_contact = contact
            business.save(update_fields=['default_contact'])
            messages.success(request, f'"{contact}" has been set as the default contact for {business.business_name}.')

        return redirect('contacts:contact_detail', contact_id=contact.contact_id)

    # If not POST, redirect back
    return redirect('contacts:contact_detail', contact_id=contact.contact_id)

def delete_contact(request, contact_id):
    """Delete a contact if it's not associated with any non-business objects"""
    contact = get_object_or_404(Contact, contact_id=contact_id)

    if request.method == 'POST':
        # Check for associated Jobs (PROTECT constraint prevents deletion regardless of status)
        from apps.jobs.models import Job
        associated_jobs = Job.objects.filter(contact=contact)

        # Check for associated Bills
        from apps.purchasing.models import Bill
        associated_bills = Bill.objects.filter(contact=contact)

        # Build error message if there are associations
        error_messages = []
        if associated_jobs.exists():
            job_numbers = list(associated_jobs.values_list('job_number', flat=True))
            error_messages.append(f"Jobs: {', '.join(job_numbers)}")

        if associated_bills.exists():
            bill_ids = list(associated_bills.values_list('bill_id', flat=True))
            error_messages.append(f"Bills: {', '.join(map(str, bill_ids))}")

        if error_messages:
            messages.error(
                request,
                f'Cannot delete contact "{contact}" because it is still associated with the following: {"; ".join(error_messages)}. '
                'Please remove these associations before deleting the contact.'
            )
            return redirect('contacts:contact_detail', contact_id=contact.contact_id)

        # Check if contact is default and if business has other contacts
        business = contact.business
        was_default = business and business.default_contact == contact
        other_contacts = []
        if business:
            other_contacts = business.contacts.exclude(contact_id=contact_id).order_by('last_name', 'first_name')

        # Prevent deleting the last contact of a business
        if business and other_contacts.count() == 0:
            messages.error(
                request,
                f'Cannot delete "{contact}" because it is the only contact for {business.business_name}. '
                'A business must have at least one contact. Please add another contact first, or delete the entire business.'
            )
            return redirect('contacts:contact_detail', contact_id=contact.contact_id)

        # If deleting default contact with multiple other contacts, require selection
        if was_default and business and other_contacts.count() > 1:
            # Check if user has selected a new default
            new_default_contact_id = request.POST.get('new_default_contact')

            if not new_default_contact_id:
                # Show selection form
                return render(request, 'contacts/select_new_default_contact.html', {
                    'contact': contact,
                    'other_contacts': other_contacts
                })

            # Validate and set new default
            try:
                new_default_contact = Contact.objects.get(
                    contact_id=new_default_contact_id,
                    business=business
                )
            except Contact.DoesNotExist:
                messages.error(request, 'Invalid contact selection. Please try again.')
                return render(request, 'contacts/select_new_default_contact.html', {
                    'contact': contact,
                    'other_contacts': other_contacts
                })

            # Set new default FIRST (before deleting), then delete the contact
            contact_name = contact
            business_name = business.business_name

            # Change default contact before deletion to avoid PROTECT constraint
            business.default_contact = new_default_contact
            business.save(update_fields=['default_contact'])

            # Now safe to delete the old contact
            contact.delete()

            messages.success(
                request,
                f'Contact "{contact_name}" has been deleted. "{new_default_contact}" is now the default contact for {business_name}.'
            )
            return redirect('contacts:business_detail', business_id=business.business_id)

        # If only one other contact, auto-assign as default
        elif was_default and business and other_contacts.count() == 1:
            contact_name = contact
            business_name = business.business_name
            new_default = other_contacts.first()

            # Set new default FIRST (before deleting) to avoid PROTECT constraint
            business.default_contact = new_default
            business.save(update_fields=['default_contact'])

            # Now safe to delete the old contact
            contact.delete()

            messages.success(
                request,
                f'Contact "{contact_name}" has been deleted. "{new_default.name}" is now the default contact for {business_name}.'
            )
            return redirect('contacts:business_detail', business_id=business.business_id)

        # Non-default contact with business
        elif business:
            contact_name = contact
            contact.delete()
            messages.success(request, f'Contact "{contact_name}" has been deleted successfully.')
            return redirect('contacts:business_detail', business_id=business.business_id)

        # Non-business contact (no business association)
        else:
            contact_name = contact
            contact.delete()
            messages.success(request, f'Contact "{contact_name}" has been deleted successfully.')
            return redirect('contacts:contact_list')

    # If not POST, redirect back
    return redirect('contacts:contact_detail', contact_id=contact.contact_id)

def delete_business(request, business_id):
    """Delete a business if none of its contacts are associated with non-business objects"""
    business = get_object_or_404(Business, business_id=business_id)

    if request.method == 'POST':
        # Get all contacts for this business
        contacts = business.contacts.all()

        # Check if any contacts have associations with Jobs or Bills
        # Use bulk queries to avoid N+1 problem
        from apps.jobs.models import Job
        from apps.purchasing.models import Bill
        from collections import defaultdict

        contact_ids = list(contacts.values_list('contact_id', flat=True))

        # Single query to get all jobs for all contacts
        jobs_by_contact = defaultdict(list)
        for item in Job.objects.filter(contact_id__in=contact_ids).values('contact_id', 'job_number'):
            jobs_by_contact[item['contact_id']].append(item['job_number'])

        # Single query to get all bills for all contacts
        bills_by_contact = defaultdict(list)
        for item in Bill.objects.filter(contact_id__in=contact_ids).values('contact_id', 'bill_id'):
            bills_by_contact[item['contact_id']].append(str(item['bill_id']))

        # Build associated contacts list using the pre-fetched data
        associated_contacts = []
        for contact in contacts:
            jobs = jobs_by_contact.get(contact.contact_id, [])
            bills = bills_by_contact.get(contact.contact_id, [])

            if jobs or bills:
                associations = []
                if jobs:
                    associations.append(f"Jobs: {', '.join(jobs)}")
                if bills:
                    associations.append(f"Bills: {', '.join(bills)}")

                associated_contacts.append({
                    'name': contact,
                    'associations': '; '.join(associations)
                })

        # If any contacts have associations, prevent deletion
        if associated_contacts:
            error_details = []
            for item in associated_contacts:
                error_details.append(f"{item['name']} ({item['associations']})")

            messages.error(
                request,
                f'Cannot delete business "{business.business_name}" because the following contacts have associations: '
                f'{"; ".join(error_details)}. Please remove these associations before deleting the business.'
            )
            return redirect('contacts:business_detail', business_id=business.business_id)

        # Get user's choice for contact action
        contact_action = request.POST.get('contact_action')

        # If there are contacts and no action specified, show confirmation form
        if contacts.exists() and not contact_action:
            return render(request, 'contacts/confirm_delete_business.html', {
                'business': business,
                'contacts': contacts,
                'contact_count': contacts.count()
            })

        # Validate contact action if contacts exist
        if contacts.exists() and contact_action not in ['unlink', 'delete']:
            messages.error(request, 'Please select what to do with the associated contacts.')
            return render(request, 'contacts/confirm_delete_business.html', {
                'business': business,
                'contacts': contacts,
                'contact_count': contacts.count()
            })

        # Perform deletion based on user's choice
        business_name = business.business_name
        contact_count = contacts.count()

        if contact_action == 'unlink':
            # Unlink contacts from business individually to trigger model validation
            for contact in contacts:
                contact.business = None
                contact.save()
            business.delete()
            messages.success(
                request,
                f'Business "{business_name}" has been deleted. {contact_count} contact(s) have been unlinked and are now independent.'
            )
        elif contact_action == 'delete':
            # Delete all contacts along with business
            contact_names = [str(c) for c in contacts[:5]]  # Get first 5 names
            contact_ids = list(contacts.values_list('contact_id', flat=True))

            # Must delete business first to avoid PROTECT constraint on default_contact
            business.delete()

            # Delete contacts individually to trigger model validation logic
            # (contacts are now orphaned since business was deleted first)
            for contact_id in contact_ids:
                try:
                    contact = Contact.objects.get(contact_id=contact_id)
                    contact.delete()
                except Contact.DoesNotExist:
                    pass

            if contact_count <= 5:
                messages.success(
                    request,
                    f'Business "{business_name}" and {contact_count} contact(s) have been deleted: {", ".join(contact_names)}.'
                )
            else:
                messages.success(
                    request,
                    f'Business "{business_name}" and all {contact_count} associated contacts have been deleted.'
                )
        else:
            # No contacts, just delete business
            business.delete()
            messages.success(request, f'Business "{business_name}" has been deleted successfully.')

        return redirect('contacts:business_list')

    # If not POST, redirect back
    return redirect('contacts:business_detail', business_id=business_id)

def edit_business(request, business_id):
    business = get_object_or_404(Business, business_id=business_id)

    if request.method == 'POST':
        # Business fields
        business_name = request.POST.get('business_name')
        business_phone = request.POST.get('business_phone')
        business_address = request.POST.get('business_address')
        tax_exemption_number = request.POST.get('tax_exemption_number')
        website = request.POST.get('website')

        if business_name and business_name.strip():
            # Check if another business with this name already exists
            existing_business = Business.objects.filter(
                business_name__iexact=business_name.strip()
            ).exclude(business_id=business.business_id).first()

            if existing_business:
                messages.error(
                    request,
                    f'A business with the name "{business_name.strip()}" already exists. '
                    'Business names must be unique.'
                )
            else:
                # Update business (reference code is auto-generated and not updated)
                business.business_name = business_name.strip()
                business.business_phone = business_phone.strip() if business_phone else ''
                business.business_address = business_address.strip() if business_address else ''
                business.tax_exemption_number = tax_exemption_number.strip() if tax_exemption_number else ''
                business.website = website.strip() if website else ''
                business.save()

                messages.success(request, f'Business "{business_name.strip()}" has been updated successfully.')
                return redirect('contacts:business_detail', business_id=business.business_id)
        else:
            messages.error(request, 'Business name is required.')

    return render(request, 'contacts/edit_business.html', {
        'business': business
    })