from __future__ import annotations

import json
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from babel.dates import format_date
from jinja2 import Environment, FileSystemLoader
from pydantic import BaseModel, TypeAdapter

# The cookies we show in the report table
TARGETS = [
    "__eoi",
    "__gfp_64b",
    "__kla_id",
    "__utm*",
    "_clck",
    "_fbp",
    "_ga",
    "_gcl_au",
    "_hj*",
    "_pcid",
    "bxID",
    "cX_G",
    "Gdynp",
    "OAID",
]
# The cookies we track in the changes section. Excludes Gdynp as
# on several sites it seems to flip on and off frequently.
CHANGES_TARGETS = [
    "__eoi",
    "__gfp_64b",
    "__kla_id",
    "__utm*",
    "_clck",
    "_fbp",
    "_ga",
    "_gcl_au",
    "_hj*",
    "_pcid",
    "bxID",
    "cX_G",
    "OAID",
]


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

    def other_matches(self):
        skip = ["_ga", "_fbp", "_clck"]
        return [t for t in TARGETS if self.matches(t) and t not in skip]


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
            assert domain != prev_domain, f"Duplicate: {domain}"
            prev_domain = domain
            cookielist = self.get_cookies(domain)
            if cookielist is None:
                # No cookies: load them with chromium.
                # Do this in a subprocess so we can kill hung processes.
                try:
                    subprocess.call(["python", "scan_single.py", domain], timeout=300)
                except subprocess.TimeoutExpired:
                    pass
                # Now read them from filesystem again
                cookielist = self.get_cookies(domain)

            self.sites.append(Site(domain, category, cookielist))

    def get_cookies(self, domain: str) -> list[Cookie] | None:
        path = self.today_path / domain.replace("/", "-")
        if path.exists():
            json_bytes = path.read_bytes()
            return CookieList.validate_json(json_bytes)

        return None

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
    env.filters["format_date_lv"] = lambda d: format_date(
        d, "EEEE, Y. 'gada' d. MMMM", "lv_LV"
    )

    num_visible = len([True for site in catalog.sites if site.any_red()])

    ctx = {
        "catalog": catalog,
        "now": datetime.now(UTC),
        "targets": TARGETS,
        "num_visible": num_visible,
    }

    site = Path("site")
    site.mkdir(exist_ok=True)

    tmpl = env.get_template("report_template.jinja2")
    with open("site/index.html", "w") as f:
        f.write(tmpl.render(**ctx))

    history_tmpl = env.get_template("history_template.jinja2")
    with open("site/history.html", "w") as f:
        f.write(history_tmpl.render(**ctx))


if __name__ == "__main__":
    # Load cookies for all sites and generate report.
    generate_report(Catalog())
