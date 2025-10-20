"""Print agent for Zebra ZD888t.

Polls the picking API for queued print jobs, forwards ZPL payloads to the
Windows spooler and optionally generates a preview image using the Labelary
rendering service.
"""

from __future__ import annotations

import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any

import requests

try:  # pragma: no cover - Windows specific dependency
    import win32print  # type: ignore
except Exception:  # pragma: no cover - non Windows environments
    win32print = None

CONFIG_PATH = Path(__file__).with_name("config.yaml")
LOGGER = logging.getLogger("print-agent")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


class AuthenticationError(RuntimeError):
    """Signal that the API rejected our credentials."""


def load_config() -> dict[str, Any]:
    import yaml  # type: ignore

    with CONFIG_PATH.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def configure_static_auth(session: requests.Session, auth_cfg: dict[str, Any]) -> None:
    service_token = auth_cfg.get("service_token")
    if service_token:
        session.headers["X-Service-Token"] = service_token
        LOGGER.info("Using service token authentication")
    token = auth_cfg.get("token")
    if token:
        session.headers["Authorization"] = f"Bearer {token}"
        LOGGER.info("Using static bearer token")


def login(session: requests.Session, api_base: str, auth_cfg: dict[str, Any]) -> str:
    username = auth_cfg.get("username")
    password = auth_cfg.get("password")
    if not username or not password:
        raise AuthenticationError("Auth configuration requires username/password for login")
    timeout = auth_cfg.get("timeout_s", 10)
    LOGGER.info("Authenticating as %s", username)
    resp = session.post(
        f"{api_base}/auth/login",
        json={"username": username, "password": password},
        timeout=timeout,
    )
    if resp.status_code != 200:
        raise AuthenticationError(f"Login failed with status {resp.status_code}: {resp.text}")
    data = resp.json()
    token = data.get("access_token")
    if not token:
        raise AuthenticationError("Login response did not include access_token")
    session.headers["Authorization"] = f"Bearer {token}"
    return token


def ensure_authorization(session: requests.Session, api_base: str, auth_cfg: dict[str, Any]) -> None:
    if "Authorization" in session.headers:
        return
    if auth_cfg.get("token"):
        session.headers["Authorization"] = f"Bearer {auth_cfg['token']}"
        return
    login(session, api_base, auth_cfg)


def send_raw_to_printer(printer_name: str, raw_data: str) -> Path | None:
    """Send ZPL to the Windows spooler. Returns the temp file used as fallback."""

    temp_path: Path | None = None
    if win32print is None:
        if os.name == "nt":  # pragma: no cover - UI interaction
            temp_path = Path(tempfile.gettempdir()) / f"zpl_job_{int(time.time())}.zpl"
            temp_path.write_text(raw_data, encoding="utf-8")
            LOGGER.warning("win32print not available; opening %s for manual printing", temp_path)
            os.startfile(str(temp_path))  # type: ignore[attr-defined]
            return temp_path
        raise RuntimeError("win32print is not available on this platform")

    handle = win32print.OpenPrinter(printer_name)
    try:
        job = win32print.StartDocPrinter(handle, 1, ("Picking", None, "RAW"))
        win32print.StartPagePrinter(handle)
        win32print.WritePrinter(handle, raw_data.encode("utf-8"))
        win32print.EndPagePrinter(handle)
        win32print.EndDocPrinter(handle)
        LOGGER.info("Job %s sent to printer %s", job, printer_name)
    finally:
        win32print.ClosePrinter(handle)
    return temp_path


