"""Check the live Applink connection from the server.

Usually run through the helper:  sudo serialkoi check | sms 019XXXXXXXX | inbox [n]
"""
from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

EXPLAIN = {
    "S1000": "Success.",
    "E1303": "This server's IP is not in the app's 'Allowed Host Address(es)'. Add {ip} in the Applink form.",
    "E1308": "Charging failed, usually not enough balance on the receiving SIM.",
    "E1309": "SMS is not allowed for this app yet. Ask Applink support.",
    "E1311": "Sending SMS is not enabled for this app. Check the SMS settings in the Applink form.",
    "E1312": "Applink rejected the request format. Send the output above to Applink support.",
    "E1313": "Wrong APPLINK_APP_ID or APPLINK_PASSWORD, or the app is not approved/active yet.",
    "E1317": "That number is not allowed.",
    "E1318": "Too many requests per second.",
    "E1319": "Daily sending limit reached.",
    "E1325": "Number format rejected (expected tel:8801XXXXXXXXX).",
    "E1342": "That number is blacklisted for this app.",
    "E1343": "That number is not whitelisted. Add it under 'Whitelisted Numbers' while the app is in limited production.",
    "E-NET": "Could not reach api.applink.com.bd from this server.",
}
OK, BAD, WARN = "\033[32mOK\033[0m", "\033[31mFAIL\033[0m", "\033[33m!!\033[0m"


def load_env(path: str) -> None:
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ[key.strip()] = value.strip()


def http(url: str, body: dict | None = None, timeout: float = 10) -> tuple[int, str]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context()) as r:
            return r.status, r.read().decode(errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")
    except Exception as e:  # DNS, TLS, timeout
        return 0, str(e)


def public_ip() -> str:
    for url in ("https://api.ipify.org", "https://ifconfig.me/ip"):
        status, text = http(url)
        if status == 200 and text.strip():
            return text.strip()
    return "unknown"


def public_base(caddyfile: str = "/etc/caddy/Caddyfile") -> str | None:
    try:
        for line in Path(caddyfile).read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and line.endswith("{") and not line.startswith("{"):
                return "https://" + line[:-1].strip()
    except OSError:
        pass
    return None


def explain(code: str, ip: str = "") -> str:
    return EXPLAIN.get(code, "See https://dev.applink.com.bd/docs/status-codes").format(ip=ip)


def cmd_check(args: argparse.Namespace) -> int:
    from app.config import Settings

    s = Settings.from_env()
    ip = public_ip()
    problems = 0
    print(f"Mode:            {s.mode}")
    print(f"Application ID:  {s.app_id}")
    print(f"API key set:     {'yes' if s.password else 'no'}")
    print(f"USSD code:       {s.ussd_code}   (patients dial {s.dial_string('1001')} for chamber 1001)")
    print(f"SMS keyword:     {s.sms_keyword}")
    print(f"Database:        {s.db_path}")
    print(f"Public IP:       {ip}   <- must be in 'Allowed Host Address(es)'")
    if s.mode != "live":
        print(f"{WARN} SK_MODE is not 'live': nothing will be sent to Applink."); problems += 1
    if s.app_id == "APP_000000" or not s.password:
        print(f"{WARN} Waiting for Applink approval: put APPLINK_APP_ID and APPLINK_PASSWORD in {args.env},"
              " then run: sudo systemctl restart serialkoi@live")
        problems += 1
    if s.ussd_code == "*213#":
        print(f"{WARN} SK_USSD_CODE is still the placeholder *213#. Use the service code + keyword Applink gives you.")

    port = os.environ.get("SK_PORT", "8791")
    status, _ = http(f"http://127.0.0.1:{port}/healthz")
    print(f"{OK if status == 200 else BAD} App answers on port {port}"); problems += status != 200

    base = args.url or public_base()
    if not base:
        print(f"{WARN} Could not find the public address in /etc/caddy/Caddyfile; pass --url https://your-domain")
        return 1
    sample = {
        "/sms/report": {"destinationAddress": "tel:8801900000000", "timeStamp": "20261120120000", "requestId": "selftest", "deliveryStatus": "DELIVERED"},
        "/caas/chargingNotification": {"externalTrxId": "selftest", "statusCode": "S1000"},
    }
    prefix = s.callback_prefix
    for path, body in sample.items():
        status, text = http(base + prefix + path, body)
        good = status == 200 and '"S1000"' in text
        print(f"{OK if good else BAD} {base}{prefix}{path} reachable over HTTPS" + ("" if good else f"  ({status} {text[:120]})"))
        problems += not good
    print("\nAll good." if not problems else f"\n{problems} thing(s) to look at above.")
    return 0 if not problems else 1


def cmd_sms(args: argparse.Namespace) -> int:
    from app.applink import ApplinkClient
    from app.config import Settings
    from app.db import Store
    from app.service import canonical_phone, now_dhaka

    s = Settings.from_env()
    if s.mode != "live":
        print(f"{WARN} SK_MODE={s.mode}: the message will only be stored locally, not sent.")
    try:
        to = canonical_phone(args.number)
    except Exception as exc:
        print(f"{BAD} {exc}")
        return 2
    text = " ".join(args.text) or "SerialKoi test: if you can read this, the Applink connection works."
    res = ApplinkClient(s, Store(s.db_path), now_dhaka).send_sms(to, text)
    print(json.dumps(res, indent=2))
    ip = public_ip()
    codes = [str(res.get("statusCode", ""))] + [str(d.get("statusCode", "")) for d in res.get("destinationResponses", [])]
    for code in dict.fromkeys(c for c in codes if c):
        print(f"{OK if code.startswith('S') else BAD} {code}: {explain(code, ip)}")
    return 0 if str(res.get("statusCode", "")).startswith("S") else 1


def cmd_inbox(args: argparse.Namespace) -> int:
    from app.config import Settings
    from app.db import Store

    s = Settings.from_env()
    rows = Store(s.db_path).all("SELECT * FROM messages ORDER BY id DESC LIMIT ?", (args.n,))
    if not rows:
        print("No messages yet.")
    for r in reversed(rows):
        arrow = "->" if r["direction"] == "out" else "<-"
        print(f"{r['created_at']}  {arrow} {r['kind']:<6} {r['address'] or '':<18} [{r['status']}] {r['body']}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--env", default="/etc/serialkoi/live.env", help="settings file of the live app")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="settings, public IP and callback reachability")
    c.add_argument("--url", help="public base URL, e.g. https://1-2-3-4.sslip.io")
    m = sub.add_parser("sms", help="send a real test SMS through Applink")
    m.add_argument("number", help="Banglalink number, e.g. 019XXXXXXXX (must be whitelisted)")
    m.add_argument("text", nargs="*")
    i = sub.add_parser("inbox", help="recent messages and callbacks")
    i.add_argument("n", nargs="?", type=int, default=20)
    args = p.parse_args()
    load_env(args.env)
    return {"check": cmd_check, "sms": cmd_sms, "inbox": cmd_inbox}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
