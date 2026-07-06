"""
Shared slowapi Limiter instance.

Lives in its own module (rather than main.py) so routers can import it to decorate
rate-limited endpoints without creating a circular import with main.py, which itself
imports the routers.
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
