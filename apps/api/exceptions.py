"""The API's central exception renderer — the error-response contract.

Two error shapes, nothing else (see architecture-and-conventions.md §Error
responses):

- Operation errors:  {'detail': '<sentence>'} + the right status code.
- Field validation:  {'<field>': ['msg', ...]} (DRF serializer shape).

Views should NOT catch a service DjangoValidationError just to re-render it
as JSON — raising it (or not catching it) lands here and renders a 400 in
the contract shape. Catch it only to change the status code or add payload
(e.g. the rate-scheme 409 with supersede_url).
"""
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models.deletion import ProtectedError
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler


def api_exception_handler(exc, context):
    # DRF's own exceptions (serializer ValidationError, PermissionDenied,
    # NotFound, Throttled, ...) already render in contract shapes.
    response = drf_exception_handler(exc, context)
    if response is not None:
        return response

    if isinstance(exc, DjangoValidationError):
        if hasattr(exc, 'message_dict'):
            # Field-keyed service/model error → DRF field shape. Django's
            # cross-field bucket is '__all__'; DRF's is 'non_field_errors'.
            data = {
                ('non_field_errors' if field == '__all__' else field): msgs
                for field, msgs in exc.message_dict.items()
            }
            return Response(data, status=status.HTTP_400_BAD_REQUEST)
        return Response({'detail': ' '.join(exc.messages)},
                        status=status.HTTP_400_BAD_REQUEST)

    if isinstance(exc, ProtectedError):
        return Response(
            {'detail': 'This record is referenced by other records and '
                       'cannot be deleted.'},
            status=status.HTTP_409_CONFLICT)

    # Anything else is a programming error — let it 500 loudly.
    return None
