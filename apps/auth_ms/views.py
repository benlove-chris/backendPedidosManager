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


class LoginView(APIView):
    def get(self, request):
        auth_url = build_auth_url(REDIRECT_URI)
        return redirect(auth_url)


class AuthCallbackView(APIView):
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

        request.session["access_token"] = token_data["access_token"]
        request.session["refresh_token"] = token_data.get("refresh_token", "")
        request.session["user_email"] = user_email
        request.session["user_name"] = user_name
        request.session.modified = True

        if user_email:
            try:
                salvar_token(
                    email=user_email,
                    access_token=token_data["access_token"],
                    refresh_token=token_data.get("refresh_token", ""),
                )
            except Exception as e:
                logger.warning(f"Não foi possível salvar token no banco: {e}")

        logger.info(f"Usuário autenticado e token salvo: {user_email}")

        # Redireciona com flag para o frontend processar fila automaticamente
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
