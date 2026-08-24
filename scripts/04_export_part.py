#!/usr/bin/env python3

"""Export a single PART from the manuscript for publishing.

Features:
- Extract one section denoted by "# PART [Roman]: [Title]"
- Remove editorial marginalia (HTML comments + ==text=={note})
- Renumber chapter headings from "## {N}: ..." to concrete numbers
- Write clean markdown and optionally render PDF/EPUB with pandoc
"""

from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Iterable


PART_HEADING_RE = re.compile(
    r"^#\s+PART\s+([IVXLCDM]+)\s*:\s*(.+?)\s*$",
    flags=re.IGNORECASE | re.MULTILINE,
)
INLINE_MARGINALIA_RE = re.compile(r"==(.+?)==\{[^\n{}]*\}")
CHAPTER_PLACEHOLDER_RE = re.compile(r"^(##\s*)\{N\}(:\s*.+)$", flags=re.MULTILINE)
END_PART_RE = re.compile(r"^\s*END\s+PART\s+[IVXLCDM]+\s*$", flags=re.IGNORECASE | re.MULTILINE)


@dataclass
class PartBlock:
    roman: str
    title: str
    start: int
    end: int


def find_parts(text: str) -> list[PartBlock]:
    matches = list(PART_HEADING_RE.finditer(text))
    parts: list[PartBlock] = []
    for idx, match in enumerate(matches):
        start = match.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        parts.append(
            PartBlock(
                roman=match.group(1).upper(),
                title=match.group(2).strip(),
                start=start,
                end=end,
            )
        )
    return parts


def normalize_part_selector(selector: str) -> str:
    token = selector.strip().upper()
    token = re.sub(r"^PART\s+", "", token)
    return token


def choose_part(parts: Iterable[PartBlock], selector: str) -> PartBlock:
    wanted = normalize_part_selector(selector)
    for part in parts:
        if part.roman == wanted:
            return part
    raise ValueError(f"PART '{selector}' not found")


def strip_yaml_front_matter(text: str) -> str:
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            return text[end + 5 :]
    return text


def strip_html_comments(text: str) -> str:
    # Remove comment blocks, including multiline comments.
    return re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)


def strip_inline_marginalia(text: str) -> str:
    # Keep the highlighted prose and remove only editorial note payload.
    while True:
        updated = INLINE_MARGINALIA_RE.sub(r"\1", text)
        if updated == text:
            return updated
        text = updated


def renumber_chapters(text: str, start_at: int) -> str:
    chapter_number = start_at - 1

    def _repl(match: re.Match[str]) -> str:
        nonlocal chapter_number
        chapter_number += 1
        return f"{match.group(1)}{chapter_number}{match.group(2)}"

    return CHAPTER_PLACEHOLDER_RE.sub(_repl, text)


def collapse_blank_lines(text: str) -> str:
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"


def normalize_heading_spacing(text: str) -> str:
    lines = text.splitlines()
    normalized: list[str] = []

    for line in lines:
        stripped = line.strip()
        is_heading = bool(re.match(r"^#{1,6}\s+\S", stripped))

        if is_heading:
            while normalized and normalized[-1] == "":
                normalized.pop()
            if normalized:
                normalized.append("")
            normalized.append(stripped)
            normalized.append("")
            continue

        normalized.append(line)

    return "\n".join(normalized)


def expand_single_line_paragraphs(text: str) -> str:
    lines = text.splitlines()
    expanded: list[str] = []

    for index, line in enumerate(lines):
        stripped = line.rstrip()
        if not stripped:
            expanded.append("")
            continue

        expanded.append(stripped)
        if index + 1 < len(lines) and lines[index + 1].strip():
            expanded.append("")

    return "\n".join(expanded)


def count_html_comments(text: str) -> int:
    return len(re.findall(r"<!--.*?-->", text, flags=re.DOTALL))


def count_inline_marginalia(text: str) -> int:
    return len(INLINE_MARGINALIA_RE.findall(text))


def count_chapter_placeholders(text: str) -> int:
    return len(CHAPTER_PLACEHOLDER_RE.findall(text))


def build_front_matter(book_title: str, part_roman: str, part_title: str, source_path: pathlib.Path) -> str:
    exported_at = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    lines = [
        f"<!-- export_title: {book_title} — Part {part_roman}: {part_title} -->",
        f"<!-- source_file: {source_path.as_posix()} -->",
        f"<!-- exported_at: {exported_at} -->",
        "",
    ]
    return "\n".join(lines)


