# AppQuest 2.0 proposal

`proposal.html` is the source; `SerialKoi-proposal.pdf` is the 8-page A4 PDF for submission (pages follow the
organisers' order: cover, executive summary, problem, solution, technical, Applink integration, business,
Blank Page Challenge).

## Still to fill in (highlighted yellow in the PDF)

| Page | Placeholder | Who |
|---|---|---|
| 1 | Team name, members 2–4 and their roles | Team |
| 1 | Live demo link, video link (GitHub link done) | Zarif, after the server is up |
| 2 | Field-check headline ("median wait X min") | From the chamber visits |
| 3 | Field check table: chambers visited, patients per evening, waits, phone types, quote | Teammates, chamber visits by 26 Nov, using `docs/field-check/SerialKoi-field-check.pdf` |
| 8 | Quote from a doctor or assistant, with name and area (ask permission) | Teammates |

Search `proposal.html` for `class="todo"` to find each one. Remove the `<mark class="todo">` wrapper once a
value is filled in.

Projections on page 7 rest on stated assumptions (40 patients per evening, 25% booking by phone, 50% revenue
share). Update them with the field-check numbers before submitting.

## Re-render the PDF (Windows, from this folder)

```powershell
& "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" --headless --disable-gpu --no-pdf-header-footer --virtual-time-budget=10000 --print-to-pdf="$PWD\SerialKoi-proposal.pdf" "file:///$($PWD -replace '\\','/')/proposal.html"
```

Screenshots in `img/` come from the running app (`/sim`, `/assistant`, `/display/4521`, `/poster/4521`).

## Sources used

- bdnews24, 28 Nov 2025: feature-phone use (46%).
- Bonik Barta, Apr 2026 (BBS data): 41.6% without internet access.
- Prothom Alo English, 2025: registered doctors per population.
- The Business Standard: "Waiting for your doctor…" (tbsnews.net/node/399878) and "Introduce referral system to reduce patient pressure" (tbsnews.net/analysis/…-399898).
- bdnews24: "Wait 78 minutes to see a DMCH doctor" (TIB study).
