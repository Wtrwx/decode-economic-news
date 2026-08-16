#!/usr/bin/env python3
"""Shared provenance, caching and HTTP helpers for evidence collectors."""

from __future__ import annotations

import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SENSITIVE_QUERY_PARTS = ("key", "token", "secret", "auth", "password")
HOST_LOCK = threading.Lock()
HOST_LAST_CALL: dict[str, float] = {}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    temp.write_bytes(payload)
    temp.replace(path)


def atomic_write_json(path: Path, data: Any) -> None:
    atomic_write_bytes(path, (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def safe_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    safe_query: list[tuple[str, str]] = []
    for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True):
        if any(part in key.lower() for part in SENSITIVE_QUERY_PARTS):
            value = "REDACTED"
        safe_query.append((key, value))
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(safe_query), parsed.fragment)
    )


def safe_proxy_url(proxy_url: str) -> str:
    """Return a proxy descriptor with any user information removed."""
    parsed = urllib.parse.urlsplit(proxy_url)
    host = parsed.hostname or ""
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    port = f":{parsed.port}" if parsed.port else ""
    userinfo = "REDACTED@" if parsed.username is not None or parsed.password is not None else ""
    return urllib.parse.urlunsplit((parsed.scheme, f"{userinfo}{host}{port}", parsed.path, "", ""))


def normalized_identifier(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip())
    return value.strip("-") or "item"


def clamp(value: float, lower: float = 0.0, upper: float = 100.0) -> float:
    return max(lower, min(upper, value))


def _cache_paths(cache_dir: Path, url: str) -> tuple[Path, Path]:
    key = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return cache_dir / f"{key}.body", cache_dir / f"{key}.meta.json"


@dataclass
class FetchResult:
    body: bytes
    source_url: str
    retrieved_at: str
    raw_sha256: str
    status: str
    http_status: int | None
    content_type: str
    warning: str = ""

    def metadata(self) -> dict[str, Any]:
        data = {
            "status": self.status,
            "retrieved_at": self.retrieved_at,
            "source_url": self.source_url,
            "raw_sha256": self.raw_sha256,
            "http_status": self.http_status,
            "content_type": self.content_type,
        }
        if self.warning:
            data["warning"] = self.warning
        return data


class ProxyHttpError(RuntimeError):
    def __init__(self, code: int) -> None:
        self.code = code
        super().__init__(f"HTTP status {code} through configured proxy")


