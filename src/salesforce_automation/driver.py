"""Chrome WebDriver creation for Salesforce automation."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

LOCAL_APP_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "MitchelNLP"
PROFILE_DIR = LOCAL_APP_DIR / "SalesforceChromeProfile"
FALLBACK_PROFILE_DIR = LOCAL_APP_DIR / "SalesforceChromeFallbackProfiles"


def find_chrome() -> str | None:
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


def create_driver():
    try:
        from selenium import webdriver
        from selenium.common.exceptions import SessionNotCreatedException
        from selenium.webdriver.chrome.options import Options
    except ImportError as exc:
        raise RuntimeError("Selenium is not installed.") from exc

    chrome_binary = find_chrome()

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
