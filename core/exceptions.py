from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status
import logging

logger = logging.getLogger(__name__)


class MicrosoftAuthError(Exception):
    """Erro durante autenticação OAuth2 Microsoft."""
    pass


class OneDriveError(Exception):
    """Erro durante operações no OneDrive."""
    pass


class FileSizeExceededError(Exception):
    """Arquivo excede o tamanho máximo permitido."""
    pass


class InvalidFileTypeError(Exception):
    """Tipo de arquivo não permitido."""
    pass


def custom_exception_handler(exc, context):
    """Handler global de exceções para a API."""
    response = exception_handler(exc, context)

    if response is not None:
        response.data = {
            "success": False,
            "error": {
                "code": response.status_code,
                "message": _flatten_errors(response.data),
            }
        }
        return response

    # Exceções não tratadas pelo DRF
    if isinstance(exc, MicrosoftAuthError):
        logger.error(f"MicrosoftAuthError: {exc}")
        return Response(
            {"success": False, "error": {"code": 401, "message": str(exc)}},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    if isinstance(exc, OneDriveError):
        logger.error(f"OneDriveError: {exc}")
        return Response(
            {"success": False, "error": {"code": 502, "message": str(exc)}},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    if isinstance(exc, (FileSizeExceededError, InvalidFileTypeError)):
        return Response(
            {"success": False, "error": {"code": 400, "message": str(exc)}},
            status=status.HTTP_400_BAD_REQUEST,
        )

    logger.exception(f"Unhandled exception: {exc}")
    return Response(
        {"success": False, "error": {"code": 500, "message": "Erro interno no servidor."}},
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


def _flatten_errors(data):
    """Transforma erros aninhados do DRF em string legível."""
    if isinstance(data, list):
        return " | ".join(str(i) for i in data)
    if isinstance(data, dict):
        parts = []
        for key, value in data.items():
            if key == "detail":
                parts.append(str(value))
            else:
                parts.append(f"{key}: {_flatten_errors(value)}")
        return " | ".join(parts)
    return str(data)
