from __future__ import annotations
import hashlib
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

CN = ZoneInfo("Asia/Shanghai")
VN = ZoneInfo("Asia/Ho_Chi_Minh")

CATEGORY_TERMS = {
    "LIVE_FIRE": ["实弹射击", "射击训练", "炮击", "枪炮射击"],
    "MILITARY_TRAINING": ["军事训练", "军事演习", "军事行动", "军事活动", "军事任务"],
}

NOTICE_RE = re.compile(r"琼航警\s*[〖\[\(（]?\s*(\d{1,4})\s*/\s*(\d{2})")
GENERIC_NOTICE_RE = re.compile(r"[\u4e00-\u9fff]{1,4}航警\s*\d{1,4}\s*/\s*\d{2}")

COORD_RE = re.compile(
    r"(?P<latd>\d{1,2})\s*[-°]\s*(?P<latm>\d{1,2}(?:\.\d+)?)\s*['′]?\s*(?P<ns>[NS])"
    r"\s*[,、，;/\s]*"
    r"(?P<lond>\d{2,3})\s*[-°]\s*(?P<lonm>\d{1,2}(?:\.\d+)?)\s*['′]?\s*(?P<ew>[EW])",
    re.I,
)

RADIUS_RE = re.compile(
    r"(?:(\d+(?:\.\d+)?)\s*海里.{0,10}(?:半径|为半径)|"
    r"(?:半径|为半径).{0,10}(\d+(?:\.\d+)?)\s*海里)"
)

PUBLISHED_RE = re.compile(
    r"(?:发布时间[:：]?\s*|发表于\s*)"
    r"(\d{4})[-年/](\d{1,2})[-月/](\d{1,2})"
    r"(?:日)?\s*(\d{1,2})?[:时](\d{2})?"
)

def _norm_text(s: str) -> str:
    return s.replace("\xa0", " ").replace("／", "/").replace("－", "-").replace("—", "-").replace("：", ":")

def split_hainan_notice_blocks(title: str, text: str) -> list[tuple[str, str]]:
    blob = _norm_text(f"{title}\n{text}")
    matches = list(NOTICE_RE.finditer(blob))
    if not matches:
        return []
    blocks = []
    for i, m in enumerate(matches):
        start = m.start()
        next_any = GENERIC_NOTICE_RE.search(blob, m.end())
        end = next_any.start() if next_any else len(blob)
        if i + 1 < len(matches):
            end = min(end, matches[i + 1].start())
        blocks.append((m.group(0), blob[start:end].strip()[:7000]))
    return blocks

def category_for(text: str):
    for cat, terms in CATEGORY_TERMS.items():
        if any(term in text for term in terms):
            return cat
    return None

def notice_number(text: str):
    m = NOTICE_RE.search(text)
    if not m:
        return None, None, None
    num, yy = m.groups()
    year = 2000 + int(yy)
    return f"琼航警{int(num)}/{yy}", f"HN{int(num)}/{yy}", year

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
        p = [lon, lat]
        if p not in pts:
            pts.append(p)
    return pts

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

def _parse_hhmm(raw: str) -> tuple[int, int, bool]:
    raw = re.sub(r"\D", "", raw or "").zfill(4)
    hh, mm = int(raw[:2]), int(raw[2:4])
    if hh == 24:
        return 0, mm, True
    return min(hh, 23), min(mm, 59), False

def _make_dt(year: int, month: int, day: int, hhmm: str) -> datetime:
    hh, mm, add_day = _parse_hhmm(hhmm)
    dt = datetime(year, month, day, hh, mm, tzinfo=CN)
    return dt + timedelta(days=1) if add_day else dt

def extract_time_range(text: str, year: int):
    t = _norm_text(text)

    patterns = [
        re.compile(
            r"(?:自)?(?:(\d{4})年)?(\d{1,2})月(\d{1,2})日\s*(\d{3,4})时?"
            r"\s*至\s*(?:(\d{4})年)?(?:(\d{1,2})月)?(\d{1,2})日\s*(\d{3,4})时?"
        ),
    ]
    m = patterns[0].search(t)
    if m:
        y1 = int(m.group(1) or year); mo1 = int(m.group(2)); d1 = int(m.group(3)); hm1 = m.group(4)
        y2 = int(m.group(5) or y1); mo2 = int(m.group(6) or mo1); d2 = int(m.group(7)); hm2 = m.group(8)
        return _make_dt(y1, mo1, d1, hm1), _make_dt(y2, mo2, d2, hm2)

    m = re.search(
        r"(?:自)?(\d{1,2})月(\d{1,2})日\s*(\d{3,4})时?"
        r"\s*至\s*(\d{1,2})日\s*(\d{3,4})时?", t
    )
    if m:
        mo, d1, hm1, d2, hm2 = int(m.group(1)), int(m.group(2)), m.group(3), int(m.group(4)), m.group(5)
        return _make_dt(year, mo, d1, hm1), _make_dt(year, mo, d2, hm2)

    m = re.search(
        r"(?:自)?(\d{1,2})月(\d{1,2})日\s*(\d{3,4})时?"
        r"\s*至\s*(\d{1,2})月(\d{1,2})日\s*(\d{3,4})时?", t
    )
    if m:
        return (
            _make_dt(year, int(m.group(1)), int(m.group(2)), m.group(3)),
            _make_dt(year, int(m.group(4)), int(m.group(5)), m.group(6)),
        )

    m = re.search(
        r"(?:自)?(?:(\d{4})年)?(\d{1,2})月(\d{1,2})日\s*(\d{3,4})时?"
        r"\s*至\s*(\d{3,4})时", t
    )
    if m:
        y = int(m.group(1) or year); mo = int(m.group(2)); d = int(m.group(3))
        return _make_dt(y, mo, d, m.group(4)), _make_dt(y, mo, d, m.group(5))

    m = re.search(
        r"(?:自)?(?:(\d{4})年)?(\d{1,2})月(\d{1,2})日"
        r"\s*至\s*(?:(\d{1,2})月)?(\d{1,2})日"
        r".{0,30}?(?:每日|每天)\s*(\d{3,4})时?\s*至\s*(\d{3,4})时?", t
    )
    if m:
        y = int(m.group(1) or year); mo1 = int(m.group(2)); d1 = int(m.group(3))
        mo2 = int(m.group(4) or mo1); d2 = int(m.group(5))
        return _make_dt(y, mo1, d1, m.group(6)), _make_dt(y, mo2, d2, m.group(7))

    return None, None

