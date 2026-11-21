# SerialKoi (সিরিয়াল কই?)

**A doctor's serial from any phone, so patients wait at home instead of in the chamber.**

In Bangladesh, a patient at a private doctor's chamber usually takes a serial in person or by phone, then
waits two to four hours on a bench without knowing when their turn will come. SerialKoi turns that wait
into an SMS:

1. **Book.** The patient dials the code on the chamber poster (for example `*213*4521#`) from any phone,
   including a button phone. The menu shows who is being seen now, how many are waiting and the estimated
   wait. They pay Tk5 from their Banglalink balance, approved with an AppLink one-time code, and get a serial
   by SMS.
2. **Wait anywhere.** The chamber assistant taps **Next** on a web page as each patient goes in. Wait
   estimates learn from how long this doctor really spends per patient.
3. **Come on time.** When 3 patients are ahead, the patient gets an SMS to come now. A patient who misses
   their turn is marked as a no-show and called next as soon as they arrive.

Built for AppQuest 2.0 on the [AppLink](https://dev.applink.com.bd) platform.

## AppLink APIs used

| API | What SerialKoi uses it for |
|---|---|
| **USSD** (`/ussd/receive` callback, `/ussd/send`) | Booking menu, status, cancel. One-step dial `*code*chamber#` skips the menu |
| **CaaS** (`/caas/direct/debit`, `/caas/otp/verify`, `/caas/chargingNotification` callback) | Tk5 booking fee from the subscriber's mobile balance, approved by OTP |
| **SMS** (`/sms/send`, `/sms/receive` and `/sms/report` callbacks) | Confirmation, "3 ahead, come now", "your turn", missed-turn notices; SMS commands `SK 4521` (book), `SK <code>` (pay), `SK STATUS`, `SK CANCEL` |

Payment follows Applink's two-step charging rules: confirming in the USSD menu **ends the session first**
(charging cannot happen inside a USSD session), then SerialKoi asks AppLink to SMS the patient a 6-digit
code. The patient replies `SK <code>` by SMS, or redials and picks "4. Enter payment code". The payment
record is saved before the charge request, a timeout is never retried, and the charging-notification
callback only books a serial when the full fee was paid. Each payment books at most one serial.

All four callbacks answer `S1000` immediately and do their work afterwards, ignore malformed bodies and
other apps' payloads, and skip redeliveries (deduplicated on `requestId` / `externalTrxId`). On the server
they live under an unguessable path (`SK_CALLBACK_PREFIX`) and can be limited to Applink's source IPs
(`SK_CALLBACK_IPS`). Payment codes are blanked out of the message log, and live-mode logs keep only the last
three digits of phone numbers.

**Checked against Applink's official kit.** SerialKoi's requests were run through the validating mock
server in [Applink-as-a-skill](https://github.com/hSenidMobileCPaaS/Applink-as-a-skill): 19 requests across
the success, unusual-response, wrong-key, wrong-code, expired-code, low-balance and timeout cases, none
malformed.

## Run it

```powershell
pip install -r requirements.txt
python -m uvicorn server:app --port 8791
```

Open <http://localhost:8791/sim> for the demo: a simulated button phone, the assistant's page and the
waiting-room screen side by side. In `sim` mode (the default) every SMS, USSD reply and charge stays on the
machine and uses the same request shapes as AppLink, so the flow can be shown before the app is approved.
Demo chamber: code `4521`, assistant PIN `2468`.

| Page | URL |
|---|---|
| Demo (simulation mode only) | `/sim` |
| Assistant's queue page | `/assistant` |
| Waiting-room TV screen | `/display/<chamber code>` |

### Going live on AppLink

[deploy/DEPLOY.md](deploy/DEPLOY.md) walks through it: one script (`deploy/setup.sh`) sets up an Ubuntu
server with HTTPS, the live app and a public simulator demo, and prints the values for AppLink's
create-app form. `sudo serialkoi check` and `sudo serialkoi sms <number>` then test the live connection.

Register each chamber:

```powershell
curl.exe -X POST https://<host>/api/admin/chambers -H "X-Admin-Key: <key>" -H "Content-Type: application/json" -d '{\"code\":\"4521\",\"name\":\"Chamber name\",\"doctor\":\"Dr. Name\",\"pin\":\"2468\",\"area\":\"Merul Badda\",\"fee\":5}'
```

## Tests

```powershell
python -m pytest -q
```

The tests cover serial numbering, learned wait times, alert timing, no-shows and recall, the USSD and
SMS flows with OTP payment (right, wrong, expired and repeated codes), callback acknowledgements, assistant
login, and the exact JSON bodies sent to each AppLink endpoint.

## Layout

```
app/
  applink.py   AppLink client: SMS, USSD, CaaS (live or simulated)
  service.py   queue, wait estimates, alerts, paid booking
  ussd.py      USSD menus (plain ASCII, 182 characters max)
  sms.py       SMS commands
  main.py      FastAPI routes: AppLink callbacks, assistant API, simulator
  static/      assistant, display, simulator and landing pages
tests/
```

## Tools used

Built during AppQuest 2.0 (from 20 Nov 2026) with Python, FastAPI and SQLite, with help from Claude
(Anthropic) as a coding assistant. Applink's [Applink-as-a-skill](https://github.com/hSenidMobileCPaaS/Applink-as-a-skill)
references and mock server were used to check the integration. Caddy serves HTTPS in production.

## Limits

- AppLink reaches Banglalink subscribers only. Patients on other operators are added by the assistant
  as walk-ins (with an optional phone number for SMS where the operator allows it).
- USSD menus are English because AppLink USSD carries plain ASCII. SMS is English too: Bangla SMS uses
  UCS-2 and fits only 70 characters per part, and AppLink can charge the subscriber per part.
- One server and SQLite: enough for hundreds of chambers; move to Postgres before that.
