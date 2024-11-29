from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import json
from random import random, randint
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
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.common.keys import Keys
from selenium_stealth import stealth
from urllib3.exceptions import ReadTimeoutError

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
    site: Site
    cookie_name: str
    added: bool

    def __lt__(self, other: Event) -> bool:
        return self.when < other.when


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


@contextmanager
def driver(user_dir: str):
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
    try:
        yield d
    finally:
        d.quit()


def load_cookies(url: str) -> list[Cookie] | None:
    print(f"[{ url }] Loading cookies")
    with tempfile.TemporaryDirectory() as user_dir, driver(user_dir) as d:
        d.set_page_load_timeout(10)

        try:
            d.get(url)
        except TimeoutException:
            print(f"[{url}] Timeout, skipping.")
            return None
        except ReadTimeoutError:
            print(f"[{url}] urllib3 timeout, skipping.")
            return None
        except WebDriverException as e:
            print(f"[{url}] {e.msg}, skipping.")
            return None

        for s in TITLE_ERRORS:
            if s in d.title:
                print(f"[{url}] Title contains '{s}', skipping.")
                return None

        time.sleep(3)

        # Now prod the page to cause more cookies to load:
        width = d.execute_script("return window.innerWidth")
        height = d.execute_script("return window.innerHeight")
        scrollh = d.execute_script("return document.body.scrollHeight")
        chain = webdriver.ActionChains(d)

        # 1. Center mouse
        x, y = int(width / 2), int(height / 2)
        chain.move_by_offset(x, y).pause(0.1)

        # 2. Jiggle mouse
        for i in range(0, 10):
            dx, dy = randint(-50, 50), randint(-50, 50)
            if 0 < x + dx < width and 0 < y + dy < height:
                x += dx
                y += dy
                chain.move_by_offset(dx, dy).pause(random() * 0.2)

        # 3. Scroll to the bottom of the page
        chain.scroll_by_amount(0, scrollh).pause(0.1)

        # 4. Scroll to the top of the page
        chain.scroll_by_amount(0, -scrollh).pause(0.1)

        # 5. Send "End" and "Home" keys
        chain.send_keys(Keys.END).pause(0.1)
        chain.pause(0.1)
        chain.send_keys(Keys.HOME).pause(0.1)

        chain.pause(3).perform()

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


class Site:
    def __init__(
        self, domain: str, category: str, cookies: list[Cookie] | None
    ) -> None:
        self.domain = domain
        self.category = category
        self.cookies = cookies
        self.cookie_names = []
        if self.cookies:
            self.cookie_names = [cookie.name for cookie in self.cookies]

    def any_red(self) -> bool:
        return any(cookie_match(target, self.cookie_names) for target in TARGETS)

    def matches(self, target: str) -> bool:
        return cookie_match(target, self.cookie_names)

    def css_classes(self) -> str:
        parts = ["site"]
        if self.any_red():
            parts.append("red")
        if self.category:
            parts.append(self.category)

        return " ".join(parts)


class Catalog:
    def __init__(self) -> None:
        now = datetime.now(UTC)
        ts = now.strftime("%Y%m%d")
        self.today_path = Path("scans") / ts
        self.today_path.mkdir(parents=True, exist_ok=True)

        self.sites: list[Site] = []
        s = open("sites.txt").read()
        prev_domain = None
        for line in s.split("\n"):
            if not line:
                continue

            parts = line.split(",")
            if len(parts) == 1:
                parts.append("null")

            domain, category = parts[0], parts[1]
            assert domain != prev_domain, f"Duplicate: { domain }"
            prev_domain = domain
            cookielist = self.get_cookies(domain)
            if cookielist is None:
                cookielist = load_cookies(f"https://{ domain }")
                if cookielist is not None:
                    self.set_cookies(domain, cookielist)

            self.sites.append(Site(domain, category, cookielist))

    def get_cookies(self, domain: str) -> list[Cookie] | None:
        path = self.today_path / domain.replace("/", "-")
        if path.exists():
            json_bytes = path.read_bytes()
            return CookieList.validate_json(json_bytes)

        return None

    def set_cookies(self, domain: str, cookielist: list[Cookie]) -> None:
        path = self.today_path / domain.replace("/", "-")
        path.write_bytes(CookieList.dump_json(cookielist))

    def get_events(self, site: Site) -> list[Event]:
        result: list[Event] = []
        state = None
        for subdir in sorted(Path("scans").iterdir()):
            path = subdir / site.domain.replace("/", "-")
            if not path.exists():
                continue

            doc = json.loads(path.open().read())
            names = set(c["name"] for c in doc)
            new_state = set(t for t in CHANGES_TARGETS if cookie_match(t, names))

            if state is not None:
                d = datetime.strptime(subdir.name, "%Y%m%d").date()
                for removed_cookie in state - new_state:
                    result.append(Event(d, site, removed_cookie, False))
                for added_cookie in new_state - state:
                    if d.isoformat() < "2024-10-21" and added_cookie == "Gdynp":
                        # We changed data collection method here causing a bunch
                        # of false positives, filter them out-
                        pass
                    else:
                        result.append(Event(d, site, added_cookie, True))

            state = new_state

        return result

    def get_all_events(self) -> list[Event]:
        events = []
        for site in self.sites:
            events.extend(self.get_events(site))

        return events


def generate_report(catalog: Catalog) -> None:
    """Render sites/index.html"""

    env = Environment(loader=FileSystemLoader("."))
    env.filters["format_date_lv"] = lambda d: format_date(d, "EEEE, d. MMMM", "lv_LV")

    tmpl = env.get_template("report_template.jinja2")
    num_visible = len([True for site in catalog.sites if site.any_red()])

    ctx = {
        "catalog": catalog,
        "now": datetime.now(UTC),
        "targets": TARGETS,
        "num_visible": num_visible,
    }

    html = tmpl.render(**ctx)
    site = Path("site")
    site.mkdir(exist_ok=True)
    with open("site/index.html", "w") as f:
        f.write(html)


if __name__ == "__main__":
    # Load cookies for all sites.
    catalog = Catalog()

    # If any site fails to load, retry:
    if any(site.cookies is None for site in catalog.sites):
        print("Now retrying failed page loads:")
        catalog = Catalog()

    generate_report(catalog)
