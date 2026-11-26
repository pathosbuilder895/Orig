#!/usr/bin/env python3
"""Read-only public smoke checks for the deployed alpha pilot."""
from __future__ import annotations

import argparse
import re
import sys
import time
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import requests

PAGES = ("/landing.html", "/bluebook/", "/original/baseline.html")
BANNED = re.compile(
    r"\b(?:detects? cheating|AI[- ]written|guaranteed accuracy|100% accurate|proves authorship|proves misconduct)\b",
    re.IGNORECASE,
)


class Assets(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls: list[str] = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag in {"script", "img", "source", "iframe", "link"}:
            key = "href" if tag == "link" else "src"
            value = values.get(key)
            if value:
                self.urls.append(value.strip())


def run(base_url: str, timeout: float = 15, max_seconds: float = 10) -> tuple[int, list[str]]:
    base = base_url.rstrip("/")
    origin = urlparse(base)
    failures: list[str] = []
    lines: list[str] = []
    session = requests.Session()
    checked_assets: set[str] = set()

    def check_asset(asset_url: str, depth: int = 0):
        parsed_asset = urlparse(asset_url)
        if parsed_asset.scheme not in {"http", "https"} or parsed_asset.netloc != origin.netloc:
            return  # Don't contact third-party hosts during this pilot check.
        if asset_url in checked_assets or depth > 3:
            return
        checked_assets.add(asset_url)
        started = time.monotonic()
        # Do not follow redirects off the pilot host: this check is intentionally
        # limited to unauthenticated requests against the pilot's own assets.
        response = session.get(asset_url, timeout=timeout, allow_redirects=False)
        elapsed = time.monotonic() - started
        asset_path = parsed_asset.path
        lines.append(f"  asset {asset_path}: HTTP {response.status_code}, {elapsed:.2f}s")
        if response.status_code != 200:
            failures.append(f"missing asset {asset_path}: HTTP {response.status_code}")
        if elapsed > max_seconds:
            failures.append(f"asset {asset_path} exceeded {max_seconds:.1f}s ({elapsed:.2f}s)")
        if "text/css" in response.headers.get("content-type", ""):
            refs = re.findall(r"url\(\s*['\"]?([^'\")]+)", response.text, re.IGNORECASE)
            refs += re.findall(r"@import\s+(?:url\()?['\"]([^'\"]+)", response.text, re.IGNORECASE)
            for ref in refs:
                value = ref.strip()
                if not value or value.startswith(("data:", "#")):
                    continue
                check_asset(urljoin(response.url, value), depth + 1)

    def get(path: str, *, page: bool = False):
        url = urljoin(base + "/", path.lstrip("/"))
        started = time.monotonic()
        response = session.get(url, timeout=timeout, allow_redirects=False)
        elapsed = time.monotonic() - started
        line = f"GET {urlparse(url).path}: HTTP {response.status_code}, {elapsed:.2f}s"
        lines.append(line)
        if response.status_code != 200:
            failures.append(f"expected 200 for {urlparse(url).path}, got {response.status_code}")
        if elapsed > max_seconds:
            failures.append(f"{urlparse(url).path} exceeded {max_seconds:.1f}s ({elapsed:.2f}s)")
        if page and BANNED.search(response.text):
            failures.append(f"banned wording found on public page {urlparse(url).path}")
        if page:
            parser = Assets()
            parser.feed(response.text)
            for ref in parser.urls:
                asset_url = urljoin(response.url, ref)
                check_asset(asset_url)
        return response

    try:
        health = get("/health")
        try:
            payload = health.json()
        except ValueError:
            payload = {}
        expected = {"backend": "postgres", "signup_open": False}
        for key, value in expected.items():
            if payload.get(key) != value:
                failures.append(f"/health {key} expected {value!r}, got {payload.get(key)!r}")
        if not payload.get("commit"):
            failures.append("/health is missing commit")
        lines.append(f"  health: commit={payload.get('commit')!r}, backend={payload.get('backend')!r}, signup_open={payload.get('signup_open')!r}")
        for page in PAGES:
            get(page, page=True)
    except requests.RequestException as exc:
        failures.append(f"request failed: {exc}")
    lines.extend(f"FAIL: {failure}" for failure in failures)
    if not failures:
        lines.append("RESULT: PASS")
    return (1 if failures else 0), lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", default="https://original-pilot.onrender.com")
    parser.add_argument("--timeout", type=float, default=15, help="per-request timeout in seconds")
    parser.add_argument("--max-seconds", type=float, default=10, help="acceptable page and asset response time")
    args = parser.parse_args(argv)
    code, output = run(args.base_url, timeout=args.timeout, max_seconds=args.max_seconds)
    print("\n".join(output))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
