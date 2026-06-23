from django.db import models
from django.utils import timezone


class QBOConnection(models.Model):
    """
    Stores OAuth tokens and connection state for QuickBooks Online.
    Singleton per Minibini instance — only one active QBO connection at a time.
    """
    realm_id = models.CharField(max_length=50)
    access_token = models.TextField()
    refresh_token = models.TextField()
    access_token_expires_at = models.DateTimeField()
    refresh_token_expires_at = models.DateTimeField()
    is_active = models.BooleanField(default=True)
    connected_at = models.DateTimeField()
    last_sync_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'qbo_connection'

    def __str__(self):
        status = 'active' if self.is_active else 'inactive'
        return f"QBO Connection {self.realm_id} ({status})"

    @property
    def is_access_token_expired(self):
        return timezone.now() >= self.access_token_expires_at

    @property
    def is_refresh_token_expiring_soon(self):
        """True if refresh token expires within 7 days."""
        return timezone.now() >= self.refresh_token_expires_at - timezone.timedelta(days=7)


class QBOSyncLog(models.Model):
    """Audit trail for all QBO sync operations."""
    entity_type = models.CharField(max_length=50)
    entity_id = models.IntegerField()
    qbo_entity_type = models.CharField(max_length=50)
    qbo_entity_id = models.CharField(max_length=50, blank=True)
    action = models.CharField(max_length=20)
    status = models.CharField(max_length=20)
    error_message = models.TextField(blank=True)
    synced_at = models.DateTimeField(auto_now_add=True)
    triggered_by = models.ForeignKey(
        'core.User', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
    )

    class Meta:
        db_table = 'qbo_sync_log'
        ordering = ['-synced_at']

    def __str__(self):
        return f"{self.action} {self.entity_type}:{self.entity_id} → {self.qbo_entity_type} ({self.status})"
