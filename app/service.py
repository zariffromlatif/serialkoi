"""Queue logic: serials, wait estimates, alerts, no-shows and paid bookings."""
from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from .applink import ApplinkClient
from .config import Settings
from .db import Store

DHAKA = timezone(timedelta(hours=6))
ACTIVE = ("waiting", "called")
OTP_VALID_MINUTES = 5  # Applink: "OTP valid for 5 minutes"
MAX_OTP_ATTEMPTS = 3


def now_dhaka() -> datetime:
    return datetime.now(DHAKA)


class QueueError(Exception):
    pass


def canonical_phone(raw: str) -> str:
    """Return an Applink address ('tel:8801XXXXXXXXX').

    Accepts what Applink sends ('tel:+8801…', 'tel: +8801…', or a masked 'tel:…' token, kept as is)
    and what an assistant types ('01712345678', '+8801712345678').
    """
    s = (raw or "").strip()
    if s.lower().startswith("tel:"):
        rest = s[4:].strip()
        if rest.startswith("+") and rest[1:].isdigit():
            rest = rest[1:]
        return "tel:" + rest
    digits = "".join(ch for ch in s if ch.isdigit())
    if len(digits) == 13 and digits.startswith("8801"):
        return "tel:" + digits
    if len(digits) == 11 and digits.startswith("01"):
        return "tel:88" + digits
    raise QueueError("Phone number should look like 01XXXXXXXXX")


def short(name: str, n: int = 26) -> str:
    """Keep names short so every SMS fits in one 160-character part."""
    return name if len(name) <= n else name[:n].rstrip(" .,")


def mask_phone(address: str | None) -> str:
    if not address:
        return ""
    rest = address[4:] if address.startswith("tel:") else address
    if rest.isdigit() and len(rest) == 13:
        local = rest[2:]
        return f"{local[:3]}-xxxxx-{local[-3:]}"
    return "Banglalink user"  # Applink may mask numbers for some app types


