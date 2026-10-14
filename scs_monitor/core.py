from __future__ import annotations
import hashlib
import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

BASE = Path(__file__).resolve().parents[1]
DB = BASE / 'data' / 'scs_events.sqlite3'
EXPORT = BASE / 'docs' / 'data'
START_YEAR = 2020
NOW_UTC = lambda: datetime.now(timezone.utc).isoformat(timespec='seconds')

CATEGORIES = {
    'LIVE_FIRE': 'Bắn đạn thật',
    'MILITARY_EXERCISE': 'Diễn tập quân sự',
    'JOINT_NAVAL_AIR_EXERCISE': 'Huấn luyện/diễn tập liên hợp hải-không',
    'COMBAT_READINESS_PATROL': 'Tuần tra sẵn sàng chiến đấu',
    'NAVAL_EXERCISE': 'Diễn tập hải quân',
    'AIR_EXERCISE': 'Diễn tập không quân',
    'MILITARY_TRAINING': 'Huấn luyện quân sự',
    'OTHER_MILITARY': 'Hoạt động quân sự khác',
}

PLACE_ALIASES = [
    ('黄岩岛', 'Bãi cạn Scarborough (Hoàng Nham)', [117.75, 15.15]),
    ('西沙', 'Quần đảo Hoàng Sa', None),
    ('南沙', 'Quần đảo Trường Sa', None),
    ('永暑礁', 'Đá Chữ Thập', [112.887, 9.55]),
    ('北部湾', 'Vịnh Bắc Bộ', None),
    ('南海', 'Biển Đông', None),
]

MILITARY_WORDS = ['实弹射击','射击训练','军事训练','军事演习','联合演训','海空联合','战备警巡','战备巡逻',
                  '军事活动','实战化训练','演训活动','训练任务','舰艇训练','舰艇编队','军演','军事行动','实弹训练']
SCS_WORDS = ['南海','黄岩岛','西沙','南沙','北部湾','永暑礁','琼航警','粤航警','桂航警', '海南岛', '海南']
PLA_ACTORS = ['南部战区','解放军','海军','空军','战区','部队','舰艇','舰船','航空兵','编队']


