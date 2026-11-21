from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.service import DHAKA, QueueError, canonical_phone, mask_phone
from app.sms import handle_sms
from app.ussd import code_from_dial

A = "tel:8801911000001"
B = "tel:8801911000002"
C = "tel:8801911000003"


class Clock:
    def __init__(self) -> None:
        self.t = datetime(2026, 11, 24, 17, 0, tzinfo=DHAKA)

    def __call__(self) -> datetime:
        return self.t

    def advance(self, minutes: float) -> None:
        self.t += timedelta(minutes=minutes)


@pytest.fixture
def env(tmp_path):
    clock = Clock()
    settings = Settings(mode="sim", db_path=str(tmp_path / "t.db"), secret="test", admin_key="adm", seed_demo=True)
    app = create_app(settings, clock)
    svc = app.state.svc
    return {"app": app, "svc": svc, "ussd": app.state.ussd, "clock": clock, "http": TestClient(app),
            "chamber": svc.chamber("4521")}


def sms_to(svc, phone):
    return [m["body"] for m in svc.store.all("SELECT body FROM messages WHERE address = ? AND kind = 'sms' AND direction = 'out' ORDER BY id", (phone,))]


def otp_for(svc, phone):
    return svc.store.one("SELECT otp FROM sim_otps WHERE phone = ? ORDER BY rowid DESC LIMIT 1", (phone,))["otp"]


# ---------------------------------------------------------------- helpers
def test_phone_formats():
    assert canonical_phone("tel:+8801959979376") == "tel:8801959979376"
    assert canonical_phone("tel: +8801959979376 ") == "tel:8801959979376"
    assert canonical_phone("01712345678") == "tel:8801712345678"
    assert canonical_phone("tel:pAsSwOrDmAsKeD") == "tel:pAsSwOrDmAsKeD"
    with pytest.raises(QueueError):
        canonical_phone("12345")
    assert mask_phone("tel:8801712345678") == "017-xxxxx-678"
    assert mask_phone("tel:maskedvalue") == "Banglalink user"


def test_dial_string_parsing():
    assert code_from_dial("*213*4521#") == "4521"
    assert code_from_dial("*213#") is None
    assert Settings(ussd_code="*213#").dial_string("4521") == "*213*4521#"
    # Applink-style service code + keyword: a 4-digit keyword must not be read as a chamber code
    assert code_from_dial("*383*7777#", "*383*7777#") is None
    assert code_from_dial("*383*7777*4521#", "*383*7777#") == "4521"
    assert Settings(ussd_code="*383*7777#").dial_string("4521") == "*383*7777*4521#"


def test_every_sms_fits_one_part(env):
    """Applink splits long SMS and the subscriber can be charged per part, so keep each under 160."""
    svc, ussd, ch = env["svc"], env["ussd"], env["chamber"]
    svc.store.run("UPDATE chambers SET doctor = 'Dr. Mohammad Shahidul Islam Chowdhury' WHERE id = ?", (ch["id"],))
    ch = svc.chamber("4521")
    for i in range(5):
        svc.walk_in(ch, f"W{i}")
    ussd.handle("x1", A, "mo-init", "*213*4521#")
    ussd.handle("x1", A, "mo-cont", "1")
    handle_sms(svc, A, f"SK {otp_for(svc, A)}")
    svc.book(ch, B)
    for _ in range(6):
        svc.call_next(ch)  # ends with A (serial 6) called
    svc.call_next(ch, no_show=True)  # A missed, B called
    bodies = [m["body"] for m in svc.store.all("SELECT body FROM messages WHERE kind = 'sms' AND direction = 'out'")]
    assert len(bodies) >= 7  # confirmations, come-now alerts, your-turn, missed
    too_long = [b for b in bodies if len(b) > 160]
    assert not too_long, too_long


# ---------------------------------------------------------------- queue
def test_serials_are_sequential_and_one_per_phone(env):
    svc, ch = env["svc"], env["chamber"]
    t1, new1 = svc.book(ch, A)
    t2, _ = svc.book(ch, B)
    again, new_again = svc.book(ch, A)
    walk = svc.walk_in(ch, "Rahima")
    assert (t1["serial"], t2["serial"], walk["serial"]) == (1, 2, 3)
    assert new1 and not new_again and again["id"] == t1["id"]


