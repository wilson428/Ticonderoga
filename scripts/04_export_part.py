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
import zipfile
from xml.sax.saxutils import escape as xml_escape
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


@dataclass
class ChapterSpan:
    number: int          # global 1-based chapter number
    title: str
    start: int           # segment start (includes any PART heading(s) immediately preceding)
    end: int
    part_roman: str      # part that contains the chapter


def find_chapter_spans(text: str, parts: list[PartBlock]) -> list[ChapterSpan]:
    """Split the manuscript into globally numbered chapter segments.

    A PART heading that sits between two chapters is attached to the start of the
    following chapter, so selecting that chapter pulls the part header with it.
    """
    matches = list(CHAPTER_PLACEHOLDER_RE.finditer(text))
    starts: list[int] = []
    prev_chapter_start = -1
    for m in matches:
        seg_start = m.start()
        for part in parts:
            if prev_chapter_start < part.start < m.start():
                seg_start = min(seg_start, part.start)
        starts.append(seg_start)
        prev_chapter_start = m.start()

    spans: list[ChapterSpan] = []
    for idx, m in enumerate(matches):
        end = starts[idx + 1] if idx + 1 < len(matches) else len(text)
        owner = ""
        for part in parts:
            if part.start < m.start():
                owner = part.roman
        title = m.group(2).lstrip(":").strip()
        spans.append(ChapterSpan(idx + 1, title, starts[idx], end, owner))
    return spans


def parse_chapter_range(spec: str, total: int) -> tuple[int, int]:
    token = spec.strip().lower().replace("\u2013", "-").replace("\u2014", "-")
    token = re.sub(r"^chapters?\s+", "", token)
    m = re.fullmatch(r"(\d+)\s*(?:-\s*(\d+))?", token)
    if not m:
        raise ValueError(f"invalid chapter range '{spec}' (use e.g. 1-50 or 12)")
    first = int(m.group(1))
    last = int(m.group(2)) if m.group(2) else first
    if first > last:
        raise ValueError(f"range start {first} is after end {last}")
    if first < 1 or last > total:
        raise ValueError(f"range {first}-{last} outside available chapters 1-{total}")
    return first, last


def make_agent_friendly(text: str) -> str:
    """Prefix chapter headings with the word 'Chapter' for standard manuscript format."""
    text = re.sub(r"^(##\s*)(\d+)(:\s*.+)$", r"\1Chapter \2\3", text, flags=re.MULTILINE)
    return text.replace("\u00a0", " ")


def latex_escape(value: str) -> str:
    out = value.replace("\\", r"\textbackslash{}")
    for ch in "&%$#_{}":
        out = out.replace(ch, "\\" + ch)
    return out.replace("~", r"\textasciitilde{}").replace("^", r"\textasciicircum{}")


def count_words(text: str) -> int:
    return len(re.findall(r"\S+", re.sub(r"^#+\s.*$", "", text, flags=re.MULTILINE)))


def build_manuscript_title_page(meta: dict[str, str], scope_label: str, words: int) -> str:
    """Standard submission title page: contact top-left, word count top-right, title centered."""
    contact = [meta.get("author", "")]
    for key in ("address", "phone", "email"):
        if meta.get(key):
            contact.append(meta[key])
    left = r"\\".join(latex_escape(c) for c in contact if c)
    rounded = int(round(words, -2)) if words >= 1000 else words
    right = r"\\".join(
        [latex_escape(f"approx. {rounded:,} words"), latex_escape(scope_label)]
        + ([latex_escape(meta["genre"])] if meta.get("genre") else [])
    )
    title = latex_escape(meta.get("title", "").upper())
    author = latex_escape(meta.get("author", ""))
    return "\n".join([
        "```{=latex}",
        r"\thispagestyle{empty}",
        r"\begin{singlespace}",
        r"\noindent\begin{minipage}[t]{0.5\textwidth}\raggedright " + left + r"\end{minipage}\hfill",
        r"\begin{minipage}[t]{0.45\textwidth}\raggedleft " + right + r"\end{minipage}",
        r"\vspace*{0.22\textheight}",
        r"\begin{center}",
        r"{\large\bfseries " + title + r"\par}",
        r"\vspace{1em}",
        r"by " + author,
        r"\end{center}",
        r"\end{singlespace}",
        r"\clearpage",
        r"\setcounter{page}{1}",
        "```",
        "",
        "",
    ])