def db_conn(path=DB):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS documents (
      url TEXT PRIMARY KEY, source TEXT NOT NULL, title_zh TEXT, body_zh TEXT,
      published_at TEXT, raw_hash TEXT NOT NULL, fetched_at TEXT NOT NULL,
      fetch_method TEXT NOT NULL, event_id TEXT
    );
    CREATE TABLE IF NOT EXISTS events (
      event_id TEXT PRIMARY KEY, payload TEXT NOT NULL, fingerprint TEXT NOT NULL,
      first_seen TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS translations (
      content_hash TEXT PRIMARY KEY, translated TEXT NOT NULL, mode TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS health (
      source TEXT PRIMARY KEY, last_attempt TEXT, last_success TEXT,
      last_error TEXT, discovered INTEGER DEFAULT 0, processed INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS backfill (
      job_id TEXT PRIMARY KEY, attempted_at TEXT NOT NULL, discovered INTEGER NOT NULL,
      processed INTEGER NOT NULL, errors TEXT NOT NULL
    );
    ''')
    return conn


def canonical_url(url):
    p = urlparse(url.strip())
    # Strip tracking parameters without removing essential article ID.
    qs = [(k, v) for k, v in parse_qsl(p.query) if not (k.startswith('utm_') or k in ('from','spm'))]
    return urlunparse((p.scheme.lower(), p.netloc.lower(), p.path.rstrip('/') or '/', '', urlencode(qs), ''))


def sha(s):
    return hashlib.sha256(str(s).encode('utf-8')).hexdigest()


def source_for_url(url):
    host = (urlparse(url).hostname or '').lower()
    if host in ('sealagom.com','www.sealagom.com'):
        return 'SEALAGOM'
    if host == 'mod.gov.cn' or host.endswith('.mod.gov.cn'):
        return 'MOD'
    if host == '81.cn' or host.endswith('.81.cn'):
        return 'PLA81'
    if host == 'msa.gov.cn' or host.endswith('.msa.gov.cn'):
        return 'MSA'
    return None


def classify(text):
    if any(w in text for w in ('实弹射击', '实弹训练', '射击训练', '炮击')): return 'LIVE_FIRE'
    if any(w in text for w in ('海空联合演训', '海空联合训练','海空联合')): return 'JOINT_NAVAL_AIR_EXERCISE'
    if any(w in text for w in ('战备警巡','战备巡逻')): return 'COMBAT_READINESS_PATROL'
    if any(w in text for w in ('军事演习','联合演习','联合演训','演训活动','演习')): return 'MILITARY_EXERCISE'
    if '海军' in text and ('训练' in text or '演练' in text): return 'NAVAL_EXERCISE'
    if '空军' in text and ('训练' in text or '演练' in text): return 'AIR_EXERCISE'
    if any(w in text for w in ('军事训练','训练','演练')): return 'MILITARY_TRAINING'
    return 'OTHER_MILITARY'


def named_place(text):
    for zh, vi, point in PLACE_ALIASES:
        if zh in text:
            return zh, vi, point
    return None, 'Chưa xác định', None


def is_relevant_pla(title, body):
    # Exclude broad press conferences/op-eds that only mention exercises in passing.
    if any(w in title for w in ('记者会','答记者问','评论员','正告','社评')): return False
    head = (title + '\n' + body[:1300])
    return (any(s in head for s in SCS_WORDS)
            and any(m in head for m in MILITARY_WORDS)
            and any(a in head for a in PLA_ACTORS))


def normalize_title(title):
    return re.sub(r'[\W_\s]+', '', title or '', flags=re.UNICODE).lower()[:110]


def is_in_scs_geometry(geom):
    if not geom: return True
    pts = geom.get('coordinates', [])
    if geom.get('type') == 'Polygon': pts = pts[0] if pts else []
    elif geom.get('type') == 'Point': pts = [pts]
    return bool(pts) and all(103.0 <= p[0] <= 122.5 and 1.0 <= p[1] <= 24.5 for p in pts)


def upsert_event(conn, event, source_doc=None):
    event_id = event['event_id']
    now = NOW_UTC()
    old = conn.execute('SELECT payload,first_seen FROM events WHERE event_id=?',(event_id,)).fetchone()
    if old:
        old_payload = json.loads(old['payload'])
        sources = {x['url']: x for x in old_payload.get('sources', [])}
        for s in event.get('sources', []): sources[s['url']] = s
        event['sources'] = list(sources.values())
        event['first_seen_at'] = old_payload.get('first_seen_at',old['first_seen'])
        # Do not drop more precise geographic data.
        if ((not event.get('geometry') and old_payload.get('geometry')) or
            (event.get('geometry_precision')=='MSA_REPOST_COORDINATES' and
             old_payload.get('geometry_precision')=='MSA_COORDINATES')):
            event['geometry'] = old_payload['geometry']
            event['geometry_precision'] = old_payload.get('geometry_precision','UNKNOWN')
        if event.get('translation_status') != 'machine' and old_payload.get('translation_status') == 'machine':
            event['title_vi'] = old_payload['title_vi']
            event['summary_vi'] = old_payload['summary_vi']
            event['translation_status'] = 'machine'
    else:
        event['first_seen_at'] = now
    # Fingerprint must not include arbitrary processing time.
    event.pop('updated_at',None)
    fingerprint = sha(json.dumps(event, sort_keys=True,ensure_ascii=False))
    prior = conn.execute('SELECT fingerprint FROM events WHERE event_id=?',(event_id,)).fetchone()
    changed = prior is None or prior['fingerprint'] != fingerprint
    if changed:
        event['updated_at'] = now
        conn.execute('INSERT OR REPLACE INTO events VALUES (?,?,?,?,?)',
                     (event_id,json.dumps(event,ensure_ascii=False),fingerprint,event['first_seen_at'],now))
    if source_doc:
        conn.execute('''INSERT INTO documents(url,source,title_zh,body_zh,published_at,raw_hash,fetched_at,fetch_method,event_id)
          VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(url) DO UPDATE SET
          raw_hash=excluded.raw_hash,fetched_at=excluded.fetched_at,event_id=excluded.event_id''',
          (source_doc['url'],source_doc['source'],source_doc['title'],source_doc['body'],
           source_doc.get('published_at'),sha(source_doc['body']),now,source_doc['fetch_method'],event_id))
    conn.commit()
    return changed, old is None


def set_health(conn, source, discovered, processed, error=None):
    now=NOW_UTC()
    prev=conn.execute('SELECT last_success FROM health WHERE source=?',(source,)).fetchone()
    last_success = now if processed > 0 else (prev['last_success'] if prev else None)
    conn.execute('INSERT OR REPLACE INTO health VALUES (?,?,?,?,?,?)',
        (source,now,last_success,error,discovered,processed))
    conn.commit()


def export_site(conn, current_year=None):
    EXPORT.mkdir(parents=True,exist_ok=True)
    current_year = current_year or datetime.now(timezone.utc).year
    rows=[json.loads(r['payload']) for r in conn.execute('SELECT payload FROM events')]
    for y in range(START_YEAR,current_year+1):
        subset=[r for r in rows if r.get('year')==y]
        subset.sort(key=lambda r: (r.get('start_at') or r.get('published_at') or '',r['event_id']),reverse=True)
        write_json(EXPORT/f'events-{y}.json',subset)
    by_year={str(y):sum(1 for r in rows if r.get('year')==y) for y in range(START_YEAR,current_year+1)}
    by_kind={k:sum(1 for r in rows if r.get('category')==k) for k in CATEGORIES}
    by_source={s:sum(1 for r in rows if any(d.get('source')==s for d in r.get('sources',[]))) for s in ('MSA','SEALAGOM','MOD','PLA81')}
    with_geo=sum(1 for r in rows if r.get('geometry'))
    write_json(EXPORT/'stats.json',{
        'total':len(rows),'by_year':by_year,'by_category':by_kind,
        'by_source':by_source,'with_geometry':with_geo,
        'generated_at':NOW_UTC(),'start_year':START_YEAR,'end_year':current_year,
        'note':'Thống kê dựa trên dữ liệu đã thu thập; không phải danh mục đầy đủ mọi hoạt động từ 2020.'
    })
    health=[dict(r) for r in conn.execute('SELECT * FROM health ORDER BY source')]
    write_json(EXPORT/'health.json',{'generated_at':NOW_UTC(),'sources':health})
    bf=[dict(r) for r in conn.execute('SELECT * FROM backfill ORDER BY job_id')]
    write_json(EXPORT/'backfill-progress.json',{'attempted_jobs':bf,'expected_months':(current_year-START_YEAR)*12+datetime.now().month,
        'note':'Đã thử tìm kiếm ≠ hoàn tất tư liệu; nguồn có thể bị chặn/không được công cụ tìm kiếm lập chỉ mục.'})
    write_json(EXPORT/'events-index.json',{'years':list(range(START_YEAR,current_year+1)),
        'generated_at':NOW_UTC(),'total':len(rows)})
    return len(rows)


def write_json(path,obj):
    payload=json.dumps(obj,ensure_ascii=False,indent=2)+'\n'
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    # Avoid commits when nothing actually changed.
    if path.exists() and path.read_text(encoding='utf-8') == payload: return
    tmp=path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(payload,encoding='utf-8')
    tmp.replace(path)
