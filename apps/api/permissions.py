from rest_framework.permissions import IsAuthenticated

# For now, all API views require authentication only.
# Permission atoms (CanManageJobs, etc.) will be added in a later task.
APIDefaultPermission = IsAuthenticated
