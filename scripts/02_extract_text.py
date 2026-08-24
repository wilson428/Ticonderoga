#!/usr/bin/env python3
import re, sys, argparse, datetime, pathlib
import subprocess
from pathlib import Path

# ---------- helpers ----------

NBSP = "\u00A0"

def normalize_spaces(s: str) -> str:
    # NBSP -> space, collapse runs, strip trailing spaces
    s = s.replace(NBSP, " ")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"[ \t]+$", "", s, flags=re.MULTILINE)
    return s

def dehyphen_join(lines):
    """
    Join hard-wrapped lines into paragraphs, with conservative dehyphenation:
    - if a line ends with '-' and the next line starts lowercase -> join w/o space
    - else join with a single space
    Paragraphs are delimited by blank lines.
    """
    out_paras = []
    buf = []

    def flush():
        nonlocal buf
        if not buf:
            out_paras.append("")
            return
        # join with rules
        joined = []
        for i, line in enumerate(buf):
            line = line.strip()
            if i == 0:
                joined.append(line)
            else:
                prev = joined[-1]
                if prev.endswith("-") and re.match(r"^[a-z]", line):
                    joined[-1] = prev[:-1] + line  # dehyphenate
                else:
                    joined[-1] = prev + " " + line
        para = normalize_spaces(joined[-1])
        out_paras.append(para)
        buf = []

    for line in lines:
        if line.strip() == "":
            flush()
        else:
            buf.append(line)
    flush()
    return out_paras


def gentle_repair_keep_newlines(text_block: str) -> str:
    """
    Preserve original newlines. Only do:
      - NBSP -> space
      - collapse multiple spaces
      - trim trailing spaces
      - dehyphenate when a line ends with '-' and the next line starts lowercase
    Keep markers/headings untouched.
    """
    lines = text_block.replace("\r\n", "\n").replace("\r", "\n").split("\n")

    def is_marker(s: str) -> bool:
        return (
            s.startswith("[[[PAGE ") and s.endswith("]]]")
            or s.startswith("<!--")
            or s.startswith("# ")
        )

    out = []
    i = 0
    while i < len(lines):
        cur = lines[i]
        # normalize spaces (but keep newline semantics)
        cur = cur.replace("\u00A0", " ")
        cur = re.sub(r"[ \t]+$", "", cur)       # strip trailing
        cur = re.sub(r"[ \t]{2,}", " ", cur)    # collapse runs

        if (
            i + 1 < len(lines)
            and not is_marker(cur)
            and not is_marker(lines[i + 1])
            and cur.endswith("-")
            and re.match(r"^[a-z]", lines[i + 1].lstrip())
        ):
            # dehyphenate across the line break: join with NO space
            nxt = lines[i + 1].lstrip()
            nxt = nxt.replace("\u00A0", " ")
            nxt = re.sub(r"[ \t]{2,}", " ", nxt)
            joined = cur[:-1] + nxt
            out.append(joined)
            i += 2
            continue

        out.append(cur)
        i += 1

    return "\n".join(out)

def extract_pages_text(pdf_path: str) -> list[str]:
    # -raw avoids justification gaps; keeps page breaks (\f)
    txt = subprocess.check_output(
        ["pdftotext", "-raw", "-enc", "UTF-8", str(pdf_path), "-"],
        encoding="utf-8",
        errors="ignore",
    )
    pages = txt.replace("\r\n", "\n").replace("\r", "\n").split("\f")
    if pages and pages[-1].strip() == "":
        pages = pages[:-1]
    return pages

# ---------- main ----------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("chapters_list", help="File with chapter IDs (e.g., Sasquatch_Part_01 per line)")
    ap.add_argument("--ocr-dir", default="data/ocr", help="Directory of OCR'd chapter PDFs")
    ap.add_argument("--out-chapters", default="text/chapters", help="Output dir for per-chapter MD")
    ap.add_argument("--master", default="text/master.md", help="Path to write concatenated master MD")
    ap.add_argument("--start", type=int, default=1, help="Global page start (default 1)")
    args = ap.parse_args()

    ocr_dir = pathlib.Path(args.ocr_dir)
    out_chaps = pathlib.Path(args.out_chapters)
    out_chaps.mkdir(parents=True, exist_ok=True)
    master_path = pathlib.Path(args.master)
    master_path.parent.mkdir(parents=True, exist_ok=True)

    with open(args.chapters_list, "r") as f:
        chapters = [ln.strip() for ln in f if ln.strip()]

    master_parts = [
        "---",
        "title: 'Believe in Me — Canonical First Draft'",
        "source: 'pdftotext -raw + gentle cleanup + cumulative markers'",
        f"build_date: '{datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%SZ')}'",
        "---",
        "",
    ]

    # Global page counter + index rows
    global_page = args.start
    page_index_rows = []  # (global, chapter, chapter_page)

    for ch in chapters:
        pdf = ocr_dir / f"{ch}.pdf"
        if not pdf.exists():
            sys.exit(f"Missing {pdf}")

        pages = extract_pages_text(pdf)

        # Build per-chapter text with cumulative [[[PAGE ...]]] markers
        per_chapter_lines = []
        for cp, page_text in enumerate(pages, start=1):
            per_chapter_lines.append(f"[[[PAGE {global_page:04d} CH={ch} CP={cp:04d}]]]")
            page_index_rows.append((global_page, ch, cp))
            # normalize spaces early
            page_text = normalize_spaces(page_text)
            per_chapter_lines.append(page_text)
            global_page += 1

        chapter_raw = "\n".join(per_chapter_lines)
        chapter_md = gentle_repair_keep_newlines(chapter_raw)

        out_file = out_chaps / f"{ch}.md"
        out_file.write_text(chapter_md, encoding="utf-8")
        print(f"✓ {ch}: {len(pages)} pages → {out_file}")

        # append to master
        master_parts.append(f"<!-- chapter:{ch} -->")
        master_parts.append("")
        master_parts.append(chapter_md.rstrip("\n"))
        master_parts.append("")
        master_parts.append(f"<!-- chapterbreak:{ch} -->")
        master_parts.append("")

    master_path.write_text("\n".join(master_parts), encoding="utf-8")
    print(f"✓ Built {master_path}")

    # Write a quick page index for navigation
    idx_path = Path("text/page_index.tsv")
    idx_path.parent.mkdir(parents=True, exist_ok=True)
    with idx_path.open("w", encoding="utf-8") as f:
        f.write("global\tchapter\tchapter_page\n")
        for g, ch, cp in page_index_rows:
            f.write(f"{g}\t{ch}\t{cp}\n")
    print(f"✓ Wrote {idx_path} ({len(page_index_rows)} rows)")

if __name__ == "__main__":
    main()