def test_next_learns_consultation_time_and_eta(env):
    svc, ch, clock = env["svc"], env["chamber"], env["clock"]
    for i in range(5):
        svc.walk_in(ch, f"P{i}")
    svc.call_next(ch)
    clock.advance(12)
    svc.call_next(ch)  # serial 1 took 12 min -> avg 0.7*7 + 0.3*12 = 8.5
    assert svc.chamber("4521")["avg_minutes"] == pytest.approx(8.5)
    snap = svc.snapshot(ch)
    assert snap["serving"]["serial"] == 2
    assert [w["serial"] for w in snap["waiting"]] == [3, 4, 5]
    assert snap["waiting"][2]["eta"] == round(2.5 * 8.5)  # 2 ahead + half of the one inside


def test_ignores_accidental_double_tap(env):
    svc, ch, clock = env["svc"], env["chamber"], env["clock"]
    svc.walk_in(ch, "x"); svc.walk_in(ch, "y"); svc.walk_in(ch, "z")
    svc.call_next(ch)
    clock.advance(0.2)
    svc.call_next(ch)
    assert svc.chamber("4521")["avg_minutes"] == 7


def test_alert_sent_once_when_three_ahead(env):
    svc, ch = env["svc"], env["chamber"]
    for i in range(4):
        svc.walk_in(ch, f"W{i}")
    t, _ = svc.book(ch, A)  # serial 5, 4 ahead -> no "come now" yet
    assert "We will SMS when 3 are ahead" in sms_to(svc, A)[-1]
    svc.call_next(ch)  # W0 inside, 3 ahead of A
    msgs = sms_to(svc, A)
    assert "3 patients ahead" in msgs[-1] and "come" in msgs[-1]
    svc.call_next(ch)
    assert len([m for m in sms_to(svc, A) if "ahead of you" in m]) == 1
    svc.call_next(ch); svc.call_next(ch); svc.call_next(ch)
    assert "It is your turn now" in sms_to(svc, A)[-1]


def test_no_show_then_recall_goes_first(env):
    svc, ch = env["svc"], env["chamber"]
    a, _ = svc.book(ch, A)
    svc.walk_in(ch, "b"); svc.walk_in(ch, "c")
    svc.call_next(ch)                 # A called
    svc.call_next(ch, no_show=True)   # A missed -> b called
    assert "You missed serial 1" in sms_to(svc, A)[-1]
    svc.recall(ch, a["id"])
    svc.call_next(ch)                 # A goes before c
    assert svc.snapshot(ch)["serving"]["serial"] == 1
    with pytest.raises(QueueError):
        svc.recall(ch, a["id"])


def test_cancel_moves_people_up_and_alerts(env):
    svc, ch = env["svc"], env["chamber"]
    first, _ = svc.book(ch, B)
    for i in range(3):
        svc.walk_in(ch, f"W{i}")
    svc.book(ch, A)  # 4 ahead
    before = len(sms_to(svc, A))
    svc.cancel(first["id"], phone=B)
    assert len(sms_to(svc, A)) == before + 1 and "3 patients ahead" in sms_to(svc, A)[-1]
    with pytest.raises(QueueError):
        svc.cancel(first["id"], phone=B)


# ---------------------------------------------------------------- USSD + CaaS
def wrong_code(svc, phone):
    return "000000" if otp_for(svc, phone) != "000000" else "111111"


def test_ussd_ends_session_before_charging_then_sms_code_books(env):
    """Applink: charging cannot happen inside a USSD session. The menu ends, then the charge starts."""
    svc, ussd = env["svc"], env["ussd"]
    svc.walk_in(env["chamber"], "already here")
    text, op = ussd.handle("s1", "tel:+8801911000001", "mo-init", "*213*4521#")
    assert op == "mt-cont" and "Dr. Farhana Rahman" in text and "Waiting: 1" in text and "Tk5" in text
    text, op, after = ussd.handle_full("s1", "tel:+8801911000001", "mo-cont", "1")
    assert op == "mt-fin" and "SK <code>" in text and len(text) <= 160
    assert svc.store.one("SELECT COUNT(*) AS n FROM payments")["n"] == 0  # nothing started before the screen
    after()
    assert svc.store.one("SELECT status, reference FROM payments")["status"] == "otp"
    assert "Wrong code, 2 tries left" in handle_sms(svc, A, f"SK {wrong_code(svc, A)}")
    assert handle_sms(svc, A, f"SK {otp_for(svc, A)}") == ""
    assert "Serial 2 confirmed" in sms_to(svc, A)[-1]
    assert svc.store.one("SELECT paid_amount FROM tickets WHERE phone = ?", (A,))["paid_amount"] == 5


