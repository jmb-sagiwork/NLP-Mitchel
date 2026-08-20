"""PCC_Email_FP1 Part A - NiCE inContact mail extraction starter.

This script starts the browser side of the PCC_Email_FP1 workflow.

Current scope:
    1. Open NiCE inContact in a new Microsoft Edge Selenium window.
    2. Let the user complete login manually.
    3. Continue only after the user confirms login from a focused OK popup.

Future mail-extraction steps should be added after the manual-login gate in
`main()`.
"""

from __future__ import annotations

import os
import re
import time
import tkinter as tk

from datetime import datetime
from pathlib import Path
from tkinter import messagebox


APP_NAME = "PCC_Email_FP1 - Part A"
NICE_INCONTACT_URL = "https://na1.nice-incontact.com/apps/#/admin/userManagement"
NOTIFICATION_BELL_XPATH = (
    "/html/body/app-root/div/div/cxone-header-v2/header/div[1]/div[2]/div[2]"
    "/cxone-notification-menu-v2/div/button"
)
TARGET_NOTIFICATION_DATE = "July 23, 2026 9:02 PM"
TARGET_NOTIFICATION_DATE_XPATH = (
    '//*[@id="mat-menu-panel-1"]/div/div/div[2]/div[1]/span/div/div[5]'
)
PLAY_BUTTON_XPATHS = (
    '//*[@id="mat-menu-panel-1"]/div/div/div[2]/div[1]/span/div/div[3]'
    "/sol-action-button/div/sol-button/button/span/span",
    '//*[@id="mat-menu-panel-1"]/div/div/div[2]/div[1]/span/div/div[3]'
    "/sol-action-button/div/sol-button/button",
)
#FALLBACK_PLAYER_URL = (
#    "https://na1.nice-incontact.com/player/#/cxone-player/contacts/"
#    "b3b188d1-cd8b-4385-8a25-244f7e11c589/segments/"
#    "9afe2a1d-6bcd-4ed8-8cf2-7362a0622212?mediaType=all"
#)
FALLBACK_PLAYER_URL = (
    "https://na1.nice-incontact.com/player/#/cxone-player/contacts/6a36abf6-ac8c-4f44-85da-986c78f79953/segments/04ec2434-1cb2-4b82-aec8-e719570245f2?mediaType=all"
)
EMAIL_BODY_XPATH = (
    "/html/body/app-root/email-player-ng2/span/div/div/cxone-email-player/"
    "regular-email-player/div/div/email-body/div/div[2]/span/div[1]/p[1]"
)

LOCAL_APP_DIR = Path(
    os.environ.get(
        "LOCALAPPDATA",
        str(Path.home() / "AppData" / "Local"),
    )
) / "SmartAdvisorAutomation"
DIAGNOSTICS_DIR = LOCAL_APP_DIR / "diagnostics"
EDGE_PROFILE_DIR = LOCAL_APP_DIR / "NiceIncontactEdgeProfile"
EDGE_FALLBACK_PROFILES_DIR = LOCAL_APP_DIR / "NiceIncontactEdgeFallbackProfiles"
EMAIL_OUTPUT_DIR = LOCAL_APP_DIR / "Email_extraction"
RUN_LOG_PATH = DIAGNOSTICS_DIR / "pcc-email-fp1-part-a-nice-incontact.log"
RUN_STARTED_AT = time.perf_counter()
_STEP_NUMBER = 0


def _log(message: str) -> None:
    """Write a timestamped log line to terminal and local diagnostics."""

    DIAGNOSTICS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    elapsed = time.perf_counter() - RUN_STARTED_AT
    line = f"[{timestamp}] [+{elapsed:06.2f}s] {message}"
    print(line, flush=True)
    with RUN_LOG_PATH.open("a", encoding="utf-8") as log_file:
        log_file.write(f"{line}\n")


def _step(message: str) -> None:
    """Log a numbered workflow step."""

    global _STEP_NUMBER
    _STEP_NUMBER += 1
    _log(f"step {_STEP_NUMBER}: {message}")


