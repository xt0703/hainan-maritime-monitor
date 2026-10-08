from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from zoneinfo import ZoneInfo

CN = ZoneInfo("Asia/Shanghai")
VN = ZoneInfo("Asia/Ho_Chi_Minh")

KEYWORDS = {
    "LIVE_FIRE": ["实弹射击", "射击训练", "炮击", "枪炮射击"],
    "MILITARY_TRAINING": ["军事训练", "军事演习", "军事活动", "军事任务"],
}

COORD_RE = re.compile(r"(?P<latd>\d{1,2})[-°](?P<latm>\d{1,2}(?:\.\d+)?)['′]?\s*(?P<ns>[NS])\s*[,、，;/ ]*\s*(?P<lond>\d{2,3})[-°](?P<lonm>\d{1,2}(?:\.\d+)?)['′]?\s*(?P<ew>[EW])", re.I)
NOTICE_RE = re.compile(r"琼航警\s*[〖\[]?\s*(\d+)\s*/\s*(\d{2})")
RADIUS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*海里.{0,8}半径|半径.{0,8}(\d+(?:\.\d+)?)\s*海里")


def dm_to_decimal(deg: str, minutes: str, hemi: str) -> float:
    value = float(deg) + float(minutes) / 60.0
    if hemi.upper() in ("S", "W"):
        value = -value
    return round(value, 6)


def extract_coords(text: str):
    pts = []
    for m in COORD_RE.finditer(text):
        lat = dm_to_decimal(m.group("latd"), m.group("latm"), m.group("ns"))
        lon = dm_to_decimal(m.group("lond"), m.group("lonm"), m.group("ew"))
        pts.append([lon, lat])
    # de-duplicate while preserving order
    out = []
    for p in pts:
        if p not in out:
            out.append(p)
    return out


def category_for(text: str):
    for cat, terms in KEYWORDS.items():
        if any(t in text for t in terms):
            return cat
    return None


def notice_number(text: str):
    m = NOTICE_RE.search(text)
    if not m:
        return None, None, None
    num, yy = m.groups()
    year = 2000 + int(yy)
    return f"琼航警{int(num)}/{yy}", f"HN{int(num)}/{yy}", year


def extract_radius_nm(text: str):
    m = RADIUS_RE.search(text)
    if not m:
        return None
    return float(m.group(1) or m.group(2))


def geometry_for(text: str):
    pts = extract_coords(text)
    radius = extract_radius_nm(text)
    if radius and pts:
        return {"type": "Point", "coordinates": pts[0], "radius_nm": radius}
    if len(pts) >= 3:
        ring = pts[:]
        if ring[0] != ring[-1]:
            ring.append(ring[0])
        return {"type": "Polygon", "coordinates": [ring]}
    if pts:
        return {"type": "Point", "coordinates": pts[0]}
    return None


def vietnamese_summary(cat: str, notice_en: str | None, geometry: dict | None, text: str) -> str:
    if cat == "LIVE_FIRE":
        activity = "Huấn luyện/bắn đạn thật"
    else:
        activity = "Huấn luyện hoặc diễn tập quân sự"
    area = "Vịnh Bắc Bộ" if "北部湾" in text else "Biển Đông" if "南海" in text else "vùng biển được thông báo"
    restriction = "; cấm tàu thuyền đi vào" if "禁止驶入" in text or "ENTERING PROHIBITED" in text.upper() else ""
    geo = ""
    if geometry:
        if geometry["type"] == "Polygon":
            geo = f"; khu vực đa giác {len(geometry['coordinates'][0]) - 1} điểm"
        elif geometry.get("radius_nm"):
            geo = f"; vùng tròn bán kính {geometry['radius_nm']:g} hải lý"
    prefix = f"{notice_en}: " if notice_en else ""
    return f"{prefix}{activity} tại {area}{geo}{restriction}."


def checksum_for(*parts) -> str:
    raw = "\n".join(str(p or "") for p in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def normalize_record(title: str, text: str, url: str, issued_at: str | None = None):
    joined = f"{title}\n{text}"
    cat = category_for(joined)
    if not cat:
        return None
    cn_no, en_no, year = notice_number(joined)
    if not cn_no:
        return None
    geom = geometry_for(joined)
    now = datetime.now(VN).isoformat(timespec="seconds")
    return {
        "record_id": en_no.replace("/", "-") if en_no else checksum_for(url),
        "notice_no_cn": cn_no,
        "notice_no_en": en_no,
        "year": year,
        "category": cat,
        "title_cn": title.strip(),
        "title_vi": "Huấn luyện bắn đạn thật" if cat == "LIVE_FIRE" else "Huấn luyện/diễn tập quân sự",
        "issued_at_cn": issued_at,
        "restriction_start_cn": None,
        "restriction_end_cn": None,
        "restriction_start_vn": None,
        "restriction_end_vn": None,
        "status": "UNKNOWN",
        "geometry": geom,
        "area_name_cn": "北部湾" if "北部湾" in joined else "南海" if "南海" in joined else "",
        "area_name_vi": "Vịnh Bắc Bộ" if "北部湾" in joined else "Biển Đông" if "南海" in joined else "",
        "body_cn": text.strip()[:5000],
        "body_vi": vietnamese_summary(cat, en_no, geom, joined),
        "source_url": url,
        "first_seen_at": now,
        "updated_at": now,
        "checksum": checksum_for(cn_no, title, text, geom),
    }