def build_title_page(book_title: str, author: str, parts_label: str, output_format: str) -> str:
    exported_on = datetime.datetime.now().strftime("%Y-%m-%d")
    if output_format == "epub":
        lines = [
            '<div style="text-align: center; margin-top: 28vh;">',
            "",
            f"# {book_title}",
            "",
            f"## By {author}",
            "",
            f"### Parts {parts_label}, exported {exported_on}",
            "",
            "</div>",
            "",
            '<div style="page-break-after: always;"></div>',
            "",
        ]
        return "\n".join(lines)

    lines = [
        "```{=latex}",
        r"\thispagestyle{empty}",
        r"\vspace*{\fill}",
        r"\begin{center}",
        rf"{{\fontsize{{44}}{{52}}\selectfont\bfseries {book_title}\par}}",
        r"\vspace{1.5cm}",
        rf"{{\Large By {author}\par}}",
        r"\vspace{1cm}",
        rf"{{\large Parts {parts_label}, exported {exported_on}\par}}",
        r"\end{center}",
        r"\vspace*{\fill}",
        r"\newpage",
        "```",
        "",
    ]
    return "\n".join(lines)


def load_export_metadata(metadata_path: pathlib.Path) -> dict[str, str]:
    defaults = {
        "title": "Believe in Me",
        "author": "Chris Wilson",
    }
    if not metadata_path.exists():
        return defaults

    try:
        raw = metadata_path.read_text(encoding="utf-8")
        parsed = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return defaults

    if not isinstance(parsed, dict):
        return defaults

    merged = dict(defaults)
    for key, value in parsed.items():
        if isinstance(value, str) and value.strip():
            merged[key] = value.strip()
    return merged