def test_ussd_redial_option_4_takes_the_code(env):
    svc, ussd = env["svc"], env["ussd"]
    ussd.handle("s1", A, "mo-init", "*213*4521#")
    ussd.handle("s1", A, "mo-cont", "1")
    text, _ = ussd.handle("s2", A, "mo-init", "*213#")
    assert "4. Enter payment code" in text
    ussd.handle("s2", A, "mo-cont", "4")
    text, op = ussd.handle("s2", A, "mo-cont", otp_for(svc, A))
    assert op == "mt-fin" and "Serial 1 confirmed" in text


def test_ussd_menu_status_and_cancel(env):
    ussd, svc = env["ussd"], env["svc"]
    text, _ = ussd.handle("s2", A, "mo-init", "*213#")
    assert "1. Get a serial" in text
    text, _ = ussd.handle("s2", A, "mo-cont", "2")
    assert "no serial" in text
    svc.book(env["chamber"], A)
    ussd.handle("s3", A, "mo-init", "*213#")
    text, op = ussd.handle("s3", A, "mo-cont", "3")
    assert "Cancel serial 1" in text
    text, op = ussd.handle("s3", A, "mo-cont", "1")
    assert op == "mt-fin" and "cancelled" in text
    assert svc.active_tickets(A) == []


def test_ussd_closed_chamber_and_existing_serial(env):
    ussd, svc, ch = env["ussd"], env["svc"], env["chamber"]
    svc.book(ch, A)
    text, op = ussd.handle("s4", A, "mo-init", "*213*4521#")
    assert op == "mt-fin" and "Serial 1" in text
    svc.set_open(ch, False)
    text, op = ussd.handle("s5", B, "mo-init", "*213*4521#")
    assert op == "mt-fin" and "not taking serials" in text


def test_three_wrong_codes_fails_without_booking(env):
    ussd, svc = env["ussd"], env["svc"]
    ussd.handle("s6", A, "mo-init", "*213*4521#")
    ussd.handle("s6", A, "mo-cont", "1")
    wrong = wrong_code(svc, A)
    handle_sms(svc, A, f"SK {wrong}")
    handle_sms(svc, A, f"SK {wrong}")
    assert "Too many" in handle_sms(svc, A, f"SK {wrong}")
    assert svc.active_tickets(A) == []


def test_otp_expires_after_five_minutes(env):
    ussd, svc, clock = env["ussd"], env["svc"], env["clock"]
    ussd.handle("s7", A, "mo-init", "*213*4521#")
    ussd.handle("s7", A, "mo-cont", "1")
    clock.advance(6)
    assert "No payment is waiting" in handle_sms(svc, A, f"SK {otp_for(svc, A)}")
    assert svc.active_tickets(A) == []


# ---------------------------------------------------------------- Applink charging rules (references/05-caas.md)
def caas_responses(monkeypatch, svc, debit=None, verify=None):
    """Make the simulated CaaS answer with given status codes."""
    real_debit, real_verify = svc.client.caas_debit, svc.client.caas_verify
    if debit:
        monkeypatch.setattr(svc.client, "caas_debit", lambda *a: {"statusCode": debit, "statusDetail": debit})
    if verify:
        monkeypatch.setattr(svc.client, "caas_verify", lambda *a: {"statusCode": verify, "statusDetail": verify})
    return real_debit, real_verify


def test_payment_row_saved_before_the_debit_call(env, monkeypatch):
    svc = env["svc"]
    seen = []
    real = svc.client.caas_debit

    def spy(address, amount, ext):
        seen.append(svc.store.one("SELECT status FROM payments WHERE ext_trx_id = ?", (ext,)))
        return real(address, amount, ext)

    monkeypatch.setattr(svc.client, "caas_debit", spy)
    svc.start_payment(env["chamber"], A, "ussd")
    assert seen == [{"status": "pending"}]