def _show_focused_info(title: str, message: str) -> None:
    """Show a top-most manual confirmation popup."""

    _log(f"show info popup: {title}")
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    root.after(250, root.lift)
    root.after(300, root.focus_force)
    messagebox.showinfo(title, message, parent=root)
    root.destroy()
    _log(f"info popup closed: {title}")


def _show_focused_error(title: str, message: str) -> None:
    """Show a top-most error popup."""

    _log(f"show error popup: {title}")
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    root.after(250, root.lift)
    root.after(300, root.focus_force)
    messagebox.showerror(title, message, parent=root)
    root.destroy()
    _log(f"error popup closed: {title}")


def _find_chrome_binary() -> str | None:
    """Return the installed Microsoft Edge binary path when known."""

    _log("checking Microsoft Edge binary path")
    env_path = os.environ.get("PCC_EDGE_BINARY") or os.environ.get("EDGE_BINARY")
    if env_path and Path(env_path).exists():
        _log("Edge binary found from environment variable")
        return env_path
    """
    candidates = (
        Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))
        / "Microsoft"
        / "Edge"
        / "Application"
        / "msedge.exe",
        Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
        / "Microsoft"
        / "Edge"
        / "Application"
        / "msedge.exe",
        Path(os.environ.get("LOCALAPPDATA", ""))
        / "Microsoft"
        / "Edge"
        / "Application"
        / "msedge.exe",
    )
    for candidate in candidates:
        _log(f"checking Edge candidate: {candidate}")
        if candidate.exists():
            _log(f"Edge binary found: {candidate}")
            return str(candidate)
    _log("Edge binary not found in known locations")
    return None"""

    candidates = (
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
        Path(os.environ.get("LOCALAPPDATA", ""))
        / "Google"
        / "Chrome"
        / "Application"
        / "chrome.exe",
    )

    for candidate in candidates:
        _log(f"checking Chrome candidate: {candidate}")
        if candidate.exists():
            _log(f"Chrome binary found: {candidate}")
            return str(candidate)

    _log("Chrome binary not found")
    return None


#def _create_edge_driver():
def _create_chrome_driver():
    """Create an Edge WebDriver using Selenium Manager for driver matching."""

    _step("Importing Selenium Edge modules")
    try:
        from selenium import webdriver
        from selenium.common.exceptions import SessionNotCreatedException
        #from selenium.webdriver.edge.options import Options as EdgeOptions
        from selenium.webdriver.chrome.options import Options as ChromeOptions
    except ImportError as exc:
        raise RuntimeError(
            "Selenium is not installed. Install it with: pip install selenium"
        ) from exc

    #edge_binary = _find_edge_binary()
    chrome_binary = _find_chrome_binary()

    def build_options(profile_dir: Path):
        _log(f"configuring Edge profile folder: {profile_dir}")
        profile_dir.mkdir(parents=True, exist_ok=True)
        #options = EdgeOptions()
        options = ChromeOptions()
        options.add_argument("--start-maximized")
        options.add_argument(f"--user-data-dir={profile_dir}")
        options.add_argument("--profile-directory=Default")
        options.add_argument("--no-first-run")
        options.add_argument("--no-default-browser-check")
        if chrome_binary:
            options.binary_location = chrome_binary
            _log(f"Edge binary selected: {chrome_binary}")
        else:
            _log("Edge binary path not found; Selenium will use system Edge")
        return options

    _step(f"Preparing primary Edge profile folder: {EDGE_PROFILE_DIR}")
    primary_options = build_options(EDGE_PROFILE_DIR)

    _step("Starting Microsoft Chrome through Selenium Manager")
    try:
        #driver = webdriver.Edge(options=primary_options)
        driver = webdriver.Chrome(options=primary_options)
        
    except SessionNotCreatedException as exc:
        fallback_profile_dir = (
            EDGE_FALLBACK_PROFILES_DIR / datetime.now().strftime("%Y%m%d-%H%M%S")
        )
        _log(
            "primary Chrome profile could not start; it may still be open from a "
            "previous run"
        )
        _log(f"retrying with isolated fallback profile: {fallback_profile_dir}")
        fallback_options = build_options(fallback_profile_dir)
        #driver = webdriver.Edge(options=fallback_options)
        driver = webdriver.Chrome(options=fallback_options)
        _log(f"Chrome WebDriver started with fallback profile after: {type(exc).__name__}")
    _log("Chrome WebDriver session created")
    return driver


