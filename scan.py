from __future__ import annotations

from dataclasses import dataclass
import json
import sqlite3
import tempfile
import time
from collections.abc import Iterable
from datetime import UTC, date, datetime
from pathlib import Path

from babel.dates import format_date
from jinja2 import Environment, FileSystemLoader
from pydantic import BaseModel, TypeAdapter
from selenium import webdriver
from selenium.common.exceptions import MoveTargetOutOfBoundsException, TimeoutException
from selenium.webdriver.common.actions.action_builder import ActionBuilder
from selenium_stealth import stealth

# The cookies we show in the report table
TARGETS = ["_ga", "_fbp", "_clck", "_pcid", "_hj*", "Gdynp", "__utm*"]
# The cookies we track in the changes section. Excludes Gdynp as
# on several sites it seems to flip on and off frequently.
CHANGES_TARGETS = ["_ga", "_fbp", "_clck", "_pcid", "_hj*", "__utm*"]

# If the website title contains any of these, we will skip loading cookies for it
TITLE_ERRORS = ["Web server is down", "SSL handshake failed"]


class Cookie(BaseModel):
    name: str
    domain: str
    httpOnly: int
    expiry: int

    def expiry_dt(self) -> date | None:
        if self.expiry:
            return datetime.fromtimestamp(self.expiry).date()
        return None


CookieList = TypeAdapter(list[Cookie])


@dataclass
class Event:
    when: date
    domain: str
    cookie_name: str
    added: bool


def read_chrome_cookiedb(path: str) -> list[Cookie]:
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        res = conn.execute(
            """SELECT
                name,
                host_key as domain,
                is_httponly as httpOnly,
                iif(expires_utc, (expires_utc / 1000000) - 11644473600, 0) as expiry
            FROM cookies"""
        )

        return [Cookie(**row) for row in res.fetchall()]


def make_driver(user_dir: str) -> webdriver.Chrome:
    opts = webdriver.ChromeOptions()
    opts.add_argument("--headless=new")
    opts.add_argument("--window-size=2560,1440")
    opts.add_argument(f"--user-data-dir={user_dir}")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    service = webdriver.ChromeService(executable_path="/usr/bin/chromedriver")
    d = webdriver.Chrome(options=opts, service=service)
    stealth(
        d,
        languages=["en-US", "en"],
        vendor="Google Inc.",
        platform="Win32",
        webgl_vendor="Intel Inc.",
        renderer="Intel Iris OpenGL Engine",
        fix_hairline=True,
    )
    return d


def load_cookies(url: str) -> list[Cookie] | None:
    print(f"[{ url }] Loading cookies")
    with tempfile.TemporaryDirectory() as user_dir:
        d = make_driver(user_dir)
        try:
            d.get(url)
        except TimeoutException:
            print(f"[{url}] Timeout, skipping.")
            return None

        for s in TITLE_ERRORS:
            if s in d.title:
                print(f"[{url}] Title contains '{s}', skipping.")
                return None

        time.sleep(3)

        # Now prod the page to cause more cookies to load:
        # 1. Move mouse to all corners of the sceeen
        width = d.execute_script("return window.innerWidth")
        height = d.execute_script("return window.innerHeight")
        for x, y in [
            (10, 10),
            (10, height - 10),
            (width - 10, 10),
            (width - 10, height - 10),
        ]:
            action = ActionBuilder(d)
            action.pointer_action.move_to_location(x, y)
            try:
                action.perform()
            except MoveTargetOutOfBoundsException as e:
                print("Element is out of bounds: ", e)

        # 2. Scroll to the bottom of the page
        scrollh = d.execute_script("return document.body.scrollHeight")
        webdriver.ActionChains(d).scroll_by_amount(0, scrollh).perform()
        time.sleep(0.5)

        # 3. Scroll to the top of the page
        webdriver.ActionChains(d).scroll_by_amount(0, -scrollh).perform()
        time.sleep(3)
        d.quit()

        # d.get_cookies() does not return httpOnly cookies, so read them from
        # chromium's sqlite database:
        return read_chrome_cookiedb(user_dir + "/Default/Cookies")


def cookie_match(target: str, cookies: Iterable[str]) -> bool:
    """Return True if a cookie name is present in `cookies`.

    This function supports wildcard matching, but for trailing wildcards only
    (_hj*, __utm*).

    """
    if target.endswith("*"):
        target = target[:-1]
        return any(name.startswith(target) for name in cookies)
    return target in cookies


def any_target_match(cookies: Iterable[str]) -> bool:
    """Return True if any cookie listed in `TARGETS` is present in `cookies`."""
    return any(cookie_match(target, cookies) for target in TARGETS)


