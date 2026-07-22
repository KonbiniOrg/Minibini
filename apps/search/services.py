from datetime import datetime
from decimal import Decimal
from django.db.models import Q, F, CharField, DecimalField
from django.db.models.functions import Cast, Concat
from apps.jobs.models import Job, Task
from apps.estimates.models import Estimate, EstimateLineItem
from apps.contacts.models import Contact, Business
from apps.invoicing.models import Invoice, InvoiceLineItem
from apps.inventory.models import InventoryItem
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLineItem


class SearchService:
    """Service class to handle search business logic"""

    # Category numeric identifiers
    CATEGORY_BUSINESSES = 1
    CATEGORY_PRICE_LIST_ITEMS = 2
    CATEGORY_CONTACTS = 3
    CATEGORY_INVOICES = 4
    CATEGORY_JOBS = 5
    CATEGORY_ESTIMATES = 6
    CATEGORY_PURCHASE_ORDERS = 10

    # Mapping from category ID to internal key name
    CATEGORY_ID_TO_KEY = {
        CATEGORY_BUSINESSES: 'businesses',
        CATEGORY_PRICE_LIST_ITEMS: 'inventory_items',
        CATEGORY_CONTACTS: 'contacts',
        CATEGORY_INVOICES: 'invoices',
        CATEGORY_JOBS: 'jobs',
        CATEGORY_ESTIMATES: 'estimates',
        CATEGORY_PURCHASE_ORDERS: 'purchase_orders',
    }

    # Mapping from internal key name to category ID
    CATEGORY_KEY_TO_ID = {v: k for k, v in CATEGORY_ID_TO_KEY.items()}

    # Mapping from category ID to display name
    CATEGORY_ID_TO_DISPLAY = {
        CATEGORY_BUSINESSES: 'Businesses',
        CATEGORY_PRICE_LIST_ITEMS: 'Price List Items',
        CATEGORY_CONTACTS: 'Contacts',
        CATEGORY_INVOICES: 'Invoices',
        CATEGORY_JOBS: 'Jobs',
        CATEGORY_ESTIMATES: 'Estimates',
        CATEGORY_PURCHASE_ORDERS: 'Purchase Orders',
    }

    # Legacy support: List of category keys (for backward compatibility)
    AVAILABLE_CATEGORIES = [
        'businesses', 'inventory_items', 'contacts', 'invoices', 'jobs',
        'estimates', 'purchase_orders'
    ]

    @classmethod
    def get_category_id_from_string(cls, category_str):
        """
        Convert a category string to its numeric ID.
        Case-insensitive lookup.
        Returns None if not found.
        """
        if not category_str:
            return None

        # Normalize to lowercase for case-insensitive comparison
        normalized = category_str.lower().strip()

        # Try exact match first
        if normalized in cls.CATEGORY_KEY_TO_ID:
            return cls.CATEGORY_KEY_TO_ID[normalized]

        # Try matching against all keys case-insensitively
        for key, category_id in cls.CATEGORY_KEY_TO_ID.items():
            if key.lower() == normalized:
                return category_id

        return None

    @classmethod
    def get_category_key_from_id(cls, category_id):
        """
        Convert a category ID to its internal key name.
        Returns None if not found.
        """
        return cls.CATEGORY_ID_TO_KEY.get(category_id)

    @classmethod
    def get_category_display_name(cls, category_id):
        """
        Get the display name for a category ID.
        Returns None if not found.
        """
        return cls.CATEGORY_ID_TO_DISPLAY.get(category_id)

    @classmethod
    def get_all_category_info(cls):
        """
        Get information about all categories.
        Returns a list of dicts with id, key, and display_name.
        """
        return [
            {
                'id': category_id,
                'key': cls.get_category_key_from_id(category_id),
                'display_name': cls.get_category_display_name(category_id)
            }
            for category_id in sorted(cls.CATEGORY_ID_TO_KEY.keys())
        ]

    @staticmethod
    def parse_price_filters(price_min_str, price_max_str):
        """Parse price filter strings into numeric values"""
        price_min_value = None
        price_max_value = None

        if price_min_str:
            try:
                price_min_value = float(price_min_str)
            except ValueError:
                pass

        if price_max_str:
            try:
                price_max_value = float(price_max_str)
            except ValueError:
                pass

        return price_min_value, price_max_value

    @staticmethod
    def search_businesses(query):
        """Search for businesses matching the query"""
        return Business.objects.filter(
            Q(business_name__icontains=query) |
            Q(our_reference_code__icontains=query) |
            Q(business_address__icontains=query) |
            Q(business_phone__icontains=query)
        )

    @staticmethod
    def search_contacts(query):
        """Search for contacts matching the query"""
        return Contact.objects.filter(
            Q(first_name__icontains=query) |
            Q(middle_initial__icontains=query) |
            Q(last_name__icontains=query) |
            Q(email__icontains=query) |
            Q(mobile_number__icontains=query) |
            Q(work_number__icontains=query) |
            Q(home_number__icontains=query) |
            Q(addr1__icontains=query) |
            Q(city__icontains=query) |
            Q(postal_code__icontains=query)
        ).select_related('business')

    @staticmethod
    def search_inventory_items(query):
        """Search for price list items matching the query"""
        return InventoryItem.objects.annotate(
            purchase_price_text=Cast('purchase_price', CharField()),
            selling_price_text=Cast('selling_price', CharField())
        ).filter(
            Q(code__icontains=query) |
            Q(description__icontains=query) |
            Q(units__icontains=query) |
            Q(purchase_price_text__icontains=query) |
            Q(selling_price_text__icontains=query)
        )

    @staticmethod
    def search_invoices_with_line_items(query):
        """Search for invoices and their line items, returning grouped results"""
        invoices = Invoice.objects.filter(
            Q(invoice_number__icontains=query) |
            Q(job__job_number__icontains=query) |
            Q(job__customer_po_number__icontains=query)
        ).select_related('job').prefetch_related('invoicelineitem_set')

        invoice_line_items = InvoiceLineItem.objects.annotate(
            price_text=Cast('price', CharField()),
            qty_text=Cast('qty', CharField()),
            total_amount_calc=F('qty') * F('price'),
            total_amount_text=Cast(F('qty') * F('price'), CharField())
        ).filter(
            Q(description__icontains=query) |
            Q(invoice__invoice_number__icontains=query) |
            Q(price_text__icontains=query) |
            Q(qty_text__icontains=query) |
            Q(units__icontains=query) |
            Q(total_amount_text__icontains=query)
        ).select_related('invoice', 'invoice__job')

        # Build a dict of invoices with their matching line items
        invoice_dict = {}
        for invoice in invoices:
            invoice_dict[invoice.invoice_id] = {
                'parent': invoice,
                'line_items': []
            }

        for line_item in invoice_line_items:
            invoice_id = line_item.invoice.invoice_id
            if invoice_id not in invoice_dict:
                invoice_dict[invoice_id] = {
                    'parent': line_item.invoice,
                    'line_items': []
                }
            invoice_dict[invoice_id]['line_items'].append(line_item)

        return list(invoice_dict.values()) if invoice_dict else []

    @staticmethod
    def search_estimates_with_line_items(query):
        """Search for estimates and their line items, returning grouped results"""
        estimates = Estimate.objects.filter(
            Q(estimate_number__icontains=query) |
            Q(job__job_number__icontains=query)
        ).select_related('job').prefetch_related('estimatelineitem_set')

        estimate_line_items = EstimateLineItem.objects.annotate(
            price_text=Cast('price', CharField()),
            qty_text=Cast('qty', CharField()),
            total_amount_calc=F('qty') * F('price'),
            total_amount_text=Cast(F('qty') * F('price'), CharField())
        ).filter(
            Q(description__icontains=query) |
            Q(estimate__estimate_number__icontains=query) |
            Q(price_text__icontains=query) |
            Q(qty_text__icontains=query) |
            Q(units__icontains=query) |
            Q(total_amount_text__icontains=query)
        ).select_related('estimate', 'estimate__job')

        # Build a dict of estimates with their matching line items
        estimate_dict = {}
        for estimate in estimates:
            estimate_dict[estimate.estimate_id] = {
                'parent': estimate,
                'line_items': []
            }

        for line_item in estimate_line_items:
            estimate_id = line_item.estimate.estimate_id
            if estimate_id not in estimate_dict:
                estimate_dict[estimate_id] = {
                    'parent': line_item.estimate,
                    'line_items': []
                }
            estimate_dict[estimate_id]['line_items'].append(line_item)

        return list(estimate_dict.values()) if estimate_dict else []

    @staticmethod
    def search_jobs_with_tasks(query):
        """Search for jobs and their matching tasks, returning grouped results."""
        jobs = Job.objects.filter(
            Q(job_number__icontains=query) |
            Q(description__icontains=query) |
            Q(customer_po_number__icontains=query) |
            Q(contact__first_name__icontains=query) |
            Q(contact__middle_initial__icontains=query) |
            Q(contact__last_name__icontains=query)
        ).select_related('contact').prefetch_related('tasks')

        tasks = Task.objects.filter(
            Q(name__icontains=query) |
            Q(job__job_number__icontains=query)
        ).select_related('assignee', 'job')

        job_dict = {}
        for job in jobs:
            job_dict[job.pk] = {'parent': job, 'tasks': []}

        for task in tasks:
            if task.job_id not in job_dict:
                job_dict[task.job_id] = {'parent': task.job, 'tasks': []}
            job_dict[task.job_id]['tasks'].append(task)

        return list(job_dict.values())

    @staticmethod
    def search_purchase_orders_with_line_items(query):
        """Search for purchase orders and their line items, returning grouped results"""
        from apps.inventory.models import Material
        material_line_ids = list(
            Material.objects.filter(
                job__job_number__icontains=query,
                po_line_item__isnull=False,
            ).values_list('po_line_item_id', flat=True)
        )
        purchase_orders = PurchaseOrder.objects.filter(
            Q(po_number__icontains=query) |
            Q(purchaseorderlineitem__in=material_line_ids)
        ).distinct().prefetch_related('purchaseorderlineitem_set')

        po_line_items = PurchaseOrderLineItem.objects.annotate(
            price_text=Cast('price', CharField()),
            qty_text=Cast('qty', CharField()),
            total_amount_calc=F('qty') * F('price'),
            total_amount_text=Cast(F('qty') * F('price'), CharField())
        ).filter(
            Q(description__icontains=query) |
            Q(purchase_order__po_number__icontains=query) |
            Q(price_text__icontains=query) |
            Q(qty_text__icontains=query) |
            Q(units__icontains=query) |
            Q(total_amount_text__icontains=query)
        ).select_related('purchase_order')

        # Build a dict of purchase orders with their matching line items
        po_dict = {}
        for po in purchase_orders:
            po_dict[po.po_id] = {
                'parent': po,
                'line_items': []
            }

        for line_item in po_line_items:
            po_id = line_item.purchase_order.po_id
            if po_id not in po_dict:
                po_dict[po_id] = {
                    'parent': line_item.purchase_order,
                    'line_items': []
                }
            po_dict[po_id]['line_items'].append(line_item)

        return list(po_dict.values()) if po_dict else []

    @classmethod
    def search_all_entities(cls, query):
        """Search across all entity types and return categorized results"""
        categories = {}

        # BUSINESSES
        businesses = cls.search_businesses(query)
        if businesses.exists():
            categories['businesses'] = {
                'items': list(businesses),
                'subcategories': {}
            }

        # PRICE LIST ITEMS
        inventory_items = cls.search_inventory_items(query)
        if inventory_items.exists():
            categories['inventory_items'] = {
                'items': list(inventory_items),
                'subcategories': {}
            }

        # CONTACTS
        contacts = cls.search_contacts(query)
        if contacts.exists():
            categories['contacts'] = {
                'items': list(contacts),
                'subcategories': {}
            }

        # INVOICES (with line items grouped by parent)
        invoice_groups = cls.search_invoices_with_line_items(query)
        if invoice_groups:
            # Keep full groups with parent and line_items, but attach line_items to parent for template access
            parents_with_line_items = []
            for group in invoice_groups:
                parent = group['parent']
                parent.matching_line_items = group['line_items']
                parents_with_line_items.append(parent)
            categories['invoices'] = {
                'grouped_items': parents_with_line_items
            }

        # JOBS (with tasks grouped by parent)
        job_groups = cls.search_jobs_with_tasks(query)
        if job_groups:
            categories['jobs'] = {
                'grouped_items': job_groups
            }

        # ESTIMATES (with line items grouped by parent)
        estimate_groups = cls.search_estimates_with_line_items(query)
        if estimate_groups:
            # Keep full groups with parent and line_items, but attach line_items to parent for template access
            parents_with_line_items = []
            for group in estimate_groups:
                parent = group['parent']
                parent.matching_line_items = group['line_items']
                parents_with_line_items.append(parent)
            categories['estimates'] = {
                'grouped_items': parents_with_line_items
            }

        # BILLS (with line items grouped by parent)
        # PURCHASE ORDERS (with line items grouped by parent)
        po_groups = cls.search_purchase_orders_with_line_items(query)
        if po_groups:
            parents_with_line_items = []
            for group in po_groups:
                parent = group['parent']
                parent.matching_line_items = group['line_items']
                parents_with_line_items.append(parent)
            categories['purchase_orders'] = {
                'items': parents_with_line_items,
                'subcategories': {}
            }

        return categories

    @classmethod
    def apply_category_filter(cls, categories, filter_category):
        """
        Apply category filter to results.
        Accepts either a category ID (int), category key (str), or 'all'.
        Uses numeric mapping to avoid case sensitivity issues.
        """
        if not filter_category or filter_category == 'all':
            return categories

        # Convert filter to category ID if it's a string
        category_id = None
        if isinstance(filter_category, int):
            category_id = filter_category
        elif isinstance(filter_category, str):
            category_id = cls.get_category_id_from_string(filter_category)

        # If we couldn't resolve to a valid category ID, return empty
        if category_id is None:
            return {}

        # Get the category key for this ID
        category_key = cls.get_category_key_from_id(category_id)

        # Return only the matching category if it exists in results
        if category_key and category_key in categories:
            return {category_key: categories[category_key]}

        return {}

    @staticmethod
    def apply_date_filter(item_date, date_from_str, date_to_str):
        """Check if an item's date passes the date filter"""
        if not item_date:
            return True

        date_passes = True

        if date_from_str:
            try:
                date_from_obj = datetime.strptime(date_from_str, '%Y-%m-%d').date()
                if item_date.date() < date_from_obj:
                    date_passes = False
            except ValueError:
                pass

        if date_to_str:
            try:
                date_to_obj = datetime.strptime(date_to_str, '%Y-%m-%d').date()
                if item_date.date() > date_to_obj:
                    date_passes = False
            except ValueError:
                pass

        return date_passes

    @classmethod
    def apply_date_and_price_filters(cls, categories, date_from, date_to, price_min_value, price_max_value):
        """Apply date and price filters to search results"""
        filtered_categories = {}

        for category_name, category_data in categories.items():
            # Handle flat lists
            if isinstance(category_data, list):
                if date_from or date_to:
                    filtered_items = []
                    for item in category_data:
                        item_date = getattr(item, 'created_date', None)
                        if cls.apply_date_filter(item_date, date_from, date_to):
                            filtered_items.append(item)
                    if filtered_items:
                        filtered_categories[category_name] = filtered_items
                else:
                    filtered_categories[category_name] = category_data

            # Handle dict structures
            elif isinstance(category_data, dict):
                # Categories with grouped_items (jobs, estimates, invoices)
                if 'grouped_items' in category_data:
                    if date_from or date_to:
                        filtered_items = []
                        for item in category_data['grouped_items']:
                            # jobs use a dict {'parent': Job, 'tasks': [...]};
                            # estimates/invoices use Model instances with
                            # attached matching_line_items.
                            if isinstance(item, dict) and 'parent' in item:
                                item_date = getattr(item['parent'], 'created_date', None)
                            else:
                                item_date = getattr(item, 'created_date', None)
                            if cls.apply_date_filter(item_date, date_from, date_to):
                                filtered_items.append(item)
                        if filtered_items:
                            filtered_categories[category_name] = {
                                'grouped_items': filtered_items,
                                'items': filtered_items
                            }
                    else:
                        filtered_categories[category_name] = category_data

                # Categories with items (jobs, contacts, businesses, etc.)
                elif 'items' in category_data:
                    if date_from or date_to:
                        filtered_items = []
                        for item in category_data['items']:
                            item_date = getattr(item, 'created_date', None)
                            if cls.apply_date_filter(item_date, date_from, date_to):
                                filtered_items.append(item)
                        if filtered_items:
                            filtered_categories[category_name] = {
                                'items': filtered_items,
                                'subcategories': category_data.get('subcategories', {})
                            }
                    else:
                        filtered_categories[category_name] = category_data

        return filtered_categories

    @classmethod
    def apply_price_filter(cls, categories, price_min, price_max):
        """Filter results by price range.
        - inventory_items: filters by selling_price.
        - invoices/estimates/purchase_orders: keeps the entity if any matching line item
          is in range; if no matching line items exist (entity matched on header fields), it passes through.
        - All other categories pass through unchanged.
        """
        if price_min is None and price_max is None:
            return categories

        filtered = {}
        for key, data in categories.items():
            if key == 'inventory_items':
                kept = [
                    item for item in data.get('items', [])
                    if cls._price_in_range(item.selling_price, price_min, price_max)
                ]
                if kept:
                    filtered[key] = {'items': kept, 'subcategories': data.get('subcategories', {})}

            elif key in ('invoices', 'estimates'):
                kept = []
                for item in data.get('grouped_items', []):
                    line_items = getattr(item, 'matching_line_items', [])
                    if not line_items or any(
                        cls._price_in_range(li.price, price_min, price_max) for li in line_items
                    ):
                        kept.append(item)
                if kept:
                    filtered[key] = {'grouped_items': kept}

            elif key == 'purchase_orders':
                kept = []
                for item in data.get('items', []):
                    line_items = getattr(item, 'matching_line_items', [])
                    if not line_items or any(
                        cls._price_in_range(li.price, price_min, price_max) for li in line_items
                    ):
                        kept.append(item)
                if kept:
                    filtered[key] = {'items': kept, 'subcategories': data.get('subcategories', {})}

            else:
                filtered[key] = data

        return filtered

    @staticmethod
    def _price_in_range(price, price_min, price_max):
        if price is None:
            return True
        if price_min is not None and price < price_min:
            return False
        if price_max is not None and price > price_max:
            return False
        return True

    @classmethod
    def apply_job_status_filter(cls, categories, job_statuses):
        """Filter job results to only those whose status is in job_statuses. Non-job categories are unchanged."""
        if not job_statuses or 'jobs' not in categories:
            return categories

        filtered = {k: v for k, v in categories.items() if k != 'jobs'}
        groups = categories['jobs'].get('grouped_items', [])
        kept = [g for g in groups if g['parent'].status in job_statuses]
        if kept:
            filtered['jobs'] = {'grouped_items': kept}
        return filtered

    @classmethod
    def apply_start_date_filter(cls, categories, start_date_from, start_date_to):
        """Filter job results by start_date range. Jobs with no start_date are excluded when a range is active. Non-job categories are unchanged."""
        if (not start_date_from and not start_date_to) or 'jobs' not in categories:
            return categories

        filtered = {k: v for k, v in categories.items() if k != 'jobs'}
        groups = categories['jobs'].get('grouped_items', [])
        kept = []
        for g in groups:
            start_date = getattr(g['parent'], 'start_date', None)
            if start_date is None:
                continue
            if cls.apply_date_filter(start_date, start_date_from, start_date_to):
                kept.append(g)
        if kept:
            filtered['jobs'] = {'grouped_items': kept}
        return filtered

    @staticmethod
    def calculate_total_count(categories):
        """Calculate total count of search results"""
        total = 0
        for category_name, category_data in categories.items():
            # Handle flat lists
            if isinstance(category_data, list):
                total += len(category_data)
            # Handle dict structures
            elif isinstance(category_data, dict):
                # Count grouped_items if present (estimates, invoices)
                if 'grouped_items' in category_data:
                    total += len(category_data['grouped_items'])
                # Otherwise count items (jobs, contacts, businesses, etc.)
                elif 'items' in category_data:
                    total += len(category_data['items'])
                    if 'subcategories' in category_data:
                        for subcategory_items in category_data['subcategories'].values():
                            total += len(subcategory_items)
        return total

    @classmethod
    def build_result_ids_for_session(cls, categories):
        """
        Build a dictionary of result IDs for session storage.
        Uses numeric category mapping to avoid case sensitivity issues.
        """
        result_ids = {}

        # Mapping from category key to model name
        CATEGORY_KEY_TO_MODEL = {
            'jobs': 'Job',
            'contacts': 'Contact',
            'businesses': 'Business',
            'inventory_items': 'InventoryItem',
            'invoices': 'Invoice',
            'estimates': 'Estimate',
            'purchase_orders': 'PurchaseOrder',
        }

        for category_name, category_data in categories.items():
            # Normalize category name using the numeric mapping system
            category_id = cls.get_category_id_from_string(category_name)
            if category_id is None:
                continue

            category_key = cls.get_category_key_from_id(category_id)
            model_name = CATEGORY_KEY_TO_MODEL.get(category_key)

            if not model_name:
                continue

            items_list = None

            # Handle dict with 'items' or 'grouped_items'
            if isinstance(category_data, dict):
                # Get items from either 'grouped_items' or 'items'
                if 'grouped_items' in category_data:
                    items_list = category_data['grouped_items']
                elif 'items' in category_data:
                    items_list = category_data['items']

            # Handle flat lists
            elif isinstance(category_data, list):
                items_list = category_data

            if items_list:
                # Jobs use a grouped shape where each entry is
                # {'parent': Job, 'tasks': [...]}; unwrap to parents.
                if items_list and isinstance(items_list[0], dict) and 'parent' in items_list[0]:
                    result_ids[model_name] = [entry['parent'].pk for entry in items_list]
                else:
                    result_ids[model_name] = [item.pk for item in items_list]

        return result_ids

    @classmethod
    def search_within_stored_results(cls, result_ids, within_query):
        """Search within previously stored search results"""
        categories = {}

        # BUSINESSES
        if 'Business' in result_ids and result_ids['Business']:
            businesses = Business.objects.filter(
                pk__in=result_ids['Business']
            ).filter(
                Q(business_name__icontains=within_query) |
                Q(our_reference_code__icontains=within_query) |
                Q(business_address__icontains=within_query) |
                Q(business_phone__icontains=within_query)
            )
            if businesses.exists():
                categories['businesses'] = {
                    'items': list(businesses),
                    'subcategories': {}
                }

        # CONTACTS
        if 'Contact' in result_ids and result_ids['Contact']:
            contacts = Contact.objects.filter(
                pk__in=result_ids['Contact']
            ).filter(
                Q(first_name__icontains=within_query) |
                Q(middle_initial__icontains=within_query) |
                Q(last_name__icontains=within_query) |
                Q(email__icontains=within_query) |
                Q(mobile_number__icontains=within_query) |
                Q(work_number__icontains=within_query) |
                Q(home_number__icontains=within_query) |
                Q(addr1__icontains=within_query) |
                Q(city__icontains=within_query) |
                Q(postal_code__icontains=within_query)
            ).select_related('business')
            if contacts.exists():
                categories['contacts'] = {
                    'items': list(contacts),
                    'subcategories': {}
                }

        # JOBS (grouped shape: parent + matching tasks)
        if 'Job' in result_ids and result_ids['Job']:
            jobs = Job.objects.filter(
                pk__in=result_ids['Job']
            ).filter(
                Q(job_number__icontains=within_query) |
                Q(description__icontains=within_query) |
                Q(customer_po_number__icontains=within_query) |
                Q(contact__first_name__icontains=within_query) |
                Q(contact__middle_initial__icontains=within_query) |
                Q(contact__last_name__icontains=within_query)
            ).select_related('contact').prefetch_related('tasks')

            tasks = Task.objects.filter(
                job_id__in=result_ids['Job']
            ).filter(
                Q(name__icontains=within_query) |
                Q(job__job_number__icontains=within_query)
            ).select_related('assignee', 'job')

            job_dict = {}
            for job in jobs:
                job_dict[job.pk] = {'parent': job, 'tasks': []}
            for task in tasks:
                if task.job_id not in job_dict:
                    job_dict[task.job_id] = {'parent': task.job, 'tasks': []}
                job_dict[task.job_id]['tasks'].append(task)

            if job_dict:
                categories['jobs'] = {
                    'grouped_items': list(job_dict.values())
                }

        # PRICE LIST ITEMS
        if 'InventoryItem' in result_ids and result_ids['InventoryItem']:
            inventory_items = InventoryItem.objects.filter(
                pk__in=result_ids['InventoryItem']
            ).annotate(
                purchase_price_text=Cast('purchase_price', CharField()),
                selling_price_text=Cast('selling_price', CharField())
            ).filter(
                Q(code__icontains=within_query) |
                Q(description__icontains=within_query) |
                Q(units__icontains=within_query) |
                Q(purchase_price_text__icontains=within_query) |
                Q(selling_price_text__icontains=within_query)
            )
            if inventory_items.exists():
                categories['inventory_items'] = {
                    'items': list(inventory_items),
                    'subcategories': {}
                }

        # INVOICES
        if 'Invoice' in result_ids and result_ids['Invoice']:
            invoices = Invoice.objects.filter(
                pk__in=result_ids['Invoice']
            ).filter(
                Q(invoice_number__icontains=within_query) |
                Q(job__job_number__icontains=within_query) |
                Q(job__customer_po_number__icontains=within_query)
            ).select_related('job')

            invoice_line_items = InvoiceLineItem.objects.annotate(
                price_text=Cast('price', CharField()),
                qty_text=Cast('qty', CharField()),
                total_amount_text=Cast(F('qty') * F('price'), CharField())
            ).filter(invoice_id__in=result_ids['Invoice']).filter(
                Q(description__icontains=within_query) |
                Q(price_text__icontains=within_query) |
                Q(qty_text__icontains=within_query) |
                Q(units__icontains=within_query) |
                Q(total_amount_text__icontains=within_query)
            ).select_related('invoice', 'invoice__job')

            invoice_dict = {inv.pk: inv for inv in invoices}
            for inv in invoice_dict.values():
                inv.matching_line_items = []
            for li in invoice_line_items:
                if li.invoice_id not in invoice_dict:
                    invoice_dict[li.invoice_id] = li.invoice
                    li.invoice.matching_line_items = []
                invoice_dict[li.invoice_id].matching_line_items.append(li)

            if invoice_dict:
                result_invoices = list(invoice_dict.values())
                categories['invoices'] = {
                    'grouped_items': result_invoices,
                    'items': result_invoices,
                }

        # ESTIMATES
        if 'Estimate' in result_ids and result_ids['Estimate']:
            estimates = Estimate.objects.filter(
                pk__in=result_ids['Estimate']
            ).filter(
                Q(estimate_number__icontains=within_query) |
                Q(job__job_number__icontains=within_query)
            ).select_related('job')

            estimate_line_items = EstimateLineItem.objects.annotate(
                price_text=Cast('price', CharField()),
                qty_text=Cast('qty', CharField()),
                total_amount_text=Cast(F('qty') * F('price'), CharField())
            ).filter(estimate_id__in=result_ids['Estimate']).filter(
                Q(description__icontains=within_query) |
                Q(price_text__icontains=within_query) |
                Q(qty_text__icontains=within_query) |
                Q(units__icontains=within_query) |
                Q(total_amount_text__icontains=within_query)
            ).select_related('estimate', 'estimate__job')

            estimate_dict = {est.pk: est for est in estimates}
            for est in estimate_dict.values():
                est.matching_line_items = []
            for li in estimate_line_items:
                if li.estimate_id not in estimate_dict:
                    estimate_dict[li.estimate_id] = li.estimate
                    li.estimate.matching_line_items = []
                estimate_dict[li.estimate_id].matching_line_items.append(li)

            if estimate_dict:
                result_estimates = list(estimate_dict.values())
                categories['estimates'] = {
                    'grouped_items': result_estimates,
                    'items': result_estimates,
                }

        # PURCHASE ORDERS
        if 'PurchaseOrder' in result_ids and result_ids['PurchaseOrder']:
            from apps.inventory.models import Material
            material_line_ids = list(
                Material.objects.filter(
                    job__job_number__icontains=within_query,
                    po_line_item__isnull=False,
                ).values_list('po_line_item_id', flat=True)
            )
            purchase_orders = PurchaseOrder.objects.filter(
                pk__in=result_ids['PurchaseOrder']
            ).filter(
                Q(po_number__icontains=within_query) |
                Q(purchaseorderlineitem__in=material_line_ids)
            ).distinct()

            po_line_items = PurchaseOrderLineItem.objects.annotate(
                price_text=Cast('price', CharField()),
                qty_text=Cast('qty', CharField()),
                total_amount_text=Cast(F('qty') * F('price'), CharField())
            ).filter(purchase_order_id__in=result_ids['PurchaseOrder']).filter(
                Q(description__icontains=within_query) |
                Q(price_text__icontains=within_query) |
                Q(qty_text__icontains=within_query) |
                Q(units__icontains=within_query) |
                Q(total_amount_text__icontains=within_query)
            ).select_related('purchase_order')

            po_dict = {po.pk: po for po in purchase_orders}
            for po in po_dict.values():
                po.matching_line_items = []
            for li in po_line_items:
                if li.purchase_order_id not in po_dict:
                    po_dict[li.purchase_order_id] = li.purchase_order
                    li.purchase_order.matching_line_items = []
                po_dict[li.purchase_order_id].matching_line_items.append(li)

            if po_dict:
                result_pos = list(po_dict.values())
                categories['purchase_orders'] = {
                    'items': result_pos,
                    'subcategories': {}
                }

        return categories
