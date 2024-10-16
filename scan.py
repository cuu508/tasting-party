from __future__ import annotations

import datetime
import json
import time
from pathlib import Path

from jinja2 import Template
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys


class CookieLoader(object):
    def __init__(self):
        self._driver = None

    def driver(self):
        if not self._driver:
            chrome_options = webdriver.ChromeOptions()
            chrome_options.add_argument("--headless=new")
            service = webdriver.ChromeService(executable_path="/usr/bin/chromedriver")
            self._driver = webdriver.Chrome(options=chrome_options, service=service)
            self._driver.execute_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )

        return self._driver

    def get_cookies(self, url):
        d = self.driver()
        d.get(url)
        time.sleep(3)
        html = d.find_element(By.TAG_NAME, "html")
        html.send_keys(Keys.END)
        time.sleep(3)
        return d.get_cookies()


class Catalog(object):
    def __init__(self):
        now = datetime.datetime.now(datetime.UTC)
        ts = now.strftime("%Y%m%d")
        self.today_path = Path("scans") / ts
        self.today_path.mkdir(parents=True, exist_ok=True)

    def get_cookies(self, domain):
        path = self.today_path / domain
        if path.exists():
            return json.loads(path.open().read())

    def set_cookies(self, domain, cookielist):
        path = self.today_path / domain
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
            item["expiry_dt"] = datetime.datetime.fromtimestamp(item["expiry"])
        sites[domain][item["name"]] = item

# Render result
now = datetime.datetime.now(datetime.UTC)
ts = now.strftime("%Y%m%d")
tmpl = Template(open("report_template.html").read())
html = tmpl.render(now=now, sites=sites)
site = Path("site")
site.mkdir(exist_ok=True)
with open("site/index.html", "w") as f:
    f.write(html)
with open(f"site/{ts}.html", "w") as f:
    f.write(html)
