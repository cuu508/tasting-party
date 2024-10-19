from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from selenium import webdriver
from selenium.webdriver.common.actions.action_builder import ActionBuilder
from selenium_stealth import stealth

TARGETS = ["_ga", "_fbp", "_clck", "_pcid", "_hj*"]


class CookieLoader(object):
    def __init__(self):
        self._driver = None

    def driver(self):
        if not self._driver:
            opts = webdriver.ChromeOptions()
            opts.add_argument("--headless=new")
            opts.add_argument("--window-size=2560,1440")
            opts.add_experimental_option("excludeSwitches", ["enable-automation"])
            opts.add_experimental_option("useAutomationExtension", False)
            service = webdriver.ChromeService(executable_path="/usr/bin/chromedriver")
            self._driver = webdriver.Chrome(options=opts, service=service)
            stealth(
                self._driver,
                languages=["en-US", "en"],
                vendor="Google Inc.",
                platform="Win32",
                webgl_vendor="Intel Inc.",
                renderer="Intel Iris OpenGL Engine",
                fix_hairline=True,
            )

        return self._driver

    def get_cookies(self, url):
        d = self.driver()
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

        return d.get_cookies()


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
                    result.append((d, domain, added_cookie, True))

            state = new_state

        return result

    def set_cookies(self, domain, cookielist):
        path = self.today_path / domain.replace("/", "-")
        path.open("w").write(json.dumps(cookielist))

    def domains(self):
        s = open("sites.txt", "r").read()
        return s.split("\n")


loader = CookieLoader()
catalog = Catalog()
sites = {}
for domain in catalog.domains():
    cookielist = catalog.get_cookies(domain)
    if cookielist is None:
        print(f"Loading cookies for { domain }")
        cookielist = loader.get_cookies(f"https://{ domain }")
        catalog.set_cookies(domain, cookielist)

    sites[domain] = {}
    cookielist.sort(key=lambda item: item["name"])
    for item in cookielist:
        if "expiry" in item:
            item["expiry_dt"] = datetime.fromtimestamp(item["expiry"])
        sites[domain][item["name"]] = item

events = []
for domain in catalog.domains():
    events.extend(catalog.get_cookie_changes(domain))

events.sort(reverse=True)


# Render result
now = datetime.now(UTC)
ts = now.strftime("%Y%m%d")


def matching(target, cookies):
    if target.endswith("*"):
        target = target[:-1]
        return any(name.startswith(target) for name in cookies)
    return target in cookies


env = Environment(loader=FileSystemLoader("."))
env.tests["matching"] = matching
tmpl = env.get_template("report_template.html")
html = tmpl.render(now=now, targets=TARGETS, sites=sites, events=events)
site = Path("site")
site.mkdir(exist_ok=True)
with open("site/index.html", "w") as f:
    f.write(html)
with open(f"site/{ts}.html", "w") as f:
    f.write(html)
