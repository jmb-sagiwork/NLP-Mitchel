"""Look up Salesforce Site ID(s) by claim number.

Ported from the standalone PCC_Email_FP1 Salesforce prototype script. The
prototype paused for three manual confirmation popups per claim (page
loaded, search results loaded, case links ready); this module instead opens
Salesforce and logs in once per pipeline run (via `login_gate`, called
lazily on first use) and relies on `WebDriverWait`-based readiness checks
for every step after that, so it can run unattended in a per-claim loop.
"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable
from urllib.parse import urljoin

from .driver import create_driver

SALESFORCE_URL = "https://mitchell.lightning.force.com/lightning/page/home"
SALESFORCE_URL_MARKERS = (
    "mitchell.lightning.force.com",
    "mitchell.my.salesforce.com",
    "login.salesforce.com",
)
SALESFORCE_START_ERROR_URL_MARKERS = (
    "mitchell.file.force.com",
    "/secur/contentdoor",
    "contentdoor",
)
SALESFORCE_START_ERROR_TEXT_MARKERS = (
    "ERR_CONNECTION_CLOSED",
    "This site can't be reached",
    "This site can’t be reached",
    "unexpectedly closed the connection",
)
SALESFORCE_READY_TEXT_MARKERS = ("Salesforce", "MiApp", "Home", "Search")
SALESFORCE_LOGIN_TEXT_MARKERS = (
    "OneLogin",
    "Login",
    "Log In",
    "Sign In",
    "Username",
    "Password",
)
SEARCH_TRIGGER_XPATH_CANDIDATES = (
    ("oneHeader collapsed search container", '//*[@id="oneHeader"]/div[2]/div[2]/div/div[1]'),
    (
        "oneHeader collapsed search button",
        '//*[@id="oneHeader"]/div[2]/div[2]/div/div[1]/button',
    ),
)
SEARCH_INPUT_XPATH_CANDIDATES = (
    ("expanded search input id 275:0", '//*[@id="275:0"]'),
    ("expanded search input id input-143", '//*[@id="input-143"]'),
    ("legacy search input id input-135", '//*[@id="input-135"]'),
)
SEARCH_INPUT_CSS_CANDIDATES = (
    ("exact placeholder search input", 'input[placeholder="Search..."]'),
    ("placeholder contains Search", 'input[placeholder*="Search"]'),
    ("type search input", 'input[type="search"]'),
    ("aria-label search input", 'input[aria-label*="Search"]'),
)
CASES_LEFT_NAV_XPATH = (
    '//*[@id="brandBand_2"]/div/div/div[2]/div/div/div/div[1]/div[1]/nav/'
    "div/div[3]/ul/li[2]/a/span/span[1]"
)
CASE_ROW_LINK_XPATH_TEMPLATE = (
    '//*[@id="brandBand_2"]/div/div/div[4]/div/div/div/div[2]/div/div/div/'
    "div[2]/div/div/div/div[2]/div/div/div/div[2]/div[2]/div[1]/"
    "div/div/table/tbody/tr[{row}]/th/span/a"
)
CASE_LINK_CSS = (
    'a[href*="/lightning/r/500"][href*="/view"], '
    'a[href*="/lightning/r/Case/"][href*="/view"], '
    'table tbody tr th a[href*="/lightning/r/"]'
)
SITE_ID_EXPLICIT_VALUE_XPATHS = (
    (
        "dynamic sectionContent Site ID lightning-formatted-text",
        "//*[starts-with(@id,'sectionContent-')]"
        "//*[self::span or self::label][normalize-space()='Site ID' or "
        "normalize-space()='Site Id' or normalize-space()='SiteID']"
        "/ancestor::*[contains(@class,'slds-form-element')][1]"
        "//lightning-formatted-text[normalize-space()]",
    ),
    (
        "dynamic sectionContent Site ID output field",
        "//*[starts-with(@id,'sectionContent-')]"
        "//*[self::span or self::label][normalize-space()='Site ID' or "
        "normalize-space()='Site Id' or normalize-space()='SiteID']"
        "/ancestor::*[contains(@class,'slds-form-element')][1]"
        "//*[contains(@class,'test-id__field-value') or "
        "contains(@class,'slds-form-element__static')]//*[normalize-space()]",
    ),
    (
        "any Details Site ID lightning-formatted-text",
        "//*[self::span or self::label][normalize-space()='Site ID' or "
        "normalize-space()='Site Id' or normalize-space()='SiteID']"
        "/ancestor::*[contains(@class,'slds-form-element')][1]"
        "//lightning-formatted-text[normalize-space()]",
    ),
)

LoginGate = Callable[[], None]
LogCallback = Callable[[str], None]


def _clean_site_id_candidate(value: str | None) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    value = re.sub(r"\s+", " ", value)
    value = re.sub(r"^(site\s*id|siteid|site)\s*[:\-]?\s*", "", value, flags=re.I)
    return value.strip(" :-\t\r\n")


def _is_valid_site_id_candidate(value: str | None) -> bool:
    value = _clean_site_id_candidate(value)
    if not value:
        return False
    if re.fullmatch(r"(?i)(site\s*id|siteid|site|details|related|edit)", value):
        return False
    if len(value) > 80:
        return False
    return bool(re.search(r"[A-Za-z0-9]", value))


def _line_after_label(lines: list[str], label_pattern: re.Pattern[str]) -> str | None:
    for index, line in enumerate(lines):
        if label_pattern.fullmatch(line.strip()):
            for next_line in lines[index + 1 : index + 5]:
                candidate = next_line.strip()
                if candidate and not label_pattern.fullmatch(candidate):
                    return candidate
    return None


def _extract_site_id_from_text(page_text: str) -> str | None:
    if not page_text.strip():
        return None

    label_regex = re.compile(r"(?i)site\s*id")
    lines = [line.strip() for line in page_text.splitlines() if line.strip()]
    candidate = _line_after_label(lines, label_regex)
    if candidate and not re.search(r"(?i)^(details|related|edit|site\s*id)$", candidate):
        return candidate

    inline_patterns = (
        r"(?im)\bSite\s*ID\b\s*[:\-]?\s*([A-Za-z0-9][A-Za-z0-9_.\- ]{1,80})",
        r"(?im)\bSiteID\b\s*[:\-]?\s*([A-Za-z0-9][A-Za-z0-9_.\- ]{1,80})",
    )
    for pattern in inline_patterns:
        match = re.search(pattern, page_text)
        if not match:
            continue
        value = match.group(1).strip()
        value = re.split(r"\s{2,}|\n|\r", value)[0].strip()
        if value and not re.search(r"(?i)^(details|related|edit|site\s*id)$", value):
            return value

    return None


class SalesforceLookup:
    """Resolve Site ID(s) for a claim number using a persistent Salesforce session."""

    def __init__(self, *, login_gate: LoginGate, log: LogCallback | None = None) -> None:
        self.login_gate = login_gate
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

    def site_id_for_claim(self, claim_number: str) -> str:
        """Return a comma-separated Site ID summary for one claim number."""

        driver = self._ensure_session()
        self._search_claim_number(driver, claim_number)
        self._click_cases_filter(driver)
        time.sleep(1.2)
        case_links = self._extract_case_links(driver)

        found_site_ids: list[str] = []
        seen: set[str] = set()
        for index, item in enumerate(case_links, start=1):
            checked = self._open_case_and_extract_site_id(driver, item["href"], index)
            site_id = (checked.get("site_id") or "").strip()
            if site_id and site_id.upper() not in seen:
                seen.add(site_id.upper())
                found_site_ids.append(site_id)

        return ", ".join(found_site_ids)

    def _ensure_session(self):
        with self._driver_lock:
            if self._driver is not None:
                return self._driver
            driver = create_driver()
            self._driver = driver
        self._open_salesforce_home_resilient(driver)
        self.login_gate()
        self._recover_after_manual_login(driver)
        return driver

    def _safe_page_state(self, driver) -> tuple[str, str]:
        try:
            current_url = driver.current_url
        except Exception as exc:
            current_url = f"<unavailable: {type(exc).__name__}>"
        try:
            title = driver.title
        except Exception as exc:
            title = f"<unavailable: {type(exc).__name__}>"
        return current_url, title

    def _read_body_text(self, driver) -> str:
        try:
            return driver.execute_script(
                "return document.body ? document.body.innerText : '';"
            ) or ""
        except Exception:
            try:
                return driver.page_source or ""
            except Exception:
                return ""

    def _is_start_error_page(self, driver) -> bool:
        current_url, title = self._safe_page_state(driver)
        current_url_lower = current_url.lower()
        title_lower = title.lower()
        if any(marker in current_url_lower for marker in SALESFORCE_START_ERROR_URL_MARKERS):
            return True
        page_text = self._read_body_text(driver)
        searchable_text = f"{title}\n{page_text}".lower()
        if any(
            marker.lower() in searchable_text for marker in SALESFORCE_START_ERROR_TEXT_MARKERS
        ):
            return True
        return "site can't be reached" in title_lower or "site can’t be reached" in title_lower

    def _looks_like_salesforce_page(self, driver) -> bool:
        current_url, title = self._safe_page_state(driver)
        if self._is_start_error_page(driver):
            return False
        page_text = self._read_body_text(driver)
        searchable_text = f"{title}\n{page_text}".lower()
        if any(marker.lower() in searchable_text for marker in SALESFORCE_LOGIN_TEXT_MARKERS):
            return True
        current_url_lower = current_url.lower()
        return any(marker in current_url_lower for marker in SALESFORCE_URL_MARKERS) and any(
            marker.lower() in searchable_text for marker in SALESFORCE_READY_TEXT_MARKERS
        )

    def _open_salesforce_home_resilient(self, driver, max_attempts: int = 4) -> None:
        from selenium.webdriver.support.ui import WebDriverWait

        last_state = ""
        for attempt in range(1, max_attempts + 1):
            self.log(f"Salesforce open attempt {attempt}/{max_attempts}")
            driver.get(SALESFORCE_URL)
            time.sleep(1.0)

            if self._is_start_error_page(driver):
                self.log("Salesforce startup error page detected; refreshing")
                driver.refresh()
                time.sleep(2.0)

            try:
                WebDriverWait(driver, 8).until(
                    lambda current_driver: self._looks_like_salesforce_page(current_driver)
                )
                self.log("Salesforce page is usable")
                return
            except Exception:
                current_url, title = self._safe_page_state(driver)
                last_state = f"current_url={current_url}; title={title}"
                self.log(f"Salesforce page not ready after attempt {attempt}: {last_state}")

        raise RuntimeError(
            "Salesforce Home could not be loaded after automatic refresh/retry. "
            f"Last browser state: {last_state}"
        )

    def _recover_after_manual_login(self, driver) -> None:
        if self._is_start_error_page(driver):
            self.log("Salesforce startup error still visible after login; reopening")
            self._open_salesforce_home_resilient(driver, max_attempts=3)
            return
        if self._looks_like_salesforce_page(driver):
            self.log("Salesforce page verified after login")
            return
        self.log("Salesforce page not verified after login; reopening Home")
        self._open_salesforce_home_resilient(driver, max_attempts=2)

    def _wait_for_search_box(self, driver, timeout: int = 45):
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait

        def find_input(short_timeout: int):
            last_error = None
            for _label, xpath in SEARCH_INPUT_XPATH_CANDIDATES:
                try:
                    return WebDriverWait(driver, short_timeout).until(
                        EC.element_to_be_clickable((By.XPATH, xpath))
                    )
                except Exception as exc:
                    last_error = exc
            for _label, selector in SEARCH_INPUT_CSS_CANDIDATES:
                try:
                    return WebDriverWait(driver, short_timeout).until(
                        lambda current_driver: next(
                            (
                                item
                                for item in current_driver.find_elements(
                                    By.CSS_SELECTOR, selector
                                )
                                if item.is_displayed() and item.is_enabled()
                            ),
                            None,
                        )
                    )
                except Exception as exc:
                    last_error = exc
            if last_error:
                raise last_error
            raise RuntimeError("no search input locators configured")

        try:
            return find_input(2)
        except Exception:
            self.log("search input not already expanded; trying collapsed search triggers")

        for label, xpath in SEARCH_TRIGGER_XPATH_CANDIDATES:
            try:
                trigger = WebDriverWait(driver, timeout).until(
                    EC.element_to_be_clickable((By.XPATH, xpath))
                )
                driver.execute_script(
                    "arguments[0].scrollIntoView({block: 'center'});", trigger
                )
                try:
                    trigger.click()
                except Exception:
                    driver.execute_script("arguments[0].click();", trigger)
                time.sleep(0.35)
                return find_input(8)
            except Exception as exc:
                self.log(f"search trigger failed: {label}: {type(exc).__name__}")

        return find_input(timeout)

    def _search_claim_number(self, driver, claim_number: str) -> None:
        from selenium.webdriver.common.keys import Keys

        self.log(f"searching Salesforce claim number: {claim_number}")
        search_box = self._wait_for_search_box(driver)
        try:
            search_box.click()
        except Exception:
            driver.execute_script("arguments[0].click();", search_box)
        time.sleep(0.2)
        search_box.send_keys(Keys.CONTROL, "a")
        search_box.send_keys(Keys.BACKSPACE)
        search_box.send_keys(claim_number)
        search_box.send_keys(Keys.ENTER)

    def _click_cases_filter(self, driver) -> None:
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait

        try:
            element = WebDriverWait(driver, 30).until(
                EC.element_to_be_clickable((By.XPATH, CASES_LEFT_NAV_XPATH))
            )
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
            driver.execute_script("arguments[0].click();", element)
            return
        except Exception as exc:
            self.log(f"Cases filter xpath failed: {type(exc).__name__}")

        candidates = driver.find_elements(
            By.XPATH,
            "//a[.//span[normalize-space()='Cases'] or normalize-space()='Cases']"
            " | //button[.//span[normalize-space()='Cases'] or normalize-space()='Cases']",
        )
        for candidate in candidates:
            if candidate.is_displayed():
                driver.execute_script(
                    "arguments[0].scrollIntoView({block: 'center'});", candidate
                )
                driver.execute_script("arguments[0].click();", candidate)
                return

        raise RuntimeError("Cases filter could not be clicked.")

    def _extract_case_links(self, driver, max_rows: int = 75) -> list[dict[str, str]]:
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait

        WebDriverWait(driver, 45).until(
            lambda d: "Cases" in d.page_source or "Case Nu" in d.page_source
        )
        time.sleep(0.8)

        links: list[dict[str, str]] = []
        seen: set[str] = set()

        for row in range(1, max_rows + 1):
            xpath = CASE_ROW_LINK_XPATH_TEMPLATE.format(row=row)
            elements = driver.find_elements(By.XPATH, xpath)
            if not elements:
                continue
            element = elements[0]
            href = element.get_attribute("href") or ""
            text = element.text.strip()
            if not href:
                continue
            href = urljoin(driver.current_url, href)
            if href in seen:
                continue
            seen.add(href)
            links.append({"row": str(row), "text": text, "href": href})

        if links:
            return links

        self.log("row xpath extraction found no links; trying CSS fallback")
        for element in driver.find_elements(By.CSS_SELECTOR, CASE_LINK_CSS):
            if not element.is_displayed():
                continue
            href = element.get_attribute("href") or ""
            text = element.text.strip()
            if not href or "/lightning/r/" not in href:
                continue
            href = urljoin(driver.current_url, href)
            if href in seen:
                continue
            seen.add(href)
            links.append({"row": "", "text": text, "href": href})

        return links

    def _extract_site_id_with_salesforce_dom_script(self, driver) -> tuple[str | None, str]:
        value = driver.execute_script(
            r"""
            const normalize = (text) => (text || '').replace(/\s+/g, ' ').trim();
            const isSiteLabel = (text) => /^(site\s*id|siteid)$/i.test(normalize(text));
            const isValue = (text) => {
                const value = normalize(text).replace(/^(site\s*id|siteid)\s*[:\-]?\s*/i, '').trim();
                return !!value && !/^(site\s*id|siteid|site|details|related|edit)$/i.test(value) &&
                    value.length <= 80 && /[A-Za-z0-9]/.test(value);
            };

            const selectors = [
                'span.test-id__field-label',
                '.test-id__field-label',
                'records-record-layout-item span',
                'records-record-layout-item label',
                'span',
                'label'
            ];
            const labels = [];
            for (const selector of selectors) {
                for (const node of document.querySelectorAll(selector)) {
                    if (isSiteLabel(node.innerText || node.textContent)) labels.push(node);
                }
                if (labels.length) break;
            }

            for (const label of labels) {
                const containers = [];
                let current = label;
                for (let depth = 0; current && depth < 8; depth += 1, current = current.parentElement) {
                    containers.push(current);
                }

                for (const container of containers) {
                    const valueSelectors = [
                        'lightning-formatted-text',
                        '[data-output-element-id="output-field"]',
                        '.test-id__field-value',
                        '.slds-form-element__static',
                        'slot[name="outputField"]',
                        'span',
                        'div'
                    ];
                    for (const selector of valueSelectors) {
                        for (const node of container.querySelectorAll(selector)) {
                            if (node === label || label.contains(node)) continue;
                            const text = normalize(node.innerText || node.textContent);
                            if (isValue(text)) {
                                return text.replace(/^(site\s*id|siteid)\s*[:\-]?\s*/i, '').trim();
                            }
                        }
                    }
                }
            }
            return '';
            """
        )
        value = _clean_site_id_candidate(value)
        if _is_valid_site_id_candidate(value):
            return value, "dom-salesforce-label-value"
        return None, "dom-salesforce-label-value-empty"

    def _extract_site_id_from_dom(self, driver) -> tuple[str | None, str]:
        from selenium.webdriver.common.by import By

        for label, xpath in SITE_ID_EXPLICIT_VALUE_XPATHS:
            try:
                elements = driver.find_elements(By.XPATH, xpath)
            except Exception:
                continue
            for element in elements:
                try:
                    value = _clean_site_id_candidate(
                        element.text or element.get_attribute("textContent")
                    )
                except Exception:
                    continue
                if _is_valid_site_id_candidate(value):
                    return value, f"xpath-{label}"

        script_value, script_method = self._extract_site_id_with_salesforce_dom_script(driver)
        if script_value:
            return script_value, script_method

        label_xpath = (
            "//*[self::span or self::div or self::label]"
            "[normalize-space()='Site ID' or normalize-space()='Site Id' "
            "or normalize-space()='SiteID' or normalize-space()='Site']"
        )
        labels = driver.find_elements(By.XPATH, label_xpath)

        for label in labels:
            try:
                value = driver.execute_script(
                    r"""
                    const label = arguments[0];
                    const containers = [
                        label.closest('.slds-form-element'),
                        label.parentElement,
                        label.parentElement && label.parentElement.parentElement,
                        label.parentElement && label.parentElement.parentElement &&
                            label.parentElement.parentElement.parentElement,
                    ].filter(Boolean);
                    for (const container of containers) {
                        const selectors = [
                            '.slds-form-element__static',
                            '.field-value',
                            'lightning-formatted-text',
                            'lightning-formatted-rich-text',
                            'a',
                            'span',
                            'div',
                        ];
                        for (const selector of selectors) {
                            for (const node of container.querySelectorAll(selector)) {
                                const text = (node.innerText || node.textContent || '').trim();
                                if (!text) continue;
                                if (/^site\s*id$/i.test(text) || /^site$/i.test(text)) continue;
                                return text;
                            }
                        }
                    }
                    return '';
                    """,
                    label,
                )
            except Exception:
                continue
            value = (value or "").strip()
            if _is_valid_site_id_candidate(value):
                return _clean_site_id_candidate(value), "dom-label"

        page_text = (
            driver.execute_script("return document.body ? document.body.innerText : '';") or ""
        )
        value = _extract_site_id_from_text(page_text)
        if _is_valid_site_id_candidate(value):
            return _clean_site_id_candidate(value), "text-regex"

        return None, "not-found"

    def _scroll_case_detail_for_site_id(self, driver) -> tuple[str | None, str]:
        for attempt in range(1, 9):
            site_id, method = self._extract_site_id_from_dom(driver)
            if site_id:
                return site_id, f"{method}-attempt-{attempt}"

            driver.execute_script(
                """
                const amount = arguments[0];
                window.scrollBy(0, amount);
                const scrollables = Array.from(document.querySelectorAll('main, section, div'))
                    .filter((el) => {
                        const style = window.getComputedStyle(el);
                        const canScroll = /(auto|scroll)/.test(style.overflowY || '');
                        return canScroll && el.scrollHeight > el.clientHeight + 80 && el.clientHeight > 180;
                    });
                for (const el of scrollables.slice(0, 12)) {
                    el.scrollTop = Math.min(el.scrollTop + amount, el.scrollHeight);
                }
                """,
                420,
            )
            time.sleep(0.55)

        return None, "not-found-after-scroll"

    def _open_case_and_extract_site_id(self, driver, case_link: str, index: int) -> dict[str, str]:
        from selenium.webdriver.support.ui import WebDriverWait

        original_handle = driver.current_window_handle
        before_handles = set(driver.window_handles)
        driver.execute_script("window.open(arguments[0], '_blank');", case_link)
        WebDriverWait(driver, 15).until(
            lambda d: len(set(d.window_handles) - before_handles) >= 1
        )
        new_handle = next(
            handle for handle in driver.window_handles if handle not in before_handles
        )
        driver.switch_to.window(new_handle)

        try:
            WebDriverWait(driver, 45).until(
                lambda d: d.execute_script(
                    "return document.readyState === 'complete' && "
                    "document.body && document.body.innerText.length > 100;"
                )
            )
            time.sleep(1.0)
            site_id, method = self._scroll_case_detail_for_site_id(driver)
            self.log(f"case {index} site id extraction method={method} value={site_id!r}")
            return {"href": case_link, "site_id": site_id or "", "method": method}
        finally:
            driver.close()
            driver.switch_to.window(original_handle)
