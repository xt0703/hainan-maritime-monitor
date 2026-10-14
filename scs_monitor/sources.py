from __future__ import annotations
import json
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from urllib.parse import quote, urljoin
import requests
from bs4 import BeautifulSoup
from .core import (BASE, CATEGORIES, MILITARY_WORDS, SCS_WORDS, NOW_UTC, canonical_url, classify,
                   db_conn, is_in_scs_geometry, is_relevant_pla, named_place,
                   normalize_title, sha, source_for_url, upsert_event, set_health)

TIMEOUT=22
HEADERS={'User-Agent':'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126 Safari/537.36',
         'Accept-Language':'zh-CN,zh;q=0.9,en;q=0.7'}

# Indexes are optional; public search discovery provides independent fallback.
INDEXES={
  'MSA':['https://www.msa.gov.cn/page/outter/weather.jsp',
         'https://www.hn.msa.gov.cn/hsfw_1_1/index.jhtml'],
  'MOD':['https://www.mod.gov.cn/gfbw/qwfb/index.html'],
  'PLA81':['https://www.81.cn/yw_208727/index.html']
}
SEED_URLS=[
 'https://www.msa.gov.cn/html/cnmsa/hxaq/article/2026/544f7fd8c8124640ae1fa1b09b2af27d.html', # user-confirmed newer MSA article endpoint
 'https://www.mod.gov.cn/gfbw/wzll/nbzq/4862409.html', # 2020: joint naval/air training
 'https://www.mod.gov.cn/gfbw/qwfb/16278351.html', # 2024: South China Sea exercise
 'https://www.mod.gov.cn/gfbw/jsxd/ly/16477289.html', # 2026: Scarborough exercise
 'https://www.81.cn/syjdt/16465132.html', # 2026: training at sea
 'https://www.81.cn/hj_208557/jdt_208558/16381975.html', # 2025: navy training
]
DATE_RE=re.compile(r'(20(?:2\d))[-年/.](1[0-2]|0?[1-9])[-月/.]([12]\d|3[01]|0?[1-9])(?:日)?(?:\s*[T ]?([01]?\d|2[0-3])[:时]([0-5]\d))?')
NOTICE_ID_RE=re.compile(r'(?P<prefix>[琼粤桂闽浙沪苏鲁辽冀津]{1,3})航警\s*[〖\[（(]?\s*(?P<n>\d{1,4})\s*[／/]\s*(?P<yy>\d{2})')


def http_text(url):
    r=requests.get(url,headers=HEADERS,timeout=TIMEOUT,allow_redirects=True)
    r.raise_for_status()
    if not r.encoding or r.encoding.lower()=='iso-8859-1':
        r.encoding=r.apparent_encoding or 'utf-8'
    return r.text


def fetch_doc(url):
    try:
        raw=http_text(url)
        mode='direct'
    except Exception as exc:
        try:
            raw=http_text('https://r.jina.ai/'+url)
            mode='reader'
        except Exception as exc2:
            raise RuntimeError(f'direct:{type(exc).__name__}:{str(exc)[:110]}; reader:{type(exc2).__name__}:{str(exc2)[:110]}') from exc2
    if '当前访问疑似黑客攻击' in raw or '已被云盾拦截' in raw:
        raise RuntimeError('WAF block page')
    title,body=extract_article(raw)
    if len(body)<35: raise RuntimeError('Short or empty page')
    pub = parse_date(raw[:3000]+'\n'+body[:450])
    return {'url':canonical_url(url),'title':title[:400],'body':body[:16000],
            'published_at':pub,'fetch_method':mode,'source':source_for_url(url)}


def extract_article(raw):
    if '<html' not in raw.lower() and '<body' not in raw.lower():
        lines=[l.strip() for l in raw.splitlines() if l.strip()]
        t=next((x.split(':',1)[1].strip() for x in lines[:25] if x.lower().startswith('title:')),'')
        if not t: t=next((x[2:] for x in lines[:25] if x.startswith('# ')),'')
        # Jina reader often contains markdown navigation; keep body for filters.
        return t, '\n'.join(lines)
    soup=BeautifulSoup(raw,'html.parser')
    for n in soup.select('script,style,nav,footer,header,aside'):
        n.decompose()
    title=''
    for selector in ('h1','.article-title','.art-title','.title','title'):
        node=soup.select_one(selector)
        if node and len(node.get_text(' ',strip=True))>5:
            title=node.get_text(' ',strip=True)
            break
    for selector in ('.TRS_Editor','.article-content','.articleContent','article','#content','.article','.content','main','body'):
        for node in soup.select(selector)[:2]:
            txt=node.get_text('\n',strip=True)
            if len(txt)>55:
                return title, txt
    return title, soup.get_text('\n',strip=True)


