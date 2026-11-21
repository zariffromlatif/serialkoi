# Putting SerialKoi online (about 20 minutes)

You end up with two addresses on one server:

- **Live app:** `https://<ip-with-dashes>.sslip.io`. Applink talks to this one.
- **Public demo:** `https://demo.<ip-with-dashes>.sslip.io/sim`. The phone simulator, safe to put in the
  AppQuest submission because nothing in it reaches Applink.

[sslip.io](https://sslip.io) is free and needs no sign-up: any name like `1-2-3-4.sslip.io` points to the IP
`1.2.3.4`, which is enough for a real HTTPS certificate. You can switch to your own domain later.

## 1. Get a server

- **System:** Ubuntu 24.04 (22.04 also works), 1 GB RAM, the smallest size is enough.
- **A public IPv4 address that does not change.** Applink only accepts calls from the address you register.
  - DigitalOcean / Vultr / Linode: the droplet's address stays as long as the droplet exists.
  - AWS: attach an **Elastic IP**. Azure: set the public IP to **Static**.
- **Open ports 22, 80 and 443** in the provider's firewall (DigitalOcean: none by default; AWS: Security
  Group; Azure: Network Security Group).

## 2. Copy the code to the server (from Windows PowerShell)

Replace `<IP>` with the server's address (use `ubuntu@<IP>` on AWS, `azureuser@<IP>` on Azure).

```powershell
scp -r E:\Agency\serialkoi root@<IP>:~/serialkoi
```

## 3. Run the setup

```powershell
ssh root@<IP>
```

Then, on the server:

```bash
sudo bash ~/serialkoi/deploy/setup.sh
```

To use your own domain, point its A record (and `demo.` subdomain) at the server first, then run
`sudo bash ~/serialkoi/deploy/setup.sh yourdomain.com`.

The script installs everything, starts both apps, creates a test chamber (code `1001`, PIN printed at the
end) and prints the exact values for the Applink form. It is safe to run again: secrets in
`/etc/serialkoi` and data in `/var/lib/serialkoi` are kept.

## 4. Fill in the Applink "Create New App" form

Copy the values the script printed (Allowed Host Address, the four URLs). The other settings are listed in
`docs/applink-findings.md`; the important ones are **Mobile Number Masking off**, **USSD Subscription
Required off**, **USSD charging off**, and your Banglalink test SIM in **Whitelisted Numbers**.

Then check everything is reachable:

```bash
sudo serialkoi check
```

Everything should say OK except "Waiting for Applink approval".

## 5. When Applink emails the API key

```bash
sudo nano /etc/serialkoi/live.env
```

Fill in `APPLINK_APP_ID`, `APPLINK_PASSWORD` and `SK_USSD_CODE` (the service code + keyword, e.g.
`*383*44#`). Save with Ctrl+O, Enter, Ctrl+X. Then:

```bash
sudo serialkoi restart
sudo serialkoi sms 019XXXXXXXX
```

The second command sends a real SMS to your whitelisted Banglalink SIM and explains any error code
(E1303 = IP not registered, E1313 = wrong key, E1343 = number not whitelisted).

Then, from that SIM, dial the USSD code plus `1001` (for example `*383*44*1001#`) and book a serial at the
test chamber. Watch it arrive:

```bash
sudo serialkoi logs
```

and log in as the assistant at `https://<your address>/assistant` with code `1001` and the printed PIN.

## Everyday commands

| Command | What it does |
|---|---|
| `sudo serialkoi check` | Settings, public IP, HTTPS reachability |
| `sudo serialkoi sms 019XXXXXXXX [text]` | Send a real test SMS |
| `sudo serialkoi inbox 30` | Last 30 messages and callbacks |
| `sudo serialkoi logs` / `logs demo` | Follow the live or demo app's log |
| `sudo serialkoi restart` | Restart both apps |

**Updating the code:** copy the folder again (step 2) and rerun `sudo bash ~/serialkoi/deploy/setup.sh`.

**Backups:** the live database is copied every day to `/var/lib/serialkoi/backups` and kept for 14 days.
