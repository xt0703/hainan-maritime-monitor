from __future__ import annotations
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from urllib.parse import quote, urljoin
import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
}
TIMEOUT = 25

OFFICIAL_INDEXES = [
    "https://www.hn.msa.gov.cn/hsfw_1_1/index.jhtml",
    "https://www.hn.msa.gov.cn/",
    "https://www.msa.gov.cn/page/outter/weather.jsp",
]

SEED_MIRROR_URLS = [
    "https://www.54seaman.com/news/detail_143464.html",
    "https://www.54seaman.com/news/index/detail/id/143652.html",
    "https://www.54seaman.com/news/index/detail/id/143774.html",
    "https://www.54seaman.com/news/detail_143848.html",
    "https://www.54seaman.com/news/detail_143871.html",
    "https://www.54seaman.com/news/detail_143922.html",
]

ARTICLE_HINT = re.compile(r"article\.do\?articleId=|/news/(?:detail_|index/detail/id/)|航行警告|琼航警", re.I)

class FetchError(RuntimeError):
    pass

def _request(url: str) -> requests.Response:
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
    r.raise_for_status()
    if r.encoding is None or r.encoding.lower() == "iso-8859-1":
        r.encoding = r.apparent_encoding or "utf-8"
    return r

def get_text(url: str) -> tuple[str, str, str]:
    try:
        r = _request(url)
        return r.text, r.url, "direct"
    except Exception as direct_exc:
        proxy_url = "https://r.jina.ai/" + url
        try:
            r = _request(proxy_url)
            return r.text, url, "jina"
        except Exception as proxy_exc:
            raise FetchError(
                f"direct={type(direct_exc).__name__}: {direct_exc}; "
                f"jina={type(proxy_exc).__name__}: {proxy_exc}"
            ) from proxy_exc

def _extract_links_from_html(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"])
        label = a.get_text(" ", strip=True)
        if ARTICLE_HINT.search(href) or "琼航警" in label or "航行警告" in label:
            if href.startswith("http") and href not in out:
                out.append(href)
    return out

def _bing_rss(query: str) -> list[str]:
    url = "https://www.bing.com/search?format=rss&q=" + quote(query)
    try:
        r = _request(url)
        root = ET.fromstring(r.text)
    except Exception:
        return []
    out = []
    for item in root.findall(".//item"):
        link = item.findtext("link") or ""
        if link.startswith("http") and link not in out:
            out.append(link)
    return out

def discover_document_links(max_links: int = 120) -> tuple[list[str], list[str]]:
    links = []
    errors = []

    for index in OFFICIAL_INDEXES:
        try:
            html, final_url, _ = get_text(index)
            for href in _extract_links_from_html(html, final_url):
                if href not in links:
                    links.append(href)
        except Exception as exc:
            errors.append(f"{index}: {type(exc).__name__}: {exc}")

    year = datetime.now().year
    queries = []
    for y in (year, year - 1):
        queries.extend([
            f'site:msa.gov.cn "琼航警" {y} "军事训练"',
            f'site:msa.gov.cn "琼航警" {y} "实弹射击"',
            f'site:msa.gov.cn "琼航警" {y} "军事演习"',
            f'site:54seaman.com/news "琼航警" {y} "军事训练"',
            f'site:54seaman.com/news "琼航警" {y} "实弹射击"',
        ])

    for q in queries:
        for href in _bing_rss(q):
            if ("msa.gov.cn" in href or "54seaman.com/news/" in href) and href not in links:
                links.append(href)
            if len(links) >= max_links:
                break
        if len(links) >= max_links:
            break

    for href in SEED_MIRROR_URLS:
        if href not in links:
            links.append(href)

    return links[:max_links], errors

def _html_to_text(html: str) -> tuple[str, str]:
    if "<html" not in html.lower() and "<body" not in html.lower():
        lines = [ln.strip() for ln in html.splitlines() if ln.strip()]
        title = ""
        for ln in lines[:20]:
            if ln.lower().startswith("title:"):
                title = ln.split(":", 1)[1].strip()
                break
            if ln.startswith("# "):
                title = ln[2:].strip()
                break
        return title, "\n".join(lines)

    soup = BeautifulSoup(html, "html.parser")
    title = ""
    for selector in ["h1", ".article-title", ".title", "title"]:
        el = soup.select_one(selector)
        if el and el.get_text(strip=True):
            title = el.get_text(" ", strip=True)
            break

    candidates = []
    for selector in [".TRS_Editor", ".article-content", ".content", "article", "main", "body"]:
        el = soup.select_one(selector)
        if el:
            txt = el.get_text("\n", strip=True)
            if txt:
                candidates.append(txt)
    body = max(candidates, key=len) if candidates else soup.get_text("\n", strip=True)
    return title, body

def fetch_document(url: str) -> dict:
    html, final_url, method = get_text(url)
    title, text = _html_to_text(html)
    if "54seaman.com" in url:
        source_kind = "mirror"
    elif method == "jina":
        source_kind = "official-via-reader"
    else:
        source_kind = "official"
    return {
        "title": title,
        "text": text,
        "url": url,
        "final_url": final_url,
        "fetch_method": method,
        "source_kind": source_kind,
    }
