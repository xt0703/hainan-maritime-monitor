"""Read public SeaLagom regional warning summaries as a *secondary* source.

No authentication bypass, paid archive access, or bulk API is attempted.
The official announcement remains the preferred primary reference. This
adapter uses only the public regional warning text with a conservative rate.
"""
from __future__ import annotations

import re
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from .core import CATEGORIES, classify, is_in_scs_geometry

CN = ZoneInfo('Asia/Shanghai')
VN = ZoneInfo('Asia/Ho_Chi_Minh')

REGIONS = [
    'https://www.sealagom.com/coastal/China%20Coastal/Hainan/',
    'https://www.sealagom.com/coastal/China%20Coastal/Guangdong/',
]

NOTICE_RE = re.compile(r'(?P<prefix>[琼粤桂])航警\s*(?P<number>\d{1,4})\s*/\s*(?P<yy>\d{2})(?!\d)')
# Support DMS 18-07-20N 109-37-50E and decimal minutes 18-51.50N 110-36.00E.
COORD_RE = re.compile(
    r'(?<![\d-])(?P<latdeg>\d{1,2})\s*[-°]\s*'
    r'(?P<latmin>\d{1,2}(?:\.\d+)?)(?:\s*[-′]\s*(?P<latsec>\d{1,2}(?:\.\d+)?))?'
    r'\s*[\'′″]?\s*(?P<latdir>[NS])\s*[,，、；;\s/]*'
    r'(?P<londeg>\d{2,3})\s*[-°]\s*'
    r'(?P<lonmin>\d{1,2}(?:\.\d+)?)(?:\s*[-′]\s*(?P<lonsec>\d{1,2}(?:\.\d+)?))?'
    r'\s*[\'′″]?\s*(?P<londir>[EW])', re.I
)
DATE_RANGE_RE = re.compile(
    r'(?:(?P<year>20\d{2})年)?(?P<mo1>\d{1,2})月(?P<day1>\d{1,2})日?'
    r'\s*(?:至|到|－|—|-)\s*'
    r'(?:(?P<mo2>\d{1,2})月)?(?P<day2>\d{1,2})日?'
)
SINGLE_DAY_RE = re.compile(r'(?:(?P<year>20\d{2})年)?(?P<mo>\d{1,2})月(?P<day>\d{1,2})日')
DAILY_RE = re.compile(r'(?:每日|每天)\s*(?P<start>\d{3,4})时?\s*至\s*(?P<end>\d{3,4})时?')
CROSS_DAY_CLOCK_RE = re.compile(r'(?P<mo>\d{1,2})月(?P<day>\d{1,2})日(?P<start>\d{3,4})时?\s*至\s*(?P<mo2>\d{1,2})月?(?P<day2>\d{1,2})日(?P<end>\d{3,4})时?')
# Time ranges where second month is omitted, e.g. 10月14日1200时至16日1400时
CROSS_DAY_SAME_MONTH_RE = re.compile(r'(?P<mo>\d{1,2})月(?P<day>\d{1,2})日(?P<start>\d{3,4})时?\s*至\s*(?P<day2>\d{1,2})日(?P<end>\d{3,4})时?')
EXACT_DAY_RE = re.compile(r'(?P<mo>\d{1,2})月(?P<day>\d{1,2})日(?P<start>\d{3,4})时?\s*至\s*(?P<end>\d{3,4})时?')
RADIUS_RE = re.compile(r'半径\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>海里|公里)')


def _point(m):
    def part(prefix):
        deg=float(m[f'{prefix}deg']); minutes=float(m[f'{prefix}min'])
        seconds=float(m[f'{prefix}sec'] or 0)
        if minutes >= 60 or seconds >= 60: raise ValueError('Invalid DMS components')
        value=deg+minutes/60+seconds/3600
        if m[f'{prefix}dir'].upper() in ('S','W'):value=-value
        return round(value,6)
    return [part('lon'),part('lat')]


def geometry_for(text):
    points=[]
    for m in COORD_RE.finditer(text):
        try: point=_point(m)
        except ValueError: continue
        if point not in points:points.append(point)
    if not points:return None
    match=RADIUS_RE.search(text)
    if match:
        radius=float(match['value'])
        if match['unit']=='公里':radius/=1.852
        geom={'type':'Point','coordinates':points[0],'radius_nm':round(radius,5)}
    elif len(points)>=3:
        ring=list(points)
        if ring[0]!=ring[-1]:ring.append(ring[0])
        geom={'type':'Polygon','coordinates':[ring]}
    else:
        geom={'type':'Point','coordinates':points[0]}
    return geom if is_in_scs_geometry(geom) else None


def _clock(hhmm):
    t=str(hhmm).zfill(4)
    hh,mm=int(t[:-2]),int(t[-2:])
    return time(hh,mm) if hh<24 and mm<60 else None


