import logging
from django.shortcuts import redirect
from django.conf import settings
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .services import build_auth_url, exchange_code_for_token, get_ms_user_info, salvar_token
from core.exceptions import MicrosoftAuthError

logger = logging.getLogger(__name__)
REDIRECT_URI = f"{settings.BACKEND_URL}/auth/callback/"

# Scheme do app nativo Capacitor
APP_SCHEME = "com.gestorpedidos.app"


def _is_native_app(request) -> bool:
    """
    Detecta se a requisição veio do app nativo (Capacitor WebView).
    O WebView do Android inclui 'wv' no User-Agent.
    Também aceita o parâmetro ?platform=android para casos onde
    o login é iniciado pelo app mas o User-Agent muda no browser externo.
    """
    user_agent = request.META.get("HTTP_USER_AGENT", "").lower()
    platform_param = request.GET.get("platform", "")
    session_platform = request.session.get("login_platform", "")

    return (
        "wv" in user_agent or
        "webview" in user_agent or
        platform_param == "android" or
        session_platform == "android"
    )


class LoginView(APIView):
    """Inicia o fluxo OAuth2 — redireciona para a Microsoft."""

    def get(self, request):
        # Salva a plataforma na sessão para usar no callback
        platform = request.GET.get("platform", "")
        if platform:
            request.session["login_platform"] = platform
            request.session.modified = True

        auth_url = build_auth_url(REDIRECT_URI)
        return redirect(auth_url)


class AuthCallbackView(APIView):
    """
    Recebe o authorization code da Microsoft,
    troca por tokens, salva na sessão e no banco.
    Redireciona para o app nativo via deep link ou para o frontend web.
    """

    def get(self, request):
        code = request.query_params.get("code")
        error = request.query_params.get("error")

        if error:
            logger.warning(f"OAuth2 erro retornado pela Microsoft: {error}")
            return Response(
                {"success": False, "error": {"code": 401, "message": f"Erro Microsoft: {error}"}},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        if not code:
            return Response(
                {"success": False, "error": {"code": 400, "message": "Parâmetro 'code' ausente."}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            token_data = exchange_code_for_token(code, REDIRECT_URI)
        except MicrosoftAuthError as e:
            return Response(
                {"success": False, "error": {"code": 401, "message": str(e)}},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        try:
            user_info = get_ms_user_info(token_data["access_token"])
            user_email = user_info.get("mail") or user_info.get("userPrincipalName", "")
            user_name = user_info.get("displayName", "")
        except MicrosoftAuthError:
            logger.warning("Não foi possível obter dados do usuário, mas login prosseguiu.")
            user_email = ""
            user_name = ""

        # Salva na sessão
        request.session["access_token"] = token_data["access_token"]
        request.session["refresh_token"] = token_data.get("refresh_token", "")
        request.session["user_email"] = user_email
        request.session["user_name"] = user_name
        request.session.modified = True

        # Persiste no banco
        if user_email:
            try:
                salvar_token(
                    email=user_email,
                    access_token=token_data["access_token"],
                    refresh_token=token_data.get("refresh_token", ""),
                )
            except Exception as e:
                logger.warning(f"Não foi possível salvar token no banco: {e}")

        logger.info(f"Usuário autenticado: {user_email}")

        # ── Redireciona para o destino correto ───────────────────────────────
        is_native = _is_native_app(request)

        # Limpa plataforma da sessão
        request.session.pop("login_platform", None)

        if is_native:
            # Deep link — abre o app nativo diretamente
            logger.info(f"Redirecionando para app nativo: {APP_SCHEME}://callback")
            return redirect(f"{APP_SCHEME}://callback?login=success&email={user_email}")
        else:
            # Web normal
            return redirect(f"{settings.FRONTEND_URL}?retornou_do_login=true")


class LogoutView(APIView):
    def post(self, request):
        request.session.flush()
        return Response({"success": True, "message": "Sessão encerrada."})


class MeView(APIView):
    def get(self, request):
        if not request.session.get("access_token"):
            return Response(
                {"success": False, "error": {"code": 401, "message": "Não autenticado."}},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        return Response({
            "success": True,
            "data": {
                "name": request.session.get("user_name"),
                "email": request.session.get("user_email"),
            }
        })
