from django.http import JsonResponse


EXEMPT_PATHS = [
    "/login/",
    "/auth/callback/",
    "/admin/",
]


class SessionAuthMiddleware:
    """
    Middleware que protege todos os endpoints da API,
    exigindo access_token na sessão.
    Rotas em EXEMPT_PATHS são liberadas.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if self._is_exempt(request.path):
            return self.get_response(request)

        if request.path.startswith("/api/") and not request.session.get("access_token"):
            return JsonResponse(
                {
                    "success": False,
                    "error": {
                        "code": 401,
                        "message": "Não autenticado. Faça login via /login/",
                    },
                },
                status=401,
            )

        return self.get_response(request)

    def _is_exempt(self, path):
        return any(path.startswith(exempt) for exempt in EXEMPT_PATHS)