def generate_preview(job_id: str, raw_data: str, preview_cfg: dict[str, Any]) -> Path | None:
    if not preview_cfg.get("enabled", False):
        return None

    dpi = preview_cfg.get("dpi", "8dpmm")
    width = preview_cfg.get("width_in", 4)
    height = preview_cfg.get("height_in", 6)
    rotate = preview_cfg.get("rotate", 0)
    timeout = preview_cfg.get("timeout_s", 10)
    base_url = preview_cfg.get("labelary_url", "https://api.labelary.com/v1")

    try:
        url = f"{base_url.rstrip('/')}/printers/{dpi}/labels/{width}x{height}/{rotate}/"
        headers = {"Accept": "image/png"}
        response = requests.post(url, headers=headers, data=raw_data.encode("utf-8"), timeout=timeout)
        response.raise_for_status()

        output_dir = preview_cfg.get("output_dir")
        if output_dir:
            output_dir = os.path.expandvars(output_dir)
        else:
            output_dir = tempfile.gettempdir()
        preview_path = Path(output_dir)
        preview_path.mkdir(parents=True, exist_ok=True)
        preview_file = preview_path / f"label_{job_id}.png"
        preview_file.write_bytes(response.content)
        LOGGER.info("Preview generated at %s", preview_file)

        if preview_cfg.get("open_file", True) and os.name == "nt":
            os.startfile(str(preview_file))  # type: ignore[attr-defined]

        return preview_file
    except Exception:
        LOGGER.exception("Unable to generate preview for job %s", job_id)
        return None


def run() -> None:
    config = load_config()
    api_base = config["api_base_url"].rstrip("/")
    printer_name = config.get("printer_name", "ZDesigner ZD888t")
    interval = int(config.get("poll_interval_s", 3))
    preview_cfg = config.get("preview", {}) or {}
    auth_cfg = config.get("auth", {}) or {}

    LOGGER.info("Starting agent for %s", printer_name)

    session = requests.Session()
    configure_static_auth(session, auth_cfg)

    while True:
        try:
            needs_bearer = bool(auth_cfg.get("username") or auth_cfg.get("password") or auth_cfg.get("token"))
            if needs_bearer:
                try:
                    ensure_authorization(session, api_base, auth_cfg)
                except AuthenticationError:
                    LOGGER.error("Authentication failed; check auth configuration")
                    time.sleep(max(5, interval))
                    continue

            resp = session.get(
                f"{api_base}/print/jobs",
                params={"status": "queued", "limit": 25},
                timeout=15,
            )
            if resp.status_code == 401:
                LOGGER.warning("Unauthorized when fetching jobs; clearing bearer token")
                session.headers.pop("Authorization", None)
                time.sleep(interval)
                continue
            resp.raise_for_status()
            jobs = resp.json()
            for job in jobs:
                job_id = job["id"]
                raw_data = job["payload_zpl"]
                copies = int(job.get("copies", 1) or 1)
                # If multiple copies requested, prefer ^PQ to avoid N submissions
                if copies > 1 and "^PQ" not in raw_data:
                    if "^XZ" in raw_data:
                        raw_data = raw_data.replace("^XZ", f"^PQ{copies}\n^XZ")
                    else:
                        raw_data = f"^XA\n^PQ{copies}\n" + raw_data + "\n^XZ"
                try:
                    send_raw_to_printer(printer_name, raw_data)
                    preview_file = generate_preview(job_id, raw_data, preview_cfg)
                    if preview_file:
                        LOGGER.info("Preview ready for job %s at %s", job_id, preview_file)
                    ack_resp = session.post(
                        f"{api_base}/print/jobs/{job_id}/ack",
                        json={"status": "sent"},
                        timeout=10,
                    )
                    if ack_resp.status_code == 401:
                        LOGGER.warning("Unauthorized acknowledging job %s; clearing bearer token", job_id)
                        session.headers.pop("Authorization", None)
                except Exception as exc:  # pragma: no cover - basic error handling
                    LOGGER.exception("Error while processing job %s", job_id)
                    session.post(
                        f"{api_base}/print/jobs/{job_id}/ack",
                        json={"status": "error", "error": str(exc)},
                        timeout=10,
                    )
        except Exception:
            LOGGER.exception("Error fetching jobs")
        time.sleep(interval)


if __name__ == "__main__":  # pragma: no cover
    run()