def test_debit_timeout_is_unknown_and_never_retried(env, monkeypatch):
    svc = env["svc"]
    caas_responses(monkeypatch, svc, debit="E-NET")
    r = svc.start_payment(env["chamber"], A, "ussd")
    assert r["result"] == "error"
    assert svc.store.one("SELECT status FROM payments")["status"] == "unknown"
    assert svc.store.one("SELECT COUNT(*) AS n FROM payments")["n"] == 1


def test_verify_timeout_does_not_count_as_wrong_code(env, monkeypatch):
    svc = env["svc"]
    svc.start_payment(env["chamber"], A, "ussd")
    caas_responses(monkeypatch, svc, verify="E-NET")
    for _ in range(4):
        assert svc.verify_payment(A, "123456")["result"] == "processing"
    assert svc.store.one("SELECT attempts, status FROM payments") == {"attempts": 0, "status": "otp"}


@pytest.mark.parametrize("code,result,reply", [("E1851", "expired", "expired"), ("E1326", "no_balance", "Not enough balance")])
def test_expired_code_and_low_balance_stop_the_payment(env, monkeypatch, code, result, reply):
    svc = env["svc"]
    svc.start_payment(env["chamber"], A, "ussd")
    caas_responses(monkeypatch, svc, verify=code)
    assert svc.verify_payment(A, "123456")["result"] == result
    assert svc.pending_payment(A) is None
    svc.start_payment(env["chamber"], A, "ussd")
    assert reply in handle_sms(svc, A, "SK 123456")


def test_partial_payment_does_not_book(env):
    http, svc = env["http"], env["svc"]
    svc.start_payment(env["chamber"], A, "ussd")
    ext = svc.store.one("SELECT ext_trx_id FROM payments")["ext_trx_id"]
    http.post("/caas/chargingNotification", json={"externalTrxId": ext, "statusCode": "S1000", "paidAmount": "2.00", "balanceDue": "3.00"})
    assert svc.store.one("SELECT status FROM payments")["status"] == "partial"
    assert svc.active_tickets(A) == []


# ---------------------------------------------------------------- callback contract (references/07-callbacks.md)
def test_callbacks_always_ack_even_for_junk(env):
    http = env["http"]
    for path in ("/ussd/receive", "/sms/receive", "/sms/report", "/caas/chargingNotification"):
        for body in (b"not json", b"[1,2]", b"{}"):
            r = http.post(path, content=body, headers={"Content-Type": "application/json"})
            assert r.status_code == 200 and r.json()["statusCode"] == "S1000", (path, body)


def test_redelivered_callbacks_are_processed_once(env):
    http, svc = env["http"], env["svc"]
    body = {"sourceAddress": "tel:+8801911000003", "message": "SK STATUS", "requestId": "R-1", "encoding": "0"}
    http.post("/sms/receive", json=body)
    http.post("/sms/receive", json=body)
    assert len(sms_to(svc, C)) == 1
    ussd_body = {"version": "1.0", "applicationId": "APP_000000", "message": "*213#", "requestId": "U-1", "sessionId": "9",
                 "ussdOperation": "mo-init", "sourceAddress": "tel:+8801911000001", "encoding": "440"}
    http.post("/ussd/receive", json=ussd_body)
    http.post("/ussd/receive", json=ussd_body)
    assert svc.store.one("SELECT COUNT(*) AS n FROM messages WHERE kind = 'ussd'")["n"] == 1


def test_payment_codes_never_reach_the_log(env):
    http, svc = env["http"], env["svc"]
    http.post("/sms/receive", json={"sourceAddress": "tel:+8801911000003", "message": "SK 482913", "requestId": "R-2"})
    logged = svc.store.one("SELECT body FROM messages WHERE direction = 'in' AND kind = 'sms'")["body"]
    assert "482913" not in logged and "******" in logged


