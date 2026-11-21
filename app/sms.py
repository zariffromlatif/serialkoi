"""Inbound SMS commands: '<KW> 4521' books, '<KW> 123456' pays, '<KW> STATUS', '<KW> CANCEL'."""
from __future__ import annotations

from .service import QueueError, Service, canonical_phone, short


def handle_sms(svc: Service, source: str, text: str) -> str:
    phone = canonical_phone(source)
    kw = svc.s.sms_keyword
    words = (text or "").strip().split()
    if words and words[0].upper() == kw:
        words = words[1:]
    if words and words[0].upper() == "PAY":
        words = words[1:]
    cmd = words[0].upper() if words else ""

    if cmd.isdigit() and len(cmd) == 6:
        r = svc.verify_payment(phone, cmd)
        if r["result"] == "booked":
            return ""  # book() already sent the confirmation SMS
        if r["result"] == "wrong_otp":
            return f"SerialKoi: Wrong code, {r['left']} tries left. Reply {kw} <6-digit code>."
        if r["result"] == "processing":
            return "SerialKoi: Payment is processing. Your serial will arrive shortly."
        if r["result"] == "failed":
            return "SerialKoi: Too many wrong codes. No serial was booked."
        if r["result"] == "expired":
            return f"SerialKoi: That code expired. No money was taken. SMS {kw} <chamber code> to try again."
        if r["result"] == "no_balance":
            return "SerialKoi: Not enough balance. No serial was booked. Please recharge and try again."
        return f"SerialKoi: No payment is waiting for a code. To book, SMS {kw} <4-digit chamber code>."

    if cmd.isdigit() and len(cmd) == 4:
        chamber = svc.chamber(cmd)
        if not chamber:
            return f"SerialKoi: No chamber with code {cmd}. Check the code on the chamber poster."
        r = svc.start_booking(chamber, phone, "sms")
        if r["result"] == "booked":
            return ""
        if r["result"] == "exists":
            v = r["view"]
            return f"SerialKoi: You already have serial {v['ticket']['serial']} at {short(chamber['doctor'])}. {v['ahead']} ahead, ~{v['eta']} min."
        if r["result"] == "closed":
            return f"SerialKoi: {short(chamber['doctor'])} is not taking serials right now."
        if r["result"] == "otp":
            return (f"SerialKoi: To book {short(chamber['doctor'])} (Tk{chamber['fee']:g}), reply {kw} <code> "
                    "with the 6-digit code AppLink just sent you. Valid 5 min.")
        return "SerialKoi: Payment could not start. No money was taken. Please try later."

    if cmd in ("STATUS", "S"):
        views = svc.active_tickets(phone)
        if not views:
            return "SerialKoi: You have no serial today."
        parts = []
        for v in views[:1]:
            t = v["ticket"]
            if t["status"] == "called":
                parts.append(f"Serial {t['serial']} ({short(v['chamber']['doctor'])}): your turn now, please go in.")
            else:
                parts.append(f"Serial {t['serial']} ({short(v['chamber']['doctor'])}): now serving {v['now_serving'] or '-'}, "
                             f"{v['ahead']} ahead, ~{v['eta']} min.")
        return "SerialKoi: " + " ".join(parts)

    if cmd in ("CANCEL", "C"):
        views = svc.active_tickets(phone)
        if not views:
            return "SerialKoi: You have no serial to cancel."
        try:
            t = svc.cancel(views[-1]["ticket"]["id"], phone=phone)
        except QueueError:
            return "SerialKoi: Could not cancel. Please call the chamber."
        return f"SerialKoi: Serial {t['serial']} cancelled."

    return (f"SerialKoi: Dial {svc.s.ussd_code} or SMS {kw} <chamber code> to get a doctor's serial. "
            f"{kw} STATUS to check, {kw} CANCEL to cancel.")