def run_pandoc(
    input_md: pathlib.Path,
    output_file: pathlib.Path,
    fmt: str,
    pdf_engine: str | None,
    pretty_pdf: bool,
    metadata: dict[str, str],
    include_toc: bool,
    suppress_pdf_title_block: bool,
    pdf_font_size: str,
) -> None:
    if shutil.which("pandoc") is None:
        raise RuntimeError("pandoc is not installed. Install pandoc to render pdf/epub.")

    cmd = ["pandoc", str(input_md), "-o", str(output_file)]
    cmd.extend(["-f", "markdown"])

    for key, value in metadata.items():
        cmd.extend(["--metadata", f"{key}={value}"])

    if include_toc:
        cmd.extend(["--toc", "--toc-depth", "2"])

    if fmt == "epub":
        cmd.extend(["--standalone"])
    elif fmt == "pdf":
        requested_size = str(pdf_font_size).strip().lower()
        match = re.match(r"^(\d+(?:\.\d+)?)pt$", requested_size)
        if match:
            size_points = float(match.group(1))
            effective_size = f"{size_points:g}pt"
        else:
            size_points = 12.0
            effective_size = "12pt"

        class_option = effective_size if size_points in {10.0, 11.0, 12.0} else "12pt"
        line_height = f"{size_points * 1.2:.1f}pt"

        if pdf_engine:
            cmd.extend(["--pdf-engine", pdf_engine])
        if suppress_pdf_title_block:
            cmd.extend(["-V", r"header-includes=\renewcommand{\maketitle}{}"])
        if pretty_pdf:
            cmd.extend([
                "-V",
                "geometry:margin=1in",
                "-V",
                f"classoption={class_option}",
                "-V",
                fr"header-includes=\AtBeginDocument{{\fontsize{{{effective_size}}}{{{line_height}}}\selectfont}}",
                "-V",
                r"header-includes=\usepackage{newtxtext}",
                "-V",
                r"header-includes=\usepackage{etoolbox}",
                "-V",
                r"header-includes=\AtBeginEnvironment{quote}{\ttfamily\setlength{\parindent}{0pt}\setlength{\leftskip}{2em}}",
                "-V",
                r"header-includes=\usepackage{titlesec}",
                "-V",
                r"header-includes=\usepackage{indentfirst}",
                "-V",
                r"header-includes=\titleformat{\section}[display]{\centering\Large\bfseries}{}{0pt}{}",
                "-V",
                r"header-includes=\setlength{\parindent}{1.5em}",
                "-V",
                r"header-includes=\setlength{\parskip}{0.45em}",
            ])

    subprocess.run(cmd, check=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export one manuscript PART to publishable formats.")
    parser.add_argument(
        "--input",
        default="manuscript/believe_in_me.md",
        help="Path to full manuscript markdown",
    )
    parser.add_argument(
        "--part",
        required=True,
        help="PART selector, e.g. I, II, III, or 'PART I'",
    )
    parser.add_argument(
        "--output-dir",
        default="build/publish",
        help="Directory for generated files",
    )
    parser.add_argument(
        "--book-title",
        default="Believe in Me",
        help="Book title used in generated front matter",
    )
    parser.add_argument(
        "--metadata-json",
        default="metadata.json",
        help="Path to JSON file with export metadata for pandoc (title, author, language, etc.)",
    )
    parser.add_argument(
        "--formats",
        default="md",
        help="Comma-separated formats: md,pdf,epub",
    )
    parser.add_argument(
        "--chapter-start",
        type=int,
        default=1,
        help="Starting chapter number for this export",
    )
    parser.add_argument(
        "--title-page",
        action="store_true",
        help="Prepend a styled title page",
    )
    parser.add_argument(
        "--toc",
        action="store_true",
        help="Include table of contents in PDF/EPUB output",
    )
    parser.add_argument(
        "--font-size",
        default="12pt",
        help="PDF font size (for example: 11pt, 12pt, 13pt)",
    )
    parser.add_argument(
        "--parts-label",
        default=None,
        help="Label for title page parts line (for example: I or I-III)",
    )
    parser.add_argument(
        "--pdf-engine",
        default=None,
        help="Pandoc PDF engine (for example: pdflatex, tectonic, weasyprint, wkhtmltopdf)",
    )
    parser.add_argument(
        "--plain-pdf",
        action="store_true",
        help="Disable built-in PDF typography defaults",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be exported without writing files",
    )
    parser.add_argument(
        "--keep-html-comments",
        action="store_true",
        help="Keep HTML comments (default strips them)",
    )
    parser.add_argument(
        "--keep-inline-marginalia",
        action="store_true",
        help="Keep inline ==text=={note} syntax (default strips note payload)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    export_metadata = load_export_metadata(pathlib.Path(args.metadata_json))

    input_path = pathlib.Path(args.input)
    if not input_path.exists():
        print(f"ERROR: missing input file: {input_path}", file=sys.stderr)
        return 2

    raw = input_path.read_text(encoding="utf-8")
    raw = strip_yaml_front_matter(raw)

    parts = find_parts(raw)
    if not parts:
        print("ERROR: no PART headings found", file=sys.stderr)
        return 2

    try:
        part = choose_part(parts, args.part)
    except ValueError as exc:
        available = ", ".join(f"PART {p.roman}" for p in parts)
        print(f"ERROR: {exc}. Available: {available}", file=sys.stderr)
        return 2

    content = raw[part.start : part.end]

    html_comment_count = count_html_comments(content)
    inline_marginalia_count = count_inline_marginalia(content)
    chapter_placeholder_count = count_chapter_placeholders(content)

    if not args.keep_html_comments:
        content = strip_html_comments(content)
    if not args.keep_inline_marginalia:
        content = strip_inline_marginalia(content)

    content = END_PART_RE.sub("", content)
    content = renumber_chapters(content, start_at=args.chapter_start)
    content = normalize_heading_spacing(content)
    content = expand_single_line_paragraphs(content)
    content = collapse_blank_lines(content)

    book_title = export_metadata.get("title", args.book_title)
    author_name = export_metadata.get("author", "Chris Wilson")

    front_matter = build_front_matter(book_title, part.roman, part.title, input_path)
    title_page = ""
    if args.title_page:
        parts_label = args.parts_label or part.roman
        requested_formats = {fmt.strip().lower() for fmt in args.formats.split(",") if fmt.strip()}
        title_page_format = "epub" if requested_formats == {"epub"} else "pdf"
        title_page = build_title_page(book_title, author_name, parts_label, title_page_format)

    exported_markdown = front_matter + title_page + content

    output_dir = pathlib.Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    part_slug = f"part_{part.roman.lower()}"
    md_path = output_dir / f"{part_slug}.md"

    requested = {fmt.strip().lower() for fmt in args.formats.split(",") if fmt.strip()}
    valid = {"md", "pdf", "epub"}
    unknown = requested - valid
    if unknown:
        print(f"ERROR: unknown format(s): {', '.join(sorted(unknown))}", file=sys.stderr)
        return 2

    if args.dry_run:
        print("dry run: no files written")
        print(f"part: PART {part.roman}: {part.title}")
        print(f"input: {input_path}")
        print(f"output_dir: {output_dir}")
        print(f"formats: {', '.join(sorted(requested))}")
        print(f"chapters_to_renumber: {chapter_placeholder_count}")
        print(f"html_comments_to_strip: {0 if args.keep_html_comments else html_comment_count}")
        print(
            f"inline_marginalia_to_strip: {0 if args.keep_inline_marginalia else inline_marginalia_count}"
        )
        print(f"pdf_font_size: {args.font_size}")
        return 0

    md_path.write_text(exported_markdown, encoding="utf-8")
    print(f"wrote markdown: {md_path}")

    for fmt in sorted(requested - {"md"}):
        out_path = output_dir / f"{part_slug}.{fmt}"
        try:
            run_pandoc(
                md_path,
                out_path,
                fmt,
                args.pdf_engine,
                pretty_pdf=not args.plain_pdf,
                metadata=export_metadata,
                include_toc=args.toc,
                suppress_pdf_title_block=args.title_page,
                pdf_font_size=args.font_size,
            )
        except subprocess.CalledProcessError as exc:
            if fmt == "pdf":
                print(
                    "ERROR: pandoc PDF conversion failed. "
                    "Install a PDF engine (for example 'tectonic' or MacTeX), "
                    "or pass --pdf-engine with an installed engine.",
                    file=sys.stderr,
                )
            print(f"ERROR: pandoc failed for {fmt}: {exc}", file=sys.stderr)
            return 2
        except RuntimeError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        print(f"wrote {fmt}: {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
