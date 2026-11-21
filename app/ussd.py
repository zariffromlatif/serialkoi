"""USSD menus. Applink USSD carries plain ASCII (encoding 440), so menus are short English."""
from __future__ import annotations

import json
from datetime import timedelta
from typing import Any, Callable

from .service import Service, canonical_phone

CONT, FIN = "mt-cont", "mt-fin"
MAX_LEN = 160  # Applink guidance: assume ~160 characters per screen on real handsets
SESSION_TTL_MINUTES = 10


def clip(text: str, n: int) -> str:
    return text if len(text) <= n else text[: n - 1] + "."


def fit(text: str) -> str:
    return text if len(text) <= MAX_LEN else text[: MAX_LEN - 1] + "."


def _tokens(dial: str) -> list[str]:
    return [p for p in dial.strip().rstrip("#").split("*") if p]


def code_from_dial(message: str, base: str = "*213#") -> str | None:
    """Chamber code typed after the app's own USSD code.

    Applink apps get a shared service code plus a keyword (e.g. base '*383*44#'), so the
    one-step booking string is '*383*44*4521#'. A bare base code has no chamber code.
    """
    parts, base_parts = _tokens(message), _tokens(base)
    if len(parts) > len(base_parts) and parts[len(base_parts)].isdigit() and len(parts[len(base_parts)]) == 4:
        return parts[len(base_parts)]
    return None


