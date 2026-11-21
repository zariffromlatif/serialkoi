#!/usr/bin/env bash
# SerialKoi server setup for Ubuntu 22.04 / 24.04 (or Debian 12).
#
# Run from the copied project folder on the server:
#     sudo bash deploy/setup.sh                 # uses <ip>.sslip.io as the domain
#     sudo bash deploy/setup.sh example.com     # or your own domain (point its A record here first)
#
# Safe to run again after updating the code: it keeps the secrets in /etc/serialkoi and the data in
# /var/lib/serialkoi.
#
# Two copies of the app run side by side:
#   live  https://<domain>        SK_MODE=live, talks to api.applink.com.bd
#   demo  https://demo.<domain>   SK_MODE=sim, the public phone-simulator demo for judges
set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "Please run with sudo."; exit 1; }

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP=/opt/serialkoi
DATA=/var/lib/serialkoi
CONF=/etc/serialkoi
SVC_USER=serialkoi
SKIP_SYSTEMD="${SKIP_SYSTEMD:-0}"   # 1 = containers without systemd (used for testing this script)

say() { printf '\n\033[1;32m== %s\033[0m\n' "$*"; }
rand() { python3 -c "import secrets; print(secrets.token_urlsafe($1))"; }

say "Installing system packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv curl ca-certificates gnupg rsync ufw debian-keyring debian-archive-keyring apt-transport-https >/dev/null
if ! command -v caddy >/dev/null; then
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/gpg.key | gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -qq
  apt-get install -y -qq caddy >/dev/null
fi

say "Finding this server's public IP"
IP="$(curl -fsS4 --max-time 10 https://api.ipify.org || curl -fsS4 --max-time 10 https://ifconfig.me)"
DOMAIN="${1:-${IP//./-}.sslip.io}"
echo "IP $IP, domain $DOMAIN"

say "Copying the app to $APP"
id -u "$SVC_USER" >/dev/null 2>&1 || useradd --system --home-dir "$APP" --shell /usr/sbin/nologin "$SVC_USER"
mkdir -p "$APP" "$DATA/backups" "$CONF"
if [[ "$SRC" != "$APP" ]]; then
  rsync -a --delete --exclude .git --exclude .env --exclude '*.db*' --exclude __pycache__ \
        --exclude .venv --exclude .pytest_cache --exclude .claude "$SRC"/ "$APP"/
fi
python3 -m venv "$APP/.venv"
"$APP/.venv/bin/pip" install -q --upgrade pip
"$APP/.venv/bin/pip" install -q -r "$APP/requirements.txt"
chown -R root:root "$APP"
chown -R "$SVC_USER:$SVC_USER" "$DATA"

say "Writing settings (existing ones are kept)"
if [[ ! -f "$CONF/live.env" ]]; then
  cat > "$CONF/live.env" <<EOF
# Live app. Fill in APPLINK_APP_ID and APPLINK_PASSWORD when Applink approves the app,
# set SK_USSD_CODE to the code it gives you (e.g. *383*44#), then:  sudo systemctl restart serialkoi@live
SK_PORT=8791
SK_MODE=live
APPLINK_APP_ID=APP_000000
APPLINK_PASSWORD=
SK_USSD_CODE=*213#
SK_SMS_KEYWORD=SK
SK_SMS_SHORTCODE=
SK_SECRET=$(rand 32)
SK_ADMIN_KEY=$(rand 24)
SK_SEED_DEMO=0
SK_DB=$DATA/live.db
# Unguessable path for Applink callbacks (defence in depth; the Applink guide recommends one)
SK_CALLBACK_PREFIX=/cb/$(python3 -c 'import secrets; print(secrets.token_hex(6))')
# Optional: comma-separated Applink source IPs (ask support@applink.com.bd for them)
SK_CALLBACK_IPS=
EOF
fi
grep -q '^SK_CALLBACK_PREFIX=' "$CONF/live.env" ||   echo "SK_CALLBACK_PREFIX=/cb/$(python3 -c 'import secrets; print(secrets.token_hex(6))')" >> "$CONF/live.env"
if [[ ! -f "$CONF/demo.env" ]]; then
  cat > "$CONF/demo.env" <<EOF
