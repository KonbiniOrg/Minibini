from rest_framework.routers import DefaultRouter
from .views import ReimbursementViewSet

router = DefaultRouter()
router.register(r'', ReimbursementViewSet, basename='reimbursement')

urlpatterns = router.urls