def parse_date(text):
    m=DATE_RE.search(text)
    if not m: return None
    y,mo,d=int(m[1]),int(m[2]),int(m[3])
    if not (2020<=y<=datetime.now().year): return None
    try:
        return datetime(y,mo,d,int(m[4] or 0),int(m[5] or 0)).strftime('%Y-%m-%dT%H:%M:%S+08:00')
    except ValueError: return None


def rss_search(query):
    url='https://www.bing.com/search?format=rss&q='+quote(query)
    raw=http_text(url)
    root=ET.fromstring(raw)
    out=[]
    for item in root.findall('.//item'):
        href=(item.findtext('link') or '').strip()
        if source_for_url(href) and href not in out:
            out.append(href)
    return out


def listing_links(url):
    raw=http_text(url)
    soup=BeautifulSoup(raw,'html.parser')
    out=[]
    for a in soup.find_all('a',href=True):
        name=a.get_text(' ',strip=True)
        href=urljoin(url,a['href'])
        if source_for_url(href) and any(x in name+href for x in MILITARY_WORDS+SCS_WORDS):
            if href!=url and href not in out: out.append(href)
    return out


def queries(source,year=None,month=None):
    suffix=''
    if year: suffix=f' {year}'
    if month: suffix+=f' {month}月'
    if source=='MSA':
        # Newer MSA articles use year-specific paths. Do NOT hardcode 2026,
        # otherwise historical backfill for 2020-2025 becomes misleading.
        path = f"site:msa.gov.cn/html/cnmsa/hxaq/article/{year}" if year else 'site:msa.gov.cn/html/cnmsa/hxaq/article/'
        return [f'{path} "航警" "军事训练"{suffix}',
                f'site:msa.gov.cn "航警" "军事训练" "南海"{suffix}',
                f'site:msa.gov.cn "琼航警" "实弹射击"{suffix}',
                f'site:msa.gov.cn "粤航警" "军事训练"{suffix}',
                f'site:msa.gov.cn "桂航警" "军事演习"{suffix}']
    if source=='MOD':
        return [f'site:mod.gov.cn "南海" "南部战区" "演训"{suffix}',
                f'site:mod.gov.cn "黄岩岛" "训练"{suffix}']
    if source=='PLA81':
        return [f'site:81.cn "南海" "南部战区" "演训"{suffix}',
                f'site:81.cn "南海" "舰艇" "训练"{suffix}']
    return []


def discover(source,year=None,month=None,per_source=35):
    found=[]; failures=[]
    if source=='MSA' and year is None:
        # Probe the newer official MSA article endpoint before pagination limits.
        found.append('https://www.msa.gov.cn/html/cnmsa/hxaq/article/2026/544f7fd8c8124640ae1fa1b09b2af27d.html')
    if source=='SEALAGOM':
        from .sealagom import REGIONS
        return (REGIONS[:per_source], []) if year is None else ([], [])
    if year is None:
        # Current discovery over two publication years; keep queries bounded.
        for y in (datetime.now().year, datetime.now().year-1):
            for q in queries(source,y)[:2]:
                try:
                    for u in rss_search(q):
                        if u not in found: found.append(u)
                except Exception as e: failures.append(f'RSS: {str(e)[:120]}')
    else:
        for q in queries(source,year,month):
            try:
                for u in rss_search(q):
                    if u not in found: found.append(u)
            except Exception as e: failures.append(f'RSS: {str(e)[:120]}')

    if year is None:
        for index in INDEXES.get(source,[]):
            try:
                for u in listing_links(index):
                    if u not in found: found.append(u)
            except Exception as e: failures.append(f'Index {index}: {str(e)[:110]}')
        for u in SEED_URLS:
            if source_for_url(u)==source and u not in found: found.append(u)
    return found[:per_source],failures