class UssdApp:
    def __init__(self, svc: Service):
        self.svc = svc

    # ------------------------------------------------------------------ session state
    def _get(self, session_id: str) -> dict[str, Any] | None:
        row = self.svc.store.one("SELECT * FROM ussd_sessions WHERE session_id = ?", (session_id,))
        if row:
            row["data"] = json.loads(row["data"])
        return row

    def _set(self, session_id: str, phone: str, state: str, data: dict[str, Any] | None = None) -> None:
        self.svc.store.run(
            "INSERT INTO ussd_sessions (session_id, phone, state, data, updated_at) VALUES (?,?,?,?,?)"
            " ON CONFLICT(session_id) DO UPDATE SET state = excluded.state, data = excluded.data, updated_at = excluded.updated_at",
            (session_id, phone, state, json.dumps(data or {}), self.svc.ts()),
        )

    def _end(self, session_id: str, text: str) -> tuple[str, str]:
        self.svc.store.run("DELETE FROM ussd_sessions WHERE session_id = ?", (session_id,))
        return fit(text), FIN

    def _ask(self, session_id: str, phone: str, state: str, text: str, data: dict[str, Any] | None = None) -> tuple[str, str]:
        self._set(session_id, phone, state, data)
        return fit(text), CONT

    # ------------------------------------------------------------------ entry point
    def handle(self, session_id: str, source: str, operation: str, message: str) -> tuple[str, str]:
        """Return (reply text, 'mt-cont' | 'mt-fin'), running any follow-up work straight away."""
        text, op, after = self.handle_full(session_id, source, operation, message)
        if after:
            after()
        return text, op

    def handle_full(self, session_id: str, source: str, operation: str,
                    message: str) -> tuple[str, str, Callable[[], None] | None]:
        """Return (reply text, operation, follow-up). Run the follow-up after the screen is sent:
        slow work such as starting a charge must not hold up a USSD session."""
        self._after: Callable[[], None] | None = None
        text, op = self._dispatch(session_id, source, operation, message)
        return text, op, self._after

    def _dispatch(self, session_id: str, source: str, operation: str, message: str) -> tuple[str, str]:
        phone = canonical_phone(source)
        msg = (message or "").strip()
        if operation == "mo-init":
            cutoff = (self.svc.clock() - timedelta(minutes=SESSION_TTL_MINUTES)).isoformat(timespec="seconds")
            self.svc.store.run("DELETE FROM ussd_sessions WHERE updated_at < ?", (cutoff,))
        session = None if operation == "mo-init" else self._get(session_id)
        if session is None:
            code = code_from_dial(msg, self.svc.s.ussd_code)
            if code:
                return self._chamber_screen(session_id, phone, code)
            return self._menu(session_id, phone)

        state, data = session["state"], session["data"]
        if msg == "0" and state != "otp":
            return self._end(session_id, "Thank you for using SerialKoi.")
        handler = getattr(self, f"_on_{state}")
        return handler(session_id, phone, msg, data)

    # ------------------------------------------------------------------ screens
    def _menu(self, session_id: str, phone: str, prefix: str = "") -> tuple[str, str]:
        lines = [prefix + "SerialKoi - doctor serial", "1. Get a serial", "2. My serial", "3. Cancel serial"]
        if self.svc.pending_payment(phone):
            lines.append("4. Enter payment code")
        lines.append("0. Exit")
        return self._ask(session_id, phone, "menu", "\n".join(lines))

    def _chamber_screen(self, session_id: str, phone: str, code: str) -> tuple[str, str]:
        chamber = self.svc.chamber(code)
        if not chamber:
            return self._ask(session_id, phone, "code", f"No chamber with code {code}.\nEnter the 4-digit code on the chamber poster:")
        if not chamber["is_open"]:
            return self._end(session_id, f"{chamber['doctor']} is not taking serials right now. Please try later.")
        mine = [v for v in self.svc.active_tickets(phone) if v["chamber"]["id"] == chamber["id"]]
        if mine:
            return self._end(session_id, self._status_line(mine[0]))
        snap = self.svc.snapshot(chamber)
        waiting = len(snap["waiting"])
        eta = self.svc.eta_minutes(chamber, waiting, snap["serving"] is not None)
        now = snap["serving"]["serial"] if snap["serving"] else "-"
        fee = f"Tk{chamber['fee']:g}" if chamber["fee"] > 0 else "Free"
        text = (f"{clip(chamber['doctor'], 32)}\n{clip(chamber['name'], 32)}\n"
                f"Now serving: {now}\nWaiting: {waiting} (~{eta} min)\nFee: {fee}\n1. Confirm\n0. Exit")
        return self._ask(session_id, phone, "confirm", text, {"code": code})

    def _status_line(self, view: dict[str, Any]) -> str:
        t, c = view["ticket"], view["chamber"]
        if t["status"] == "called":
            return f"Serial {t['serial']} - {clip(c['doctor'], 28)}\nIt is your turn now. Please go in."
        now = view["now_serving"] or "-"
        return (f"Serial {t['serial']} - {clip(c['doctor'], 28)}\nNow serving {now}. "
                f"{view['ahead']} ahead, ~{view['eta']} min.")

    def _booked_text(self, view: dict[str, Any]) -> str:
        t, c = view["ticket"], view["chamber"]
        return (f"Serial {t['serial']} confirmed!\n{clip(c['doctor'], 32)}\n"
                f"{view['ahead']} ahead, ~{view['eta']} min.\nWe will SMS you when your turn is near.")

    # ------------------------------------------------------------------ state handlers
    def _on_menu(self, sid: str, phone: str, msg: str, data: dict[str, Any]) -> tuple[str, str]:
        if msg == "1":
            return self._ask(sid, phone, "code", "Enter the 4-digit chamber code (on the poster at the chamber):")
        if msg == "2":
            views = self.svc.active_tickets(phone)
            if not views:
                return self._end(sid, "You have no serial today.")
            return self._end(sid, "\n".join(self._status_line(v) for v in views[:2]))
        if msg == "3":
            views = self.svc.active_tickets(phone)
            if not views:
                return self._end(sid, "You have no serial to cancel.")
            if len(views) == 1:
                v = views[0]
                return self._ask(sid, phone, "cancel", f"Cancel serial {v['ticket']['serial']} with {clip(v['chamber']['doctor'], 30)}?\n1. Yes\n0. No",
                                 {"ids": [v["ticket"]["id"]]})
            lines = [f"{i}. Serial {v['ticket']['serial']} - {clip(v['chamber']['doctor'], 24)}" for i, v in enumerate(views[:3], 1)]
            return self._ask(sid, phone, "cancel", "Which serial to cancel?\n" + "\n".join(lines) + "\n0. Exit",
                             {"ids": [v["ticket"]["id"] for v in views[:3]]})
        if msg == "4" and self.svc.pending_payment(phone):
            return self._ask(sid, phone, "otp", "Enter the 6-digit code from the AppLink SMS:")
        return self._menu(sid, phone, prefix="Invalid choice.\n")

    def _on_code(self, sid: str, phone: str, msg: str, data: dict[str, Any]) -> tuple[str, str]:
        if not (msg.isdigit() and len(msg) == 4):
            return self._ask(sid, phone, "code", "Please enter the 4-digit chamber code:")
        return self._chamber_screen(sid, phone, msg)

    def _on_confirm(self, sid: str, phone: str, msg: str, data: dict[str, Any]) -> tuple[str, str]:
        if msg != "1":
            return self._chamber_screen(sid, phone, data["code"])
        chamber = self.svc.chamber(data["code"])
        blocked = self.svc.precheck(chamber, phone)  # type: ignore[arg-type]
        if blocked and blocked["result"] == "exists":
            return self._end(sid, self._status_line(blocked["view"]))
        if blocked:
            return self._end(sid, "Sorry, this chamber just stopped taking serials.")
        if chamber["fee"] <= 0:  # type: ignore[index]
            ticket, _ = self.svc.book(chamber, phone, "ussd")  # type: ignore[arg-type]
            return self._end(sid, self._booked_text(self.svc.ticket_view(ticket)))
        # Applink: charging cannot happen inside a USSD session. End it, then start the charge.
        self._after = lambda: self._start_payment(chamber, phone)  # type: ignore[arg-type]
        kw, code = self.svc.s.sms_keyword, self.svc.s.ussd_code
        fee = chamber["fee"]  # type: ignore[index]
        to = f" to {self.svc.s.sms_shortcode}" if self.svc.s.sms_shortcode else ""
        return self._end(sid, f"To pay Tk{fee:g}, AppLink will SMS you a 6-digit code.\n"
                              f"Reply by SMS: {kw} <code>{to}\nor dial {code} and press 4.")

    def _start_payment(self, chamber: dict[str, Any], phone: str) -> None:
        r = self.svc.start_payment(chamber, phone, "ussd")
        if r["result"] == "error":
            self.svc.client.notify(phone, "SerialKoi: The payment could not start, so no money was taken. "
                                          "Please dial again in a few minutes.")

    def _on_otp(self, sid: str, phone: str, msg: str, data: dict[str, Any]) -> tuple[str, str]:
        if msg == "0":
            kw = self.svc.s.sms_keyword
            return self._end(sid, f"OK. Reply by SMS with: {kw} <6-digit code> within 5 minutes to get your serial.")
        r = self.svc.verify_payment(phone, msg)
        if r["result"] == "booked":
            return self._end(sid, self._booked_text(r["view"]))
        if r["result"] == "wrong_otp":
            return self._ask(sid, phone, "otp", f"Wrong code. {r['left']} tries left. Enter the 6-digit code:")
        if r["result"] == "processing":
            return self._end(sid, "Payment is processing. Your serial will arrive by SMS shortly.")
        if r["result"] == "failed":
            return self._end(sid, "Too many wrong codes. No serial was booked. Please dial again.")
        if r["result"] == "no_balance":
            return self._end(sid, "Not enough balance. No serial was booked. Please recharge and dial again.")
        return self._end(sid, "The payment code expired. Please dial again.")

    def _on_cancel(self, sid: str, phone: str, msg: str, data: dict[str, Any]) -> tuple[str, str]:
        ids = data.get("ids", [])
        idx = int(msg) - 1 if msg.isdigit() else -1
        if not 0 <= idx < len(ids):
            return self._end(sid, "Nothing was cancelled.")
        t = self.svc.cancel(ids[idx], phone=phone)
        return self._end(sid, f"Serial {t['serial']} cancelled.")