def manuscript_pdf_header_includes(meta: dict[str, str]) -> list[str]:
    surname = (meta.get("author", "").split() or [""])[-1]
    running = latex_escape(f"{surname} / {meta.get('title', '').upper()}")
    return [
        r"\usepackage{setspace}\doublespacing",
        r"\usepackage{etoolbox}\AtBeginEnvironment{quote}{\singlespacing}",
        r"\usepackage{indentfirst}\setlength{\parindent}{0.5in}\setlength{\parskip}{0pt}",
        r"\usepackage{fancyhdr}\pagestyle{fancy}\fancyhf{}\renewcommand{\headrulewidth}{0pt}"
        + rf"\rhead{{{running} / \thepage}}",
        r"\usepackage{titlesec}\newcommand{\sectionbreak}{\clearpage}",
        r"\titleformat{\section}[display]{\centering\bfseries\large}{}{0pt}{\vspace*{0.3\textheight}}",
        r"\titleformat{\subsection}[display]{\centering\bfseries}{}{0pt}{}",
        r"\titlespacing*{\section}{0pt}{0pt}{2em}\titlespacing*{\subsection}{0pt}{2em}{1em}",
        r"\renewcommand{\maketitle}{}",
    ]


_INLINE_RE = re.compile(r"(\*\*.+?\*\*|(?<![\w\\])_.+?_(?!\w)|\*.+?\*|\\.)")


def _runs(text: str, bold: bool = False, italic: bool = False, size: int = 24) -> str:
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    out: list[str] = []
    pos = 0
    for m in _INLINE_RE.finditer(text):
        out.append(_run(text[pos : m.start()], bold, italic, size))
        tok = m.group(0)
        if tok.startswith("\\"):
            out.append(_run(tok[1:], bold, italic, size))
        elif tok.startswith("**"):
            out.append(_runs(tok[2:-2], True, italic, size))
        else:
            out.append(_runs(tok[1:-1], bold, True, size))
        pos = m.end()
    out.append(_run(text[pos:], bold, italic, size))
    return "".join(out)


_FONT_XML = '<w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" w:cs="Times New Roman" w:eastAsia="Times New Roman"/>'


def _run(text: str, bold: bool, italic: bool, size: int = 24) -> str:
    # Formatting is applied directly (not only via styles) so it survives viewers that ignore styles.xml.
    if not text:
        return ""
    props = _FONT_XML + ("<w:b/>" if bold else "") + ("<w:i/>" if italic else "") + f'<w:sz w:val="{size}"/><w:szCs w:val="{size}"/>'
    rpr = f"<w:rPr>{props}</w:rPr>"
    return f'<w:r>{rpr}<w:t xml:space="preserve">{xml_escape(text)}</w:t></w:r>'


def _para(inner: str, style: str | None = None, ppr_extra: str = "") -> str:
    ppr = (f'<w:pStyle w:val="{style}"/>' if style else "") + ppr_extra
    return f"<w:p><w:pPr>{ppr}</w:pPr>{inner}</w:p>" if ppr else f"<w:p>{inner}</w:p>"


_PPR_BODY = '<w:spacing w:after="0" w:line="480" w:lineRule="auto"/>'
_PAGE_BREAK = '<w:p><w:pPr><w:spacing w:before="0" w:after="0" w:line="240" w:lineRule="auto"/><w:ind w:firstLine="0"/></w:pPr><w:r><w:br w:type="page"/></w:r></w:p>'
_INDENT_RUN = "<w:r><w:tab/></w:r>"
_PPR_PART = '<w:keepNext/><w:spacing w:before="4320" w:after="480" w:line="240" w:lineRule="auto"/><w:ind w:firstLine="0"/><w:jc w:val="center"/>'
_PPR_CHAPTER = '<w:keepNext/><w:spacing w:before="480" w:after="240" w:line="240" w:lineRule="auto"/><w:ind w:firstLine="0"/><w:jc w:val="center"/>'
_PPR_QUOTE = '<w:spacing w:before="{before}" w:after="0" w:line="240" w:lineRule="auto"/><w:ind w:left="720" w:firstLine="0"/>'
_PPR_CENTER = '<w:spacing w:after="0" w:line="480" w:lineRule="auto"/><w:ind w:firstLine="0"/><w:jc w:val="center"/>'
_SPEAKER_RE = re.compile(r"^[A-Z0-9][A-Z0-9'\u2019 .\-]{1,30}(\s*\([^)]*\))?$")


