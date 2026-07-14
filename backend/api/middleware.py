import os

from django.http import JsonResponse


class RequireAccessKeyMiddleware:
    """
    Gates every request behind a shared secret (APP_ACCESS_KEY) so a publicly
    reachable deployment is only usable by whoever you hand the key to,
    without building out full user accounts/auth.

    - No-ops entirely if APP_ACCESS_KEY isn't set (e.g. local development).
    - /admin/ is exempt since Django's own login already gates it.
    - Everything else (the API) must send `X-Access-Key: <the shared secret>`.

    This is a stopgap for sharing a demo with one or two people, not a
    replacement for real authentication/authorization.
    """

    EXEMPT_PREFIXES = ("/admin",)

    def __init__(self, get_response):
        self.get_response = get_response
        self.access_key = os.environ.get("APP_ACCESS_KEY", "").strip()

    def __call__(self, request):
        if self.access_key and not request.path.startswith(self.EXEMPT_PREFIXES):
            provided = request.headers.get("X-Access-Key", "")
            if provided != self.access_key:
                return JsonResponse({"error": "Unauthorized"}, status=401)

        return self.get_response(request)
