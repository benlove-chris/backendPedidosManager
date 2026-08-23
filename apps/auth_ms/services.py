import requests
import logging
from django.conf import settings
from core.exceptions import MicrosoftAuthError

logger = logging.getLogger(__name__)

AUTHORITY = f"https://login.microsoftonline.com/{settings.MS_TENANT}"
SCOPES = ["User.Read", "Files.ReadWrite", "offline_access"]
REDIRECT_URI = f"{settings.BACKEND_URL}/auth/callback/"


# ─── OAuth2 ───────────────────────────────────────────────────────────────────

def build_auth_url(redirect_uri: str) -> str:
    params = {
        "client_id": settings.MS_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "response_mode": "query",
        "scope": " ".join(SCOPES),
    }
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return f"{AUTHORITY}/oauth2/v2.0/authorize?{query}"


def exchange_code_for_token(code: str, redirect_uri: str) -> dict:
    url = f"{AUTHORITY}/oauth2/v2.0/token"
    payload = {
        "client_id": settings.MS_CLIENT_ID,
        "client_secret": settings.MS_CLIENT_SECRET,
        "code": code,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
        "scope": " ".join(SCOPES),
    }
    try:
        response = requests.post(url, data=payload, timeout=10)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as e:
        raise MicrosoftAuthError(f"Falha ao trocar código por token: {e}")

    if "access_token" not in data:
        raise MicrosoftAuthError(f"Token não retornado: {data.get('error_description', data)}")

    logger.info("Token Microsoft obtido com sucesso.")
    return data


def refresh_access_token(refresh_token: str, redirect_uri: str) -> dict:
    url = f"{AUTHORITY}/oauth2/v2.0/token"
    payload = {
        "client_id": settings.MS_CLIENT_ID,
        "client_secret": settings.MS_CLIENT_SECRET,
        "refresh_token": refresh_token,
        "redirect_uri": redirect_uri,
        "grant_type": "refresh_token",
        "scope": " ".join(SCOPES),
    }
    try:
        response = requests.post(url, data=payload, timeout=10)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as e:
        raise MicrosoftAuthError(f"Falha ao renovar token: {e}")

    if "access_token" not in data:
        raise MicrosoftAuthError("Refresh token inválido ou expirado. Faça login novamente.")

    logger.info("Access token renovado com sucesso.")
    return data


def get_ms_user_info(access_token: str) -> dict:
    try:
        response = requests.get(
            "https://graph.microsoft.com/v1.0/me",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        raise MicrosoftAuthError(f"Falha ao obter dados do usuário: {e}")


# ─── Token Utils ──────────────────────────────────────────────────────────────

def _token_valido(access_token: str) -> bool:
    try:
        r = requests.get(
            "https://graph.microsoft.com/v1.0/me",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=5,
        )
        return r.status_code == 200
    except requests.RequestException:
        return False


def salvar_token(email: str, access_token: str, refresh_token: str) -> None:
    """Salva ou atualiza o token no banco."""
    from apps.pedidos.models import MicrosoftToken

    MicrosoftToken.objects.update_or_create(
        user_email=email,
        defaults={
            "access_token": access_token,
            "refresh_token": refresh_token,
        }
    )
    logger.info(f"Token salvo no banco para {email}")


def get_valid_token(request) -> str:
    """
    Retorna sempre um access_token válido.
    1. Tenta o da sessão
    2. Tenta o do banco
    3. Renova via refresh_token
    """
    from apps.pedidos.models import MicrosoftToken

    email = request.session.get("user_email")

    # 1. Tenta token da sessão
    access_token = request.session.get("access_token")
    if access_token and _token_valido(access_token):
        return access_token

    # 2. Busca no banco pelo email
    registro = None
    if email:
        registro = MicrosoftToken.objects.filter(user_email=email).first()

    if not registro:
        raise MicrosoftAuthError("Sessão expirada. Faça login novamente.")

    # 3. Testa o token salvo no banco
    if _token_valido(registro.access_token):
        request.session["access_token"] = registro.access_token
        request.session["refresh_token"] = registro.refresh_token
        request.session.modified = True
        return registro.access_token

    # 4. Renova via refresh_token
    try:
        token_data = refresh_access_token(registro.refresh_token, REDIRECT_URI)
        novo_access = token_data["access_token"]
        novo_refresh = token_data.get("refresh_token", registro.refresh_token)

        request.session["access_token"] = novo_access
        request.session["refresh_token"] = novo_refresh
        request.session.modified = True

        registro.access_token = novo_access
        registro.refresh_token = novo_refresh
        registro.save()

        logger.info(f"Token renovado automaticamente para {email}")
        return novo_access

    except Exception as e:
        logger.error(f"Falha ao renovar token para {email}: {e}")
        raise MicrosoftAuthError("Não foi possível renovar o token. Faça login novamente.")