def markdown_to_docx_body(content: str) -> str:
    body: list[str] = []
    buf: list[str] = []

    def flush() -> None:
        if buf:
            body.append(_para(_INDENT_RUN + _runs(" ".join(l.strip() for l in buf)), None, _PPR_BODY))
            buf.clear()

    for line in content.splitlines():
        stripped = line.strip()
        if not stripped:
            flush()
        elif re.match(r"^#\s+\S", stripped):
            flush()
            body.append(_PAGE_BREAK)
            body.append(_para(_runs(re.sub(r"^#\s+", "", stripped), True, False, 28), "Heading1", _PPR_PART))
        elif re.match(r"^##\s+\S", stripped):
            flush()
            body.append(_para(_runs(re.sub(r"^##\s+", "", stripped), True, False, 24), "Heading2", _PPR_CHAPTER))
        elif stripped.startswith(">"):
            flush()
            qtext = stripped.lstrip("> ").strip()
            before = 200 if _SPEAKER_RE.match(qtext) else 0
            body.append(_para(_runs(qtext), "Quote", _PPR_QUOTE.format(before=before)))
        elif re.fullmatch(r"(\*\s*){3,}|(-\s*){3,}|(_\s*){3,}", stripped):
            flush()
            body.append(_para(_run("#", False, False), "SceneBreak", _PPR_CENTER))
        else:
            buf.append(line)
    flush()
    return "".join(body)


def write_manuscript_docx(content: str, meta: dict[str, str], scope_label: str, words: int, out_path: pathlib.Path) -> None:
    """Write a standard-manuscript-format .docx with no external dependencies."""
    author = meta.get("author", "")
    title = meta.get("title", "")
    surname = (author.split() or [""])[-1]
    contact = [author] + [meta[k] for k in ("address", "phone", "email") if meta.get(k)]
    rounded = int(round(words, -2)) if words >= 1000 else words
    right = [f"approx. {rounded:,} words", scope_label] + ([meta["genre"]] if meta.get("genre") else [])
    rows = max(len(contact), len(right))
    title_page: list[str] = []
    for i in range(rows):
        l = contact[i] if i < len(contact) else ""
        r = right[i] if i < len(right) else ""
        inner = _run(l, False, False) + "<w:r><w:tab/></w:r>" + _run(r, False, False)
        title_page.append(_para(inner, "TitlePageLine", '<w:tabs><w:tab w:val="right" w:pos="9360"/></w:tabs><w:spacing w:after="0" w:line="240" w:lineRule="auto"/><w:ind w:firstLine="0"/>'))
    title_page.append(_para(_run(title.upper(), True, False, 28), "TitlePageTitle", '<w:spacing w:before="3600" w:after="240" w:line="240" w:lineRule="auto"/><w:ind w:firstLine="0"/><w:jc w:val="center"/>'))
    # Section break: title page has no header; the body restarts page numbering at 1.
    title_page.append(
        '<w:p><w:pPr><w:sectPr><w:pgSz w:w="12240" w:h="15840"/>'
        '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" w:header="720" w:footer="720" w:gutter="0"/>'
        "</w:sectPr></w:pPr></w:p>"
    )
    by = _para(_run(f"by {author}", False, False), "TitlePageBy", '<w:spacing w:after="0" w:line="240" w:lineRule="auto"/><w:ind w:firstLine="0"/><w:jc w:val="center"/>')
    # "by" line belongs under the title, before the section break
    title_page.insert(len(title_page) - 1, by)

    final_sect = (
        '<w:sectPr><w:headerReference w:type="default" r:id="rId3"/>'
        '<w:pgSz w:w="12240" w:h="15840"/>'
        '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" w:header="720" w:footer="720" w:gutter="0"/>'
        '<w:pgNumType w:start="1"/></w:sectPr>'
    )
    ns = (
        'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    )
    document = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document {ns}><w:body>'
        + "".join(title_page)
        + markdown_to_docx_body(content)
        + final_sect
        + "</w:body></w:document>"
    )

    font = '<w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" w:cs="Times New Roman" w:eastAsia="Times New Roman"/>'
    def style(sid: str, name: str, ppr: str, rpr: str = "", based: str = "Normal") -> str:
        return (
            f'<w:style w:type="paragraph" w:styleId="{sid}"><w:name w:val="{name}"/><w:basedOn w:val="{based}"/>'
            f"<w:qFormat/><w:pPr>{ppr}</w:pPr><w:rPr>{rpr}</w:rPr></w:style>"
        )
    styles = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:styles {ns}>'
        f'<w:docDefaults><w:rPrDefault><w:rPr>{font}<w:sz w:val="24"/><w:szCs w:val="24"/><w:lang w:val="en-US"/></w:rPr></w:rPrDefault>'
        '<w:pPrDefault><w:pPr><w:spacing w:after="0" w:line="480" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>'
        '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/>'
        '<w:pPr><w:ind w:firstLine="720"/></w:pPr></w:style>'
        + style("Heading1", "heading 1", '<w:keepNext/><w:spacing w:before="4320" w:after="480" w:line="240" w:lineRule="auto"/><w:ind w:firstLine="0"/><w:jc w:val="center"/><w:outlineLvl w:val="0"/>', "<w:b/><w:sz w:val=\"28\"/>")
        + style("Heading2", "heading 2", '<w:keepNext/><w:spacing w:before="480" w:after="240" w:line="240" w:lineRule="auto"/><w:ind w:firstLine="0"/><w:jc w:val="center"/><w:outlineLvl w:val="1"/>', "<w:b/>")
        + style("Quote", "Quote", '<w:spacing w:line="240" w:lineRule="auto"/><w:ind w:left="720" w:firstLine="0"/>')
        + style("SceneBreak", "Scene Break", '<w:ind w:firstLine="0"/><w:jc w:val="center"/>')
        + style("TitlePageLine", "Title Page Line", '<w:tabs><w:tab w:val="right" w:pos="9360"/></w:tabs><w:spacing w:line="240" w:lineRule="auto"/><w:ind w:firstLine="0"/>')
        + style("TitlePageTitle", "Title Page Title", '<w:spacing w:before="3600" w:after="240" w:line="240" w:lineRule="auto"/><w:ind w:firstLine="0"/><w:jc w:val="center"/>', "<w:b/><w:sz w:val=\"28\"/>")
        + style("TitlePageBy", "Title Page By", '<w:spacing w:line="240" w:lineRule="auto"/><w:ind w:firstLine="0"/><w:jc w:val="center"/>')
        + style("Header", "header", '<w:spacing w:line="240" w:lineRule="auto"/><w:ind w:firstLine="0"/><w:jc w:val="right"/>')
        + "</w:styles>"
    )
    rp = f"<w:rPr>{_FONT_XML}<w:sz w:val=\"24\"/></w:rPr>"
    running = xml_escape(f"{surname} / {title.upper()} / ")
    header = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:hdr {ns}><w:p><w:pPr><w:pStyle w:val="Header"/><w:spacing w:after="0" w:line="240" w:lineRule="auto"/><w:ind w:firstLine="0"/><w:jc w:val="right"/></w:pPr>'
        f'<w:r>{rp}<w:t xml:space="preserve">{running}</w:t></w:r>'
        f'<w:r>{rp}<w:fldChar w:fldCharType="begin"/></w:r><w:r>{rp}<w:instrText xml:space="preserve"> PAGE </w:instrText></w:r>'
        f'<w:r>{rp}<w:fldChar w:fldCharType="separate"/></w:r><w:r>{rp}<w:t>1</w:t></w:r><w:r>{rp}<w:fldChar w:fldCharType="end"/></w:r>'
        "</w:p></w:hdr>"
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
        '<Override PartName="/word/header1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"/>'
        "</Types>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        "</Relationships>"
    )
    doc_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
        '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/header" Target="header1.xml"/>'
        "</Relationships>"
    )
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("word/document.xml", document)
        zf.writestr("word/styles.xml", styles)
        zf.writestr("word/header1.xml", header)
        zf.writestr("word/_rels/document.xml.rels", doc_rels)


