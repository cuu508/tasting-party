from __future__ import annotations

import datetime
import json
import time
from pathlib import Path

from jinja2 import Template
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

now = datetime.datetime.now(datetime.UTC)
ts = now.strftime("%Y%m%d")
data = Path("scans") / ts
data.mkdir(parents=True, exist_ok=True)

driver = None
cookies = {}
sites = sorted(open("sites.txt", "r").readlines())
for site in sites:
    site = site.strip()
    if not site:
        continue

    spath = data / site
    if not spath.exists():
        if driver is None:
            chrome_options = webdriver.ChromeOptions()
            chrome_options.add_argument("--incognito")
            driver = webdriver.Chrome(options=chrome_options)
            driver.execute_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )
        print(f"Loading { site }")
        driver.get(f"https://{ site }")
        time.sleep(3)
        html = driver.find_element(By.TAG_NAME, "html")
        html.send_keys(Keys.END)
        time.sleep(3)
        spath.open("w").write(json.dumps(driver.get_cookies()))

    cookie_doc = json.loads(spath.open().read())
    cookies[site] = [c["name"] for c in cookie_doc]
    cookies[site].sort()

# Render result
tmpl = Template(open("report_template.html").read())
html = tmpl.render(now=now, cookies=cookies)
site = data = Path("site")
site.mkdir(exist_ok=True)
with open("site/index.html", "w") as f:
    f.write(html)
with open(f"site/{ts}.html", "w") as f:
    f.write(html)
