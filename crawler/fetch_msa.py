from __future__ import annotations

import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
}
TIMEOUT = 25

# Crawler cố gắng nguồn Hải Nam trước. Nếu WAF chặn, dùng trang trung ương China MSA.
INDEX_CANDIDATES = [
    "https://www.hn.msa.gov.cn/hsfw_1_1/index.jhtml",
    "https://www.hn.msa.gov.cn/",
    "https://www.msa.gov.cn/page/outter/weather.jsp",
]

ARTICLE_RE = re.compile(r"article\.do\?articleId=|/hxjg/|航警|航行警告")


def get(url: str):
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
    r.raise_for_status()
    r.encoding = r.apparent_encoding or r.encoding
    return r


def discover_article_links(max_links=80):
    links = []
    errors = []
    for index in INDEX_CANDIDATES:
        try:
            r = get(index)
        except Exception as exc:
            errors.append(f"{index}: {type(exc).__name__}: {exc}")
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.find_all("a", href=True):
            href = urljoin(r.url, a["href"])
            label = a.get_text(" ", strip=True)
            if ARTICLE_RE.search(href) or "航警" in label or "航行警告" in label:
                if href not in links:
                    links.append(href)
                    if len(links) >= max_links:
                        return links, errors
    return links, errors


def fetch_article(url: str):
    r = get(url)
    soup = BeautifulSoup(r.text, "html.parser")
    title = ""
    for selector in ["h1", ".article-title", ".title", "title"]:
        el = soup.select_one(selector)
        if el and el.get_text(strip=True):
            title = el.get_text(" ", strip=True)
            break
    body = ""
    candidates = []
    for selector in [".TRS_Editor", ".article-content", ".content", "article", "body"]:
        el = soup.select_one(selector)
        if el:
            txt = el.get_text("\n", strip=True)
            candidates.append(txt)
    if candidates:
        body = max(candidates, key=len)
    return title, body, r.url
