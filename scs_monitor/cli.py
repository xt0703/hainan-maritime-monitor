from __future__ import annotations
import argparse
import json
from datetime import datetime
from .core import db_conn,export_site
from .sources import crawl_source,import_legacy

SOURCES=['MSA','SEALAGOM','MOD','PLA81']

def update(conn,per_source):
    count=import_legacy(conn)
    print(f'legacy_imported={count}',flush=True)
    for src in SOURCES:
        crawl_source(conn,src,per_source=per_source)
    print(f'exported_events={export_site(conn)}',flush=True)


def backfill(conn,batch=4,year=None,month=None,per_source=20,retry_failed=False):
    now=datetime.now(); jobs=[]
    years=[year] if year else list(range(2020,now.year+1))
    for y in years:
        for mo in ([month] if month else range(1,13)):
            if (y,mo)>(now.year,now.month):continue
            job=f'{y}-{mo:02}'
            row=conn.execute('SELECT discovered,processed FROM backfill WHERE job_id=?',(job,)).fetchone()
            if row and not retry_failed:continue
            jobs.append((y,mo,job))
    for y,mo,job in jobs[:batch]:
        found=done=0;errors=[]
        print(f'backfill {job}',flush=True)
        for src in [s for s in SOURCES if s!='SEALAGOM']:
            n,p,e=crawl_source(conn,src,year=y,month=mo,per_source=per_source)
            found+=n;done+=p;errors.extend(e)
        conn.execute('INSERT OR REPLACE INTO backfill VALUES (?,?,?,?,?)',
                     (job,datetime.now().isoformat(),found,done,'; '.join(errors[:8])))
        conn.commit()
        print(f'backfill_result {job}: discovered={found}, processed={done}, errors={len(errors)}',flush=True)
    print(f'exported_events={export_site(conn)}')
    print('Note: attempted months do not imply complete coverage. Investigate errors / missing years.')


def main():
    parser=argparse.ArgumentParser(description='SCS Military Activity Monitor v2')
    sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('update',help='Live discovery from official sources and legacy MSA')
    p.add_argument('--per-source',type=int,default=25)
    p=sub.add_parser('backfill',help='Incremental monthly official document search from 2020')
    p.add_argument('--batch',type=int,default=4,help='Number of month checkpoints in this run')
    p.add_argument('--year',type=int)
    p.add_argument('--month',type=int)
    p.add_argument('--retry-failed',action='store_true')
    p.add_argument('--per-source',type=int,default=18)
    sub.add_parser('export')
    p=sub.add_parser('import-legacy')
    args=parser.parse_args()
    with db_conn() as conn:
        if args.command=='update':update(conn,args.per_source)
        elif args.command=='backfill':
            if args.year and not (2020<=args.year<=datetime.now().year): parser.error('year outside 2020..present')
            if args.month and not (1<=args.month<=12):parser.error('month outside 1..12')
            backfill(conn,args.batch,args.year,args.month,args.per_source,args.retry_failed)
        elif args.command=='import-legacy':
            print('imported='+str(import_legacy(conn)))
            print('exported_events='+str(export_site(conn)))
        else:
            print('exported_events='+str(export_site(conn)))

if __name__=='__main__':main()
