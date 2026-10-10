from __future__ import annotations
import json
import shutil
from pathlib import Path
from fetch_msa import discover_document_links, fetch_document
from parse_notice import normalize_notice_block, split_hainan_notice_blocks

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "notices.json"
DOCS_DB = ROOT / "docs" / "data" / "notices.json"

def load_db():
    if not DB.exists():
        return []
    return json.loads(DB.read_text(encoding="utf-8"))

def save_db(records):
    records = sorted(records, key=lambda x: (x.get("year") or 0, x.get("notice_no_en") or ""), reverse=True)
    DB.parent.mkdir(parents=True, exist_ok=True)
    DB.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    DOCS_DB.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(DB, DOCS_DB)

def main():
    existing = load_db()
    by_id = {r["record_id"]: r for r in existing}
    links, errors = discover_document_links()
    print(f"discovered_documents={len(links)}")
    for e in errors:
        print("source_error:", e)

    added = updated = parsed_blocks = 0
    for link in links:
        try:
            doc = fetch_document(link)
        except Exception as exc:
            print("document_error:", link, exc)
            continue

        for _, block in split_hainan_notice_blocks(doc["title"], doc["text"]):
            parsed_blocks += 1
            try:
                rec = normalize_notice_block(
                    block,
                    source_url=doc["url"],
                    source_kind=doc["source_kind"],
                    page_title=doc["title"],
                )
            except Exception as exc:
                print("parse_error:", link, exc)
                continue

            if not rec or rec.get("year") not in (2025, 2026):
                continue

            old = by_id.get(rec["record_id"])
            if not old:
                by_id[rec["record_id"]] = rec
                added += 1
            elif old.get("checksum") != rec.get("checksum"):
                rec["first_seen_at"] = old.get("first_seen_at", rec["first_seen_at"])
                by_id[rec["record_id"]] = {**old, **rec}
                updated += 1

    save_db(list(by_id.values()))
    print(f"parsed_blocks={parsed_blocks} added={added} updated={updated} total={len(by_id)}")

if __name__ == "__main__":
    main()
