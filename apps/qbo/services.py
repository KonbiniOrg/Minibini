import datetime
from django.conf import settings
from django.utils import timezone
from apps.qbo.models import QBOConnection, QBOSyncLog


class QBOService:
    """
    Thin wrapper around python-quickbooks API calls.
    This class is the mock boundary — tests mock methods on this class
    rather than mocking python-quickbooks internals.
    """

    @staticmethod
    def get_active_connection():
        """Return the active QBO connection, or None."""
        return QBOConnection.objects.filter(is_active=True).first()

    @staticmethod
    def get_client():
        """
        Build and return an authenticated QuickBooks client.
        Refreshes the access token if expired.
        Returns None if no active connection.
        """
        conn = QBOService.get_active_connection()
        if not conn:
            return None

        from quickbooks import QuickBooks
        from intuitlib.client import AuthClient

        auth_client = AuthClient(
            client_id=settings.QBO_CLIENT_ID,
            client_secret=settings.QBO_CLIENT_SECRET,
            redirect_uri=settings.QBO_REDIRECT_URI,
            environment=settings.QBO_ENVIRONMENT,
            access_token=conn.access_token,
            refresh_token=conn.refresh_token,
        )

        if conn.is_access_token_expired:
            auth_client.refresh()
            now = timezone.now()
            conn.access_token = auth_client.access_token
            conn.refresh_token = auth_client.refresh_token
            conn.access_token_expires_at = now + datetime.timedelta(hours=1)
            conn.refresh_token_expires_at = now + datetime.timedelta(days=100)
            conn.save()

        return QuickBooks(
            auth_client=auth_client,
            refresh_token=conn.refresh_token,
            company_id=conn.realm_id,
        )

    @staticmethod
    def log_sync(entity_type, entity_id, qbo_entity_type, qbo_entity_id,
                 action, status, error_message=''):
        """Create a sync log entry."""
        return QBOSyncLog.objects.create(
            entity_type=entity_type,
            entity_id=entity_id,
            qbo_entity_type=qbo_entity_type,
            qbo_entity_id=qbo_entity_id,
            action=action,
            status=status,
            error_message=error_message,
        )


class QBODisplayNameService:
    """Generates QBO-compliant DisplayNames for customer/vendor records."""

    QBO_DISPLAY_NAME_MAX = 500

    @staticmethod
    def generate_display_name(business, role):
        """
        Generate a QBO DisplayName for a Business.

        Rules:
        - First QBO record for this business uses the plain business_name.
        - Second record gets a suffix: (Customer) or (Vendor).
        - role: 'customer' or 'vendor'
        """
        name = business.business_name
        other_role_field = (
            'qbo_vendor_id' if role == 'customer' else 'qbo_customer_id'
        )

        other_exists = bool(getattr(business, other_role_field, ''))

        if other_exists:
            suffix = f' ({role.capitalize()})'
            max_base = QBODisplayNameService.QBO_DISPLAY_NAME_MAX - len(suffix)
            name = name[:max_base] + suffix

        return name


class QBOCustomerSyncService:
    """Syncs Minibini Business records to QBO as Customers."""

    @staticmethod
    def push_customer(business):
        """
        Push a Business to QBO as a Customer.
        Returns the QBO Customer ID.
        Skips if already synced (qbo_customer_id is set).
        """
        if business.qbo_customer_id:
            return business.qbo_customer_id

        client = QBOService.get_client()
        if not client:
            raise ValueError('No active QBO connection')

        customer = QBOCustomerSyncService._build_customer(business)

        try:
            customer.save(qb=client)
            business.qbo_customer_id = str(customer.Id)
            business.save(update_fields=['qbo_customer_id'])

            QBOService.log_sync(
                entity_type='customer',
                entity_id=business.pk,
                qbo_entity_type='Customer',
                qbo_entity_id=str(customer.Id),
                action='create',
                status='success',
            )
            return str(customer.Id)

        except Exception as e:
            QBOService.log_sync(
                entity_type='customer',
                entity_id=business.pk,
                qbo_entity_type='Customer',
                qbo_entity_id='',
                action='create',
                status='failed',
                error_message=str(e),
            )
            raise

    @staticmethod
    def _build_customer(business):
        """Build a QBO Customer object from a Business."""
        from quickbooks.objects.customer import Customer

        customer = Customer()
        customer.CompanyName = business.business_name
        customer.DisplayName = QBODisplayNameService.generate_display_name(
            business, role='customer'
        )

        if business.business_phone:
            from quickbooks.objects.base import PhoneNumber
            customer.PrimaryPhone = PhoneNumber()
            customer.PrimaryPhone.FreeFormNumber = business.business_phone

        # Use default contact's email if available
        default_contact = business.default_contact
        if default_contact and default_contact.email:
            from quickbooks.objects.base import EmailAddress
            customer.PrimaryEmailAddr = EmailAddress()
            customer.PrimaryEmailAddr.Address = default_contact.email

        return customer