def import_legacy(conn):
    path=BASE/'data'/'notices.json'
    if not path.exists(): return 0
    data=json.loads(path.read_text(encoding='utf-8'))
    added=0
    for r in data:
        if not (2020<=int(r.get('year') or 0)<=datetime.now().year): continue
        geom=r.get('geometry')
        if not is_in_scs_geometry(geom): geom=None
        id_='MSA-'+r['record_id']
        url=r.get('source_url') or ''
        source='MSA' if source_for_url(url)=='MSA' else 'MIRROR'
        src={'source':source,'url':url,'kind':r.get('source_kind','unknown')}
        ev={
         'event_id':id_,'year':r['year'],'category':r.get('category','OTHER_MILITARY'),
         'title_zh':r.get('title_cn',''),'title_vi':r.get('title_vi',''),
         'summary_zh':(r.get('body_cn') or '')[:3000],
         'summary_vi':r.get('body_vi') or '', 'translation_status':'glossary',
         'start_at':r.get('restriction_start_vn'),'end_at':r.get('restriction_end_vn'),
         'published_at':r.get('issued_at_cn'),
         'date_precision':'EXACT_RESTRICTION' if r.get('restriction_start_vn') and r.get('restriction_end_vn') else 'UNKNOWN',
         'geometry':geom,'geometry_precision':('MSA_REPOST_COORDINATES' if source=='MIRROR' else 'MSA_COORDINATES') if geom else 'UNKNOWN',
         'place_zh':r.get('area_name_cn') or '',
         'place_vi':r.get('area_name_vi') or 'Biển Đông',
         'sources':[src], 'notice_number':r.get('notice_no_en') or '',
         'first_seen_at':r.get('first_seen_at') or NOW_UTC()
        }
        changed,is_new=upsert_event(conn,ev)
        added+=int(is_new)
    return added


def parse_msa_blocks(doc):
    try:
        from crawler.parse_notice import geometry_for,extract_time_range
    except ImportError:
        # Running against a repo without the existing crawler: defer parsing.
        return []
    text=doc['title']+'\n'+doc['body']
    matches=list(NOTICE_ID_RE.finditer(text))
    out=[]
    for i,m in enumerate(matches):
        end=matches[i+1].start() if i+1<len(matches) else len(text)
        block=text[m.start():end][:6500]
        if not any(w in block[:1500] for w in MILITARY_WORDS): continue
        prefix,num,yy=m['prefix'],int(m['n']),int(m['yy'])
        year=2000+yy
        if not (2020<=year<=datetime.now().year):continue
        geom=geometry_for(block)
        from .sealagom import geometry_for as new_geometry_for, dates_for as new_dates_for
        # New MSA article pages may use DMS with seconds, unsupported by legacy parser.
        if not geom: geom=new_geometry_for(block)
        if not is_in_scs_geometry(geom):continue
        # East-China-Sea regions are excluded unless actual coordinates/text in SCS.
        if prefix not in ('琼','粤','桂') and not any(w in block for w in SCS_WORDS): continue
        try: start,end=extract_time_range(block,year)
        except Exception: start,end=None,None
        date_precision='EXACT_RESTRICTION' if start and end else 'UNKNOWN'
        daily_window=None
        fallback_start=fallback_end=None
        if not (start and end):
            fallback_start,fallback_end,date_precision,daily_window=new_dates_for(block,year)
        place_zh,place_vi,_=named_place(block)
        cat=classify(block)
        code=f'{prefix}{num}/{yy:02d}'
        translations={
          '琼':'HN','粤':'GD','桂':'GX','闽':'FJ','浙':'ZJ','沪':'SH','苏':'JS','鲁':'SD','辽':'LN','冀':'HE','津':'TJ'
        }
        notice_no=f'{translations.get(prefix,prefix)}{num}/{yy:02d}'
        title_vi=f'{CATEGORIES[cat]} — {notice_no}'
        summary_vi=(f'{CATEGORIES[cat]} tại {place_vi if place_zh else "vùng biển theo thông báo"}. '
                    f'{"Có vùng tọa độ hàng hải." if geom else "Chưa xác định được ranh giới."} '
                    + ('Nguồn nêu cấm đi vào.' if '禁止驶入' in block else ''))
        ev={
          'event_id':f'MSA-{translations.get(prefix,prefix)}{num}-{yy:02d}','year':year,'category':cat,
          'title_zh':code+' '+doc['title'],'title_vi':title_vi,
          'summary_zh':block[:3000],'summary_vi':summary_vi,'translation_status':'glossary',
          'start_at':start.astimezone(__import__('zoneinfo').ZoneInfo('Asia/Ho_Chi_Minh')).isoformat() if start else fallback_start,
          'end_at':end.astimezone(__import__('zoneinfo').ZoneInfo('Asia/Ho_Chi_Minh')).isoformat() if end else fallback_end,
          'date_precision':date_precision, 'daily_window_cn':daily_window,
          'published_at':doc.get('published_at'), 'geometry':geom,
          'geometry_precision':'MSA_COORDINATES' if geom else 'UNKNOWN',
          'place_zh':place_zh or '', 'place_vi':place_vi,
          'sources':[{'url':doc['url'],'source':doc['source'],'kind':doc['fetch_method']}],
          'notice_number':notice_no
        }
        out.append(ev)
    return out