# Public simulator demo: nothing here reaches Applink.
SK_PORT=8792
SK_MODE=sim
SK_USSD_CODE=*213#
SK_SMS_KEYWORD=SK
SK_SECRET=$(rand 32)
SK_ADMIN_KEY=
SK_SEED_DEMO=1
SK_DB=$DATA/demo.db
EOF
fi
chown root:"$SVC_USER" "$CONF"/*.env
chmod 640 "$CONF"/*.env

say "Web server (Caddy, automatic HTTPS)"
sed "s/{\$DOMAIN}/$DOMAIN/g" "$APP/deploy/Caddyfile" > /etc/caddy/Caddyfile
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null 2>&1 \
  || { caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile; exit 1; }

say "Command-line helper and daily backup"
install -m 755 "$APP/deploy/serialkoi" /usr/local/bin/serialkoi
install -m 755 "$APP/deploy/backup.sh" /etc/cron.daily/serialkoi-backup

if [[ "$SKIP_SYSTEMD" == "1" ]]; then
  say "SKIP_SYSTEMD=1: not starting services"
  exit 0
fi

say "Firewall: SSH, HTTP, HTTPS"
for p in $(sshd -T 2>/dev/null | awk '/^port /{print $2}') 22; do ufw allow "$p/tcp" >/dev/null; done
ufw allow 80/tcp >/dev/null
ufw allow 443/tcp >/dev/null
ufw --force enable >/dev/null

say "Starting services"
install -m 644 "$APP/deploy/serialkoi@.service" /etc/systemd/system/serialkoi@.service
systemctl daemon-reload
systemctl enable --now serialkoi@live serialkoi@demo >/dev/null
systemctl restart serialkoi@live serialkoi@demo
systemctl reload caddy || systemctl restart caddy

for port in 8791 8792; do
  for _ in $(seq 1 20); do curl -fs "http://127.0.0.1:$port/healthz" >/dev/null && break; sleep 0.5; done
done

TEST_PIN=""
# shellcheck disable=SC1091
CB="$(. "$CONF/live.env"; echo "${SK_CALLBACK_PREFIX:-}")"
if [[ ! -f "$CONF/test-chamber.txt" ]]; then
  # shellcheck disable=SC1091
  ADMIN_KEY="$(. "$CONF/live.env"; echo "$SK_ADMIN_KEY")"
  TEST_PIN="$(python3 -c 'import secrets; print(f"{secrets.randbelow(10**6):06d}")')"
  if curl -fs -X POST http://127.0.0.1:8791/api/admin/chambers -H "X-Admin-Key: $ADMIN_KEY" \
       -H 'Content-Type: application/json' \
       -d "{\"code\":\"1001\",\"name\":\"SerialKoi Test Chamber\",\"doctor\":\"Dr. Test\",\"pin\":\"$TEST_PIN\",\"area\":\"Dhaka\",\"fee\":5}" >/dev/null; then
    echo "code=1001 pin=$TEST_PIN" > "$CONF/test-chamber.txt"
    chmod 600 "$CONF/test-chamber.txt"
  fi
fi

cat <<EOF

$(printf '\033[1;32m')SerialKoi is running.$(printf '\033[0m')

  Live app:      https://$DOMAIN
  Public demo:   https://demo.$DOMAIN/sim
  Test chamber:  $(cat "$CONF/test-chamber.txt" 2>/dev/null || echo "see $CONF/test-chamber.txt")  (log in at https://$DOMAIN/assistant)

Values for the Applink "Create New App" form:
  Allowed Host Address(es):     $IP
  SMS Message Receiving URL:    https://$DOMAIN$CB/sms/receive
  SMS delivery report URL:      https://$DOMAIN$CB/sms/report
  USSD Connection URL:          https://$DOMAIN$CB/ussd/receive
  CaaS Charging Notification:   https://$DOMAIN$CB/caas/chargingNotification

Next: sudo serialkoi check   (then, once the API key is in $CONF/live.env:  sudo serialkoi sms 019XXXXXXXX)
EOF