def test_live_mode_ignores_other_apps_and_uses_secret_path(tmp_path):
    s = Settings(mode="live", app_id="APP_123", password="k", db_path=str(tmp_path / "l.db"), seed_demo=False,
                 callback_prefix="/cb/s3cret")
    app = create_app(s, Clock())
    http = TestClient(app)
    other = {"applicationId": "APP_999", "message": "*213#", "requestId": "1", "sessionId": "1",
             "ussdOperation": "mo-init", "sourceAddress": "tel:8801911000001"}
    assert http.post("/cb/s3cret/ussd/receive", json=other).json()["statusCode"] == "S1000"
    assert app.state.svc.store.one("SELECT COUNT(*) AS n FROM ussd_sessions")["n"] == 0
    assert http.post("/ussd/receive", json=other).status_code == 404  # only the secret path exists


def test_every_ussd_screen_fits_160(env):
    svc, ussd, ch = env["svc"], env["ussd"], env["chamber"]
    svc.store.run("UPDATE chambers SET doctor = ?, name = ? WHERE id = ?",
                  ("Professor Dr. Mohammad Shahidul Islam Chowdhury", "Bangladesh Specialized Medicine & Diabetes Care Chamber", ch["id"]))
    for i in range(12):
        svc.walk_in(ch, f"W{i}")
    screens = [ussd.handle("t1", A, "mo-init", "*213#")[0], ussd.handle("t1", A, "mo-cont", "1")[0],
               ussd.handle("t1", A, "mo-cont", "4521")[0], ussd.handle("t1", A, "mo-cont", "1")[0],
               ussd.handle("t2", A, "mo-init", "*213#")[0], ussd.handle("t2", A, "mo-cont", "4")[0]]
    assert all(len(s) <= 160 for s in screens), [len(s) for s in screens]


# ---------------------------------------------------------------- SMS
def test_sms_booking_status_cancel(env):
    http, svc = env["http"], env["svc"]
    http.post("/sms/receive", json={"sourceAddress": "tel:+8801911000003", "message": "SK 4521", "requestId": "1", "encoding": "0"})
    assert "reply SK <code>" in sms_to(svc, C)[-1]
    http.post("/sms/receive", json={"sourceAddress": "tel:+8801911000003", "message": f"sk {otp_for(svc, C)}"})
    assert "Serial 1 confirmed" in sms_to(svc, C)[-1]
    http.post("/sms/receive", json={"sourceAddress": "tel:+8801911000003", "message": "SK STATUS"})
    assert "Serial 1" in sms_to(svc, C)[-1]
    http.post("/sms/receive", json={"sourceAddress": "tel:+8801911000003", "message": "SK CANCEL"})
    assert "cancelled" in sms_to(svc, C)[-1]
    http.post("/sms/receive", json={"sourceAddress": "tel:+8801911000003", "message": "hello"})
    assert "Dial *213#" in sms_to(svc, C)[-1]


def test_charging_notification_completes_payment_once(env):
    http, svc = env["http"], env["svc"]
    svc.start_booking(env["chamber"], A, "ussd")
    ext = svc.store.one("SELECT ext_trx_id FROM payments")["ext_trx_id"]
    for _ in range(2):
        r = http.post("/caas/chargingNotification", json={"externalTrxId": ext, "statusCode": "S1000", "paidAmount": "5.00"})
        assert r.json()["statusCode"] == "S1000"
    assert len(svc.active_tickets(A)) == 1
    assert svc.verify_payment(A, otp_for(svc, A))["result"] == "no_pending"


# ---------------------------------------------------------------- HTTP API
def test_ussd_callback_acks_and_replies(env):
    http, svc = env["http"], env["svc"]
    r = http.post("/ussd/receive", json={"version": "1.0", "applicationId": "APP_000000", "message": "*213#", "requestId": "9",
                                         "sessionId": "777", "ussdOperation": "mo-init", "sourceAddress": "tel:+8801911000001",
                                         "encoding": "440"})
    assert r.json() == {"statusCode": "S1000", "statusDetail": "Success"}
    sent = svc.store.one("SELECT * FROM messages WHERE kind = 'ussd' ORDER BY id DESC LIMIT 1")
    assert sent["address"] == A and sent["status"] == "mt-cont" and "Get a serial" in sent["body"]