def dates_for(text,notice_year):
    """Return day-span / exact-single-day windows + precision and daily slot.

    Caution: multi-day daily windows are not a continuous exclusion interval.
    The exported day-span is annotated as DAILY_WINDOWS and should not be
    treated as proof of an active exclusion at all hours in that span.
    """
    daily=DAILY_RE.search(text)
    m=DATE_RANGE_RE.search(text)
    if m:
        try:
            year=int(m['year'] or notice_year)
            start=datetime(year,int(m['mo1']),int(m['day1']),tzinfo=CN)
            end=datetime(year,int(m['mo2'] or m['mo1']),int(m['day2']),23,59,59,tzinfo=CN)
            if end<start or (end-start).days>366: return None,None,'UNKNOWN',None
            window=None
            if daily:
                c1,c2=_clock(daily['start']),_clock(daily['end'])
                if c1 and c2:
                    window={'start_cn':c1.strftime('%H:%M'), 'end_cn':c2.strftime('%H:%M')}
            precision='DAILY_WINDOWS' if window else 'DATE_RANGE_DAY_LEVEL'
            return start.astimezone(VN).isoformat(),end.astimezone(VN).isoformat(),precision,window
        except ValueError:pass
    for regex in (CROSS_DAY_CLOCK_RE,CROSS_DAY_SAME_MONTH_RE):
        m=regex.search(text)
        if m:
            try:
                c1,c2=_clock(m['start']),_clock(m['end'])
                if c1 and c2:
                    mo1=int(m['mo']); mo2=int(m['mo2'] or mo1) if 'mo2' in m.groupdict() else mo1
                    a=datetime.combine(datetime(notice_year,mo1,int(m['day'])),c1,tzinfo=CN)
                    b=datetime.combine(datetime(notice_year,mo2,int(m['day2'])),c2,tzinfo=CN)
                    if b>=a and (b-a).days<=31:
                        return a.astimezone(VN).isoformat(),b.astimezone(VN).isoformat(),'EXACT_RESTRICTION',None
            except ValueError: pass
    m=EXACT_DAY_RE.search(text)
    if m:
        try:
            c1,c2=_clock(m['start']),_clock(m['end'])
            if c1 and c2:
                s=datetime.combine(datetime(notice_year,int(m['mo']),int(m['day'])),c1,tzinfo=CN)
                e=datetime.combine(datetime(notice_year,int(m['mo']),int(m['day'])),c2,tzinfo=CN)
                if e<s:e+=timedelta(days=1)
                return s.astimezone(VN).isoformat(),e.astimezone(VN).isoformat(),'EXACT_RESTRICTION',None
        except ValueError:pass
    m=SINGLE_DAY_RE.search(text)
    if m:
        try:
            y=int(m['year'] or notice_year)
            s=datetime(y,int(m['mo']),int(m['day']),tzinfo=CN)
            e=s+timedelta(days=1)-timedelta(seconds=1)
            return s.astimezone(VN).isoformat(),e.astimezone(VN).isoformat(),'DATE_DAY_LEVEL',None
        except ValueError:pass
    return None,None,'UNKNOWN',None


def extract_blocks(raw,region_prefix=None):
    """Prefer the public 'Full content' section; do not mix English copies.

    The live region page sometimes lists the same notices again below the
    main content. Only the first occurrence of each notice ID is kept.
    """
    text=raw.replace('\xa0',' ')
    if 'Full content' in text:
        text=text.split('Full content',1)[1]
        for stop in ('Recent active messages','## Recent active messages','Archived / Canceled'):
            if stop in text:text=text.split(stop,1)[0]
    hits=list(NOTICE_RE.finditer(text))
    blocks=[];seen=set()
    for i,m in enumerate(hits):
        if region_prefix and m['prefix'] != region_prefix:continue
        key=(m['prefix'],m['number'],m['yy'])
        if key in seen: continue
        seen.add(key)
        end=hits[i+1].start() if i+1<len(hits) else len(text)
        block=text[m.start():end].strip()[:7500]
        if len(block)>20:blocks.append((m,block))
    return blocks


def parse_sealagom(doc):
    from .core import MILITARY_WORDS
    body=doc['body']
    region=doc['url'].rstrip('/').rsplit('/',1)[-1].lower()
    prefix='琼' if region=='hainan' else '粤' if region=='guangdong' else None
    results=[]
    for m,block in extract_blocks(body,prefix):
        if not any(term in block for term in MILITARY_WORDS):continue
        year=2000+int(m['yy'])
        if year<2020 or year>datetime.now(CN).year:continue
        geom=geometry_for(block)
        if not geom:continue  # Do not invent an exclusion polygon.
        tr={'琼':'HN','粤':'GD','桂':'GX'}
        no=f"{tr[m['prefix']]}{int(m['number'])}/{m['yy']}"
        start,end,precision,window=dates_for(block,year)
        cat=classify(block)
        place='Vịnh Bắc Bộ' if '北部湾' in block else 'Biển Đông' if '南海' in block else 'Hải Nam / Quảng Đông'
        summary=f"{CATEGORIES[cat]} tại {place}; khu vực được trích từ thông báo hàng hải dẫn lại bởi SeaLagom."
        if '禁止驶入' in block:summary+=' Thông báo nêu cấm đi vào khu vực.'
        if precision=='DAILY_WINDOWS':
            summary+=(f" Hoạt động theo khung giờ mỗi ngày {window['start_cn']}–{window['end_cn']} (giờ Trung Quốc, UTC+8); "
                      'không phải cấm liên tục trong cả ngày.')
        if precision in ('DATE_DAY_LEVEL','DATE_RANGE_DAY_LEVEL'):
            summary+=' Thời gian chỉ xác định theo ngày, chưa xác định giờ chính xác.'
        results.append({
            'event_id':f"MSA-{tr[m['prefix']]}{int(m['number'])}-{m['yy']}",
            'year':year,'category':cat,
            'title_zh':f"{m.group(0)} {block[:100]}",
            'title_vi':f'{CATEGORIES[cat]} — {no}',
            'summary_zh':block[:3000],'summary_vi':summary,'translation_status':'glossary',
            'start_at':start,'end_at':end,'date_precision':precision,
            'published_at':doc.get('published_at'),
            'daily_window_cn':window,
            'geometry':geom,'geometry_precision':'MSA_REPOST_COORDINATES',
            'place_zh':'北部湾' if '北部湾' in block else '南海' if '南海' in block else '',
            'place_vi':place,
            'sources':[{'url':doc['url'],'source':'SEALAGOM','kind':'public_secondary_aggregator'}],
            'notice_number':no
        })
    return results
