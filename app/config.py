"""Settings read from environment variables (see .env.example)."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class Settings:
    mode: str = "sim"  # "sim" keeps every SMS/USSD/charge local; "live" calls api.applink.com.bd
    app_id: str = "APP_000000"
    password: str = ""
    base_url: str = "https://api.applink.com.bd"
    db_path: str = "serialkoi.db"
    secret: str = "dev-secret-change-me"
    admin_key: str = ""
    sms_keyword: str = "SK"
    sms_shortcode: str = ""  # the number patients text, from Applink provisioning (e.g. 77000); "" = unknown yet
    ussd_code: str = "*213#"  # placeholder: Applink assigns the real code at provisioning
    seed_demo: bool = True
    callback_prefix: str = ""  # e.g. "/cb/x7f3k9": an unguessable path segment for Applink callbacks
    callback_ips: tuple[str, ...] = ()  # if set, only these source IPs may post callbacks

    @classmethod
    def from_env(cls) -> "Settings":
        env = os.environ.get
        return cls(
            mode=env("SK_MODE", "sim").lower(),
            app_id=env("APPLINK_APP_ID", "APP_000000"),
            password=env("APPLINK_PASSWORD", ""),
            base_url=env("APPLINK_BASE_URL", "https://api.applink.com.bd").rstrip("/"),
            db_path=env("SK_DB", "serialkoi.db"),
            secret=env("SK_SECRET", "dev-secret-change-me"),
            admin_key=env("SK_ADMIN_KEY", ""),
            sms_keyword=env("SK_SMS_KEYWORD", "SK").upper(),
            sms_shortcode=env("SK_SMS_SHORTCODE", "").strip(),
            ussd_code=env("SK_USSD_CODE", "*213#"),
            seed_demo=env("SK_SEED_DEMO", "1") == "1",
            callback_prefix=env("SK_CALLBACK_PREFIX", "").rstrip("/"),
            callback_ips=tuple(ip.strip() for ip in env("SK_CALLBACK_IPS", "").split(",") if ip.strip()),
        )

    @property
    def is_sim(self) -> bool:
        return self.mode != "live"

    def dial_string(self, chamber_code: str) -> str:
        """'*213#' + '4521' -> '*213*4521#' (the one-step booking code printed on a chamber poster)."""
        base = self.ussd_code.rstrip("#")
        return f"{base}*{chamber_code}#"