def test_assistant_api_requires_login(env):
    http = env["http"]
    assert http.get("/api/chamber/4521").status_code == 401
    assert http.post("/api/login", json={"code": "4521", "pin": "0000"}).status_code == 401
    token = http.post("/api/login", json={"code": "4521", "pin": "2468"}).json()["token"]
    h = {"X-Token": token}
    http.post("/api/chamber/4521/walkin", json={"name": "Rahima", "phone": ""}, headers=h)
    http.post("/api/chamber/4521/walkin", json={"name": "Karim", "phone": "01911000002"}, headers=h)
    snap = http.post("/api/chamber/4521/next", headers=h).json()
    assert snap["serving"]["label"] == "Rahima" and snap["waiting"][0]["label"] == "Karim"
    assert http.post("/api/chamber/4521/walkin", json={"phone": "123"}, headers=h).status_code == 400
    pub = http.get("/api/public/4521").json()
    assert pub["serving"] == 1 and pub["next"] == [2] and pub["chamber"]["dial"] == "*213*4521#"


def test_admin_creates_chamber(env):
    http = env["http"]
    body = {"code": "7310", "name": "Rampura Child Care", "doctor": "Dr. Test", "pin": "1357"}
    assert http.post("/api/admin/chambers", json=body).status_code == 403
    r = http.post("/api/admin/chambers", json=body, headers={"X-Admin-Key": "adm"})
    assert r.json() == {"code": "7310", "dial": "*213*7310#"}


# ---------------------------------------------------------------- live client request shapes
def test_live_client_matches_applink_docs(env, monkeypatch):
    from app import applink

    calls = []

    class Resp:
        def __init__(self, data):
            self._d = data

        def json(self):
            return self._d

    def fake_post(url, json, headers, timeout):
        calls.append((url, json))
        if url.endswith("/caas/direct/debit"):
            return Resp({"statusCode": "P1003", "requestCorrelator": "REF1", "externalTrxId": json["externalTrxId"]})
        return Resp({"statusCode": "S1000"})

    monkeypatch.setattr(applink.httpx, "post", fake_post)
    s = Settings(mode="live", app_id="APP_123", password="key", db_path=":memory:")
    from app.db import Store
    client = applink.ApplinkClient(s, Store(":memory:"), env["clock"])
    client.send_sms(A, "hi")
    client.send_ussd("55", A, "menu", "mt-cont")
    client.caas_debit(A, 5, "SK1")
    client.caas_verify("REF1", "123456", A)
    urls = [u for u, _ in calls]
    assert urls == ["https://api.applink.com.bd/sms/send", "https://api.applink.com.bd/ussd/send",
                    "https://api.applink.com.bd/caas/direct/debit", "https://api.applink.com.bd/caas/otp/verify"]
    sms, ussd_body, debit, verify = (b for _, b in calls)
    assert sms["applicationId"] == "APP_123" and sms["password"] == "key" and sms["destinationAddresses"] == [A]
    assert ussd_body["sessionId"] == "55" and ussd_body["ussdOperation"] == "mt-cont" and ussd_body["encoding"] == "440"
    assert debit == {"applicationId": "APP_123", "password": "key", "externalTrxId": "SK1", "amount": "5.00",
                     "paymentInstrumentName": "Mobile Account", "subscriberId": A, "Currency": "BDT"}
    assert verify["referenceNo"] == "REF1" and verify["otp"] == "123456" and verify["sourceAddress"] == A


# ---------------------------------------------------------------- poster
def test_poster_shows_this_chambers_code_and_a_qr(env):
    http = env["http"]
    r = http.get("/poster/4521")
    assert r.status_code == 200
    page = r.text
    assert "*213*4521#" in page and "Dr. Farhana Rahman" in page and "৳৫" in page
    assert "<svg" in page and "/display/4521" not in page.split("<svg")[0][-200:]  # QR is drawn, not a bare link
    assert http.get("/poster/9999").status_code == 404


def test_poster_escapes_chamber_text(env):
    svc, http = env["svc"], env["http"]
    svc.create_chamber("7777", "<script>x</script>", "Dr. <b>Bold</b>", "1357")
    page = http.get("/poster/7777").text
    assert "<script>x</script>" not in page and "&lt;script&gt;" in page
