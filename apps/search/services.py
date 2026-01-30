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

    AVAILABLE_CATEGORIES = [
        'businesses', 'price_list_items', 'contacts', 'invoices', 'jobs',
        'estimates', 'work_orders', 'est_worksheets', 'bills', 'purchase_orders'
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

    @staticmethod
    def apply_category_filter(categories, filter_category):
        """Apply category filter to results"""
        if filter_category and filter_category != 'all':
            # Normalize to lowercase to match category keys
            normalized_category = filter_category.lower()
            if normalized_category in categories:
                return {normalized_category: categories[normalized_category]}
            else:
                return {}
        return categories

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

    @staticmethod
    def build_result_ids_for_session(categories):
        """Build a dictionary of result IDs for session storage"""
        result_ids = {}

        for category_name, category_data in categories.items():
            # Handle dict with 'items' or 'grouped_items'
            if isinstance(category_data, dict):
                model_name = None
                items_list = None

                # Determine model name
                if category_name == 'jobs':
                    model_name = 'Job'
                elif category_name == 'contacts':
                    model_name = 'Contact'
                elif category_name == 'businesses':
                    model_name = 'Business'
                elif category_name == 'price_list_items':
                    model_name = 'PriceListItem'
                elif category_name == 'invoices':
                    model_name = 'Invoice'
                elif category_name == 'estimates':
                    model_name = 'Estimate'
                elif category_name == 'bills':
                    model_name = 'Bill'
                elif category_name == 'purchase_orders':
                    model_name = 'PurchaseOrder'

                # Get items from either 'grouped_items' or 'items'
                if 'grouped_items' in category_data:
                    items_list = category_data['grouped_items']
                elif 'items' in category_data:
                    items_list = category_data['items']

                if model_name and items_list:
                    result_ids[model_name] = [item.pk for item in items_list]

            # Handle flat lists (work_orders, est_worksheets)
            elif isinstance(category_data, list):
                if category_name == 'work_orders':
                    result_ids['WorkOrder'] = [item.pk for item in category_data]
                elif category_name == 'est_worksheets':
                    result_ids['EstWorksheet'] = [item.pk for item in category_data]

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