class Site:
    def __init__(self, domain):
        self.domain = domain

    def cookies(self) -> list[Cookie] | None:
        cookielist = catalog.get_cookies(self.domain)
        if cookielist is None:
            cookielist = load_cookies(f"https://{ self.domain }")
            if cookielist is not None:
                catalog.set_cookies(self.domain, cookielist)
        return cookielist


class Catalog:
    def __init__(self) -> None:
        now = datetime.now(UTC)
        ts = now.strftime("%Y%m%d")
        self.today_path = Path("scans") / ts
        self.today_path.mkdir(parents=True, exist_ok=True)

        self._domains: dict[str, str] = {}
        s = open("sites.txt").read()
        for line in s.split("\n"):
            if not line:
                continue

            parts = line.split(",")
            if len(parts) == 1:
                parts.append("null")

            self._domains[parts[0]] = parts[1]

    def get_cookies(self, domain: str) -> list[Cookie] | None:
        path = self.today_path / domain.replace("/", "-")
        if path.exists():
            json_bytes = path.read_bytes()
            return CookieList.validate_json(json_bytes)

        return None

    def get_events(self, domain: str) -> list[Event]:
        result, state = [], None
        for subdir in sorted(Path("scans").iterdir()):
            path = subdir / domain.replace("/", "-")
            if not path.exists():
                continue

            doc = json.loads(path.open().read())
            names = set(c["name"] for c in doc)
            new_state = set(t for t in CHANGES_TARGETS if cookie_match(t, names))

            if state is not None:
                d = datetime.strptime(subdir.name, "%Y%m%d").date()
                for removed_cookie in state - new_state:
                    result.append(Event(d, domain, removed_cookie, False))
                for added_cookie in new_state - state:
                    if d.isoformat() < "2024-10-21" and added_cookie == "Gdynp":
                        # We changed data collection method here causing a bunch
                        # of false positives, filter them out-
                        pass
                    else:
                        result.append(Event(d, domain, added_cookie, True))

            state = new_state

        return result

    def set_cookies(self, domain: str, cookielist: list[Cookie]) -> None:
        path = self.today_path / domain.replace("/", "-")
        path.write_bytes(CookieList.dump_json(cookielist))

    def domains(self) -> Iterable[str]:
        return self._domains.keys()

    def sites(self):
        for domain in self._domains.keys():
            return Site(domain)

    def category(self, domain: str) -> str:
        return self._domains[domain]


def load_todays_cookies(catalog: Catalog) -> dict[str, dict[str, Cookie]]:
    sites = {}
    for domain in catalog.domains():
        # Load cookies from local cache (catalog).
        # If they are not in the cache, load the website.
        cookielist = catalog.get_cookies(domain)
        if cookielist is None:
            cookielist = load_cookies(f"https://{ domain }")
            if cookielist is not None:
                catalog.set_cookies(domain, cookielist)

        sites[domain] = {}
        if cookielist:
            cookielist.sort(key=lambda item: item.name)
            for item in cookielist:
                sites[domain][item.name] = item

    return sites


def all_events(catalog: Catalog) -> list[Event]:
    events = []
    for domain in catalog.domains():
        events.extend(catalog.get_events(domain))

    return events


def generate_report(
    catalog: Catalog, sites: dict[str, dict[str, Cookie]], events: list[Event]
) -> None:
    """Render sites/index.html"""
    site_classes = {}
    for domain, cookies in sites.items():
        parts = ["site"]
        if any_target_match(cookies):
            parts.append("red")
        if category := catalog.category(domain):
            parts.append(category)
        site_classes[domain] = " ".join(parts)

    env = Environment(loader=FileSystemLoader("."))
    env.tests["matching"] = cookie_match
    env.tests["matching_any"] = any_target_match
    env.filters["format_date_lv"] = lambda d: format_date(d, "EEEE, d. MMMM", "lv_LV")
    env.filters["site_classes"] = lambda domain: site_classes[domain]

    tmpl = env.get_template("report_template.jinja2")
    ctx = {
        "catalog": catalog,
        "now": datetime.now(UTC),
        "targets": TARGETS,
        "sites": sites,
        "events": events,
        "num_visible": sum(any_target_match(cookies) for cookies in sites.values()),
    }

    html = tmpl.render(**ctx)
    site = Path("site")
    site.mkdir(exist_ok=True)
    with open("site/index.html", "w") as f:
        f.write(html)


if __name__ == "__main__":
    catalog = Catalog()
    sites = load_todays_cookies(catalog)
    events = all_events(catalog)
    generate_report(catalog, sites, events)
