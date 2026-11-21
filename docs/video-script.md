# SerialKoi: 2-minute demo video script

**Rules from the organisers:** up to 2 minutes, in English, and it must show the Applink integration working.
**Target length:** 1:55. The voiceover is 221 words, about 1:36 spoken at a calm pace, which leaves room for pauses.
**Record by:** 28 Nov, so there is a day to fix anything before the 30 Nov deadline.

## Two versions: pick on the day

| | Plan A: live (preferred) | Plan B: Applink not approved yet |
|---|---|---|
| Patient's phone | A real Banglalink phone (button phone if you can borrow one), filmed from above | The `/sim` page's phone on screen |
| Proof of Applink | Split screen: `sudo serialkoi logs` on the server showing `Applink POST /caas/direct/debit -> P1003` etc. | Same log lines, which say `(simulated)`. Say so in the voiceover and show the official mock-server check (shot 9B) |
| Code shown on the poster | The real USSD code Applink assigned | `*213*4521#` |

Plan B is honest but weaker on "Applink integration working" (20% of the score). Do everything possible to
get approval and a Banglalink SIM before 28 Nov.

## Shot list and voiceover

Timings are cumulative. VO = voiceover (record separately, in a quiet room, phone held 20 cm from mouth).
On-screen text is short caption text added in editing.

| # | Time | Picture | VO | On-screen text |
|---|---|---|---|---|
| 1 | 0:00–0:09 | A real chamber waiting room, crowded bench, wall clock (film with the chamber's permission; no faces in close-up, or blur them). | "Every evening in Dhaka, thousands of patients sit in doctors' chambers for hours, holding a serial number but no idea when they'll be called." | "Waiting for the doctor: often hours" |
| 2 | 0:09–0:15 | The SerialKoi poster on the chamber wall, slow push in on the dial code. | "SerialKoi fixes that, on any phone. Even a button phone." | **SerialKoi** · সিরিয়াল কই? |
| 3 | 0:15–0:24 | Close-up: thumb dials the code on the phone. Menu appears showing the doctor, "Now serving", "Waiting: 5 (~38 min)", "Fee: Tk5". | "The patient dials the code on the chamber poster. Applink's USSD API shows who is inside, how many are waiting and the estimated wait." | "Applink USSD API" |
| 4 | 0:24–0:31 | Press 1. Screen shows "To pay Tk5, AppLink will SMS you a 6-digit code". Right half of screen: log lines `/ussd/send -> S1000 (mt-fin)` then `/caas/direct/debit -> P1003`. | "Press one to book. The menu closes, and Applink's charging API texts the patient a code to approve the five-taka fee." | "Applink CaaS: Tk5, approved by OTP" |
| 5 | 0:31–0:40 | Phone: code SMS arrives, patient replies `SK 482913`. Log: `/caas/otp/verify -> S1000`, `/sms/send -> S1000`. Phone: "Serial 8 confirmed". | "The patient replies with the code, the payment goes through, and the serial arrives by SMS." | "Serial confirmed by Applink SMS" |
| 6 | 0:40–0:52 | Assistant's phone (screen recording of `/assistant`): taps **পরের রোগী · Next patient**, number changes 2 → 3; the waiting-room TV (`/display`) updates at the same time. | "At the chamber, the assistant runs the queue from any phone browser. One tap calls the next patient, and the waiting-room screen updates." | "One tap: Next patient" |
| 7 | 0:52–1:00 | Close on the "min each" figure on the assistant page changing after a few taps. | "Every tap teaches SerialKoi how long this doctor really takes, so wait times stay accurate." | "Wait times learn the doctor's pace" |
| 8 | 1:00–1:08 | Patient's phone buzzes: "Serial 8 - 3 patients ahead of you. Please come … now (~24 min)." Then later: "It is your turn now". | "When three patients are ahead, the patient gets an SMS: come now. Then another when it's their turn." | "SMS when 3 are ahead" |
| 9 | 1:08–1:20 | Assistant taps **আসেননি · No-show**; the patient moves to "Missed"; tap **Arrived** and they go to the front. Then add a walk-in by name. | "Didn't show up? One tap skips them, and they're called first when they arrive. Patients on other networks are added as walk-ins." | "No-shows and walk-ins handled" |
| 9B | (Plan B only, replaces part of 10) | Terminal: Applink's official mock server printing `OK caas-otp-generation`, `OK caas-otp-verify`, `OK sms-send`, `OK ussd-send`. | "Every request is checked against Applink's own mock server: nineteen requests, none malformed." | "Validated with Applink's official mock" |
| 10 | 1:20–1:36 | Architecture slide from the proposal (page 5), then the API table (page 6). | "Under the hood: three Applink APIs (USSD, CaaS and SMS), callbacks that answer instantly and never charge twice, and thirty-four automated tests." | "USSD · CaaS · SMS" |
| 11 | 1:36–1:47 | Printing the poster from the assistant page; a teammate sticking it on a chamber wall. | "Each booking earns five taka, shared with Applink. We start with five chambers near BRAC University in December." | "Tk5 per booking · 5-chamber pilot" |
| 12 | 1:47–1:55 | Logo card on teal, team name, Track A, BRAC University. | "SerialKoi. Wait at home, not in the chamber." | **SerialKoi** · Team [name] · BRAC University |

Total voiceover: 221 words (Plan A). If a take runs long, cut shot 7 first, then the walk-in sentence in shot 9.

## Before recording

**The demo data**
1. On the server (Plan A) or locally (Plan B): reset the demo, then add 6 sample patients, then tap Next
   twice, so the queue shows "Now serving 2" and 5 waiting, matching the voiceover.
   - Plan B: the **Reset demo** and **Add 6 sample patients** buttons on `/sim`.
   - Plan A: use the live test chamber (code `1001`) and add 5 walk-ins from the assistant page.
2. Open in three browser windows at 1920×1080: the phone (`/sim` or the real phone on a stand), `/assistant`
   (use the browser's phone size), `/display/<code>`.
3. Plan A: open an SSH window with `sudo serialkoi logs` running, font size 18+, dark background.

**Recording**
- Screen: OBS Studio (free), 1920×1080, 30 fps. Record each shot separately; keep 2 seconds of stillness at
  the start and end of each clip.
- Phone close-ups: another phone on a stand, overhead, with daylight from a window. Turn on Do Not Disturb
  on both phones, except for SMS.
- Hide anything private: real phone numbers (the app already masks them), the Applink API key, the server's
  secret callback path (`/cb/...`) in the logs. In the log window, run
  `sudo serialkoi logs | grep --line-buffered "Applink POST"` so only the API lines show.
- Chamber footage: ask the doctor or assistant first; avoid patients' faces or blur them.

**Editing** (CapCut, DaVinci Resolve or Clipchamp, all free)
- Add the on-screen text as lower-third captions in the brand teal (`#0d6b61`) with white text.
- Burn in English subtitles for the whole voiceover: judges often watch without sound.
- Export 1080p MP4 and check the length is under 2:00 (aim for 1:55).
- Upload to YouTube as **Unlisted** (or Google Drive with "anyone with the link"), and test the link in a
  private window before submitting.

## Who does what

| Task | Who | When |
|---|---|---|
| Waiting-room and poster footage (shots 1, 2, 11) | Teammates, during the chamber visits | by 26 Nov |
| Screen recordings (shots 3–10) | Zarif | 27–28 Nov |
| Voiceover | Whoever has the clearest English voice | 28 Nov |
| Edit, subtitles, upload | One teammate | 28–29 Nov |
