"""SerialKoi web app: Applink callbacks, the assistant's queue API, a public display and a phone simulator."""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, BackgroundTasks, Body, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .applink import ApplinkClient
from .config import Settings
from .db import Store
from .poster import render_poster
from .service import QueueError, Service, canonical_phone, now_dhaka
from .sms import handle_sms
from .ussd import UssdApp

STATIC = Path(__file__).parent / "static"
OK = {"statusCode": "S1000", "statusDetail": "Success"}
log = logging.getLogger("serialkoi")

DEMO_CHAMBER = dict(code="4521", name="Merul Badda Medicine Chamber", doctor="Dr. Farhana Rahman",
                    area="Merul Badda, Dhaka", pin="2468", fee=5, avg_minutes=7)


def create_app(settings: Settings | None = None, clock: Callable[[], datetime] = now_dhaka) -> FastAPI:
    settings = settings or Settings.from_env()
    store = Store(settings.db_path)
    client = ApplinkClient(settings, store, clock)
    svc = Service(store, client, settings, clock)
    ussd = UssdApp(svc)
    if settings.seed_demo and not svc.chamber(DEMO_CHAMBER["code"]):
        svc.create_chamber(**DEMO_CHAMBER)

    app = FastAPI(title="SerialKoi", version="0.1.0")
    app.state.svc = svc
    app.state.ussd = ussd

    def page(name: str) -> FileResponse:
        return FileResponse(STATIC / name, headers={"Cache-Control": "no-store"})

    def authed(code: str, token: str | None) -> dict[str, Any]:
        chamber = svc.chamber(code)
        if not chamber or not svc.check_token(chamber, token or ""):
            raise HTTPException(401, "Log in again")
        return chamber

    def bad(exc: QueueError) -> HTTPException:
        return HTTPException(400, str(exc))

    # ------------------------------------------------------------------ Applink callbacks (Applink calls us)
    # Contract (Applink-as-a-skill, references/07-callbacks.md): always answer 200 + S1000 at once and
    # do the work afterwards; ignore malformed bodies, other apps' payloads and redeliveries.
    async def payload(request: Request) -> dict | None:
        if settings.callback_ips and (request.client is None or request.client.host not in settings.callback_ips):
            return None
        try:
            body = await request.json()
        except Exception:
            return None
        if not isinstance(body, dict):
            return None
        app_id = body.get("applicationId")
        if not settings.is_sim and app_id and app_id != settings.app_id:
            return None
        return body

    def safely(fn: Callable[..., Any], *args: Any) -> None:
        try:
            fn(*args)
        except Exception:
            log.exception("callback processing failed")

    def process_ussd(p: dict) -> None:
        session, source = str(p["sessionId"]), p["sourceAddress"]
        text, op, after = ussd.handle_full(session, source, p.get("ussdOperation", "mo-cont"), str(p.get("message", "")))
        client.send_ussd(session, canonical_phone(source), text, op)  # the screen goes out first
        if after:
            after()  # then slow work such as starting a charge

    def process_sms(p: dict) -> None:
        source = canonical_phone(p["sourceAddress"])
        client._log("in", "sms", source, str(p.get("message", "")), "")
        reply = handle_sms(svc, source, str(p.get("message", "")))
        if reply:
            client.send_sms(source, reply)

    cb = APIRouter(prefix=settings.callback_prefix)

    @cb.post("/ussd/receive")
    async def ussd_receive(request: Request, bg: BackgroundTasks) -> dict:
        p = await payload(request)
        if p and p.get("sessionId") and p.get("sourceAddress") and store.first_time("ussd", str(p.get("requestId", "")), svc.ts()):
            bg.add_task(safely, process_ussd, p)
        return OK

    @cb.post("/sms/receive")
    async def sms_receive(request: Request, bg: BackgroundTasks) -> dict:
        p = await payload(request)
        if p and p.get("sourceAddress") and store.first_time("sms", str(p.get("requestId", "")), svc.ts()):
            bg.add_task(safely, process_sms, p)
        return OK

    @cb.post("/sms/report")
    async def sms_report(request: Request) -> dict:
        p = await payload(request)
        if p and store.first_time("report", f"{p.get('requestId', '')}:{p.get('deliveryStatus', '')}", svc.ts()):
            client._log("in", "report", p.get("destinationAddress"), str(p.get("requestId", "")), str(p.get("deliveryStatus", "")))
        return OK

    @cb.post("/caas/chargingNotification")
    async def charging_notification(request: Request, bg: BackgroundTasks) -> dict:
        p = await payload(request)
        if p and p.get("externalTrxId") and store.first_time("charge", f"{p['externalTrxId']}:{p.get('statusCode', '')}", svc.ts()):
            client._log("in", "charge", None, str(p["externalTrxId"]), str(p.get("statusCode", "")))
            bg.add_task(safely, svc.on_charging_notification, p)
        return OK

    app.include_router(cb)

    # ------------------------------------------------------------------ assistant API
    @app.post("/api/login")
    def login(p: dict = Body(...)) -> dict:
        chamber = svc.chamber(str(p.get("code", "")).strip())
        if not chamber or not svc.check_pin(chamber, str(p.get("pin", "")).strip()):
            raise HTTPException(401, "Wrong chamber code or PIN")
        return {"token": svc.token(chamber), "code": chamber["code"]}

    @app.get("/api/chamber/{code}")
    def state(code: str, x_token: str | None = Header(None)) -> dict:
        return svc.snapshot(authed(code, x_token))

    @app.post("/api/chamber/{code}/next")
    def next_patient(code: str, x_token: str | None = Header(None)) -> dict:
        chamber = authed(code, x_token)
        svc.call_next(chamber)
        return svc.snapshot(chamber)

    @app.post("/api/chamber/{code}/noshow")
    def no_show(code: str, x_token: str | None = Header(None)) -> dict:
        chamber = authed(code, x_token)
        svc.call_next(chamber, no_show=True)
        return svc.snapshot(chamber)

    @app.post("/api/chamber/{code}/recall/{ticket_id}")
    def recall(code: str, ticket_id: int, x_token: str | None = Header(None)) -> dict:
        chamber = authed(code, x_token)
        try:
            svc.recall(chamber, ticket_id)
        except QueueError as exc:
            raise bad(exc)
        return svc.snapshot(chamber)

    @app.post("/api/chamber/{code}/cancel/{ticket_id}")
    def cancel(code: str, ticket_id: int, x_token: str | None = Header(None)) -> dict:
        chamber = authed(code, x_token)
        t = svc.ticket(ticket_id)
        if not t or t["chamber_id"] != chamber["id"]:
            raise HTTPException(404, "No such serial")
        try:
            svc.cancel(ticket_id)
        except QueueError as exc:
            raise bad(exc)
        return svc.snapshot(chamber)

    @app.post("/api/chamber/{code}/walkin")
    def walk_in(code: str, p: dict = Body(...), x_token: str | None = Header(None)) -> dict:
        chamber = authed(code, x_token)
        try:
            svc.walk_in(chamber, str(p.get("name", "")), str(p.get("phone", "")))
        except QueueError as exc:
            raise bad(exc)
        return svc.snapshot(chamber)

    @app.post("/api/chamber/{code}/open")
    def set_open(code: str, p: dict = Body(...), x_token: str | None = Header(None)) -> dict:
        chamber = authed(code, x_token)
        svc.set_open(chamber, bool(p.get("open")))
        return svc.snapshot(chamber)

    # ------------------------------------------------------------------ public waiting-room display
    @app.get("/api/public/{code}")
    def public(code: str) -> dict:
        chamber = svc.chamber(code)
        if not chamber:
            raise HTTPException(404, "No such chamber")
        snap = svc.snapshot(chamber)
        return {
            "chamber": {k: snap["chamber"][k] for k in ("code", "name", "doctor", "area", "avg_minutes", "is_open", "dial", "fee")},
            "serving": snap["serving"]["serial"] if snap["serving"] else None,
            "next": [w["serial"] for w in snap["waiting"][:6]],
            "waiting": len(snap["waiting"]),
        }

    # ------------------------------------------------------------------ admin: register a chamber
    @app.post("/api/admin/chambers")
    def add_chamber(p: dict = Body(...), x_admin_key: str | None = Header(None)) -> dict:
        if not settings.admin_key or x_admin_key != settings.admin_key:
            raise HTTPException(403, "Admin key required")
        try:
            c = svc.create_chamber(str(p["code"]), p["name"], p["doctor"], str(p["pin"]), p.get("area", ""),
                                   float(p.get("fee", 5)), float(p.get("avg_minutes", 8)), int(p.get("alert_ahead", 3)))
        except (QueueError, KeyError) as exc:
            raise HTTPException(400, str(exc))
        return {"code": c["code"], "dial": settings.dial_string(c["code"])}

    # ------------------------------------------------------------------ simulator (sim mode only)
    if settings.is_sim:
        @app.post("/sim/ussd")
        def sim_ussd(bg: BackgroundTasks, p: dict = Body(...)) -> dict:
            text, op, after = ussd.handle_full(str(p["sessionId"]), p["phone"], p.get("ussdOperation", "mo-cont"), str(p.get("message", "")))
            client.send_ussd(str(p["sessionId"]), canonical_phone(p["phone"]), text, op)
            if after:
                bg.add_task(safely, after)  # e.g. start the charge after the screen is shown
            return {"message": text, "ussdOperation": op}

        @app.post("/sim/sms")
        def sim_sms(p: dict = Body(...)) -> dict:
            process_sms({"sourceAddress": p["phone"], "message": p.get("message", "")})
            return {"ok": True}

        @app.get("/sim/inbox")
        def sim_inbox(phone: str, after: int = 0) -> dict:
            address = canonical_phone(phone)
            rows = store.all(
                "SELECT id, kind, direction, body, created_at FROM messages WHERE address = ? AND kind IN ('sms','otp') AND id > ? ORDER BY id",
                (address, after),
            )
            return {"messages": rows}

        @app.post("/sim/fill")
        def sim_fill(p: dict = Body(default={})) -> dict:
            """Put a few remote and walk-in patients in the demo queue (for recording)."""
            chamber = svc.chamber(str(p.get("code", DEMO_CHAMBER["code"])))
            if not chamber:
                raise HTTPException(404, "No such chamber")
            names = ["Rahima Begum", "Abdul Karim", "Shirin Akter", "Mizanur Rahman", "Nasima Khatun", "Jamal Uddin"]
            for i, name in enumerate(names[: int(p.get("count", 6))]):
                if i % 2:
                    svc.walk_in(chamber, name)
                else:
                    svc.book(chamber, f"tel:88014{(1000000 + i * 7919) % 10000000:08d}", "ussd", paid=chamber["fee"])
            return svc.snapshot(chamber)

        @app.post("/sim/reset")
        def sim_reset() -> dict:
            with store.tx() as c:
                for table in ("tickets", "payments", "ussd_sessions", "messages", "sim_otps", "seen_callbacks"):
                    c.execute(f"DELETE FROM {table}")
                c.execute("UPDATE chambers SET avg_minutes = 7, is_open = 1 WHERE code = ?", (DEMO_CHAMBER["code"],))
            return {"ok": True}

    # ------------------------------------------------------------------ pages
    @app.get("/healthz")
    def health() -> dict:
        return {"ok": True, "mode": settings.mode}

    @app.get("/")
    def index() -> FileResponse:
        return page("index.html")

    @app.get("/assistant")
    def assistant_page() -> FileResponse:
        return page("assistant.html")

    @app.get("/display/{code}")
    def display_page(code: str) -> FileResponse:
        return page("display.html")

    @app.get("/poster/{code}")
    def poster(code: str, request: Request) -> HTMLResponse:
        chamber = svc.chamber(code)
        if not chamber:
            raise HTTPException(404, "No such chamber")
        display_url = str(request.base_url).rstrip("/") + f"/display/{code}"
        return HTMLResponse(render_poster(chamber, settings.dial_string(code), settings.ussd_code, display_url,
                                          settings.sms_keyword, settings.sms_shortcode))

    @app.get("/sim")
    def sim_page():
        if not settings.is_sim:
            return RedirectResponse("/")
        return page("sim.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app
