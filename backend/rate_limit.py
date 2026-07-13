"""
Shared slowapi Limiter instance.

Lives in its own module (rather than main.py) so routers can import it to decorate
rate-limited endpoints without creating a circular import with main.py, which itself
imports the routers.
"""
from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address


def get_client_ip(request: Request) -> str:
    """Real client IP behind Cloudflare Tunnel. The app binds to 127.0.0.1 and only
    cloudflared connects to it locally, so request.client.host is always the tunnel
    daemon itself — every request would otherwise share one rate-limit bucket.
    CF-Connecting-IP is set by Cloudflare's edge and can't be spoofed by the client
    through the tunnel, so it's trusted directly; falls back to get_remote_address
    for local/direct access (e.g. dev without cloudflared in front)."""
    return request.headers.get("CF-Connecting-IP") or get_remote_address(request)


limiter = Limiter(key_func=get_client_ip)
