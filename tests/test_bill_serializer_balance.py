from decimal import Decimal
from django.test import TestCase
from django.utils import timezone
from apps.contacts.models import Business, Contact
from apps.core.models import AccountingCategory
from apps.purchasing.models import Bill, BillLineItem, BillPayment
from apps.api.purchasing.serializers import BillSerializer


class BillSerializerBalanceTest(TestCase):
    def test_exact_balance_after_partial_payment(self):
        contact = Contact.objects.create(first_name='Acme', last_name='Co', email='a@acme.com')
        b = Business.objects.create(business_name='Acme', default_contact=contact)
        ac = AccountingCategory.objects.create(code='MAT', name='Materials')
        bill = Bill.objects.create(business=b, vendor_invoice_number='INV-1',
                                   status=Bill.STATUS_RECEIVED)
        BillLineItem.objects.create(bill=bill, line_number=1, description='x',
                                    qty=Decimal('1'), price=Decimal('100.00'),
                                    units='none', accounting_category=ac)
        BillPayment.objects.create(bill=bill, amount=Decimal('30.00'),
                                   payment_date=timezone.now(),
                                   method=BillPayment.METHOD_CHECK)
        data = BillSerializer(bill).data
        self.assertEqual(data['amount_paid'], '30.00')
        self.assertEqual(data['balance'], '70.00')
        self.assertEqual(len(data['payments']), 1)

    def test_no_fan_out_with_multiple_line_items_and_payments(self):
        """Regression: summary-mode annotations must not multiply rows when a bill
        has both multiple line items AND multiple payments (fan-out join)."""
        contact = Contact.objects.create(first_name='Bob', last_name='Ltd', email='b@bob.com')
        b = Business.objects.create(business_name='Bob Ltd', default_contact=contact)
        ac = AccountingCategory.objects.create(code='SUP', name='Supplies')
        bill = Bill.objects.create(business=b, vendor_invoice_number='INV-2',
                                   status=Bill.STATUS_RECEIVED)
        # 2 line items: total = 50 + 75 = 125
        BillLineItem.objects.create(bill=bill, line_number=1, description='item1',
                                    qty=Decimal('1'), price=Decimal('50.00'),
                                    units='none', accounting_category=ac)
        BillLineItem.objects.create(bill=bill, line_number=2, description='item2',
                                    qty=Decimal('1'), price=Decimal('75.00'),
                                    units='none', accounting_category=ac)
        # 2 payments: paid = 20 + 30 = 50
        BillPayment.objects.create(bill=bill, amount=Decimal('20.00'),
                                   payment_date=timezone.now(),
                                   method=BillPayment.METHOD_CHECK)
        BillPayment.objects.create(bill=bill, amount=Decimal('30.00'),
                                   payment_date=timezone.now(),
                                   method=BillPayment.METHOD_CHECK)

        # Test detail serializer: no fan-out, balance should be 75 (125 - 50)
        data = BillSerializer(bill).data
        self.assertEqual(data['amount_paid'], '50.00')
        self.assertEqual(data['balance'], '75.00')
        self.assertEqual(len(data['payments']), 2)

        # Test summary-mode annotations used by BillViewSet.get_queryset.
        # Mirror the subquery approach from the view (subquery for paid_anno to
        # avoid fan-out from two simultaneous reverse-relation aggregations).
        from django.db.models import (
            F, Sum, Value, ExpressionWrapper, DecimalField, OuterRef, Subquery,
        )
        from django.db.models.functions import Coalesce
        from apps.purchasing.models import Bill as BillModel

        _MONEY = DecimalField(max_digits=12, decimal_places=2)
        paid_subquery = Coalesce(
            Subquery(
                BillPayment.objects.filter(bill=OuterRef('pk'))
                .values('bill')
                .annotate(s=Sum('amount'))
                .values('s')[:1],
                output_field=_MONEY,
            ),
            Value(0), output_field=_MONEY,
        )
        qs = BillModel.objects.filter(pk=bill.pk).annotate(
            total_anno=Coalesce(
                Sum(ExpressionWrapper(
                    F('billlineitem__qty') * F('billlineitem__price'),
                    output_field=_MONEY)),
                Value(0), output_field=_MONEY),
            paid_anno=paid_subquery,
        ).annotate(
            balance_anno=ExpressionWrapper(
                F('total_anno') - F('paid_anno'), output_field=_MONEY),
        )
        row = qs.first()
        self.assertEqual(row.total_anno, Decimal('125.00'),
                         f"Fan-out detected: total_anno={row.total_anno}, expected 125.00")
        self.assertEqual(row.paid_anno, Decimal('50.00'),
                         f"Fan-out detected: paid_anno={row.paid_anno}, expected 50.00")
        self.assertEqual(row.balance_anno, Decimal('75.00'),
                         f"Fan-out detected: balance_anno={row.balance_anno}, expected 75.00")
