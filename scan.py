from __future__ import annotations

import json
import sqlite3
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from babel.dates import format_date
from jinja2 import Environment, FileSystemLoader
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


def read_chrome_cookiedb(path):
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

        return [dict(row) for row in res.fetchall()]


def make_driver(user_dir):
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


def load_cookies(url):
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
        time.sleep(3)

        # 3. Scroll to the top of the page
        webdriver.ActionChains(d).scroll_by_amount(0, -scrollh).perform()
        time.sleep(3)
        d.quit()

        # d.get_cookies() does not return httpOnly cookies, so read them from
        # chromium's sqlite database:
        return read_chrome_cookiedb(user_dir + "/Default/Cookies")


def cookie_match(target, cookies):
    if target.endswith("*"):
        target = target[:-1]
        return any(name.startswith(target) for name in cookies)
    return target in cookies


def any_target_match(cookies):
    return any(cookie_match(target, cookies) for target in TARGETS)


class Catalog:
    def __init__(self):
        now = datetime.now(UTC)
        ts = now.strftime("%Y%m%d")
        self.today_path = Path("scans") / ts
        self.today_path.mkdir(parents=True, exist_ok=True)

        self._domains = {}
        s = open("sites.txt").read()
        for line in s.split("\n"):
            if not line:
                continue

            parts = line.split(",")
            if len(parts) == 1:
                parts.append("null")

            self._domains[parts[0]] = parts[1]

    def get_cookies(self, domain):
        path = self.today_path / domain.replace("/", "-")
        if path.exists():
            return json.loads(path.open().read())

    def get_cookie_changes(self, domain):
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
                    result.append((d, domain, removed_cookie, False))
                for added_cookie in new_state - state:
                    if d.isoformat() < "2024-10-21" and added_cookie == "Gdynp":
                        # We changed data collection method here causing a bunch
                        # of false positives, filter them out-
                        pass
                    else:
                        result.append((d, domain, added_cookie, True))

            state = new_state

        return result

    def set_cookies(self, domain, cookielist):
        path = self.today_path / domain.replace("/", "-")
        path.open("w").write(json.dumps(cookielist))

    def domains(self):
        return self._domains.keys()

    def category(self, domain):
        return self._domains[domain]


if __name__ == "__main__":
    catalog = Catalog()
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
            cookielist.sort(key=lambda item: item["name"])
            for item in cookielist:
                if item.get("expiry"):
                    item["expiry_dt"] = datetime.fromtimestamp(item["expiry"]).date()
                sites[domain][item["name"]] = item

    events = []
    for domain in catalog.domains():
        events.extend(catalog.get_cookie_changes(domain))

    events.sort(reverse=True)

    site_classes = {}
    for domain, cookies in sites.items():
        parts = ["site"]
        if any_target_match(cookies):
            parts.append("red")
        if category := catalog.category(domain):
            parts.append(category)
        site_classes[domain] = " ".join(parts)

    # Render result
    env = Environment(loader=FileSystemLoader("."))
    env.tests["matching"] = cookie_match
    env.tests["matching_any"] = any_target_match
    env.filters["format_date_lv"] = lambda d: format_date(d, "EEEE, d. MMMM", "lv_LV")
    env.filters["site_classes"] = lambda domain: site_classes[domain]

    tmpl = env.get_template("report_template.jinja2")
    ctx = {
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

    now = ctx["now"]
    with open(f"site/{now:%Y%m%d}.html", "w") as f:
        f.write(html)
