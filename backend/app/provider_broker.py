from __future__ import annotations
from typing import Any
import httpx
from .config import settings

class BrokerUnavailable(RuntimeError):
    def __init__(self, message: str, *, category: str = "broker_unavailable", retryable: bool = False, status_code: int | None = None):
        super().__init__(message)
        self.category = category
        self.retryable = retryable
        self.status_code = status_code
    def as_dict(self) -> dict:
        return {"category":self.category,"message":str(self),"retryable":self.retryable,"http_status":self.status_code}

def configured() -> bool:
    return bool((getattr(settings,"access_gateway_url",None) or "").strip())

async def evaluate(latitude: float, longitude: float, radius_m: int = 1500) -> dict[str, Any]:
    if not configured():
        raise BrokerUnavailable("Central provider broker is not configured.", category="broker_not_configured")
    base=str(settings.access_gateway_url).strip().rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=max(5.0,float(getattr(settings,"access_gateway_timeout_seconds",20.0)))) as client:
            r=await client.post(f"{base}/api/provider/traffic/evaluate",json={"latitude":float(latitude),"longitude":float(longitude),"radius_m":int(radius_m)})
    except httpx.HTTPError as exc:
        raise BrokerUnavailable("Central traffic broker could not be reached.",category="broker_network_failure",retryable=True) from exc
    try:data=r.json() if r.content else {}
    except ValueError:data={}
    if r.status_code>=400:
        detail=data.get("detail") if isinstance(data,dict) else None
        if isinstance(detail,dict):
            raise BrokerUnavailable(detail.get("message") or "Central traffic broker request failed.",category=detail.get("category") or "broker_error",retryable=bool(detail.get("retryable")),status_code=r.status_code)
        raise BrokerUnavailable(str(detail or "Central traffic broker request failed."),category="broker_error",retryable=r.status_code>=500,status_code=r.status_code)
    return data
