"""Printable A4 poster for a chamber's wall: the dial code, how to pay, and a QR code to the live queue."""
from __future__ import annotations

import html
from typing import Any

import segno

BN_DIGITS = str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯")


def bn(value: Any) -> str:
    """Bangla numerals for prices and counts (dial codes stay Latin: that is what keypads show)."""
    return str(value).translate(BN_DIGITS)


def qr_svg(url: str) -> str:
    qr = segno.make(url, error="m")
    return qr.svg_inline(scale=6, border=0, dark="#12201d", light=None, omitsize=True)


def render_poster(chamber: dict[str, Any], dial: str, base_code: str, display_url: str, sms_keyword: str,
                  sms_shortcode: str = "") -> str:
    e = html.escape
    fee = chamber["fee"]
    fee_bn = f"৳{bn(f'{fee:g}')}" if fee > 0 else "ফ্রি"
    pay_step = (
        f"""<li><span class="n">২</span><div><b>৬ সংখ্যার কোড আসবে SMS-এ</b>
            <p>আবার <span class="mono">{e(base_code)}</span> ডায়াল করে <span class="mono">4</span> চাপুন, কোডটি দিন।"""
        + (f""" অথবা SMS করুন <span class="mono">{e(sms_keyword)} কোড</span> → <span class="mono">{e(sms_shortcode)}</span>""" if sms_shortcode else "")
        + f"""</p><i>A 6-digit payment code arrives by SMS. Redial, press 4, enter it.</i></div></li>"""
        if fee > 0 else
        """<li><span class="n">২</span><div><b>সিরিয়াল নম্বর চলে আসবে SMS-এ</b>
            <p>কোনো খরচ নেই।</p><i>Your serial number arrives by SMS.</i></div></li>"""
    )
    return f"""<!doctype html>
<html lang="bn">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SerialKoi Poster</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Hind+Siliguri:wght@400;500;600;700&family=Space+Mono:wght@700&display=swap" rel="stylesheet">
<style>
  @page {{ size: A4; margin: 0; }}
  * {{ box-sizing: border-box; }}
  :root {{ --teal: #0d6b61; --teal-dark: #08514a; --teal-soft: #e3f0ed; --amber: #ffc145; --ink: #12201d; --muted: #55635f; --paper: #fffdf8; }}
  html, body {{ margin: 0; }}
  body {{ -webkit-text-size-adjust: 100%; text-size-adjust: 100%; background: #d9d5cb; font-family: "Hind Siliguri", system-ui, sans-serif; color: var(--ink); -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
  .bar {{ position: sticky; top: 0; z-index: 2; display: flex; gap: 10px; justify-content: center; align-items: center; padding: 10px 16px; background: #12201d; color: #fff; font-size: 14px; flex-wrap: wrap; }}
  .bar button {{ font: inherit; font-weight: 700; border: 0; border-radius: 10px; padding: 8px 16px; background: var(--amber); color: var(--ink); cursor: pointer; }}
  .stage {{ padding: 20px 0 40px; display: flex; justify-content: center; overflow: hidden; }}
  .sheet {{ flex: none; width: 210mm; height: 297mm; background: var(--paper); box-shadow: 0 10px 40px rgba(0,0,0,.25); display: flex; flex-direction: column; overflow: hidden; transform-origin: top center; }}
  .mono {{ font-family: "Space Mono", ui-monospace, monospace; font-weight: 700; letter-spacing: .02em; }}

  header {{ background: var(--teal); color: #fff; padding: 10mm 16mm 8mm; position: relative; }}
  header::after {{ content: ""; position: absolute; right: -30mm; top: -30mm; width: 90mm; height: 90mm; border-radius: 50%; background: rgba(255,255,255,.07); }}
  .brand {{ display: flex; align-items: center; gap: 3mm; font-weight: 700; font-size: 5mm; opacity: .95; }}
  .mark {{ width: 9mm; height: 9mm; border-radius: 2.5mm; background: #fff; color: var(--teal); display: grid; place-items: center; font-size: 5.5mm; }}
  h1 {{ font-size: 14.5mm; line-height: 1.0; margin: 4.5mm 0 2.5mm; letter-spacing: -.01em; }}
  .lead {{ font-size: 5.4mm; line-height: 1.28; margin: 0; font-weight: 500; }}
  .lead-en {{ font-size: 3.6mm; opacity: .8; margin: 1.5mm 0 0; }}

  .doctor {{ padding: 6mm 16mm 0; }}
  .doctor b {{ display: block; font-size: 7.5mm; line-height: 1.1; }}
  .doctor span {{ color: var(--muted); font-size: 4.2mm; line-height: 1.2; }}

  .dial {{ margin: 4.5mm 16mm 0; border: 1mm solid var(--teal); border-radius: 6mm; padding: 4mm 8mm 3.5mm; text-align: center; background: #fff; }}
  .dial .lbl {{ font-size: 5mm; font-weight: 600; line-height: 1.2; }}
  .dial .code {{ font-size: 17mm; line-height: 1.05; color: var(--teal-dark); margin: 1.5mm 0 1.5mm; white-space: nowrap; }}
  .dial .fee {{ display: inline-block; background: var(--amber); border-radius: 99mm; padding: .6mm 5mm; font-weight: 700; font-size: 4.6mm; line-height: 1.3; }}
  .dial .en {{ display: block; color: var(--muted); font-size: 3.4mm; margin-top: 1.2mm; line-height: 1.2; }}

  ol {{ list-style: none; margin: 5mm 16mm 0; padding: 0; display: grid; gap: 3mm; }}
  li {{ display: grid; grid-template-columns: 12mm 1fr; gap: 4mm; align-items: start; }}
  li .n {{ width: 12mm; height: 12mm; border-radius: 50%; background: var(--teal-soft); color: var(--teal-dark); font-weight: 700; font-size: 6.5mm; display: grid; place-items: center; }}
  li b {{ font-size: 5.2mm; line-height: 1.2; display: block; }}
  li p {{ margin: .3mm 0 0; font-size: 4.2mm; line-height: 1.3; }}
  li i {{ display: block; font-style: normal; color: var(--muted); font-size: 3.2mm; margin-top: .2mm; line-height: 1.2; }}
  li .mono {{ background: var(--teal-soft); border-radius: 1.2mm; padding: 0 1.2mm; font-size: .92em; }}

  .bottom {{ margin: auto 16mm 0; display: grid; grid-template-columns: 34mm 1fr; gap: 7mm; align-items: center; padding: 4.5mm 0; border-top: .4mm dashed #c9c3b5; }}
  .qr svg {{ width: 34mm; height: 34mm; display: block; }}
  .qr small {{ display: block; text-align: center; font-size: 3.2mm; color: var(--muted); margin-top: 1.5mm; }}
  .notes p {{ margin: 0 0 1.8mm; font-size: 3.9mm; line-height: 1.3; }}
  .notes p b {{ font-weight: 700; }}
  .notes .en {{ color: var(--muted); font-size: 3.1mm; }}
  footer {{ background: var(--ink); color: #cfdcd8; padding: 3.5mm 16mm; display: flex; justify-content: space-between; font-size: 3.6mm; }}
  footer b {{ color: #fff; }}

  @media print {{
    body {{ background: none; }}
    .stage {{ overflow: visible; height: auto !important; }}
    .bar {{ display: none; }}
    .stage {{ padding: 0; display: block; }}
    .sheet {{ box-shadow: none; transform: none !important; }}
  }}
</style>
</head>
<body>
<div class="bar"><span>A4 poster for {e(chamber['doctor'])}. Print it and put it where patients wait.</span><button type="button" onclick="window.print()">প্রিন্ট · Print</button></div>
<div class="stage" id="stage">
<div class="sheet" id="sheet">
  <header>
    <div class="brand"><div class="mark">স</div>সিরিয়াল কই · SerialKoi</div>
    <h1>লাইনে বসে<br>থাকবেন না</h1>
    <p class="lead">ফোনে সিরিয়াল নিন, বাসায় অপেক্ষা করুন।<br>আপনার পালা কাছে এলে SMS পাবেন।</p>
    <p class="lead-en">Get your serial by phone and wait at home. We'll SMS you when your turn is near.</p>
  </header>

  <div class="doctor"><b>{e(chamber['doctor'])}</b><span>{e(chamber['name'])}{' · ' + e(chamber['area']) if chamber['area'] else ''}</span></div>

  <div class="dial">
    <div class="lbl">যেকোনো বাংলালিংক ফোন থেকে ডায়াল করুন</div>
    <div class="code mono">{e(dial)}</div>
    <span class="fee">খরচ {fee_bn}{' · ব্যালেন্স থেকে' if fee > 0 else ''}</span>
    <span class="en">Dial from any Banglalink phone, even a button phone{f' · Tk{fee:g} from your balance' if fee > 0 else ''}</span>
  </div>

  <ol>
    <li><span class="n">১</span><div><b>ডায়াল করে <span class="mono">1</span> চাপুন</b>
      <p>স্ক্রিনে দেখবেন এখন কত নম্বর চলছে আর কতক্ষণ লাগবে।</p><i>See who is being seen and the wait, then press 1 to confirm.</i></div></li>
    {pay_step}
    <li><span class="n">৩</span><div><b>বাসায় বা কাজে থাকুন</b>
      <p>সামনে {bn(chamber['alert_ahead'])} জন বাকি থাকলে SMS আসবে, তখন চলে আসুন।</p><i>We SMS you when {chamber['alert_ahead']} patients are ahead. Come then.</i></div></li>
  </ol>

  <div class="bottom">
    <div class="qr">{qr_svg(display_url)}<small>এখন কত নম্বর চলছে · Live queue</small></div>
    <div class="notes">
      <p><b>সিরিয়াল দেখতে:</b> আবার ডায়াল করে <span class="mono">2</span> · <b>বাতিল:</b> <span class="mono">3</span><br><span class="en">Check your serial: redial and press 2. Cancel: press 3.</span></p>
      <p><b>অন্য অপারেটর?</b> সহকারীকে বলুন, তিনি সিরিয়াল দিয়ে দেবেন।<br><span class="en">Not on Banglalink? Ask the assistant at the desk.</span></p>
      <p><b>ডাক মিস করলে?</b> এসে সহকারীকে বলুন, পরের জন হিসেবে ডাকা হবে।<br><span class="en">Missed your turn? Tell the assistant; you'll be called next.</span></p>
    </div>
  </div>
  <footer><span><b>সিরিয়াল কই</b> · SerialKoi</span><span>চেম্বার কোড <b class="mono">{e(chamber['code'])}</b></span></footer>
</div>
</div>
<script>
  // Fit the A4 sheet to small screens (print uses the real size).
  function fit() {{
    const s = document.getElementById("sheet"), st = document.getElementById("stage");
    s.style.transform = ""; const w = s.offsetWidth, h = s.offsetHeight;
    const k = Math.min(1, (document.documentElement.clientWidth - 24) / w);
    s.style.transform = k < 1 ? `scale(${{k}})` : "";
    st.style.height = k < 1 ? (h * k + 40) + "px" : "";
  }}
  window.addEventListener("resize", fit); window.addEventListener("load", fit); fit();
</script>
</body>
</html>"""
