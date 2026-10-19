from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, HttpUrl

app = FastAPI(title="SmartScan optional AI gateway", version="0.1.0")


class ProviderCheck(BaseModel):
    base_url: HttpUrl
    model: str


def ensure_public_https(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("provider URL must use HTTPS")
    for info in socket.getaddrinfo(parsed.hostname, parsed.port or 443):
        address = ipaddress.ip_address(info[4][0])
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
        ):
            raise ValueError("provider URL resolves to a non-public address")


@app.get("/health")
def health():
    return {"status": "ok", "enabled": False}


@app.post("/v1/providers/check")
def check_provider(payload: ProviderCheck):
    try:
        ensure_public_https(str(payload.base_url))
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"accepted": True, "model": payload.model, "note": "No media was transmitted."}
