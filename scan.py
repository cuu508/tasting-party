from __future__ import annotations

import json
import sqlite3
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from selenium import webdriver
from selenium.webdriver.common.actions.action_builder import ActionBuilder
from selenium_stealth import stealth

TARGETS = ["_ga", "_fbp", "_clck", "_pcid", "_hj*", "Gdynp"]


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
    with tempfile.TemporaryDirectory() as user_dir:
        d = make_driver(user_dir)
        d.get(url)
        time.sleep(3)

        # Now prod the page to cause more cookies to load:
        # 1. Move mouse to all corners of the sceeen
        width = d.execute_script("return document.documentElement.clientWidth")
        height = d.execute_script("return document.documentElement.clientHeight")
        for x, y in [
            (10, 10),
            (10, height - 10),
            (width - 10, 10),
            (width - 10, height - 10),
        ]:
            action = ActionBuilder(d)
            action.pointer_action.move_to_location(x, y)
            action.perform()

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


class Catalog(object):
    def __init__(self):
        now = datetime.now(UTC)
        ts = now.strftime("%Y%m%d")
        self.today_path = Path("scans") / ts
        self.today_path.mkdir(parents=True, exist_ok=True)

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
            new_state = set(c["name"] for c in doc if c["name"] in TARGETS)

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
        s = open("sites.txt", "r").read()
        return s.split("\n")


catalog = Catalog()
sites = {}
for domain in catalog.domains():
    cookielist = catalog.get_cookies(domain)
    if cookielist is None:
        print(f"Loading cookies for { domain }")
        cookielist = load_cookies(f"https://{ domain }")
        catalog.set_cookies(domain, cookielist)

    sites[domain] = {}
    cookielist.sort(key=lambda item: item["name"])
    for item in cookielist:
        if item.get("expiry"):
            item["expiry_dt"] = datetime.fromtimestamp(item["expiry"]).date()
        sites[domain][item["name"]] = item

events = []
for domain in catalog.domains():
    events.extend(catalog.get_cookie_changes(domain))

events.sort(reverse=True)


# Render result
def matching(target, cookies):
    if target.endswith("*"):
        target = target[:-1]
        return any(name.startswith(target) for name in cookies)
    return target in cookies


env = Environment(loader=FileSystemLoader("."))
env.tests["matching"] = matching

tmpl = env.get_template("report_template.html")
now = datetime.now(UTC)
html = tmpl.render(now=now, targets=TARGETS, sites=sites, events=events)
site = Path("site")
site.mkdir(exist_ok=True)
with open("site/index.html", "w") as f:
    f.write(html)
with open(f"site/{now:%Y%m%d}.html", "w") as f:
    f.write(html)
