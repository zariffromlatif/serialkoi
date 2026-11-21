"""Applink API client (SMS, USSD, CaaS), following https://dev.applink.com.bd/docs.

In "sim" mode nothing leaves the machine: messages go to the `messages` table (which the phone
simulator reads) and CaaS OTPs are generated locally, so the full flow can be demoed before the
app is approved and before a provisioned server IP exists.
"""
from __future__ import annotations

import logging
import re
import secrets
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Callable

import httpx

from .config import Settings
from .db import Store

log = logging.getLogger("serialkoi.applink")


class ApplinkClient:
    def __init__(self, settings: Settings, store: Store, clock: Callable[[], datetime]):
        self.s = settings
        self.store = store
        self.clock = clock
        self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="applink-sms")

    # ------------------------------------------------------------------ plumbing
    def _log(self, direction: str, kind: str, address: str | None, body: str, status: str = "") -> None:
        if direction == "in":
            body = re.sub(r"\b\d{6}\b", "******", body or "")  # payment codes never reach the log
        if not self.s.is_sim and address:
            address = address[:-3].rstrip("0123456789") + "…" + address[-3:]  # last 3 digits only
        self.store.run(
            "INSERT INTO messages (direction, kind, address, body, status, created_at) VALUES (?,?,?,?,?,?)",
            (direction, kind, address, body, status, self.clock().isoformat(timespec="seconds")),
        )

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        payload = {"applicationId": self.s.app_id, "password": self.s.password, **body}
        try:
            r = httpx.post(
                self.s.base_url + path,
                json=payload,
                headers={"Content-Type": "application/json;charset=utf-8"},
                timeout=15,
            )
            data = r.json()
        except Exception as exc:  # network error or non-JSON body
            log.warning("Applink %s failed: %s", path, exc)
            return {"statusCode": "E-NET", "statusDetail": str(exc)}
        code = str(data.get("statusCode", ""))
        if code.startswith(("S", "P")):
            log.info("Applink POST %-26s -> %s", path, code)  # one line per call: visible proof in the logs
        else:
            log.warning("Applink POST %-26s -> %s %s", path, code, data.get("statusDetail"))
        return data

    @staticmethod
    def _sim_trace(path: str, code: str) -> None:
        log.info("Applink POST %-26s -> %s (simulated)", path, code)

    # ------------------------------------------------------------------ SMS
    def notify(self, address: str, message: str) -> None:
        """Send an SMS without making the caller wait (live mode); synchronous in sim mode."""
        if self.s.is_sim:
            self.send_sms(address, message)
            return

        def run() -> None:
            try:
                self.send_sms(address, message)
            except Exception:
                log.exception("SMS to %s failed", address[-3:])

        self._pool.submit(run)

    def send_sms(self, address: str, message: str) -> dict[str, Any]:
        if self.s.is_sim:
            self._log("out", "sms", address, message, "S1000")
            self._sim_trace("/sms/send", "S1000")
            return {"statusCode": "S1000", "statusDetail": "Simulated"}
        res = self._post(
            "/sms/send",
            {
                "version": "1.0",
                "message": message,
                "destinationAddresses": [address],
                "deliveryStatusRequest": "1",
                "encoding": "0",
            },
        )
        self._log("out", "sms", address, message, res.get("statusCode", ""))
        return res

    # ------------------------------------------------------------------ USSD
    def send_ussd(self, session_id: str, address: str, message: str, operation: str) -> dict[str, Any]:
        if self.s.is_sim:
            self._log("out", "ussd", address, message, operation)
            self._sim_trace("/ussd/send", f"S1000 ({operation})")
            return {"statusCode": "S1000", "statusDetail": "Simulated"}
        res = self._post(
            "/ussd/send",
            {
                "version": "1.0",
                "message": message,
                "sessionId": session_id,
                "ussdOperation": operation,
                "destinationAddress": address,
                "encoding": "440",
            },
        )
        self._log("out", "ussd", address, message, res.get("statusCode", ""))
        return res

    # ------------------------------------------------------------------ CaaS (one-time charge, OTP-approved)
    def caas_debit(self, address: str, amount: float, ext_trx_id: str) -> dict[str, Any]:
        if self.s.is_sim:
            reference = "SIM" + secrets.token_hex(6)
            otp = f"{secrets.randbelow(1_000_000):06d}"
            self.store.run(
                "INSERT INTO sim_otps (reference, phone, otp, ext_trx_id, amount) VALUES (?,?,?,?,?)",
                (reference, address, otp, ext_trx_id, amount),
            )
            # What the subscriber would receive from AppLink itself.
            self._log("out", "otp", address, f"AppLink: {otp} is your code to pay Tk{amount:g} to SerialKoi. Valid 5 min.", "S1000")
            self._sim_trace("/caas/direct/debit", "P1003 (OTP sent)")
            return {
                "statusCode": "P1003",
                "statusDetail": "Request successfully proceed. OTP will send to user.",
                "externalTrxId": ext_trx_id,
                "requestCorrelator": reference,
            }
        return self._post(
            "/caas/direct/debit",
            {
                "externalTrxId": ext_trx_id,
                "amount": f"{amount:.2f}",
                "paymentInstrumentName": "Mobile Account",
                "subscriberId": address,
                "Currency": "BDT",
            },
        )

    def caas_verify(self, reference: str, otp: str, address: str) -> dict[str, Any]:
        if self.s.is_sim:
            row = self.store.one("SELECT * FROM sim_otps WHERE reference = ?", (reference,))
            if row and not row["used"] and row["otp"] == otp.strip():
                self.store.run("UPDATE sim_otps SET used = 1 WHERE reference = ?", (reference,))
                self._sim_trace("/caas/otp/verify", "S1000 (charged)")
                return {"statusCode": "S1000", "statusDetail": "Success"}
            self._sim_trace("/caas/otp/verify", "E1850 (wrong code)")
            return {"statusCode": "E1850", "statusDetail": "Invalid OTP (simulated)"}
        return self._post(
            "/caas/otp/verify",
            {"referenceNo": reference, "otp": otp.strip(), "sourceAddress": address},
        )