class Service:
    def __init__(self, store: Store, client: ApplinkClient, settings: Settings, clock: Callable[[], datetime] = now_dhaka):
        self.store = store
        self.client = client
        self.s = settings
        self.clock = clock

    # ------------------------------------------------------------------ helpers
    def today(self) -> str:
        return self.clock().date().isoformat()

    def ts(self) -> str:
        return self.clock().isoformat(timespec="seconds")

    def _hash_pin(self, pin: str) -> str:
        return hmac.new(self.s.secret.encode(), pin.encode(), hashlib.sha256).hexdigest()

    # ------------------------------------------------------------------ chambers
    def create_chamber(self, code: str, name: str, doctor: str, pin: str, area: str = "",
                       fee: float = 5, avg_minutes: float = 8, alert_ahead: int = 3) -> dict[str, Any]:
        if not (code.isdigit() and len(code) == 4):
            raise QueueError("Chamber code must be 4 digits")
        if not (pin.isdigit() and 4 <= len(pin) <= 6):
            raise QueueError("PIN must be 4 to 6 digits")
        try:
            with self.store.tx() as c:
                c.execute(
                    "INSERT INTO chambers (code, name, doctor, area, pin_hash, fee, avg_minutes, alert_ahead, is_open, created_at)"
                    " VALUES (?,?,?,?,?,?,?,?,1,?)",
                    (code, name.strip(), doctor.strip(), area.strip(), self._hash_pin(pin), fee, avg_minutes, alert_ahead, self.ts()),
                )
        except sqlite3.IntegrityError:
            raise QueueError("That chamber code is taken")
        return self.chamber(code)  # type: ignore[return-value]

    def chamber(self, code: str) -> dict[str, Any] | None:
        return self.store.one("SELECT * FROM chambers WHERE code = ?", (code,))

    def chamber_by_id(self, chamber_id: int) -> dict[str, Any]:
        return self.store.one("SELECT * FROM chambers WHERE id = ?", (chamber_id,))  # type: ignore[return-value]

    def check_pin(self, chamber: dict[str, Any], pin: str) -> bool:
        return hmac.compare_digest(chamber["pin_hash"], self._hash_pin(pin))

    def token(self, chamber: dict[str, Any]) -> str:
        msg = f"{chamber['code']}:{chamber['pin_hash']}".encode()
        return hmac.new(self.s.secret.encode(), msg, hashlib.sha256).hexdigest()[:32]

    def check_token(self, chamber: dict[str, Any], token: str) -> bool:
        return hmac.compare_digest(self.token(chamber), token or "")

    def set_open(self, chamber: dict[str, Any], is_open: bool) -> None:
        self.store.run("UPDATE chambers SET is_open = ? WHERE id = ?", (1 if is_open else 0, chamber["id"]))

    # ------------------------------------------------------------------ reads
    def ticket(self, ticket_id: int) -> dict[str, Any] | None:
        return self.store.one("SELECT * FROM tickets WHERE id = ?", (ticket_id,))

    def waiting(self, chamber_id: int) -> list[dict[str, Any]]:
        return self.store.all(
            "SELECT * FROM tickets WHERE chamber_id = ? AND day = ? AND status = 'waiting' ORDER BY priority DESC, serial ASC",
            (chamber_id, self.today()),
        )

    def serving(self, chamber_id: int) -> dict[str, Any] | None:
        return self.store.one(
            "SELECT * FROM tickets WHERE chamber_id = ? AND day = ? AND status = 'called' ORDER BY called_at DESC, id DESC LIMIT 1",
            (chamber_id, self.today()),
        )

    def eta_minutes(self, chamber: dict[str, Any], ahead: int, someone_inside: bool) -> int:
        """Wait estimate from the chamber's learned average consultation time.

        Someone already inside counts as half a consultation still to go.
        """
        units = ahead + (0.5 if someone_inside else 0)
        return int(round(units * chamber["avg_minutes"]))

    def ticket_view(self, ticket: dict[str, Any]) -> dict[str, Any]:
        chamber = self.chamber_by_id(ticket["chamber_id"])
        serving = self.serving(chamber["id"])
        if ticket["status"] == "waiting":
            queue = self.waiting(chamber["id"])
            ahead = next(i for i, t in enumerate(queue) if t["id"] == ticket["id"])
        else:
            ahead = 0
        return {
            "ticket": ticket,
            "chamber": chamber,
            "ahead": ahead,
            "eta": self.eta_minutes(chamber, ahead, serving is not None) if ticket["status"] == "waiting" else 0,
            "now_serving": serving["serial"] if serving else None,
        }

    def active_tickets(self, phone: str) -> list[dict[str, Any]]:
        rows = self.store.all(
            "SELECT * FROM tickets WHERE phone = ? AND day = ? AND status IN ('waiting','called') ORDER BY id",
            (phone, self.today()),
        )
        return [self.ticket_view(t) for t in rows]

    def snapshot(self, chamber: dict[str, Any]) -> dict[str, Any]:
        chamber = self.chamber_by_id(chamber["id"])  # fresh avg / open flag
        serving = self.serving(chamber["id"])
        queue = self.waiting(chamber["id"])
        day = self.today()
        skipped = self.store.all(
            "SELECT * FROM tickets WHERE chamber_id = ? AND day = ? AND status = 'skipped' ORDER BY finished_at DESC",
            (chamber["id"], day),
        )
        stats = self.store.one(
            "SELECT SUM(status = 'done') AS served, SUM(source IN ('ussd','sms')) AS remote,"
            " SUM(source = 'walkin') AS walkin, COALESCE(SUM(paid_amount), 0) AS collected"
            " FROM tickets WHERE chamber_id = ? AND day = ?",
            (chamber["id"], day),
        ) or {}

        def row(t: dict[str, Any], ahead: int | None = None) -> dict[str, Any]:
            out = {
                "id": t["id"], "serial": t["serial"], "source": t["source"],
                "label": t["name"] or mask_phone(t["phone"]) or "Walk-in",
                "has_phone": bool(t["phone"]), "alerted": bool(t["alerted"]), "recalled": bool(t["priority"]),
            }
            if ahead is not None:
                out["ahead"] = ahead
                out["eta"] = self.eta_minutes(chamber, ahead, serving is not None)
            return out

        return {
            "chamber": {k: chamber[k] for k in ("code", "name", "doctor", "area", "fee", "alert_ahead")}
            | {"avg_minutes": round(chamber["avg_minutes"], 1), "is_open": bool(chamber["is_open"]),
               "dial": self.s.dial_string(chamber["code"])},
            "serving": row(serving) if serving else None,
            "waiting": [row(t, i) for i, t in enumerate(queue)],
            "skipped": [row(t) for t in skipped],
            "stats": {
                "served": stats.get("served") or 0,
                "remote": stats.get("remote") or 0,
                "walkin": stats.get("walkin") or 0,
                "collected": stats.get("collected") or 0,
            },
        }

    # ------------------------------------------------------------------ booking
    def book(self, chamber: dict[str, Any], phone: str | None = None, source: str = "ussd",
             name: str | None = None, paid: float = 0) -> tuple[dict[str, Any], bool]:
        """Give the next serial. Returns (ticket, created). A phone holds one active serial per chamber per day."""
        day = self.today()
        with self.store.tx() as c:
            if phone:
                existing = c.execute(
                    "SELECT * FROM tickets WHERE chamber_id = ? AND day = ? AND phone = ? AND status IN ('waiting','called')",
                    (chamber["id"], day, phone),
                ).fetchone()
                if existing:
                    return dict(existing), False
            serial = c.execute(
                "SELECT COALESCE(MAX(serial), 0) + 1 FROM tickets WHERE chamber_id = ? AND day = ?",
                (chamber["id"], day),
            ).fetchone()[0]
            tid = c.execute(
                "INSERT INTO tickets (chamber_id, day, serial, phone, name, source, status, paid_amount, created_at)"
                " VALUES (?,?,?,?,?,?,'waiting',?,?)",
                (chamber["id"], day, serial, phone, (name or "").strip() or None, source, paid, self.ts()),
            ).lastrowid
        ticket = self.ticket(tid)
        if phone:
            v = self.ticket_view(ticket)  # type: ignore[arg-type]
            doc = short(chamber["doctor"])
            if v["ahead"] <= chamber["alert_ahead"]:
                self.store.run("UPDATE tickets SET alerted = 1 WHERE id = ?", (tid,))
                msg = (f"SerialKoi: Serial {serial} confirmed - {doc}. "
                       f"{self._ahead_text(v['ahead'])} Please come now (~{v['eta']} min).")
            else:
                now = f"Now serving {v['now_serving']}." if v["now_serving"] else "Not started yet."
                msg = (f"SerialKoi: Serial {serial} confirmed - {doc}. {now} "
                       f"About {v['eta']} min. We will SMS when {chamber['alert_ahead']} are ahead. "
                       f"Check: {self.s.sms_keyword} STATUS")
            self.client.notify(phone, msg)
        return self.ticket(tid), True  # type: ignore[return-value]

    @staticmethod
    def _ahead_text(ahead: int) -> str:
        if ahead == 0:
            return "You are next."
        return f"{ahead} patient{'s' if ahead != 1 else ''} ahead of you."

    # ------------------------------------------------------------------ assistant actions
    def call_next(self, chamber: dict[str, Any], no_show: bool = False) -> dict[str, Any] | None:
        """Finish (or mark no-show) whoever is inside and call the next patient."""
        now = self.clock()
        outbox: list[tuple[str, str]] = []
        with self.store.tx() as c:
            cur = c.execute(
                "SELECT * FROM tickets WHERE chamber_id = ? AND day = ? AND status = 'called' ORDER BY called_at DESC, id DESC LIMIT 1",
                (chamber["id"], self.today()),
            ).fetchone()
            if cur:
                cur = dict(cur)
                if no_show:
                    c.execute("UPDATE tickets SET status = 'skipped', finished_at = ? WHERE id = ?", (now.isoformat(timespec="seconds"), cur["id"]))
                    if cur["phone"]:
                        outbox.append((cur["phone"], f"SerialKoi: You missed serial {cur['serial']} at {short(chamber['doctor'])}. "
                                                     "Tell the assistant when you arrive and you will be called next."))
                else:
                    c.execute("UPDATE tickets SET status = 'done', finished_at = ? WHERE id = ?", (now.isoformat(timespec="seconds"), cur["id"]))
                    self._learn_duration(c, chamber, cur, now)
            nxt = c.execute(
                "SELECT * FROM tickets WHERE chamber_id = ? AND day = ? AND status = 'waiting' ORDER BY priority DESC, serial ASC LIMIT 1",
                (chamber["id"], self.today()),
            ).fetchone()
            if nxt:
                nxt = dict(nxt)
                c.execute("UPDATE tickets SET status = 'called', called_at = ?, alerted = 1 WHERE id = ?", (now.isoformat(timespec="seconds"), nxt["id"]))
                if nxt["phone"]:
                    outbox.append((nxt["phone"], f"SerialKoi: It is your turn now - serial {nxt['serial']}, {short(chamber['doctor'])}. Please go in."))
        for phone, msg in outbox:
            self.client.notify(phone, msg)
        self.send_due_alerts(chamber)
        return self.ticket(nxt["id"]) if nxt else None

    def _learn_duration(self, c: sqlite3.Connection, chamber: dict[str, Any], ticket: dict[str, Any], now: datetime) -> None:
        """Moving average of real consultation times, so estimates match this doctor's pace."""
        if not ticket["called_at"]:
            return
        minutes = (now - datetime.fromisoformat(ticket["called_at"])).total_seconds() / 60
        if not 1 <= minutes <= 45:  # ignore accidental double taps and forgotten taps
            return
        avg = c.execute("SELECT avg_minutes FROM chambers WHERE id = ?", (chamber["id"],)).fetchone()[0]
        new_avg = min(40.0, max(2.0, 0.7 * avg + 0.3 * minutes))
        c.execute("UPDATE chambers SET avg_minutes = ? WHERE id = ?", (round(new_avg, 2), chamber["id"]))

    def send_due_alerts(self, chamber: dict[str, Any]) -> int:
        """SMS every waiting patient who is now within `alert_ahead` of the door, once."""
        chamber = self.chamber_by_id(chamber["id"])
        queue = self.waiting(chamber["id"])
        inside = self.serving(chamber["id"]) is not None
        due = [(i, t) for i, t in enumerate(queue) if i <= chamber["alert_ahead"] and not t["alerted"] and t["phone"]]
        for ahead, t in due:
            self.store.run("UPDATE tickets SET alerted = 1 WHERE id = ?", (t["id"],))
            eta = self.eta_minutes(chamber, ahead, inside)
            self.client.notify(
                t["phone"],
                f"SerialKoi: Serial {t['serial']} - {self._ahead_text(ahead)} "
                f"Please come to {short(chamber['doctor'])}'s chamber now (~{eta} min).",
            )
        return len(due)

    def recall(self, chamber: dict[str, Any], ticket_id: int) -> dict[str, Any]:
        """A no-show who has now arrived goes to the front of the line."""
        t = self.ticket(ticket_id)
        if not t or t["chamber_id"] != chamber["id"] or t["status"] != "skipped":
            raise QueueError("Only a missed serial can be recalled")
        self.store.run("UPDATE tickets SET status = 'waiting', priority = 1, alerted = 1, finished_at = NULL WHERE id = ?", (ticket_id,))
        return self.ticket(ticket_id)  # type: ignore[return-value]

    def cancel(self, ticket_id: int, phone: str | None = None) -> dict[str, Any]:
        t = self.ticket(ticket_id)
        if not t or t["status"] not in ACTIVE or (phone and t["phone"] != phone):
            raise QueueError("No active serial to cancel")
        self.store.run("UPDATE tickets SET status = 'cancelled', finished_at = ? WHERE id = ?", (self.ts(), ticket_id))
        self.send_due_alerts(self.chamber_by_id(t["chamber_id"]))
        return self.ticket(ticket_id)  # type: ignore[return-value]

    def walk_in(self, chamber: dict[str, Any], name: str = "", phone: str = "") -> dict[str, Any]:
        address = canonical_phone(phone) if phone.strip() else None
        ticket, _ = self.book(chamber, address, source="walkin", name=name or None)
        return ticket

    # ------------------------------------------------------------------ paid booking (CaaS + OTP)
    # Applink charging is two steps: /caas/direct/debit only sends the patient an OTP (P1003, nothing is
    # charged); the money moves at /caas/otp/verify; the charging notification is the final word.
    # Rules followed here (Applink-as-a-skill, references/05-caas.md): the payment row and its
    # externalTrxId are saved before the call, step 1 is never re-run to "retry", a timeout is left
    # UNKNOWN instead of being treated as a failure or a success, and a notification only books a serial
    # when paidAmount covers the fee with nothing due.

    def precheck(self, chamber: dict[str, Any], phone: str) -> dict[str, Any] | None:
        """Cheap local checks before any payment: closed | exists, or None if booking may go ahead."""
        chamber = self.chamber_by_id(chamber["id"])
        if not chamber["is_open"]:
            return {"result": "closed"}
        mine = [v for v in self.active_tickets(phone) if v["chamber"]["id"] == chamber["id"]]
        if mine:
            return {"result": "exists", "view": mine[0]}
        return None

    def start_booking(self, chamber: dict[str, Any], phone: str, source: str) -> dict[str, Any]:
        """Begin a remote booking. Results: booked | otp | exists | closed | error."""
        chamber = self.chamber_by_id(chamber["id"])
        blocked = self.precheck(chamber, phone)
        if blocked:
            return blocked
        if chamber["fee"] <= 0:
            ticket, _ = self.book(chamber, phone, source)
            return {"result": "booked", "view": self.ticket_view(ticket)}
        return self.start_payment(chamber, phone, source)

    def start_payment(self, chamber: dict[str, Any], phone: str, source: str) -> dict[str, Any]:
        """CaaS step 1. Results: otp | booked | error."""
        ext = f"SK{int(self.clock().timestamp())}{secrets.token_hex(3)}"
        pid = self.store.run(  # persist before the call, so every charge has a record
            "INSERT INTO payments (ext_trx_id, phone, chamber_id, source, amount, status, created_at, updated_at)"
            " VALUES (?,?,?,?,?,'pending',?,?)",
            (ext, phone, chamber["id"], source, chamber["fee"], self.ts(), self.ts()),
        )
        res = self.client.caas_debit(phone, chamber["fee"], ext)
        code = str(res.get("statusCode", ""))
        if code.startswith(("S", "P")):
            self.store.run(
                "UPDATE payments SET status = 'otp', reference = ?, internal_trx_id = ?, updated_at = ? WHERE id = ?",
                (res.get("requestCorrelator"), res.get("internalTrxId"), self.ts(), pid),
            )
            if code.startswith("S"):  # charged without an OTP step
                return self._complete_payment(pid)
            return {"result": "otp", "payment_id": pid}
        # A timeout may still have reached Applink; never resend step 1, leave it for reconciliation.
        status = "unknown" if code == "E-NET" else "failed"
        self.store.run("UPDATE payments SET status = ?, updated_at = ? WHERE id = ?", (status, self.ts(), pid))
        return {"result": "error", "code": code, "detail": res.get("statusDetail") or code}

    def pending_payment(self, phone: str) -> dict[str, Any] | None:
        cutoff = (self.clock() - timedelta(minutes=OTP_VALID_MINUTES)).isoformat(timespec="seconds")
        return self.store.one(
            "SELECT * FROM payments WHERE phone = ? AND status = 'otp' AND created_at >= ? ORDER BY id DESC LIMIT 1",
            (phone, cutoff),
        )

    def verify_payment(self, phone: str, otp: str) -> dict[str, Any]:
        """CaaS step 2. Results: booked | wrong_otp | failed | expired | no_balance | processing | no_pending."""
        p = self.pending_payment(phone)
        if not p:
            return {"result": "no_pending"}
        res = self.client.caas_verify(p["reference"] or "", otp, phone)
        code = str(res.get("statusCode", ""))
        if code.startswith("S"):
            return self._complete_payment(p["id"])
        if code.startswith("P") or code == "E-NET":
            return {"result": "processing"}  # the charging notification settles it; never re-run step 1
        if code in ("E1851", "E1326"):
            self.store.run("UPDATE payments SET status = 'failed', updated_at = ? WHERE id = ?", (self.ts(), p["id"]))
            return {"result": "expired" if code == "E1851" else "no_balance"}
        attempts = p["attempts"] + 1
        status = "failed" if attempts >= MAX_OTP_ATTEMPTS else "otp"
        self.store.run("UPDATE payments SET attempts = ?, status = ?, updated_at = ? WHERE id = ?", (attempts, status, self.ts(), p["id"]))
        if status == "failed":
            return {"result": "failed"}
        return {"result": "wrong_otp", "left": MAX_OTP_ATTEMPTS - attempts}

    def _complete_payment(self, payment_id: int) -> dict[str, Any]:
        with self.store.tx() as c:
            claimed = c.execute(
                "UPDATE payments SET status = 'paid', updated_at = ? WHERE id = ? AND status NOT IN ('paid', 'partial')",
                (self.ts(), payment_id),
            ).rowcount
        p = self.store.one("SELECT * FROM payments WHERE id = ?", (payment_id,))
        if not claimed:  # already settled by the other path (verify vs. notification)
            t = self.ticket(p["ticket_id"]) if p and p["ticket_id"] else None
            return {"result": "booked", "view": self.ticket_view(t)} if t else {"result": "processing"}
        chamber = self.chamber_by_id(p["chamber_id"])
        ticket, _ = self.book(chamber, p["phone"], p["source"], paid=p["amount"])
        self.store.run("UPDATE payments SET ticket_id = ? WHERE id = ?", (ticket["id"], payment_id))
        return {"result": "booked", "view": self.ticket_view(ticket)}

    def on_charging_notification(self, payload: dict[str, Any]) -> None:
        p = self.store.one("SELECT * FROM payments WHERE ext_trx_id = ?", (str(payload.get("externalTrxId", "")),))
        if not p:
            return
        if str(payload.get("statusCode", "")).startswith("S"):
            paid, due = _money(payload.get("paidAmount"), p["amount"]), _money(payload.get("balanceDue"), 0)
            if paid >= Decimal(str(p["amount"])) and due == 0:
                self._complete_payment(p["id"])
            elif p["status"] != "paid":
                self.store.run("UPDATE payments SET status = 'partial', updated_at = ? WHERE id = ?", (self.ts(), p["id"]))
        elif p["status"] in ("otp", "pending", "unknown"):
            self.store.run("UPDATE payments SET status = 'failed', updated_at = ? WHERE id = ?", (self.ts(), p["id"]))


def _money(value: Any, default: Any) -> Decimal:
    try:
        return Decimal(str(value if value not in (None, "") else default))
    except InvalidOperation:
        return Decimal(str(default))
