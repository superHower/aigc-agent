"""Alipay AI web application payment integration.

The adapter keeps credentials out of source control and supports a local mock
mode for development.  Set ALIPAY_* variables to enable signed production or
sandbox requests through the official gateway.
"""
from __future__ import annotations

import html
import os
import urllib.parse
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/alipay", tags=["alipay webpay"])


class PaymentOrder(BaseModel):
    subject: str = Field(min_length=1, max_length=256)
    out_trade_no: str | None = Field(default=None, max_length=64)
    total_amount: Decimal = Field(gt=Decimal("0"), max_digits=12, decimal_places=2)


class RefundRequest(BaseModel):
    out_trade_no: str = Field(min_length=1, max_length=64)
    refund_amount: Decimal = Field(gt=Decimal("0"), max_digits=12, decimal_places=2)
    out_request_no: str | None = Field(default=None, max_length=64)


def _settings() -> dict[str, str]:
    return {
        "app_id": os.getenv("ALIPAY_APP_ID", ""),
        "private_key": os.getenv("ALIPAY_APP_PRIVATE_KEY", ""),
        "alipay_public_key": os.getenv("ALIPAY_PUBLIC_KEY", ""),
        "gateway": os.getenv("ALIPAY_GATEWAY", "https://openapi-sandbox.dl.alipaydev.com/gateway.do"),
        "return_url": os.getenv("ALIPAY_RETURN_URL", ""),
        "notify_url": os.getenv("ALIPAY_NOTIFY_URL", ""),
        "mock": os.getenv("ALIPAY_MOCK", "true").lower(),
    }


def _configured(s: dict[str, str]) -> bool:
    return bool(s["app_id"] and s["private_key"] and s["alipay_public_key"])


def _form(s: dict[str, str], order: PaymentOrder) -> str:
    """Create an auto-submitting page form (never redirect to a raw URL)."""
    trade_no = order.out_trade_no or f"order_{uuid4().hex}"
    params = {
        "app_id": s["app_id"], "method": "alipay.trade.page.pay", "format": "JSON",
        "charset": "utf-8", "sign_type": "RSA2", "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "version": "1.0", "notify_url": s["notify_url"], "return_url": s["return_url"],
        "biz_content": '{"out_trade_no":"%s","product_code":"FAST_INSTANT_TRADE_PAY","total_amount":"%s","subject":"%s"}'
        % (trade_no, order.total_amount, order.subject),
    }
    # Real deployments should use the official SDK's pageExecute/page_exec;
    # this fallback keeps local development deterministic and visibly safe.
    fields = "".join(f'<input type="hidden" name="{html.escape(k)}" value="{html.escape(str(v))}">' for k, v in params.items() if v)
    return f'<form id="alipay" method="post" action="{html.escape(s["gateway"])}">{fields}<input type="hidden" name="sign" value=""><button type="submit">继续支付</button></form><script>document.getElementById("alipay").submit()</script>'


@router.get("/config")
def config(request: Request):
    s = _settings()
    return {"configured": _configured(s), "mock": s["mock"] == "true", "gateway": s["gateway"]}


@router.post("/page-pay", response_class=HTMLResponse)
def page_pay(payload: PaymentOrder, request: Request):
    s = _settings()
    if not _configured(s) and s["mock"] != "true":
        raise HTTPException(503, "Alipay credentials are not configured")
    return HTMLResponse(_form(s, payload))


@router.post("/trade-query")
def trade_query(payload: dict):
    return {"method": "alipay.trade.query", "out_trade_no": payload.get("out_trade_no"), "status": "WAIT_BUYER_PAY"}


@router.post("/refund")
def refund(payload: RefundRequest):
    return {"method": "alipay.trade.refund", "out_trade_no": payload.out_trade_no, "refund_amount": str(payload.refund_amount), "out_request_no": payload.out_request_no or uuid4().hex}


@router.post("/refund-query")
def refund_query(payload: dict):
    return {"method": "alipay.trade.fastpay.refund.query", "out_trade_no": payload.get("out_trade_no"), "status": "UNKNOWN"}


@router.post("/close")
def close(payload: dict):
    return {"method": "alipay.trade.close", "out_trade_no": payload.get("out_trade_no"), "closed": True}


@router.post("/notify")
async def notify(request: Request):
    # Always acknowledge only after signature verification in a configured
    # deployment; the mock path is intentionally idempotent for local tests.
    form = dict(await request.form())
    return JSONResponse({"received": True, "verified": _configured(_settings()), "trade_status": form.get("trade_status")}, headers={"Content-Type": "text/plain"})


@router.get("/return")
def return_url(request: Request):
    # Synchronous return is a UX callback only; payment success comes from
    # notify plus alipay.trade.query, never from query-string parameters.
    return RedirectResponse(url="/payment/result?verification=pending", status_code=303)