def parse_published_at(text: str):
    m = PUBLISHED_RE.search(text)
    if not m:
        return None
    y, mo, d = map(int, m.group(1, 2, 3))
    hh = int(m.group(4) or 0)
    mm = int(m.group(5) or 0)
    return datetime(y, mo, d, hh, mm, tzinfo=CN)

def vietnamese_summary(cat: str, notice_en: str, geometry: dict | None, text: str) -> str:
    activity = "Huấn luyện/bắn đạn thật" if cat == "LIVE_FIRE" else "Huấn luyện/diễn tập hoặc hoạt động quân sự"
    area = "Vịnh Bắc Bộ" if "北部湾" in text else "Biển Đông" if "南海" in text else "vùng biển được thông báo"
    restriction = "; cấm tàu thuyền đi vào" if "禁止驶入" in text or "ENTERING PROHIBITED" in text.upper() else ""
    shape = ""
    if geometry:
        if geometry["type"] == "Polygon":
            shape = f"; khu vực đa giác {len(geometry['coordinates'][0]) - 1} điểm"
        elif geometry.get("radius_nm"):
            shape = f"; vùng tròn bán kính {geometry['radius_nm']:g} hải lý"
    return f"{notice_en}: {activity} tại {area}{shape}{restriction}."

def checksum_for(*parts) -> str:
    raw = "\n".join(str(p or "") for p in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]

def status_for(start, end) -> str:
    n = datetime.now(CN)
    if start and end and start <= n <= end:
        return "ACTIVE"
    if start and n < start:
        return "UPCOMING"
    if end and n > end:
        return "EXPIRED"
    return "UNKNOWN"

def normalize_notice_block(block: str, source_url: str, source_kind: str = "official", page_title: str = ""):
    block = _norm_text(block)
    cat = category_for(block)
    if not cat:
        return None
    cn_no, en_no, year = notice_number(block)
    if not en_no:
        return None
    geom = geometry_for(block)
    start_cn, end_cn = extract_time_range(block, year)
    published = parse_published_at(block)
    now_vn = datetime.now(VN).isoformat(timespec="seconds")
    area_cn = "北部湾" if "北部湾" in block else "南海" if "南海" in block else ""
    area_vi = "Vịnh Bắc Bộ" if area_cn == "北部湾" else "Biển Đông" if area_cn == "南海" else ""
    return {
        "record_id": en_no.replace("/", "-"),
        "notice_no_cn": cn_no,
        "notice_no_en": en_no,
        "year": year,
        "category": cat,
        "title_cn": "实弹射击训练" if cat == "LIVE_FIRE" else "军事训练/演习",
        "title_vi": "Huấn luyện/bắn đạn thật" if cat == "LIVE_FIRE" else "Huấn luyện/diễn tập quân sự",
        "issued_at_cn": published.isoformat(timespec="seconds") if published else None,
        "restriction_start_cn": start_cn.isoformat(timespec="seconds") if start_cn else None,
        "restriction_end_cn": end_cn.isoformat(timespec="seconds") if end_cn else None,
        "restriction_start_vn": start_cn.astimezone(VN).isoformat(timespec="seconds") if start_cn else None,
        "restriction_end_vn": end_cn.astimezone(VN).isoformat(timespec="seconds") if end_cn else None,
        "status": status_for(start_cn, end_cn),
        "geometry": geom,
        "area_name_cn": area_cn,
        "area_name_vi": area_vi,
        "body_cn": block[:6000],
        "body_vi": vietnamese_summary(cat, en_no, geom, block),
        "source_url": source_url,
        "source_kind": source_kind,
        "first_seen_at": now_vn,
        "updated_at": now_vn,
        "checksum": checksum_for(cn_no, block, geom, start_cn, end_cn),
    }
