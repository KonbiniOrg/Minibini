"""QBO import endpoints: snapshot pull, per-area dismissal.

Area → permission mirrors each panel surface's own write permission:
categories/schemes are Settings surfaces (config), catalog is financials,
contacts is jobs.
"""
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.qbo.import_services import (
    QBOImportState, QBOImportSummary, QBOSnapshotService,
    QBOSuggestionService, QBOImportCommitService,
)
from apps.qbo.services import QBOService

AREA_PERMS = {
    'categories': 'core.can_manage_config',
    'schemes': 'core.can_manage_config',
    'catalog': 'core.can_manage_financials',
    'contacts': 'core.can_manage_jobs',
}


def _area_or_error(request):
    area = (request.data.get('area') or '').strip()
    if area not in QBOImportState.AREAS:
        return None, Response({'area': ['Unknown import area.']}, status=400)
    if not request.user.has_perm(AREA_PERMS[area]):
        return None, Response(status=403)
    return area, None


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def import_pull(request):
    area, error = _area_or_error(request)
    if error:
        return error
    client = QBOService.get_client()
    if not client:
        return Response({'detail': 'No active QBO connection.'}, status=400)
    snapshot = QBOSnapshotService.pull(client)
    QBOImportState.undismiss(area)  # local effect only — others stay sticky
    return Response({'fetched_at': snapshot['fetched_at'],
                     'summary': QBOImportSummary.diff_summary()})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def import_dismiss(request):
    area, error = _area_or_error(request)
    if error:
        return error
    QBOImportState.dismiss(area)
    return Response({'dismissed': area})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def import_suggestions(request, area):
    if area not in QBOImportState.AREAS:
        return Response({'area': ['Unknown import area.']}, status=400)
    if not request.user.has_perm(AREA_PERMS[area]):
        return Response(status=403)
    return Response(QBOSuggestionService.suggestions(area))


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def import_commit_categories(request):
    if not request.user.has_perm(AREA_PERMS['categories']):
        return Response(status=403)
    created = QBOImportCommitService.commit_categories(
        request.data.get('rows') or [])
    return Response({'created': len(created)})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def import_commit_schemes(request):
    if not request.user.has_perm(AREA_PERMS['schemes']):
        return Response(status=403)
    mapping = QBOImportCommitService.commit_schemes(
        request.data.get('rows') or [])
    return Response({'created': len(set(mapping.values())),
                     'scheme_pk_by_qbo_item_id': mapping})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def import_commit_catalog(request):
    if not request.user.has_perm(AREA_PERMS['catalog']):
        return Response(status=403)
    return Response(QBOImportCommitService.commit_catalog(
        request.data.get('rows') or []))


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def import_commit_contacts(request):
    if not request.user.has_perm(AREA_PERMS['contacts']):
        return Response(status=403)
    return Response(QBOImportCommitService.commit_contacts(request.data))