def translate_text(conn,text):
    """Best effort machine translation (Google Translate unofficial web); clearly label failures.
    Never send API keys or private data: only public official announcement text.
    """
    text=text.strip()[:1300]
    if not text:return '', 'unavailable'
    key=sha(text)
    old=conn.execute('SELECT translated,mode FROM translations WHERE content_hash=?',(key,)).fetchone()
    if old:return old['translated'],old['mode']
    if os.environ.get('SCS_TRANSLATE_MODE','google')=='google':
        try:
            from deep_translator import GoogleTranslator
            result=GoogleTranslator(source='zh-CN',target='vi').translate(text)
            if result and result.strip() != text.strip():
                conn.execute('INSERT OR REPLACE INTO translations VALUES (?,?,?)',(key,result,'machine'))
                conn.commit()
                return result,'machine'
        except Exception:
            pass
    return '', 'glossary'


def parse_pla(doc,conn):
    title=doc['title']; body=doc['body']; url=doc['url']
    if not is_relevant_pla(title,body):return []
    pub=doc.get('published_at')
    if not pub:return []  # Never infer historical year from discovery time.
    year=int(pub[:4]); cat=classify(title+'\n'+body[:1100]); zh,vi,point=named_place(title+'\n'+body[:850])
    brief=body[:850]
    vi_title, mt=translate_text(conn,title)
    vi_summary, mb=translate_text(conn,brief)
    if not vi_title: vi_title=f'{CATEGORIES[cat]} — {vi}'
    if not vi_summary:
        vi_summary=f'Thông báo của {doc["source"]} đề cập {CATEGORIES[cat].lower()} tại {vi}. Chưa dịch tự động được; xem nguyên văn tiếng Trung và nguồn.'
    # Place marker locates named landmark only, NOT a military operating polygon.
    geometry={'type':'Point','coordinates':point} if point else None
    ev={
       'event_id':f'PLA-{pub[:10]}-{sha(normalize_title(title))[:14]}',
       'year':year,'category':cat,
       'title_zh':title,'title_vi':vi_title,'summary_zh':brief,'summary_vi':vi_summary,
       'translation_status':'machine' if mt=='machine' and mb=='machine' else 'glossary',
       'start_at':None,'end_at':None, 'date_precision':'PUBLICATION_DATE_ONLY',
       'published_at':pub,
       'geometry':geometry,'geometry_precision':'LANDMARK_ONLY' if geometry else 'UNKNOWN',
       'place_zh':zh or '', 'place_vi':vi,
       'sources':[{'url':url,'source':doc['source'],'kind':doc['fetch_method']}],
       'notice_number':''
    }
    return [ev]


def crawl_source(conn, source, year=None, month=None, per_source=35):
    urls,errors=discover(source,year,month,per_source)
    processed=added=updated=0
    for url in urls:
        try:
            u=canonical_url(url)
            existing=conn.execute('SELECT raw_hash,event_id FROM documents WHERE url=?',(u,)).fetchone()
            doc=fetch_doc(u)
            if existing and existing['raw_hash']==sha(doc['body']):
                # Source reached successfully; no need to translate/normalize again.
                processed+=1;continue
            if source=='MSA':
                events=parse_msa_blocks(doc)
            elif source=='SEALAGOM':
                from .sealagom import parse_sealagom
                events=parse_sealagom(doc)
            else:
                events=parse_pla(doc,conn)
            if not events: continue
            for ev in events:
                changed,new=upsert_event(conn,ev,doc)
                added+=int(new);updated+=int(changed and not new)
            processed+=1
        except Exception as exc:
            errors.append(f'{url}: {type(exc).__name__}: {str(exc)[:170]}')
        time.sleep(.25)
    set_health(conn,source,len(urls),processed,'; '.join(errors[:4]) if errors else None)
    print(f'{source}: urls={len(urls)} parsed={processed} added={added} updated={updated} errors={len(errors)}',flush=True)
    return len(urls),processed,errors
