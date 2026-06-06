import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def now():
    return time.time()


def compact(text):
    return re.sub(r"\s+", " ", str(text or "")).strip()


def safe_name(name, fallback="paper"):
    name = compact(name).replace("\\", " ").replace("/", " ")
    name = re.sub(r"[<>:\"|?*\x00-\x1f]+", " ", name).strip(" .")
    return (name or fallback)[:120]


def file_id(path):
    path = Path(path)
    stat = path.stat()
    key = f"{path.resolve()}::{stat.st_mtime_ns}::{stat.st_size}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]


def rank_score(meta):
    ccf = compact(meta.get("ccf") or meta.get("CCF")).upper()
    sci = compact(meta.get("sci") or meta.get("SCI")).upper()
    jcr = compact(meta.get("jcr") or meta.get("JCR")).upper()
    if compact(meta.get("rankScore") or meta.get("RankScore")).isdigit():
        return int(compact(meta.get("rankScore") or meta.get("RankScore")))
    ccf_score = {"A": 3, "B": 2, "C": 1}.get(ccf, 0)
    quartile = {"Q1": 4, "Q2": 3, "Q3": 2, "Q4": 1}
    return ccf_score + max(quartile.get(sci, 0), quartile.get(jcr, 0))


def db_path(root):
    return Path(root) / "reflow-cache" / "scireader.sqlite"


def library_dir(root):
    path = Path(root) / "reflow-cache" / "scireader-library"
    path.mkdir(parents=True, exist_ok=True)
    return path


def connect(root):
    path = db_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    return con