def _click_notification_bell(driver) -> None:
    """Click the NiCE notification bell after the user has logged in."""

    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait

    _step("Waiting for NiCE notification bell button")
    _log(f"notification bell xpath: {NOTIFICATION_BELL_XPATH}")
    bell_button = WebDriverWait(driver, 60).until(
        EC.element_to_be_clickable((By.XPATH, NOTIFICATION_BELL_XPATH))
    )
    _log("notification bell button is clickable")
    bell_button.click()
    _log("clicked notification bell button")


def _read_clipboard_text() -> str:
    """Read text from the Windows clipboard using Tkinter."""

    root = tk.Tk()
    root.withdraw()
    try:
        return root.clipboard_get()
    except tk.TclError:
        return ""
    finally:
        root.destroy()


def _safe_filename_part(value: str) -> str:
    """Return a filesystem-safe filename fragment."""

    cleaned = re.sub(r"[^A-Za-z0-9._ -]+", "_", value).strip(" ._")
    return cleaned or "email"


def _wait_for_new_window_or_tab(driver, existing_handles: set[str], timeout: float) -> str | None:
    """Return the first new window handle, or None if no new handle appears."""

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        current_handles = set(driver.window_handles)
        new_handles = current_handles - existing_handles
        if new_handles:
            return next(iter(new_handles))
        time.sleep(0.2)
    return None


def _click_target_notification_play(driver) -> bool:
    """Click Play only when the target notification date is present."""

    from selenium.common.exceptions import TimeoutException
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait

    _step(f"Checking target notification date: {TARGET_NOTIFICATION_DATE}")
    try:
        date_element = WebDriverWait(driver, 20).until(
            EC.visibility_of_element_located((By.XPATH, TARGET_NOTIFICATION_DATE_XPATH))
        )
    except TimeoutException:
        _log("target notification date element not found")
        return False

    visible_date = date_element.text.strip()
    _log(f"notification date found: {visible_date!r}")
    if visible_date != TARGET_NOTIFICATION_DATE:
        _log("target notification date did not match; using fallback player URL")
        return False

    _step("Clicking target notification Play button")
    for index, play_xpath in enumerate(PLAY_BUTTON_XPATHS, start=1):
        try:
            _log(f"trying Play button xpath {index}: {play_xpath}")
            play_button = WebDriverWait(driver, 15).until(
                EC.element_to_be_clickable((By.XPATH, play_xpath))
            )
            play_button.click()
            _log(f"clicked Play button using xpath {index}")
            return True
        except TimeoutException:
            _log(f"Play button xpath {index} was not clickable")
    return False


def _open_player_from_notification_or_fallback(driver) -> None:
    """Open the email player from notification Play, or from fallback URL."""

    original_handle = driver.current_window_handle
    existing_handles = set(driver.window_handles)
    clicked_play = _click_target_notification_play(driver)

    if clicked_play:
        _step("Waiting for CXone Player window or tab")
        new_handle = _wait_for_new_window_or_tab(driver, existing_handles, timeout=15)
        if new_handle:
            driver.switch_to.window(new_handle)
            _log("switched to newly opened CXone Player window")
            return
        _log("Play click did not open a new window; checking current page")
        if "cxone-player" in driver.current_url:
            _log("current window is already CXone Player")
            return
        driver.switch_to.window(original_handle)

    _step("Opening fallback CXone Player URL in new Edge window")
    driver.switch_to.new_window("window")
    driver.get(FALLBACK_PLAYER_URL)
    _log(f"fallback player URL opened: {FALLBACK_PLAYER_URL}")


