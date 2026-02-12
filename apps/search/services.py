from datetime import datetime
from decimal import Decimal
from django.db.models import Q, F, CharField, DecimalField
from django.db.models.functions import Cast, Concat
from apps.jobs.models import Job, Estimate, Task, WorkOrder, EstWorksheet, EstimateLineItem
from apps.contacts.models import Contact, Business
from apps.invoicing.models import Invoice, InvoiceLineItem, PriceListItem
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLineItem, Bill, BillLineItem


class SearchService:
    """Service class to handle search business logic"""

    # Category numeric identifiers
    CATEGORY_BUSINESSES = 1
    CATEGORY_PRICE_LIST_ITEMS = 2
    CATEGORY_CONTACTS = 3
    CATEGORY_INVOICES = 4
    CATEGORY_JOBS = 5
    CATEGORY_ESTIMATES = 6
    CATEGORY_WORK_ORDERS = 7
    CATEGORY_EST_WORKSHEETS = 8
    CATEGORY_BILLS = 9
    CATEGORY_PURCHASE_ORDERS = 10

    # Mapping from category ID to internal key name
    CATEGORY_ID_TO_KEY = {
        CATEGORY_BUSINESSES: 'businesses',
        CATEGORY_PRICE_LIST_ITEMS: 'price_list_items',
        CATEGORY_CONTACTS: 'contacts',
        CATEGORY_INVOICES: 'invoices',
        CATEGORY_JOBS: 'jobs',
        CATEGORY_ESTIMATES: 'estimates',
        CATEGORY_WORK_ORDERS: 'work_orders',
        CATEGORY_EST_WORKSHEETS: 'est_worksheets',
        CATEGORY_BILLS: 'bills',
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
        CATEGORY_WORK_ORDERS: 'Work Orders',
        CATEGORY_EST_WORKSHEETS: 'Est Worksheets',
        CATEGORY_BILLS: 'Bills',
        CATEGORY_PURCHASE_ORDERS: 'Purchase Orders',
    }

    # Legacy support: List of category keys (for backward compatibility)
    AVAILABLE_CATEGORIES = [
        'businesses', 'price_list_items', 'contacts', 'invoices', 'jobs',
        'estimates', 'work_orders', 'est_worksheets', 'bills', 'purchase_orders'
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
    def search_jobs(query):
        """Search for jobs matching the query"""
        return Job.objects.filter(
            Q(job_number__icontains=query) |
            Q(customer_po_number__icontains=query) |
            Q(description__icontains=query) |
            Q(contact__first_name__icontains=query) |
            Q(contact__middle_initial__icontains=query) |
            Q(contact__last_name__icontains=query)
        ).select_related('contact')

    @staticmethod
    def search_price_list_items(query):
        """Search for price list items matching the query"""
        return PriceListItem.objects.annotate(
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
            price_text=Cast('price_currency', CharField()),
            qty_text=Cast('qty', CharField()),
            total_amount_calc=F('qty') * F('price_currency'),
            total_amount_text=Cast(F('qty') * F('price_currency'), CharField())
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
            price_text=Cast('price_currency', CharField()),
            qty_text=Cast('qty', CharField()),
            total_amount_calc=F('qty') * F('price_currency'),
            total_amount_text=Cast(F('qty') * F('price_currency'), CharField())
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
    def search_work_orders_with_tasks(query):
        """Search for work orders and their tasks, returning grouped results"""
        work_orders = WorkOrder.objects.filter(
            Q(job__job_number__icontains=query) |
            Q(job__description__icontains=query)
        ).select_related('job').prefetch_related('task_set')

        tasks = Task.objects.annotate(
            rate_text=Cast('rate', CharField())
        ).filter(
            Q(name__icontains=query) |
            Q(units__icontains=query) |
            Q(rate_text__icontains=query) |
            Q(work_order__job__job_number__icontains=query)
        ).select_related('assignee', 'work_order', 'work_order__job', 'est_worksheet')

        # Build a dict of work orders with their matching tasks
        wo_dict = {}
        for wo in work_orders:
            wo_dict[wo.work_order_id] = {
                'parent': wo,
                'tasks': []
            }

        for task in tasks:
            if task.work_order:
                wo_id = task.work_order.work_order_id
                if wo_id not in wo_dict:
                    wo_dict[wo_id] = {
                        'parent': task.work_order,
                        'tasks': []
                    }
                wo_dict[wo_id]['tasks'].append(task)

        return list(wo_dict.values()) if wo_dict else []

    @staticmethod
    def search_bills_with_line_items(query):
        """Search for bills and their line items, returning grouped results"""
        bills = Bill.objects.filter(
            Q(vendor_invoice_number__icontains=query) |
            Q(purchase_order__po_number__icontains=query) |
            Q(contact__first_name__icontains=query) |
            Q(contact__middle_initial__icontains=query) |
            Q(contact__last_name__icontains=query)
        ).select_related('purchase_order', 'contact').prefetch_related('billlineitem_set')

        bill_line_items = BillLineItem.objects.annotate(
            price_text=Cast('price_currency', CharField()),
            qty_text=Cast('qty', CharField()),
            total_amount_calc=F('qty') * F('price_currency'),
            total_amount_text=Cast(F('qty') * F('price_currency'), CharField())
        ).filter(
            Q(description__icontains=query) |
            Q(bill__vendor_invoice_number__icontains=query) |
            Q(price_text__icontains=query) |
            Q(qty_text__icontains=query) |
            Q(units__icontains=query) |
            Q(total_amount_text__icontains=query)
        ).select_related('bill', 'bill__purchase_order', 'bill__contact')

        # Build a dict of bills with their matching line items
        bill_dict = {}
        for bill in bills:
            bill_dict[bill.bill_id] = {
                'parent': bill,
                'line_items': []
            }

        for line_item in bill_line_items:
            bill_id = line_item.bill.bill_id
            if bill_id not in bill_dict:
                bill_dict[bill_id] = {
                    'parent': line_item.bill,
                    'line_items': []
                }
            bill_dict[bill_id]['line_items'].append(line_item)

        return list(bill_dict.values()) if bill_dict else []

    @staticmethod
    def search_purchase_orders_with_line_items(query):
        """Search for purchase orders and their line items, returning grouped results"""
        purchase_orders = PurchaseOrder.objects.filter(
            Q(po_number__icontains=query) |
            Q(job__job_number__icontains=query)
        ).select_related('job').prefetch_related('purchaseorderlineitem_set')

        po_line_items = PurchaseOrderLineItem.objects.annotate(
            price_text=Cast('price_currency', CharField()),
            qty_text=Cast('qty', CharField()),
            total_amount_calc=F('qty') * F('price_currency'),
            total_amount_text=Cast(F('qty') * F('price_currency'), CharField())
        ).filter(
            Q(description__icontains=query) |
            Q(purchase_order__po_number__icontains=query) |
            Q(price_text__icontains=query) |
            Q(qty_text__icontains=query) |
            Q(units__icontains=query) |
            Q(total_amount_text__icontains=query)
        ).select_related('purchase_order', 'purchase_order__job')

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

    @staticmethod
    def search_est_worksheets(query):
        """Search for est worksheets matching the query"""
        return EstWorksheet.objects.filter(
            Q(job__job_number__icontains=query) |
            Q(estimate__estimate_number__icontains=query)
        ).select_related('job', 'estimate')

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
        price_list_items = cls.search_price_list_items(query)
        if price_list_items.exists():
            categories['price_list_items'] = {
                'items': list(price_list_items),
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

        # JOBS
        jobs = cls.search_jobs(query)
        if jobs.exists():
            categories['jobs'] = {
                'items': list(jobs),
                'subcategories': {}
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

        # WORK ORDERS (with tasks grouped by parent)
        wo_groups = cls.search_work_orders_with_tasks(query)
        if wo_groups:
            # Extract parent work orders for flat list
            categories['work_orders'] = [group['parent'] for group in wo_groups]

        # EST WORKSHEETS
        est_worksheets = cls.search_est_worksheets(query)
        if est_worksheets.exists():
            categories['est_worksheets'] = list(est_worksheets)

        # BILLS (with line items grouped by parent)
        bill_groups = cls.search_bills_with_line_items(query)
        if bill_groups:
            # Extract parent bills for items
            categories['bills'] = {
                'items': list({group['parent'] for group in bill_groups}),
                'subcategories': {}
            }

        # PURCHASE ORDERS (with line items grouped by parent)
        po_groups = cls.search_purchase_orders_with_line_items(query)
        if po_groups:
            # Extract parent POs for items
            categories['purchase_orders'] = {
                'items': list({group['parent'] for group in po_groups}),
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
            # Handle flat lists (work_orders, est_worksheets)
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
                # Categories with grouped_items (estimates, invoices)
                if 'grouped_items' in category_data:
                    if date_from or date_to:
                        filtered_items = []
                        for item in category_data['grouped_items']:
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

    @staticmethod
    def calculate_total_count(categories):
        """Calculate total count of search results"""
        total = 0
        for category_name, category_data in categories.items():
            # Handle flat lists (work_orders, est_worksheets)
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
            'price_list_items': 'PriceListItem',
            'invoices': 'Invoice',
            'estimates': 'Estimate',
            'bills': 'Bill',
            'purchase_orders': 'PurchaseOrder',
            'work_orders': 'WorkOrder',
            'est_worksheets': 'EstWorksheet',
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

            # Handle flat lists (work_orders, est_worksheets)
            elif isinstance(category_data, list):
                items_list = category_data

            if items_list:
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

        # JOBS
        if 'Job' in result_ids and result_ids['Job']:
            jobs = Job.objects.filter(
                pk__in=result_ids['Job']
            ).filter(
                Q(job_number__icontains=within_query) |
                Q(customer_po_number__icontains=within_query) |
                Q(description__icontains=within_query) |
                Q(contact__first_name__icontains=within_query) |
                Q(contact__middle_initial__icontains=within_query) |
                Q(contact__last_name__icontains=within_query)
            ).select_related('contact')
            if jobs.exists():
                categories['jobs'] = {
                    'items': list(jobs),
                    'subcategories': {}
                }

        # PRICE LIST ITEMS
        if 'PriceListItem' in result_ids and result_ids['PriceListItem']:
            price_list_items = PriceListItem.objects.filter(
                pk__in=result_ids['PriceListItem']
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
            if price_list_items.exists():
                categories['price_list_items'] = {
                    'items': list(price_list_items),
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

            if invoices.exists():
                categories['invoices'] = {
                    'grouped_items': list(invoices),
                    'items': list(invoices)
                }

        # ESTIMATES
        if 'Estimate' in result_ids and result_ids['Estimate']:
            estimates = Estimate.objects.filter(
                pk__in=result_ids['Estimate']
            ).filter(
                Q(estimate_number__icontains=within_query) |
                Q(job__job_number__icontains=within_query)
            ).select_related('job')

            if estimates.exists():
                categories['estimates'] = {
                    'grouped_items': list(estimates),
                    'items': list(estimates)
                }

        # WORK ORDERS
        if 'WorkOrder' in result_ids and result_ids['WorkOrder']:
            work_orders = WorkOrder.objects.filter(
                pk__in=result_ids['WorkOrder']
            ).filter(
                Q(job__job_number__icontains=within_query) |
                Q(job__description__icontains=within_query)
            ).select_related('job')

            if work_orders.exists():
                categories['work_orders'] = list(work_orders)

        # EST WORKSHEETS
        if 'EstWorksheet' in result_ids and result_ids['EstWorksheet']:
            est_worksheets = EstWorksheet.objects.filter(
                pk__in=result_ids['EstWorksheet']
            ).filter(
                Q(job__job_number__icontains=within_query) |
                Q(estimate__estimate_number__icontains=within_query)
            ).select_related('job', 'estimate')

            if est_worksheets.exists():
                categories['est_worksheets'] = list(est_worksheets)

        # BILLS
        if 'Bill' in result_ids and result_ids['Bill']:
            bills = Bill.objects.filter(
                pk__in=result_ids['Bill']
            ).filter(
                Q(vendor_invoice_number__icontains=within_query) |
                Q(purchase_order__po_number__icontains=within_query) |
                Q(contact__first_name__icontains=within_query) |
                Q(contact__middle_initial__icontains=within_query) |
                Q(contact__last_name__icontains=within_query)
            ).select_related('purchase_order', 'contact')

            if bills.exists():
                categories['bills'] = {
                    'items': list(bills),
                    'subcategories': {}
                }

        # PURCHASE ORDERS
        if 'PurchaseOrder' in result_ids and result_ids['PurchaseOrder']:
            purchase_orders = PurchaseOrder.objects.filter(
                pk__in=result_ids['PurchaseOrder']
            ).filter(
                Q(po_number__icontains=within_query) |
                Q(job__job_number__icontains=within_query)
            ).select_related('job')

            if purchase_orders.exists():
                categories['purchase_orders'] = {
                    'items': list(purchase_orders),
                    'subcategories': {}
                }

        return categories
