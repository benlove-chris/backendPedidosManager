import requests
import logging
from datetime import timedelta
from django.conf import settings
from django.utils import timezone
from core.exceptions import MicrosoftAuthError

logger = logging.getLogger(__name__)

AUTHORITY = f"https://login.microsoftonline.com/{settings.MS_TENANT}"
SCOPES = ["User.Read", "Files.ReadWrite", "offline_access"]


# ─── OAuth2 ───────────────────────────────────────────────────────────────────

def build_auth_url(redirect_uri: str) -> str:
    """Monta a URL de autorização OAuth2 da Microsoft."""
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
    """
    Troca o authorization code por access_token + refresh_token.
    Retorna o dict completo de tokens.
    """
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
    """
    Usa o refresh_token para obter um novo access_token.
    Retorna o dict completo de tokens.
    """
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
    """Retorna informações básicas do usuário autenticado."""
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        response = requests.get(
            "https://graph.microsoft.com/v1.0/me",
            headers=headers,
            timeout=10,
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        raise MicrosoftAuthError(f"Falha ao obter dados do usuário: {e}")


# ─── Persistência de token no banco ──────────────────────────────────────────

def save_token_to_db(user_email: str, token_data: dict) -> None:
    """
    Salva ou atualiza os tokens no banco de dados (MicrosoftToken).
    Calcula expires_at com base em expires_in (segundos).
    """
    from apps.pedidos.models import MicrosoftToken

    expires_in = token_data.get("expires_in", 3600)
    expires_at = timezone.now() + timedelta(seconds=int(expires_in) - 60)  # 60s de margem

    MicrosoftToken.objects.update_or_create(
        user_email=user_email,
        defaults={
            "access_token": token_data["access_token"],
            "refresh_token": token_data.get("refresh_token", ""),
            "expires_at": expires_at,
        },
    )
    logger.info(f"Token salvo no banco para {user_email}, expira em {expires_at:%H:%M:%S}.")


def get_valid_token(request) -> str:
    """
    Retorna um access_token sempre válido.

    Estratégia em camadas:
    1. Busca o token no banco pelo email da sessão
    2. Se não expirou, retorna direto (sem chamada de rede extra)
    3. Se expirou, renova via refresh_token automaticamente
    4. Salva o novo token no banco e na sessão
    5. Nunca exige novo login enquanto o refresh_token for válido
       (refresh tokens da Microsoft duram até 90 dias com uso regular)
    """
    from apps.pedidos.models import MicrosoftToken

    user_email = request.session.get("user_email")
    redirect_uri = f"{settings.BACKEND_URL}/auth/callback/"

    # ── Tenta buscar do banco pelo email ──────────────────────────────────────
    if user_email:
        try:
            record = MicrosoftToken.objects.get(user_email=user_email)

            if not record.is_expired():
                # Token ainda válido — retorna sem chamada de rede
                logger.debug(f"Token do banco válido para {user_email}.")
                return record.access_token

            # Token expirado — renova via refresh_token do banco
            if record.refresh_token:
                logger.info(f"Token expirado para {user_email} — renovando via banco...")
                token_data = refresh_access_token(record.refresh_token, redirect_uri)
                save_token_to_db(user_email, token_data)
                # Atualiza sessão também
                request.session["access_token"] = token_data["access_token"]
                if token_data.get("refresh_token"):
                    request.session["refresh_token"] = token_data["refresh_token"]
                request.session.modified = True
                return token_data["access_token"]

        except MicrosoftToken.DoesNotExist:
            pass  # não tem no banco, tenta pela sessão

    # ── Fallback: tenta pela sessão ───────────────────────────────────────────
    access_token = request.session.get("access_token")
    refresh_token = request.session.get("refresh_token")

    if not access_token and not refresh_token:
        raise MicrosoftAuthError("Sessão não encontrada. Faça login.")

    # Testa se o access_token da sessão ainda é válido
    if access_token:
        try:
            test = requests.get(
                "https://graph.microsoft.com/v1.0/me",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=5,
            )
            if test.status_code != 401:
                return access_token
        except requests.RequestException:
            pass

    # Token da sessão expirado — renova via refresh_token da sessão
    if not refresh_token:
        raise MicrosoftAuthError("Token expirado. Faça login novamente.")

    logger.info("Renovando token via refresh_token da sessão...")
    token_data = refresh_access_token(refresh_token, redirect_uri)

    # Salva na sessão
    request.session["access_token"] = token_data["access_token"]
    if token_data.get("refresh_token"):
        request.session["refresh_token"] = token_data["refresh_token"]
    request.session.modified = True

    # Salva no banco se souber o email
    if user_email:
        save_token_to_db(user_email, token_data)

    return token_data["access_token"]
