from __future__ import annotations

import os
import re
import threading
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from mitchel_pipeline.models import ExtractedEmail
from mitchel_pipeline.run_control import RunControl

NICE_INCONTACT_URL = "https://na1.nice-incontact.com/apps/#/admin/userManagement"
PLAYER_URLS = (
    "https://na1.nice-incontact.com/player/#/cxone-player/contacts/"
    "238a6b57-2c9a-4a40-9d2a-bd3f1b971590/segments/"
    "44665862-6905-4425-8e84-f841ed170184?mediaType=all",
    "https://na1.nice-incontact.com/player/#/cxone-player/contacts/"
    "da59780d-d064-4ce0-9ef6-2698f52121c4/segments/"
    "8aa55c9c-7eb7-49ee-8973-d24837e5cea5?mediaType=all",
    "https://na1.nice-incontact.com/player/#/cxone-player/contacts/"
    "b3b188d1-cd8b-4385-8a25-244f7e11c589/segments/"
    "9afe2a1d-6bcd-4ed8-8cf2-7362a0622212?mediaType=all",
)
EMAIL_BODY_XPATH = (
    "/html/body/app-root/email-player-ng2/span/div/div/cxone-email-player/"
    "regular-email-player/div/div/email-body/div/div[2]/span/div[1]/p[1]"
)

LOCAL_APP_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "MitchelNLP"
PROFILE_DIR = LOCAL_APP_DIR / "NiceIncontactChromeProfile"
FALLBACK_PROFILE_DIR = LOCAL_APP_DIR / "NiceIncontactFallbackProfiles"
EMAIL_OUTPUT_DIR = Path.home() / "Downloads" / "Email_extraction"

ProgressCallback = Callable[[int, int, str], None]
LoginGate = Callable[[], None]
LogCallback = Callable[[str], None]


def normalize_text(text: str) -> str:
    lines = [
        line.rstrip()
        for line in (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    ]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines).strip()


def _looks_like_header(lines: list[str], index: int) -> bool:
    if not re.match(r"^\s*From\s*:", lines[index], re.IGNORECASE):
        return False
    nearby = "\n".join(lines[index + 1 : index + 10])
    return bool(re.search(r"(?im)^\s*(Sent|Date|To|Subject)\s*:", nearby))


def keep_original_email(text: str) -> str:
    """Return the oldest message from a copied reply chain."""

    normalized = normalize_text(text)
    lines = normalized.splitlines()
    starts = [index for index in range(len(lines)) if _looks_like_header(lines, index)]
    if starts:
        return normalize_text("\n".join(lines[starts[-1] :]))
    separator = re.search(r"(?im)^-+\s*Original Message\s*-+\s*$", normalized)
    if separator:
        return normalize_text(normalized[separator.end() :]) or normalized
    return normalized


def _subject_from_email(text: str) -> str:
    match = re.search(r"(?im)^\s*Subject\s*:\s*(.+?)\s*$", text)
    return match.group(1).strip() if match else ""


def _safe_filename(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._ -]+", "_", value).strip(" ._")
    return cleaned[:80] or "email"


class IncontactExtractor:
    """Extract the three configured CXone player emails with Selenium."""

    def __init__(
        self,
        *,
        login_gate: LoginGate,
        output_dir: Path = EMAIL_OUTPUT_DIR,
        log: LogCallback | None = None,
    ) -> None:
        self.login_gate = login_gate
        self.output_dir = output_dir
        self.log = log or (lambda _message: None)
        self._driver = None
        self._driver_lock = threading.Lock()

    def close(self) -> None:
        with self._driver_lock:
            driver, self._driver = self._driver, None
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass

    def extract(
        self,
        control: RunControl,
        progress: ProgressCallback,
    ) -> list[ExtractedEmail]:
        driver = self._create_driver()
        with self._driver_lock:
            self._driver = driver
        try:
            control.checkpoint()
            progress(0, len(PLAYER_URLS), "Opening NICE CXone")
            driver.get(NICE_INCONTACT_URL)
            self.login_gate()
            control.checkpoint()

            extracted: list[ExtractedEmail] = []
            original_handle = driver.current_window_handle
            for index, player_url in enumerate(PLAYER_URLS, start=1):
                control.checkpoint()
                progress(index - 1, len(PLAYER_URLS), f"Extracting email {index} of {len(PLAYER_URLS)}")
                driver.switch_to.new_window("window")
                driver.get(player_url)
                text = keep_original_email(self._extract_text(driver))
                path = self._save(text, driver.title, index)
                extracted.append(
                    ExtractedEmail(
                        message_id=f"cxone-{index}",
                        subject=_subject_from_email(text),
                        body=text,
                        saved_path=path,
                    )
                )
                driver.close()
                if original_handle in driver.window_handles:
                    driver.switch_to.window(original_handle)
                progress(index, len(PLAYER_URLS), f"Extracted email {index} of {len(PLAYER_URLS)}")
            return extracted
        finally:
            self.close()

    def _create_driver(self):
        try:
            from selenium import webdriver
            from selenium.common.exceptions import SessionNotCreatedException
            from selenium.webdriver.chrome.options import Options
        except ImportError as exc:
            raise RuntimeError("Selenium is not installed.") from exc

        chrome_binary = self._find_chrome()

        def options_for(profile: Path):
            profile.mkdir(parents=True, exist_ok=True)
            options = Options()
            options.add_argument("--start-maximized")
            options.add_argument(f"--user-data-dir={profile}")
            options.add_argument("--profile-directory=Default")
            options.add_argument("--no-first-run")
            options.add_argument("--no-default-browser-check")
            if chrome_binary:
                options.binary_location = chrome_binary
            return options

        try:
            return webdriver.Chrome(options=options_for(PROFILE_DIR))
        except SessionNotCreatedException:
            fallback = FALLBACK_PROFILE_DIR / datetime.now().strftime("%Y%m%d-%H%M%S")
            return webdriver.Chrome(options=options_for(fallback))

    @staticmethod
    def _find_chrome() -> str | None:
        configured = os.environ.get("PCC_CHROME_BINARY") or os.environ.get("CHROME_BINARY")
        candidates = [
            Path(configured) if configured else None,
            Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
            / "Google/Chrome/Application/chrome.exe",
            Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))
            / "Google/Chrome/Application/chrome.exe",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
        ]
        return next((str(path) for path in candidates if path and path.exists()), None)

    @staticmethod
    def _extract_text(driver) -> str:
        from selenium.common.exceptions import TimeoutException
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait

        try:
            WebDriverWait(driver, 60).until(
                EC.visibility_of_element_located((By.XPATH, EMAIL_BODY_XPATH))
            )
        except TimeoutException:
            WebDriverWait(driver, 30).until(
                EC.visibility_of_element_located((By.TAG_NAME, "body"))
            )

        text = driver.execute_script(
            """
            for (const selector of ['regular-email-player','cxone-email-player','email-body','body']) {
              const node = document.querySelector(selector);
              const text = node ? (node.innerText || node.textContent || '').trim() : '';
              if (text) return text;
            }
            return '';
            """
        )
        normalized = normalize_text(str(text or ""))
        if not normalized:
            normalized = normalize_text(driver.find_element(By.TAG_NAME, "body").text)
        if not normalized:
            raise RuntimeError("email_text_not_found")
        return normalized

    def _save(self, text: str, title: str, sequence: int) -> Path:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = self.output_dir / f"{stamp}_email-{sequence:02d}_{_safe_filename(title)}.txt"
        path.write_text(text, encoding="utf-8")
        self.log(f"saved extracted email {sequence} to {path.name}")
        return path