def run_pandoc_manuscript(input_md: pathlib.Path, output_pdf: pathlib.Path, pdf_engine: str | None, meta: dict[str, str]) -> None:
    if shutil.which("pandoc") is None:
        raise RuntimeError("pandoc is not installed. Install pandoc to render pdf.")
    cmd = ["pandoc", str(input_md), "-o", str(output_pdf), "-f", "markdown"]
    if pdf_engine:
        cmd.extend(["--pdf-engine", pdf_engine])
    cmd.extend(["-V", "geometry:margin=1in", "-V", "fontsize=12pt", "-V", "mainfont=TeX Gyre Termes"])
    for line in manuscript_pdf_header_includes(meta):
        cmd.extend(["-V", f"header-includes={line}"])
    subprocess.run(cmd, check=True)


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


def build_title_page(book_title: str, author: str, parts_label: str, output_format: str, label_prefix: str = "Parts") -> str:
    exported_on = datetime.datetime.now().strftime("%Y-%m-%d")
    if output_format == "epub":
        lines = [
            '<div style="text-align: center; margin-top: 28vh;">',
            "",
            f"# {book_title}",
            "",
            f"## By {author}",
            "",
            f"### {label_prefix} {parts_label}, exported {exported_on}",
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
        rf"{{\large {label_prefix} {parts_label}, exported {exported_on}\par}}",
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
        default=None,
        help="PART selector, e.g. I, II, III, or 'PART I' (ignored if --chapters is given)",
    )
    parser.add_argument(
        "--chapters",
        default=None,
        help="Chapter range to export, e.g. 1-50 or 12. PART headings inside the range are kept.",
    )
    parser.add_argument(
        "--agent-friendly",
        action="store_true",
        help="Standard literary-agent manuscript format: title page, 12pt serif, double-spaced, 1in margins, running header, chapters start on new pages (PDF)",
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

    range_mode = bool(args.chapters)
    if not range_mode and not args.part:
        print("ERROR: provide --part or --chapters", file=sys.stderr)
        return 2

    chapter_first = chapter_last = 0
    included_parts: list[str] = []
    if range_mode:
        spans = find_chapter_spans(raw, parts)
        try:
            chapter_first, chapter_last = parse_chapter_range(args.chapters, len(spans))
        except ValueError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        selected = spans[chapter_first - 1 : chapter_last]
        content = raw[selected[0].start : selected[-1].end]
        seg_lo, seg_hi = selected[0].start, selected[-1].end
        included_parts = [p.roman for p in parts if seg_lo <= p.start < seg_hi]
        part = PartBlock(
            roman=selected[0].part_roman,
            title=f"Chapters {chapter_first}-{chapter_last}",
            start=seg_lo,
            end=seg_hi,
        )
        html_comment_count = count_html_comments(content)
        inline_marginalia_count = count_inline_marginalia(content)
        chapter_placeholder_count = count_chapter_placeholders(content)
    else:
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
    content = renumber_chapters(content, start_at=chapter_first if range_mode else args.chapter_start)
    content = normalize_heading_spacing(content)
    content = expand_single_line_paragraphs(content)
    content = collapse_blank_lines(content)
    if args.agent_friendly:
        content = collapse_blank_lines(make_agent_friendly(content))

    book_title = export_metadata.get("title", args.book_title)
    author_name = export_metadata.get("author", "Chris Wilson")

    if args.agent_friendly:
        front_matter = ""
        args.toc = False
        args.title_page = False
        if not ({f.strip().lower() for f in args.formats.split(",")} & {"pdf", "docx"}):
            args.formats = "pdf"
        scope_label = (
            (f"Chapters {chapter_first}\u2013{chapter_last}" if chapter_first != chapter_last else f"Chapter {chapter_first}")
            if range_mode
            else f"Part {part.roman}"
        )
        mm = dict(export_metadata)
        mm.setdefault("title", book_title)
        mm.setdefault("author", author_name)
        title_page = build_manuscript_title_page(mm, scope_label + " (excerpt)", count_words(content))
    elif range_mode:
        front_matter = build_front_matter(book_title, part.roman, part.title, input_path)
    else:
        front_matter = build_front_matter(book_title, part.roman, part.title, input_path)
    if not args.agent_friendly:
        title_page = ""
    if args.title_page:
        parts_label = args.parts_label or (f"{chapter_first}\u2013{chapter_last}" if range_mode else part.roman)
        requested_formats = {fmt.strip().lower() for fmt in args.formats.split(",") if fmt.strip()}
        title_page_format = "epub" if requested_formats == {"epub"} else "pdf"
        title_page = build_title_page(book_title, author_name, parts_label, title_page_format, "Chapters" if range_mode else "Parts")

    exported_markdown = front_matter + title_page + content

    output_dir = pathlib.Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if range_mode:
        part_slug = f"chapters_{chapter_first}-{chapter_last}" + ("_agent" if args.agent_friendly else "")
    else:
        part_slug = f"part_{part.roman.lower()}" + ("_agent" if args.agent_friendly else "")
    md_path = output_dir / f"{part_slug}.md"

    requested = {fmt.strip().lower() for fmt in args.formats.split(",") if fmt.strip()}
    valid = {"md", "pdf", "epub", "docx"}
    unknown = requested - valid
    if "docx" in requested and not args.agent_friendly:
        print("ERROR: docx output is only available with --agent-friendly", file=sys.stderr)
        return 2
    if unknown:
        print(f"ERROR: unknown format(s): {', '.join(sorted(unknown))}", file=sys.stderr)
        return 2

    if args.dry_run:
        print("dry run: no files written")
        print(f"part: PART {part.roman}: {part.title}")
        if range_mode:
            print(f"parts_included: {', '.join(included_parts)}")
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
            if args.agent_friendly and fmt == "docx":
                write_manuscript_docx(content, mm, scope_label + " (excerpt)", count_words(content), out_path)
                print(f"wrote {fmt}: {out_path}")
                continue
            if args.agent_friendly:
                run_pandoc_manuscript(md_path, out_path, args.pdf_engine, mm)
                print(f"wrote {fmt}: {out_path}")
                continue
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
