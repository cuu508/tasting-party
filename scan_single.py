from __future__ import annotations

import sqlite3
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from random import randint, random

from pydantic import BaseModel, TypeAdapter
from selenium import webdriver
from selenium.common.exceptions import (
    JavascriptException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.common.keys import Keys
from selenium_stealth import stealth
from urllib3.exceptions import ReadTimeoutError

# If the website title contains any of these, we will skip loading cookies for it
TITLE_ERRORS = ["Web server is down", "SSL handshake failed"]


class Cookie(BaseModel):
    name: str
    domain: str
    httpOnly: int
    expiry: int


CookieList = TypeAdapter(list[Cookie])


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


def get_driver(user_dir: str):
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


def load_cookies(url: str, skip_on_timeout: bool) -> list[Cookie] | None:
    print(f"[{url}] Loading cookies")
    with tempfile.TemporaryDirectory() as user_dir:
        d = get_driver(user_dir)
        d.set_page_load_timeout(90)
        try:
            d.get(url)
        except TimeoutException:
            if skip_on_timeout:
                print(f"[{url}] Page load timed out, skipping.")
                d.quit()
                return None
            else:
                print(f"[{url}] Page load timed out, cookies may still be loading.")
        except ReadTimeoutError:
            print(f"[{url}] urllib3 timeout, skipping.")
            d.quit()
            return None
        except WebDriverException as e:
            print(f"[{url}] {e.msg}, skipping.")
            d.quit()
            return None

        try:
            title = d.title
        except TimeoutException:
            print(f"[{url}] Page load timed out while retrieving title, skipping.")
            d.quit()
            return None

        for s in TITLE_ERRORS:
            if s in title:
                print(f"[{url}] Title contains '{s}', skipping.")
                d.quit()
                return None

        time.sleep(3)

        # Now prod the page to cause more cookies to load:
        try:
            width = d.execute_script("return window.innerWidth")
            height = d.execute_script("return window.innerHeight")
            scrollh = d.execute_script("return document.body.scrollHeight")
        except JavascriptException as e:
            print(f"[{url}] {e}, skipping.")
            d.quit()
            return None

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
        d.quit()

        # d.get_cookies() does not return httpOnly cookies, so read them from
        # chromium's sqlite database:
        return read_chrome_cookiedb(user_dir + "/Default/Cookies")


if __name__ == "__main__":
    domain = sys.argv[1]

    now = datetime.now(UTC)
    ts = now.strftime("%Y%m%d")
    today_path = Path("scans") / ts
    today_path.mkdir(parents=True, exist_ok=True)

    cookielist = load_cookies(f"https://{domain}", skip_on_timeout=True)
    if cookielist is None:
        cookielist = load_cookies(f"https://{domain}", skip_on_timeout=False)

    if cookielist is not None:
        path = today_path / domain.replace("/", "-")
        path.write_bytes(CookieList.dump_json(cookielist))
