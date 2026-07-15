import hmac
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
            # Constant-time comparison -- a plain `!=` leaks timing
            # information proportional to how many leading characters
            # matched, which is unnecessary risk for a few extra characters
            # of code.
            if not hmac.compare_digest(provided, self.access_key):
                return JsonResponse({"error": "Unauthorized"}, status=401)

        return self.get_response(request)


class MaxUploadSizeMiddleware:
    """
    Rejects requests whose declared body size exceeds MAX_UPLOAD_SIZE_BYTES
    before Django reads/buffers any of it, so a single oversized upload
    (accidental or adversarial) can't tie up web-process memory/disk. There's
    no reverse proxy in front of this app to enforce this at a lower layer,
    so it's done here instead.

    Relies on the client-supplied Content-Length header, which is a
    best-effort check (a malicious client could omit/lie about it), not a
    hard guarantee -- a real production deployment should also cap this at
    the reverse proxy / load balancer level.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.max_bytes = int(
            os.environ.get("MAX_UPLOAD_SIZE_MB", "200").strip() or "200"
        ) * 1024 * 1024

    def __call__(self, request):
        content_length = request.META.get("CONTENT_LENGTH")
        if content_length:
            try:
                if int(content_length) > self.max_bytes:
                    return JsonResponse(
                        {"error": "Uploaded file is too large."}, status=413
                    )
            except (TypeError, ValueError):
                pass

        return self.get_response(request)