class CachedHttpClient:
    def __init__(
        self,
        cache_dir: Path | None = None,
        *,
        timeout: float = 20.0,
        retries: int = 3,
        user_agent: str = "decode-economic-news/1.0 (+reproducible research)",
        default_min_interval: float = 0.2,
    ) -> None:
        self.cache_dir = (cache_dir or Path(".cache/economic-news")).resolve()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        self.retries = max(1, retries)
        self.user_agent = user_agent
        self.default_min_interval = max(0.0, default_min_interval)

    def _pace(self, host: str, interval: float) -> None:
        with HOST_LOCK:
            wait = interval - (time.monotonic() - HOST_LAST_CALL.get(host, 0.0))
            if wait > 0:
                time.sleep(wait + random.uniform(0.02, min(0.20, interval / 4 + 0.02)))
            HOST_LAST_CALL[host] = time.monotonic()

    @staticmethod
    def _curl_config_value(value: str) -> str:
        if "\n" in value or "\r" in value:
            raise ValueError("curl configuration values must not contain newlines")
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'

    def _curl_proxy_fetch(
        self,
        url: str,
        *,
        proxy_url: str,
        headers: dict[str, str],
    ) -> tuple[bytes, int, str]:
        curl = shutil.which("curl")
        if not curl:
            raise RuntimeError("curl is required for SOCKS/HTTP proxy transport")
        config_lines = [f"proxy = {self._curl_config_value(proxy_url)}"]
        for key, value in headers.items():
            config_lines.append(f"header = {self._curl_config_value(f'{key}: {value}')}")
        marker = b"\n__DECODE_ECONOMIC_NEWS_HTTP_META__"
        command = [
            curl,
            "--silent",
            "--show-error",
            "--location",
            "--max-time",
            str(max(1, int(self.timeout))),
            "--write-out",
            marker.decode("ascii") + "%{http_code}\t%{content_type}",
            "--config",
            "-",
            "--url",
            url,
        ]
        completed = subprocess.run(
            command,
            input=("\n".join(config_lines) + "\n").encode("utf-8"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=self.timeout + 5,
            check=False,
        )
        if completed.returncode != 0:
            stderr = completed.stderr.decode("utf-8", errors="replace").strip()
            stderr = stderr.replace(proxy_url, "[REDACTED_PROXY]")
            raise RuntimeError(f"proxy transport failed with curl exit {completed.returncode}: {stderr[:500]}")
        if marker not in completed.stdout:
            raise RuntimeError("proxy transport returned no HTTP metadata")
        body, raw_meta = completed.stdout.rsplit(marker, 1)
        status_text, _, content_type = raw_meta.decode("utf-8", errors="replace").partition("\t")
        try:
            status_code = int(status_text)
        except ValueError as exc:
            raise RuntimeError("proxy transport returned an invalid HTTP status") from exc
        if status_code >= 400:
            raise ProxyHttpError(status_code)
        if not body:
            raise RuntimeError("empty HTTP response")
        return body, status_code, content_type.strip()

    def get(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        ttl_seconds: float = 0,
        min_interval_seconds: float | None = None,
        allow_stale: bool = True,
        proxy_url: str | None = None,
    ) -> FetchResult:
        if proxy_url:
            proxy_scheme = urllib.parse.urlsplit(proxy_url).scheme.lower()
            if proxy_scheme not in ("http", "https", "socks5", "socks5h"):
                raise ValueError(f"unsupported proxy scheme: {proxy_scheme or '<missing>'}")
        body_path, meta_path = _cache_paths(self.cache_dir, url)
        cached_meta: dict[str, Any] = {}
        if body_path.exists() and meta_path.exists():
            try:
                cached_meta = load_json(meta_path)
                age = time.time() - float(cached_meta["epoch"])
                if ttl_seconds > 0 and age <= ttl_seconds:
                    body = body_path.read_bytes()
                    return FetchResult(
                        body=body,
                        source_url=str(cached_meta.get("source_url") or safe_url(url)),
                        retrieved_at=str(cached_meta["retrieved_at"]),
                        raw_sha256=sha256_bytes(body),
                        status="cached",
                        http_status=cached_meta.get("http_status"),
                        content_type=str(cached_meta.get("content_type") or ""),
                    )
            except (OSError, ValueError, KeyError, TypeError):
                cached_meta = {}

        parsed = urllib.parse.urlsplit(url)
        interval = self.default_min_interval if min_interval_seconds is None else min_interval_seconds
        request_headers = {"User-Agent": self.user_agent, "Accept": "*/*"}
        request_headers.update(headers or {})
        last_error: Exception | None = None
        for attempt in range(1, self.retries + 1):
            self._pace(parsed.netloc, max(0.0, interval))
            try:
                if proxy_url:
                    body, status_code, content_type = self._curl_proxy_fetch(
                        url,
                        proxy_url=proxy_url,
                        headers=request_headers,
                    )
                else:
                    request = urllib.request.Request(url, headers=request_headers, method="GET")
                    with urllib.request.urlopen(request, timeout=self.timeout) as response:
                        body = response.read()
                        if not body:
                            raise RuntimeError("empty HTTP response")
                        status_code = int(getattr(response, "status", 200))
                        content_type = str(response.headers.get("Content-Type", ""))
                retrieved_at = utc_now()
                atomic_write_bytes(body_path, body)
                atomic_write_json(
                    meta_path,
                    {
                        "epoch": time.time(),
                        "retrieved_at": retrieved_at,
                        "source_url": safe_url(url),
                        "http_status": status_code,
                        "content_type": content_type,
                        "raw_sha256": sha256_bytes(body),
                    },
                )
                return FetchResult(
                    body=body,
                    source_url=safe_url(url),
                    retrieved_at=retrieved_at,
                    raw_sha256=sha256_bytes(body),
                    status="fresh",
                    http_status=status_code,
                    content_type=content_type,
                )
            except urllib.error.HTTPError as exc:
                last_error = exc
                if exc.code not in (408, 429, 500, 502, 503, 504):
                    break
            except ProxyHttpError as exc:
                last_error = exc
                if exc.code not in (408, 429, 500, 502, 503, 504):
                    break
            except (urllib.error.URLError, subprocess.TimeoutExpired, TimeoutError, ConnectionError, OSError, RuntimeError) as exc:
                last_error = exc
            if attempt < self.retries:
                time.sleep(min(8.0, 0.6 * (2 ** (attempt - 1))) + random.uniform(0.0, 0.3))

        if allow_stale and body_path.exists() and cached_meta:
            body = body_path.read_bytes()
            return FetchResult(
                body=body,
                source_url=str(cached_meta.get("source_url") or safe_url(url)),
                retrieved_at=str(cached_meta.get("retrieved_at") or utc_now()),
                raw_sha256=sha256_bytes(body),
                status="stale",
                http_status=cached_meta.get("http_status"),
                content_type=str(cached_meta.get("content_type") or ""),
                warning=f"live fetch failed; using stale cache: {type(last_error).__name__}: {last_error}",
            )
        proxy_note = f" via {safe_proxy_url(proxy_url)}" if proxy_url else ""
        raise RuntimeError(
            f"HTTP fetch failed for {safe_url(url)}{proxy_note}: {type(last_error).__name__}: {last_error}"
        )

    def get_json(self, url: str, **kwargs: Any) -> tuple[Any, FetchResult]:
        result = self.get(url, **kwargs)
        try:
            return json.loads(result.body.decode("utf-8-sig")), result
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"invalid JSON from {result.source_url}: {exc}") from exc


def provider(
    provider_id: str,
    publisher: str,
    authority_score: float,
    endpoint_stability: float,
) -> dict[str, Any]:
    return {
        "id": provider_id,
        "publisher": publisher,
        "authority_score": authority_score,
        "endpoint_stability": endpoint_stability,
    }


def warnings_from_fetches(fetches: list[FetchResult]) -> list[str]:
    warnings = [item.warning for item in fetches if item.warning]
    for item in fetches:
        if item.status == "stale" and not item.warning:
            warnings.append(f"stale cached response used: {item.source_url}")
    return warnings