def _normalize_extracted_text(text: str) -> str:
    """Normalize copied email text while keeping the original wording."""

    lines = [line.rstrip() for line in (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines).strip()


def _looks_like_email_header_start(lines: list[str], index: int) -> bool:
    """Return True when a From line appears to start an email header block."""

    if not re.match(r"^\s*From\s*:", lines[index], flags=re.IGNORECASE):
        return False

    nearby_headers = set()
    for line in lines[index + 1 : index + 10]:
        match = re.match(r"^\s*(Sent|Date|To|Cc|Subject)\s*:", line, flags=re.IGNORECASE)
        if match:
            nearby_headers.add(match.group(1).lower())

    return bool({"sent", "date", "to", "subject"} & nearby_headers)


def _keep_original_email_from_chain(email_text: str) -> str:
    """Keep the oldest/original email from a copied reply chain."""

    normalized_text = _normalize_extracted_text(email_text)
    lines = normalized_text.split("\n")
    header_start_indexes = [
        index for index, line in enumerate(lines) if _looks_like_email_header_start(lines, index)
    ]

    if header_start_indexes:
        original_start = header_start_indexes[-1]
        original_text = _normalize_extracted_text("\n".join(lines[original_start:]))
        if original_start > 0:
            _log(
                "email chain detected; kept original mail "
                f"from line {original_start + 1} of {len(lines)}"
            )
        else:
            _log("single email header detected; saved from first From header")
        return original_text

    original_message_match = re.search(
        r"(?im)^-+\s*Original Message\s*-+\s*$",
        normalized_text,
    )
    if original_message_match:
        original_text = _normalize_extracted_text(normalized_text[original_message_match.end() :])
        _log("email chain detected by Original Message separator")
        return original_text or normalized_text

    _log("no reply-chain header detected; saving extracted email text as-is")
    return normalized_text


def _dom_inner_text(driver, xpath: str) -> str:
    """Return innerText/textContent for an XPath without interacting with it."""

    text = driver.execute_script(
        """
        const xpath = arguments[0];
        const result = document.evaluate(
            xpath,
            document,
            null,
            XPathResult.FIRST_ORDERED_NODE_TYPE,
            null
        );
        const node = result.singleNodeValue;
        if (!node) {
            return "";
        }
        return (node.innerText || node.textContent || "").trim();
        """,
        xpath,
    )
    return _normalize_extracted_text(str(text or ""))


def _dom_first_text(driver, selectors: list[str]) -> tuple[str, str]:
    """Return text from the first CSS selector that contains useful content."""

    result = driver.execute_script(
        """
        const selectors = arguments[0];
        for (const selector of selectors) {
            const node = document.querySelector(selector);
            const text = node ? (node.innerText || node.textContent || "").trim() : "";
            if (text) {
                return {selector, text};
            }
        }
        return {selector: "", text: ""};
        """,
        selectors,
    )
    if isinstance(result, dict):
        return str(result.get("selector") or ""), _normalize_extracted_text(str(result.get("text") or ""))
    return "", ""


def _extract_email_text(driver) -> str:
    """Extract all readable text from the CXone Player email window."""

    from selenium.common.exceptions import TimeoutException
    from selenium.webdriver import Keys
    from selenium.webdriver.common.action_chains import ActionChains
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait

    _step("Waiting for email body in CXone Player")
    try:
        body_element = WebDriverWait(driver, 60).until(
            EC.visibility_of_element_located((By.XPATH, EMAIL_BODY_XPATH))
        )
        _log("email body paragraph located")
    except TimeoutException:
        _log("specific email body paragraph not found; falling back to page body")
        body_element = WebDriverWait(driver, 30).until(
            EC.visibility_of_element_located((By.TAG_NAME, "body"))
        )

    _step("Extracting email text from page DOM")
    for xpath in (
        "/html/body/app-root/email-player-ng2/span/div/div/cxone-email-player/regular-email-player",
        "/html/body/app-root/email-player-ng2/span/div/div/cxone-email-player",
        EMAIL_BODY_XPATH,
    ):
        extracted_text = _dom_inner_text(driver, xpath)
        if extracted_text:
            _log(f"extracted email text by DOM xpath characters={len(extracted_text)}")
            return extracted_text

    selector, extracted_text = _dom_first_text(
        driver,
        [
            "regular-email-player",
            "cxone-email-player",
            "email-body",
            "body",
        ],
    )
    if extracted_text:
        _log(f"extracted email text by DOM selector={selector} characters={len(extracted_text)}")
        return extracted_text

    _step("DOM text empty; trying keyboard copy fallback")
    try:
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", body_element)
        driver.execute_script("arguments[0].focus && arguments[0].focus();", body_element)
    except Exception as exc:
        _log(f"focus email element fallback skipped: {exc}")

    try:
        page_body = driver.find_element(By.TAG_NAME, "body")
        ActionChains(driver).move_to_element(page_body).click().perform()
    except Exception as exc:
        _log(f"body click fallback skipped: {exc}")

    ActionChains(driver).key_down(Keys.CONTROL).send_keys("a").key_up(Keys.CONTROL).perform()
    time.sleep(0.2)
    ActionChains(driver).key_down(Keys.CONTROL).send_keys("c").key_up(Keys.CONTROL).perform()
    time.sleep(0.5)

    clipboard_text = _read_clipboard_text().strip()
    if clipboard_text:
        clipboard_text = _normalize_extracted_text(clipboard_text)
        _log(f"copied email text from keyboard fallback characters={len(clipboard_text)}")
        return clipboard_text

    extracted_text = _normalize_extracted_text(body_element.text)
    if not extracted_text:
        extracted_text = _normalize_extracted_text(driver.find_element(By.TAG_NAME, "body").text)
    if extracted_text:
        _log(f"extracted email text from Selenium fallback characters={len(extracted_text)}")
        return extracted_text

    raise RuntimeError("email_text_not_found")


def _save_email_text(driver, email_text: str) -> Path:
    """Save extracted email text to a notepad-compatible .txt file."""

    EMAIL_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    email_text = _keep_original_email_from_chain(email_text)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    page_title = _safe_filename_part(driver.title)
    output_path = EMAIL_OUTPUT_DIR / f"{timestamp}_{page_title}.txt"
    output_path.write_text(email_text, encoding="utf-8")
    _log(f"saved email text to: {output_path}")
    return output_path


def main() -> int:
    """Open NiCE inContact and pause for manual login confirmation."""

    _log("=" * 60)
    _step("Part A NiCE inContact starter launched")
    _log(f"Target URL: {NICE_INCONTACT_URL}")

    driver = None
    try:
        _step("Creating Microsoft Edge WebDriver")
        #driver = _create_edge_driver()
        driver = _create_chrome_driver()
        _log("Microsoft Edge WebDriver started")
        _step("Opening NiCE inContact URL")
        driver.get(NICE_INCONTACT_URL)
        _log("NiCE inContact URL opened")

        _step("Waiting for user to complete manual login")
        time.sleep(1.0)
        _show_focused_info(
            APP_NAME,
            "Please complete NiCE inContact login manually in the Edge window.\n\n"
            "After the page is fully logged in and ready, click OK here to continue.",
        )

        _step("User confirmed login completion")
        _log(f"Manual login confirmed by user; current_url={driver.current_url}")
        _log(f"Page title after confirmation: {driver.title}")
        _click_notification_bell(driver)
        _open_player_from_notification_or_fallback(driver)
        email_text = _extract_email_text(driver)
        output_path = _save_email_text(driver, email_text)
        _step("Showing Part A completion confirmation")
        _show_focused_info(
            APP_NAME,
            "NiCE email extraction completed.\n\n"
            f"Saved notepad text file:\n{output_path}",
        )
        _step("Part A starter completed")
        return 0
    except Exception as exc:
        print("\n================ FULL TRACEBACK ================\n")
        import traceback
        traceback.print_exc()

        print("\n================================================\n")
        _log(f"Part A starter failed: {type(exc).__name__}: {exc}")
        _show_focused_error(APP_NAME, f"Part A could not start.\n\nReason: {exc}")
        return 1
    finally:
        if driver is not None:
            _step("Closing Edge WebDriver session")
            try:
                driver.quit()
                _log("Edge WebDriver session closed")
            except Exception as exc:
                _log(f"Edge WebDriver close skipped: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())
