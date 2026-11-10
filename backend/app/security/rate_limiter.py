"""Rate Limiting and Abuse Prevention Boundary (Requirement F3.1).

Implements sliding window rate limiting for sensitive/expensive endpoints:
- POST /resume/upload (Resource exhaustion defense)
- POST /identity/{session}/check (Biometric compute defense)
- POST /interview/{session}/audio (Speech model compute defense)
- POST /interview/{session}/answer (LLM reasoning compute defense)

Supports Redis with automatic in-memory fallback for high availability.
"""

from collections import defaultdict
import logging
from threading import Lock
import time
from typing import Callable, Dict, List, Optional, Tuple

from fastapi import HTTPException, Request, Response, status

from app.config import settings

logger = logging.getLogger("security.rate_limiter")


class RateLimiter:
    """Sliding-window rate limiter supporting both Redis and in-memory storage."""

    def __init__(self, redis_url: Optional[str] = None):
        self.redis_url = redis_url or getattr(settings, "redis_url", "")
        self._redis_client = None
        self._memory_store: Dict[str, List[float]] = defaultdict(list)
        self._lock = Lock()

        if self.redis_url:
            try:
                import redis
                self._redis_client = redis.from_url(
                    self.redis_url,
                    socket_connect_timeout=0.5,
                    decode_responses=True,
                )
                self._redis_client.ping()
                logger.info("RateLimiter connected to Redis at %s", self.redis_url)
            except Exception as e:
                logger.warning("RateLimiter Redis connection failed, falling back to memory: %s", e)
                self._redis_client = None

    def check(
        self,
        key: str,
        limit: int,
        window_seconds: int,
    ) -> Tuple[bool, int, int]:
        """Checks whether the request under `key` is allowed within `window_seconds`.

        Returns:
            (allowed: bool, remaining: int, retry_after_seconds: int)
        """
        now = time.time()
        window_start = now - window_seconds

        # 1. Try Redis sliding window via sorted set (ZSET)
        if self._redis_client:
            try:
                pipe = self._redis_client.pipeline()
                pipe.zremrangebyscore(key, 0, window_start)
                pipe.zcard(key)
                pipe.zadd(key, {str(now): now})
                pipe.expire(key, window_seconds + 5)
                results = pipe.execute()

                current_count = results[1]
                if current_count >= limit:
                    # Remove the newly added request since it was blocked
                    self._redis_client.zrem(key, str(now))
                    return False, 0, int(window_seconds)

                remaining = max(0, limit - current_count - 1)
                return True, remaining, 0
            except Exception as e:
                logger.warning("Redis rate limit operation failed, falling back to in-memory: %s", e)
                # Fall through to memory store

        # 2. In-memory sliding window fallback
        with self._lock:
            timestamps = self._memory_store[key]
            # Prune old timestamps
            self._memory_store[key] = [t for t in timestamps if t > window_start]
            active_requests = self._memory_store[key]

            if len(active_requests) >= limit:
                oldest_in_window = active_requests[0]
                retry_after = max(1, int(oldest_in_window + window_seconds - now))
                return False, 0, retry_after

            # Record this request
            active_requests.append(now)
            remaining = max(0, limit - len(active_requests))
            return True, remaining, 0

    def reset(self, key_prefix: Optional[str] = None) -> None:
        """Clears rate limit state (used in test suites)."""
        with self._lock:
            if key_prefix:
                keys_to_del = [k for k in self._memory_store if k.startswith(key_prefix)]
                for k in keys_to_del:
                    del self._memory_store[k]
            else:
                self._memory_store.clear()

        if self._redis_client:
            try:
                if key_prefix:
                    keys = self._redis_client.keys(f"{key_prefix}*")
                    if keys:
                        self._redis_client.delete(*keys)
                else:
                    self._redis_client.flushdb()
            except Exception:
                pass


# Global singleton instance
rate_limiter_instance = RateLimiter()


def rate_limit(
    limit: int = 60,
    window_seconds: int = 60,
    key_prefix: str = "general",
) -> Callable:
    """FastAPI dependency enforcing sliding-window rate limits per IP or authenticated user."""

    async def dependency(request: Request, response: Response):
        # Prefer authenticated user ID if present; fallback to client IP
        auth_header = request.headers.get("Authorization", "")
        client_ip = request.client.host if request.client else "unknown_ip"
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            client_ip = forwarded_for.split(",")[0].strip()

        identifier = client_ip
        if auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()
            try:
                from app.core.security import decode_access_token
                claims = decode_access_token(token)
                sub = claims.get("sub")
                if sub:
                    identifier = f"user_{sub}"
            except Exception:
                pass

        rate_key = f"ratelimit:{key_prefix}:{identifier}"
        allowed, remaining, retry_after = rate_limiter_instance.check(
            rate_key,
            limit=limit,
            window_seconds=window_seconds,
        )

        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Too Many Requests: Rate limit exceeded for {key_prefix}. Try again in {retry_after}s.",
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                },
            )

        # Inject standard rate limit headers
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)

    return dependency
