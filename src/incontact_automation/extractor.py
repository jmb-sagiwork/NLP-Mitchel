"""Callable NICE CXone email extraction service.

Drives the live MAX agent desktop: accept the next assigned email, extract
its subject/body, and (once the caller has a reply ready) paste that reply
and click Park Email — never Send — so the next assigned email enters the
working inbox and the loop continues.
"""

from __future__ import annotations

import os
import re
import socket
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from datetime import datetime
from pathlib import Path

from mitchel_pipeline.models import ExtractedEmail
from mitchel_pipeline.run_control import RunControl

NICE_INCONTACT_URL = "https://na1.nice-incontact.com/apps/#/admin/userManagement"
NICE_INCONTACT_URL_MARKER = "na1.nice-incontact.com/apps"
NICE_LOGGED_IN_TEXT_MARKERS = (
    "NiCE CXone",
    "Employees",
    "Admin",
    "Start typing to find user",
)
MAX_EMAILS_PER_RUN = int(os.environ.get("PCC_MAX_EMAILS_PER_RUN", "25"))
NEXT_EMAIL_ACCEPT_WAIT_SECONDS = int(os.environ.get("PCC_NEXT_EMAIL_ACCEPT_WAIT_SECONDS", "45"))
CHROME_DEBUGGER_ADDRESS = "127.0.0.1:9225"
MAX_URL = "https://max.niceincontact.com/index.html"
NINE_DOTS_XPATHS = (
    "/html/body/app-root/div/div/cxone-header-v2/header/div[1]/div[1]/div[1]/sol-icon",
    "//cxone-header-v2//header//sol-icon",
    "//header//sol-icon[1]",
    "//sol-icon[contains(@icon,'grid') or contains(@icon,'apps')"
    " or contains(@name,'grid') or contains(@name,'apps')]",
)
MAX_APP_XPATHS = (
    '//*[@id="select-max"]/div/div/span',
    '//*[@id="select-max"]',
    "//*[contains(@id,'select-max')]",
)
INTEGRATED_SOFTPHONE_XPATH = '//*[@id="sessionconnectui-0"]/div/div/div[3]/div[1]/div/label/div'
CONNECT_BUTTON_XPATH = '//*[@id="sessionconnectui-0"]/div/div/div[3]/div[4]/button[1]/h4'
AGENT_STATE_DROPDOWN_XPATH = '//*[@id="agentstateui-0"]/div/div[2]/div[1]/span[1]'
AVAILABLE_STATE_XPATH = '//*[@id="agentstateui-0stateList"]/li[1]/span'
ACCEPT_BUTTON_XPATHS = (
    "//*[starts-with(@id,'contactacceptui-')]//button[normalize-space()='Accept']",
    "//button[normalize-space()='Accept']",
    '//*[@id="contactacceptui-1"]/div/div[2]/div[3]/button[1]',
)
ASSIGNED_EMAIL_CONTAINER_XPATH = '//*[@id="email-container"]/div[5]'
ASSIGNED_EMAIL_OPEN_XPATHS = (
    '//*[@id="email-container"]',
    '//*[@id="email-container"]/div[5]',
    '//*[@id="email-container"]//iframe',
    "//*[contains(normalize-space(),'Quick Replies')]",
    "//*[normalize-space()='End Email']",
    "//*[normalize-space()='Park Email']",
)
ASSIGNED_EMAIL_SUBJECT_XPATHS = (
    "/html/body/div[1]/div/div[3]/div[3]/div[1]/div[2]/div/div/div[2]/div/div/div"
    "/div[1]/div[5]/div[1]/div[2]/div[1]/input",
    '//*[@id="email-container"]/div[5]/div[1]/div[2]/div[1]',
    '//*[@id="email-container"]/div[5]/div[1]/div[2]/div[1]/input',
    '//*[@id="email-container"]//input',
)
ASSIGNED_EMAIL_BODY_IFRAME_XPATHS = (
    "//iframe[contains(concat(' ', normalize-space(@class), ' '), ' email-body ')]",
    "//iframe[@aria-label='Email Body']",
    "/html/body/div[1]/div/div[3]/div[3]/div[1]/div[2]/div/div/div[2]/div/div/div"
    "/div[1]/div[5]/iframe",
    '//*[@id="email-container"]/div[5]/iframe',
)
ASSIGNED_EMAIL_BODY_XPATHS = ("/html/body",)
REPLY_BUTTON_XPATHS = (
    '//*[@id="email-container"]/div[4]/div[2]/button[3]',
    '//*[@id="email-container"]/div[4]/div[2]/button[3]/svg',
)
PARK_EMAIL_BUTTON_XPATHS = (
    '//*[@id="email-container"]/div[4]/div[2]/button[6]',
    "//*[@id='email-container']//button[normalize-space()='Park Email']",
)
ADD_ATTACHMENT_INPUT_XPATHS = (
    '//*[@id="email-container"]/div[5]/div[1]/div[2]/div[1]/div[2]/label/input',
    "//label[.//span[contains(@class,'add-attachment-input-label-text')]]//input[@type='file']",
    "//input[contains(@class,'add-attachment-input')]",
)
REPLY_COMPOSE_EDITOR_XPATHS = (
    '//*[@id="email-container"]//*[@contenteditable="true"]',
    '//*[@id="email-container"]//*[@role="textbox"]',
    '//*[@id="email-container"]//textarea',
    '//*[@id="email-container"]/div[5]//iframe',
    '//*[@id="email-container"]//iframe',
)
MAX_OPEN_EMAIL_TEXT_MARKERS = (
    "Quick Replies",
    "Reply All",
    "Forward",
    "Park Email",
    "End Email",
    "Working (1)",
)
REPLY_SIGNATURE = (
    "\n\nAmtrust Mitchell Bill Review Support Team\nAMTRUSTCSV@mitchell.com\n866-380-9811"
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


def _safe_filename(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._ -]+", "_", value).strip(" ._")
    return cleaned[:80] or "email"


def _read_clipboard_text() -> str:
    import tkinter as tk

    root = tk.Tk()
    root.withdraw()
    try:
        return root.clipboard_get()
    except tk.TclError:
        return ""
    finally:
        root.destroy()


def _set_clipboard_text(text: str) -> None:
    import tkinter as tk

    root = tk.Tk()
    root.withdraw()
    try:
        root.clipboard_clear()
        root.clipboard_append(text)
        root.update()
    finally:
        root.destroy()


def _is_debugger_port_open(address: str) -> bool:
    host, port_text = address.rsplit(":", 1)
    try:
        with socket.create_connection((host, int(port_text)), timeout=0.35):
            return True
    except OSError:
        return False


class IncontactExtractor:
    """Drive the live MAX Accept -> Reply -> Park loop with Selenium."""

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

    # -- extraction loop ---------------------------------------------------

    def extract(
        self,
        control: RunControl,
        progress: ProgressCallback,
    ) -> Iterator[ExtractedEmail]:
        driver = self._create_driver()
        with self._driver_lock:
            self._driver = driver
        try:
            control.checkpoint()
            progress(0, MAX_EMAILS_PER_RUN, "Opening NICE CXone")
            self._open_or_focus_nice(driver)
            if not self._is_nice_logged_in(driver, quick_timeout=6):
                self.login_gate()
            control.checkpoint()

            self._open_max_from_nice(driver)
            if not self._is_assigned_email_pane_visible(driver, quick_timeout=10):
                self._connect_integrated_softphone(driver)
                if not self._is_assigned_email_pane_visible(driver, quick_timeout=5):
                    self._change_agent_state_available(driver)
                    if not self._is_assigned_email_pane_visible(driver, quick_timeout=5):
                        self._accept_assigned_email(driver)

            for index in range(1, MAX_EMAILS_PER_RUN + 1):
                control.checkpoint()
                progress(index - 1, MAX_EMAILS_PER_RUN, f"Extracting email {index}")
                self._is_assigned_email_pane_visible(driver, quick_timeout=15)
                subject = self._extract_subject(driver)
                body = self._extract_body(driver)
                text = keep_original_email(body)
                path = self._save(text, subject, index)
                email = ExtractedEmail(
                    message_id=f"max-{index}",
                    subject=subject,
                    body=text,
                    saved_path=path,
                )
                progress(index, MAX_EMAILS_PER_RUN, f"Extracted email {index}")
                # Yield only after subject/body extraction. The caller
                # calls send_reply() once it has a real reply, which clicks
                # Reply/Park on this same open email before we resume here.
                yield email

                if index >= MAX_EMAILS_PER_RUN:
                    self.log(f"stopping assigned email loop at safety cap={MAX_EMAILS_PER_RUN}")
                    break

                control.checkpoint()
                if not self._click_accept_popup_if_present(
                    driver, wait_seconds=NEXT_EMAIL_ACCEPT_WAIT_SECONDS
                ):
                    self.log("no next assigned email appeared; ending assigned email loop")
                    break
        finally:
            self.close()

    def send_reply(self, reply_text: str, attachments: Sequence[str] | None = None) -> None:
        """Reply to the currently open MAX email, then Park it (never Send)."""

        with self._driver_lock:
            driver = self._driver
        if driver is None:
            raise RuntimeError("no active MAX session to reply on")

        full_reply = f"{reply_text.rstrip()}{REPLY_SIGNATURE}"
        self._click_reply_button(driver)
        self._paste_reply_template(driver, full_reply)
        if attachments:
            self._attach_files(driver, attachments)
        self._click_park_email(driver)

    def park_now(self) -> None:
        """Park the currently open MAX email immediately, with no reply pasted."""

        with self._driver_lock:
            driver = self._driver
        if driver is None:
            raise RuntimeError("no active MAX session to park")
        self._click_park_email(driver)

    # -- driver setup --------------------------------------------------

    def _create_driver(self):
        try:
            from selenium import webdriver
            from selenium.common.exceptions import SessionNotCreatedException
            from selenium.webdriver.chrome.options import Options
        except ImportError as exc:
            raise RuntimeError("Selenium is not installed.") from exc

        if _is_debugger_port_open(CHROME_DEBUGGER_ADDRESS):
            attach_options = Options()
            attach_options.debugger_address = CHROME_DEBUGGER_ADDRESS
            return webdriver.Chrome(options=attach_options)

        chrome_binary = self._find_chrome()

        def options_for(profile: Path):
            profile.mkdir(parents=True, exist_ok=True)
            options = Options()
            options.add_argument("--start-maximized")
            options.add_argument(f"--user-data-dir={profile}")
            options.add_argument("--profile-directory=Default")
            options.add_argument("--no-first-run")
            options.add_argument("--no-default-browser-check")
            options.add_argument(
                f"--remote-debugging-port={CHROME_DEBUGGER_ADDRESS.rsplit(':', 1)[1]}"
            )
            options.add_experimental_option("detach", True)
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

    # -- frame-aware element helpers ----------------------------------------

    @staticmethod
    def _visible(element) -> bool:
        try:
            return element.is_displayed()
        except Exception:
            return False

    @staticmethod
    def _visible_enabled(element) -> bool:
        try:
            return element.is_displayed() and element.is_enabled()
        except Exception:
            return False

    def _find_in_frames(self, driver, by, locator: str, max_depth: int = 4, require_enabled: bool = True):
        is_match = self._visible_enabled if require_enabled else self._visible

        def search(depth: int):
            for element in driver.find_elements(by, locator):
                if is_match(element):
                    return element
            if depth >= max_depth:
                return None
            frames = driver.find_elements(by, "//iframe | //frame")
            for frame in frames:
                entered = False
                try:
                    driver.switch_to.frame(frame)
                    entered = True
                    result = search(depth + 1)
                    if result is not None:
                        return result
                except Exception:
                    pass
                finally:
                    try:
                        if entered:
                            driver.switch_to.parent_frame()
                    except Exception:
                        driver.switch_to.default_content()
            return None

        driver.switch_to.default_content()
        return search(0)

    def _wait_xpath_any_frame(self, driver, xpath: str, timeout: int = 45):
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.common.by import By

        def locate(current_driver):
            return self._find_in_frames(current_driver, By.XPATH, xpath)

        return WebDriverWait(driver, timeout).until(locate)

    def _find_file_input_any_frame(self, driver, xpaths: tuple[str, ...], timeout: int = 30):
        """Locate a (likely CSS-hidden) file input by XPath, walking iframes.

        Unlike `_find_in_frames`, this does not require `is_displayed()` -- the
        native <input type="file"> behind the styled "Add Attachment" label is
        hidden and only its label/span is visible to a human clicking it.
        """

        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.common.by import By

        def search(depth: int, max_depth: int = 4):
            for xpath in xpaths:
                for element in driver.find_elements(By.XPATH, xpath):
                    return element
            if depth >= max_depth:
                return None
            for frame in driver.find_elements(By.XPATH, "//iframe | //frame"):
                entered = False
                try:
                    driver.switch_to.frame(frame)
                    entered = True
                    result = search(depth + 1, max_depth)
                    if result is not None:
                        return result
                except Exception:
                    pass
                finally:
                    try:
                        if entered:
                            driver.switch_to.parent_frame()
                    except Exception:
                        driver.switch_to.default_content()
            return None

        def locate(current_driver):
            current_driver.switch_to.default_content()
            return search(0)

        return WebDriverWait(driver, timeout).until(locate)

    def _click_xpath_any_frame(self, driver, xpath: str, timeout: int = 45) -> None:
        element = self._wait_xpath_any_frame(driver, xpath, timeout=timeout)
        try:
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
        except Exception:
            pass
        try:
            element.click()
            return
        except Exception:
            pass
        driver.execute_script(
            """
            const node = arguments[0];
            const clickable = node.closest('button,a,[role="button"],sol-icon,div') || node;
            clickable.click();
            """,
            element,
        )

    def _click_first_xpath_any_frame(
        self, driver, xpaths: tuple[str, ...], timeout: int = 45
    ) -> None:
        from selenium.common.exceptions import TimeoutException

        deadline = time.monotonic() + timeout
        last_exc: Exception | None = None
        while True:
            for xpath in xpaths:
                try:
                    self._click_xpath_any_frame(driver, xpath, timeout=1)
                    return
                except Exception as exc:
                    last_exc = exc
            if time.monotonic() >= deadline:
                break
            time.sleep(0.5)
        raise TimeoutException(
            f"none of the candidate xpaths were clickable: {xpaths}"
        ) from last_exc

    @staticmethod
    def _element_text_or_value(driver, element) -> str:
        text = driver.execute_script(
            """
            const node = arguments[0];
            return (
                node.value || node.innerText || node.textContent ||
                node.getAttribute('aria-label') || ''
            ).trim();
            """,
            element,
        )
        return normalize_text(str(text or ""))

    def _copy_element_text(self, driver, element) -> str:
        """Click/select/copy an element's text, falling back to its DOM value."""

        from selenium.webdriver import Keys
        from selenium.webdriver.common.action_chains import ActionChains

        try:
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
        except Exception:
            pass

        dom_text = self._element_text_or_value(driver, element)
        try:
            ActionChains(driver).move_to_element(element).click().perform()
            time.sleep(0.15)
            ActionChains(driver).key_down(Keys.CONTROL).send_keys("a").key_up(Keys.CONTROL).perform()
            time.sleep(0.15)
            ActionChains(driver).key_down(Keys.CONTROL).send_keys("c").key_up(Keys.CONTROL).perform()
            time.sleep(0.25)
            clipboard_text = normalize_text(_read_clipboard_text())
            if clipboard_text and (
                not dom_text
                or clipboard_text == dom_text
                or len(clipboard_text) <= len(dom_text) + 200
            ):
                return clipboard_text
        except Exception:
            pass

        return dom_text

    # -- NICE login / MAX navigation ----------------------------------------

    def _page_text(self, driver) -> str:
        try:
            return driver.execute_script(
                "return document.body ? document.body.innerText : '';"
            ) or ""
        except Exception:
            try:
                return driver.find_element("tag name", "body").text
            except Exception:
                return ""

    def _switch_to_existing_nice_window(self, driver) -> bool:
        for handle in driver.window_handles:
            try:
                driver.switch_to.window(handle)
                if NICE_INCONTACT_URL_MARKER in driver.current_url:
                    return True
            except Exception:
                pass
        return False

    def _open_or_focus_nice(self, driver) -> None:
        if self._switch_to_existing_nice_window(driver) and self._is_nice_logged_in(
            driver, quick_timeout=2
        ):
            return
        driver.get(NICE_INCONTACT_URL)

    def _is_nice_logged_in(self, driver, quick_timeout: int = 3) -> bool:
        from selenium.webdriver.common.by import By

        deadline = time.monotonic() + max(quick_timeout, 0)
        while True:
            try:
                current_url = driver.current_url
                title = driver.title
                if NICE_INCONTACT_URL_MARKER in current_url:
                    for xpath in NINE_DOTS_XPATHS:
                        nine_dots = driver.find_elements(By.XPATH, xpath)
                        if any(self._visible(element) for element in nine_dots):
                            return True
                text = self._page_text(driver)
                if NICE_INCONTACT_URL_MARKER in current_url and any(
                    marker.lower() in f"{title}\n{text}".lower()
                    for marker in NICE_LOGGED_IN_TEXT_MARKERS
                ):
                    return True
            except Exception:
                pass
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.3)

    def _wait_new_window(self, driver, existing_handles: set[str], timeout: float) -> str | None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            new_handles = set(driver.window_handles) - existing_handles
            if new_handles:
                return next(iter(new_handles))
            time.sleep(0.2)
        return None

    def _switch_to_max_window(self, driver, existing_handles: set[str], timeout: int = 45) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for handle in driver.window_handles:
                try:
                    driver.switch_to.window(handle)
                    current_url = driver.current_url
                    title = driver.title
                    if "max.niceincontact.com" in current_url or "MAX" in title.upper():
                        try:
                            driver.maximize_window()
                        except Exception:
                            pass
                        return
                except Exception:
                    pass
            new_handle = self._wait_new_window(driver, existing_handles, timeout=0.5)
            if new_handle:
                try:
                    driver.switch_to.window(new_handle)
                except Exception:
                    pass
            time.sleep(0.3)
        raise RuntimeError("MAX window did not open.")

    def _open_max_from_nice(self, driver) -> None:
        existing_handles = set(driver.window_handles)
        self._click_first_xpath_any_frame(driver, NINE_DOTS_XPATHS, timeout=60)
        time.sleep(0.6)
        self._click_first_xpath_any_frame(driver, MAX_APP_XPATHS, timeout=30)
        self._switch_to_max_window(driver, existing_handles, timeout=45)

    def _max_visible_text(self, driver, max_depth: int = 4) -> str:
        from selenium.webdriver.common.by import By

        text_parts: list[str] = []
        driver.switch_to.default_content()

        def collect(depth: int = 0) -> None:
            try:
                body_text = driver.find_element(By.TAG_NAME, "body").text
                if body_text:
                    text_parts.append(body_text)
            except Exception:
                pass
            if depth >= max_depth:
                return
            for frame in driver.find_elements(By.XPATH, "//iframe | //frame"):
                entered = False
                try:
                    driver.switch_to.frame(frame)
                    entered = True
                    collect(depth + 1)
                except Exception:
                    pass
                finally:
                    try:
                        if entered:
                            driver.switch_to.parent_frame()
                    except Exception:
                        driver.switch_to.default_content()

        collect()
        driver.switch_to.default_content()
        return normalize_text("\n".join(text_parts))

    def _is_assigned_email_pane_visible(self, driver, quick_timeout: int = 1) -> bool:
        from selenium.webdriver.common.by import By

        deadline = time.monotonic() + max(quick_timeout, 0)
        while True:
            for xpath in ASSIGNED_EMAIL_OPEN_XPATHS:
                try:
                    if self._find_in_frames(driver, By.XPATH, xpath, require_enabled=False):
                        driver.switch_to.default_content()
                        return True
                except Exception:
                    driver.switch_to.default_content()

            visible_text = self._max_visible_text(driver).lower()
            if any(marker.lower() in visible_text for marker in MAX_OPEN_EMAIL_TEXT_MARKERS):
                return True

            if time.monotonic() >= deadline:
                return False
            time.sleep(0.25)

    def _connect_integrated_softphone(self, driver) -> None:
        if self._is_assigned_email_pane_visible(driver, quick_timeout=2):
            return
        try:
            self._click_xpath_any_frame(driver, INTEGRATED_SOFTPHONE_XPATH, timeout=8)
            time.sleep(0.2)
            self._click_xpath_any_frame(driver, CONNECT_BUTTON_XPATH, timeout=8)
            time.sleep(2.0)
        except Exception:
            body_text = self._max_visible_text(driver)
            if self._is_assigned_email_pane_visible(driver, quick_timeout=1):
                return
            if any(
                marker in body_text
                for marker in ("AGENT LEG", "AVAILABLE", "UNAVAILABLE", "Inbox", "Quick Replies")
            ):
                return
            raise

    def _change_agent_state_available(self, driver) -> None:
        if self._is_assigned_email_pane_visible(driver, quick_timeout=2):
            return
        try:
            self._click_xpath_any_frame(driver, AGENT_STATE_DROPDOWN_XPATH, timeout=8)
            time.sleep(0.4)
            self._click_xpath_any_frame(driver, AVAILABLE_STATE_XPATH, timeout=8)
        except Exception:
            body_text = self._max_visible_text(driver)
            if self._is_assigned_email_pane_visible(driver, quick_timeout=1):
                return
            if "AVAILABLE" in body_text or "Inbox" in body_text or "Working (" in body_text:
                return
            raise

    def _click_accept_popup_if_present(self, driver, wait_seconds: int) -> bool:
        deadline = time.monotonic() + max(wait_seconds, 0)
        while True:
            for xpath in ACCEPT_BUTTON_XPATHS:
                try:
                    self._click_xpath_any_frame(driver, xpath, timeout=1)
                    time.sleep(2.0)
                    return True
                except Exception:
                    pass
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.5)

    def _accept_assigned_email(self, driver) -> None:
        if self._is_assigned_email_pane_visible(driver, quick_timeout=2):
            return
        if self._click_accept_popup_if_present(driver, wait_seconds=24):
            return
        if self._is_assigned_email_pane_visible(driver, quick_timeout=2):
            return
        raise RuntimeError("assigned email Accept button not found")

    # -- subject/body extraction --------------------------------------------

    def _email_container_text(self, driver) -> str:
        from selenium.webdriver.common.by import By

        for xpath in (ASSIGNED_EMAIL_CONTAINER_XPATH, '//*[@id="email-container"]'):
            try:
                element = self._find_in_frames(driver, By.XPATH, xpath, require_enabled=False)
                if element is not None:
                    text = self._element_text_or_value(driver, element)
                    if text:
                        driver.switch_to.default_content()
                        return text
            except Exception:
                driver.switch_to.default_content()
        return ""

    def _guess_subject_from_email_container_text(self, driver) -> str:
        skipped_exact = {
            "Reply", "Reply All", "Forward", "Park Email", "Transfer", "Requeue",
            "Launch", "End Email", "Quick Replies", "Skill Level", "Favorites",
        }
        text = self._email_container_text(driver)
        for line in (item.strip() for item in text.splitlines()):
            if not line or line in skipped_exact:
                continue
            if "@" in line or len(line) > 140:
                continue
            if re.search(r"\b\d{1,2}:\d{2}\b", line) or re.search(
                r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)day\b", line
            ):
                continue
            if line.lower() in {"inbox", "outbound (0)", "working (1)", "parked (0)"}:
                continue
            return line
        return ""

    def _extract_subject(self, driver) -> str:
        from selenium.webdriver.common.by import By

        for xpath in ASSIGNED_EMAIL_SUBJECT_XPATHS:
            try:
                element = self._wait_xpath_any_frame(driver, xpath, timeout=12)
                subject = normalize_text(self._copy_element_text(driver, element))
                if subject and subject.strip().lower() not in {"subject", "subject:"}:
                    return subject
            except Exception:
                pass

        guessed = self._guess_subject_from_email_container_text(driver)
        if guessed:
            return guessed
        raise RuntimeError("accepted email subject not found")

    def _fallback_longest_email_body_text(self, driver) -> str:
        from selenium.webdriver.common.by import By

        driver.switch_to.default_content()
        candidates: list[str] = []

        def collect(depth: int = 0) -> None:
            for element in driver.find_elements(
                By.XPATH, "//p | //div[contains(@class,'message') or contains(@id,'email')]"
            ):
                if element.is_displayed():
                    text = normalize_text(element.text)
                    if len(text) > 20:
                        candidates.append(text)
            if depth >= 4:
                return
            for frame in driver.find_elements(By.XPATH, "//iframe | //frame"):
                entered = False
                try:
                    driver.switch_to.frame(frame)
                    entered = True
                    collect(depth + 1)
                except Exception:
                    pass
                finally:
                    try:
                        if entered:
                            driver.switch_to.parent_frame()
                    except Exception:
                        driver.switch_to.default_content()

        collect()
        return max(candidates, key=len) if candidates else ""

    def _extract_body(self, driver) -> str:
        from selenium.common.exceptions import TimeoutException
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait

        try:
            driver.switch_to.default_content()
            iframe = None
            last_iframe_error: Exception | None = None
            for iframe_xpath in ASSIGNED_EMAIL_BODY_IFRAME_XPATHS:
                try:
                    driver.switch_to.default_content()
                    iframe = WebDriverWait(driver, 20).until(
                        lambda d, xp=iframe_xpath: self._find_in_frames(
                            d, By.XPATH, xp, require_enabled=False
                        )
                    )
                    break
                except Exception as exc:
                    last_iframe_error = exc
            if iframe is None:
                raise RuntimeError(f"accepted email body iframe not found: {last_iframe_error}")
            driver.switch_to.frame(iframe)
            for xpath in ASSIGNED_EMAIL_BODY_XPATHS:
                try:
                    element = WebDriverWait(driver, 10).until(
                        lambda d: next(
                            (item for item in d.find_elements(By.XPATH, xpath) if item.is_displayed()),
                            None,
                        )
                    )
                    body = normalize_text(self._copy_element_text(driver, element))
                    if body:
                        driver.switch_to.default_content()
                        return body
                except Exception:
                    pass
            raise RuntimeError("accepted email body iframe text not found")
        except Exception as exc:
            self.log(f"provided email body xpath failed; using fallback scan: {exc}")
            driver.switch_to.default_content()
            body = normalize_text(self._fallback_longest_email_body_text(driver))
            driver.switch_to.default_content()
            if not body:
                raise RuntimeError("accepted email body not found") from exc
            return body

    # -- reply / park --------------------------------------------------

    def _click_reply_button(self, driver) -> None:
        driver.switch_to.default_content()
        last_error = None
        for xpath in REPLY_BUTTON_XPATHS:
            try:
                self._click_xpath_any_frame(driver, xpath, timeout=10)
                time.sleep(1.0)
                return
            except Exception as exc:
                last_error = exc
        raise RuntimeError(f"MAX email Reply button not found: {last_error}")

    def _insert_text_into_editor(self, driver, element, text: str) -> bool:
        return bool(
            driver.execute_script(
                """
                const node = arguments[0];
                const text = arguments[1];
                const doc = node.ownerDocument || document;

                function fire(target) {
                    target.dispatchEvent(new InputEvent('input', {bubbles: true, inputType: 'insertText', data: text}));
                    target.dispatchEvent(new Event('change', {bubbles: true}));
                    target.dispatchEvent(new KeyboardEvent('keyup', {bubbles: true, key: ' '}));
                }

                function insertInto(target) {
                    target.scrollIntoView({block: 'center'});
                    target.focus();

                    if (target.tagName === 'TEXTAREA' || target.tagName === 'INPUT') {
                        const start = target.selectionStart || 0;
                        const end = target.selectionEnd || start;
                        target.value = target.value.slice(0, start) + text + target.value.slice(end);
                        target.selectionStart = target.selectionEnd = start + text.length;
                        fire(target);
                        return true;
                    }

                    const editable = (
                        target.isContentEditable || target.getAttribute('role') === 'textbox'
                            ? target
                            : target.querySelector('[contenteditable="true"], [role="textbox"], textarea, input')
                    );
                    if (!editable) {
                        return false;
                    }

                    editable.scrollIntoView({block: 'center'});
                    editable.focus();
                    const selection = doc.getSelection();
                    if (selection && editable.isContentEditable) {
                        const range = doc.createRange();
                        range.selectNodeContents(editable);
                        range.collapse(true);
                        selection.removeAllRanges();
                        selection.addRange(range);
                        if (doc.execCommand && doc.execCommand('insertText', false, text)) {
                            fire(editable);
                            return true;
                        }
                        range.insertNode(doc.createTextNode(text));
                        range.collapse(false);
                        fire(editable);
                        return true;
                    }

                    if (editable.tagName === 'TEXTAREA' || editable.tagName === 'INPUT') {
                        editable.value = text + editable.value;
                        fire(editable);
                        return true;
                    }

                    editable.textContent = text + "\\n" + editable.textContent;
                    fire(editable);
                    return true;
                }

                return insertInto(node);
                """,
                element,
                text,
            )
        )

    def _reply_template_visible(self, driver, text: str) -> bool:
        first_line = text.splitlines()[0].strip()
        if not first_line:
            return False
        if first_line in self._max_visible_text(driver):
            return True
        try:
            active_value = driver.execute_script(
                """
                const node = document.activeElement;
                return node ? (node.value || node.innerText || node.textContent || '') : '';
                """
            )
            return first_line in str(active_value or "")
        except Exception:
            return False

    def _paste_reply_template(self, driver, text: str) -> None:
        from selenium.webdriver.common.by import By

        last_error = None
        for xpath in REPLY_COMPOSE_EDITOR_XPATHS:
            try:
                compose_element = self._find_in_frames(driver, By.XPATH, xpath, require_enabled=False)
                if compose_element is None:
                    continue

                if (compose_element.tag_name or "").lower() == "iframe":
                    driver.switch_to.frame(compose_element)
                    compose_element = next(
                        (
                            item
                            for item in driver.find_elements(
                                By.XPATH,
                                "//*[@contenteditable='true'] | //*[@role='textbox'] | //textarea | /html/body",
                            )
                            if self._visible(item)
                        ),
                        None,
                    )
                    if compose_element is None:
                        raise RuntimeError("reply compose iframe body/editor not found")

                if not self._insert_text_into_editor(driver, compose_element, text):
                    raise RuntimeError("javascript editor insertion returned false")
                time.sleep(0.5)
                if self._reply_template_visible(driver, text):
                    return
            except Exception as exc:
                last_error = exc
            finally:
                driver.switch_to.default_content()

        try:
            from selenium.webdriver import Keys
            from selenium.webdriver.common.action_chains import ActionChains

            _set_clipboard_text(text)
            time.sleep(0.6)
            ActionChains(driver).key_down(Keys.CONTROL).send_keys("v").key_up(Keys.CONTROL).perform()
            time.sleep(0.8)
            if self._reply_template_visible(driver, text):
                return
        except Exception as exc:
            last_error = exc

        try:
            active_element = driver.switch_to.active_element
            active_element.send_keys(text)
            time.sleep(0.8)
            if self._reply_template_visible(driver, text):
                return
        except Exception as exc:
            last_error = exc

        raise RuntimeError(f"reply template paste failed: {last_error}")

    def _attach_files(self, driver, paths: Sequence[str]) -> None:
        """Attach each file to the open MAX reply via the hidden file input.

        Uses `send_keys` on the underlying <input type="file"> directly, which
        sets the file programmatically without opening the native OS picker
        that a human sees when clicking "Add Attachment".
        """

        for path in paths:
            driver.switch_to.default_content()
            file_input = self._find_file_input_any_frame(
                driver, ADD_ATTACHMENT_INPUT_XPATHS, timeout=30
            )
            file_input.send_keys(str(Path(path).resolve()))
            time.sleep(1.5)

    def _click_park_email(self, driver) -> None:
        driver.switch_to.default_content()
        last_error = None
        for xpath in PARK_EMAIL_BUTTON_XPATHS:
            try:
                self._click_xpath_any_frame(driver, xpath, timeout=10)
                time.sleep(1.0)
                return
            except Exception as exc:
                last_error = exc
        raise RuntimeError(f"MAX Park Email button not found: {last_error}")

    # -- persistence --------------------------------------------------

    def _save(self, text: str, title: str, sequence: int) -> Path:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = self.output_dir / f"{stamp}_email-{sequence:02d}_{_safe_filename(title)}.txt"
        path.write_text(text, encoding="utf-8")
        self.log(f"saved extracted email {sequence} to {path.name}")
        return path