def init_db(con):
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS papers (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            authors TEXT DEFAULT '',
            year TEXT DEFAULT '',
            venue TEXT DEFAULT '',
            ccf TEXT DEFAULT '',
            sci TEXT DEFAULT '',
            jcr TEXT DEFAULT '',
            rank_score INTEGER DEFAULT 0,
            code_status TEXT DEFAULT '',
            code_url TEXT DEFAULT '',
            code_evidence TEXT DEFAULT '',
            importance INTEGER DEFAULT 0,
            abstract TEXT DEFAULT '',
            pdf_path TEXT NOT NULL,
            doc_id TEXT DEFAULT '',
            source TEXT DEFAULT 'local',
            zotero_item_id TEXT DEFAULT '',
            status TEXT DEFAULT '',
            stage TEXT DEFAULT '',
            progress INTEGER DEFAULT 0,
            error TEXT DEFAULT '',
            summary_path TEXT DEFAULT '',
            created_at REAL DEFAULT 0,
            updated_at REAL DEFAULT 0
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_papers_pdf_path ON papers(pdf_path);
        CREATE INDEX IF NOT EXISTS idx_papers_rank ON papers(rank_score, importance);
        CREATE TABLE IF NOT EXISTS attachments (
            id TEXT PRIMARY KEY,
            paper_id TEXT NOT NULL,
            title TEXT DEFAULT '',
            path TEXT NOT NULL,
            type TEXT DEFAULT 'pdf',
            created_at REAL DEFAULT 0,
            FOREIGN KEY(paper_id) REFERENCES papers(id) ON DELETE CASCADE
        );
        """
    )
    con.commit()


def row_dict(row):
    return {
        "id": row["id"],
        "title": row["title"],
        "authors": row["authors"],
        "year": row["year"],
        "venue": row["venue"],
        "ccf": row["ccf"],
        "sci": row["sci"],
        "jcr": row["jcr"],
        "rankScore": row["rank_score"],
        "codeStatus": row["code_status"],
        "codeUrl": row["code_url"],
        "codeEvidence": row["code_evidence"],
        "importance": row["importance"],
        "abstract": row["abstract"],
        "pdfPath": row["pdf_path"],
        "docId": row["doc_id"],
        "source": row["source"],
        "zoteroItemId": row["zotero_item_id"],
        "status": row["status"],
        "stage": row["stage"],
        "progress": row["progress"],
        "error": row["error"],
        "summaryPath": row["summary_path"],
        "updatedAt": row["updated_at"],
    }


def list_papers(con):
    rows = con.execute(
        """
        SELECT * FROM papers
        ORDER BY rank_score DESC, importance DESC, updated_at DESC, title COLLATE NOCASE
        """
    ).fetchall()
    return [row_dict(row) for row in rows]


def parse_extra(extra):
    out = {}
    for line in str(extra or "").splitlines():
        m = re.match(r"^(?:AI Reflow|SciReader) (Venue|CCF|SCI|JCR|RankScore|Stars|CodeStatus|CodeURL|CodeEvidence|Evidence):\s*(.*)$", line)
        if m:
            out[m.group(1)] = compact(m.group(2))
    return out


def upsert_paper(con, root, path, title="", authors="", year="", venue="", abstract="", source="local", zotero_item_id="", copy=False, extra=None):
    src = Path(path).resolve()
    if not src.exists() or src.suffix.lower() != ".pdf":
        raise ValueError(f"PDF not found: {path}")
    target = src
    if copy:
        provisional = safe_name(title or src.stem, src.stem)
        target_dir = library_dir(root) / "pdfs"
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{provisional}-{hashlib.sha1(str(src).encode('utf-8')).hexdigest()[:8]}.pdf"
        if not target.exists():
            shutil.copy2(src, target)
    doc_id = file_id(target)
    paper_id = f"p_{doc_id}"
    meta = extra or {}
    final_venue = compact(meta.get("Venue")) or compact(venue)
    stars = int(meta.get("Stars") or 0) if str(meta.get("Stars") or "").isdigit() else 0
    values = {
        "id": paper_id,
        "title": compact(title) or target.stem,
        "authors": compact(authors),
        "year": compact(year),
        "venue": final_venue,
        "ccf": compact(meta.get("CCF")),
        "sci": compact(meta.get("SCI")),
        "jcr": compact(meta.get("JCR")),
        "rank_score": rank_score(meta),
        "code_status": compact(meta.get("CodeStatus")),
        "code_url": compact(meta.get("CodeURL")),
        "code_evidence": compact(meta.get("CodeEvidence") or meta.get("Evidence")),
        "importance": max(0, min(5, stars)),
        "abstract": compact(abstract),
        "pdf_path": str(target),
        "doc_id": doc_id,
        "source": source,
        "zotero_item_id": str(zotero_item_id or ""),
        "updated_at": now(),
    }
    existing = con.execute("SELECT id, importance FROM papers WHERE pdf_path=? OR doc_id=?", (values["pdf_path"], doc_id)).fetchone()
    if existing:
        values["id"] = existing["id"]
        if not values["importance"]:
            values["importance"] = existing["importance"]
        con.execute(
            """
            UPDATE papers SET
                title=:title, authors=:authors, year=:year, venue=:venue, ccf=:ccf, sci=:sci, jcr=:jcr,
                rank_score=:rank_score, code_status=:code_status, code_url=:code_url, code_evidence=:code_evidence,
                importance=:importance, abstract=COALESCE(NULLIF(:abstract, ''), abstract), pdf_path=:pdf_path,
                doc_id=:doc_id, source=:source, zotero_item_id=:zotero_item_id, updated_at=:updated_at
            WHERE id=:id
            """,
            values,
        )
    else:
        values["created_at"] = now()
        con.execute(
            """
            INSERT INTO papers (
                id,title,authors,year,venue,ccf,sci,jcr,rank_score,code_status,code_url,code_evidence,
                importance,abstract,pdf_path,doc_id,source,zotero_item_id,created_at,updated_at
            ) VALUES (
                :id,:title,:authors,:year,:venue,:ccf,:sci,:jcr,:rank_score,:code_status,:code_url,:code_evidence,
                :importance,:abstract,:pdf_path,:doc_id,:source,:zotero_item_id,:created_at,:updated_at
            )
            """,
            values,
        )
    con.execute(
        "INSERT OR REPLACE INTO attachments (id,paper_id,title,path,type,created_at) VALUES (?,?,?,?,?,?)",
        (f"a_{doc_id}", values["id"], "Full Text PDF", values["pdf_path"], "pdf", now()),
    )
    con.commit()
    return row_dict(con.execute("SELECT * FROM papers WHERE id=?", (values["id"],)).fetchone())


def get_item_field(cur, item_id, field):
    row = cur.execute(
        """
        SELECT v.value
        FROM itemData d
        JOIN fields f ON f.fieldID=d.fieldID
        JOIN itemDataValues v ON v.valueID=d.valueID
        WHERE d.itemID=? AND f.fieldName=?
        """,
        (item_id, field),
    ).fetchone()
    return row[0] if row else ""


def get_creators(cur, item_id):
    rows = cur.execute(
        """
        SELECT c.firstName, c.lastName
        FROM itemCreators ic
        JOIN creators c ON c.creatorID=ic.creatorID
        WHERE ic.itemID=?
        ORDER BY ic.orderIndex
        """,
        (item_id,),
    ).fetchall()
    names = []
    for first, last in rows:
        names.append(compact(f"{first or ''} {last or ''}"))
    return ", ".join([name for name in names if name])


def resolve_zotero_path(zotero_root, attachment_key, raw_path):
    raw_path = str(raw_path or "")
    if raw_path.startswith("storage:"):
        return Path(zotero_root) / "storage" / attachment_key / raw_path.split(":", 1)[1]
    if raw_path.startswith("file://"):
        return Path(raw_path.replace("file://", ""))
    path = Path(raw_path)
    if not path.is_absolute():
        path = Path(zotero_root) / raw_path
    return path


def import_zotero(con, root, zotero_root=None):
    zotero_root = Path(zotero_root or Path.home() / "Zotero")
    zdb = zotero_root / "zotero.sqlite"
    if not zdb.exists():
        raise ValueError(f"Zotero database not found: {zdb}")
    zcon = sqlite3.connect(f"file:{zdb}?mode=ro", uri=True)
    cur = zcon.cursor()
    rows = cur.execute(
        """
        SELECT a.itemID AS attachmentID, a.parentItemID, a.path, ai.key AS attachmentKey
        FROM itemAttachments a
        JOIN items ai ON ai.itemID=a.itemID
        WHERE a.contentType='application/pdf'
        """
    ).fetchall()
    imported = []
    for attachment_id, parent_id, raw_path, attachment_key in rows:
        parent = parent_id or attachment_id
        pdf_path = resolve_zotero_path(zotero_root, attachment_key, raw_path)
        if not pdf_path.exists():
            continue
        title = get_item_field(cur, parent, "title") or get_item_field(cur, attachment_id, "title") or pdf_path.stem
        abstract = get_item_field(cur, parent, "abstractNote")
        venue = get_item_field(cur, parent, "publicationTitle") or get_item_field(cur, parent, "conferenceName")
        date = get_item_field(cur, parent, "date")
        year_match = re.search(r"(19|20)\d{2}", str(date or ""))
        extra = parse_extra(get_item_field(cur, parent, "extra"))
        imported.append(upsert_paper(
            con,
            root,
            pdf_path,
            title=title,
            authors=get_creators(cur, parent),
            year=year_match.group(0) if year_match else "",
            venue=venue,
            abstract=abstract,
            source="zotero",
            zotero_item_id=parent,
            copy=False,
            extra=extra,
        ))
    zcon.close()
    return {"imported": len(imported), "papers": list_papers(con)}


def update_status(con, payload):
    con.execute(
        """
        UPDATE papers SET doc_id=?, status=?, stage=?, progress=?, error=?, updated_at=?
        WHERE id=?
        """,
        (
            payload.get("docId", ""),
            payload.get("status", ""),
            payload.get("stage", ""),
            int(payload.get("progress") or 0),
            payload.get("error", ""),
            now(),
            payload.get("paperId"),
        ),
    )
    con.commit()
    return {"ok": True}


def update_metadata(con, payload):
    meta = payload.get("metadata") or {}
    score = int(meta.get("rankScore") if str(meta.get("rankScore", "")).isdigit() else rank_score(meta))
    con.execute(
        """
        UPDATE papers SET
            title=COALESCE(NULLIF(?, ''), title),
            venue=COALESCE(NULLIF(?, ''), venue),
            ccf=?, sci=?, jcr=?, rank_score=?, code_status=?, code_url=?, code_evidence=?,
            doc_id=COALESCE(NULLIF(?, ''), doc_id), updated_at=?
        WHERE id=?
        """,
        (
            compact(meta.get("title")),
            compact(meta.get("venue")),
            compact(meta.get("ccf")),
            compact(meta.get("sci")),
            compact(meta.get("jcr")),
            score,
            compact(meta.get("codeStatus")),
            compact(meta.get("codeUrl")),
            compact(meta.get("codeEvidence") or meta.get("evidence")),
            payload.get("docId", ""),
            now(),
            payload.get("paperId"),
        ),
    )
    con.commit()
    return {"ok": True}


def set_stars(con, paper_id, stars):
    stars = max(0, min(5, int(stars or 0)))
    con.execute("UPDATE papers SET importance=?, updated_at=? WHERE id=?", (stars, now(), paper_id))
    con.commit()
    return {"ok": True, "stars": stars}


def sync_items(con):
    rows = con.execute("SELECT title,pdf_path FROM papers WHERE pdf_path<>''").fetchall()
    return [{"title": row["title"], "path": row["pdf_path"]} for row in rows if Path(row["pdf_path"]).exists()]


def main():
    command = sys.argv[1] if len(sys.argv) > 1 else "list"
    payload = json.loads(sys.stdin.read() or "{}")
    root = Path(payload.get("workspaceRoot") or ROOT)
    con = connect(root)
    init_db(con)
    if command == "init":
        result = {"ok": True, "db": str(db_path(root))}
    elif command == "list":
        result = list_papers(con)
    elif command == "upsert_pdfs":
        result = {
            "imported": len(payload.get("paths") or []),
            "papers": [
                upsert_paper(con, root, path, source=payload.get("source") or "local", copy=bool(payload.get("copy")))
                for path in payload.get("paths") or []
            ],
        }
    elif command == "import_zotero":
        result = import_zotero(con, root, payload.get("zoteroRoot"))
    elif command == "set_stars":
        result = set_stars(con, payload.get("paperId"), payload.get("stars"))
    elif command == "update_status":
        result = update_status(con, payload)
    elif command == "update_metadata":
        result = update_metadata(con, payload)
    elif command == "sync_items":
        result = sync_items(con)
    else:
        raise ValueError(f"Unknown command: {command}")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
