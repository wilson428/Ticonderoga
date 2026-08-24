#!/usr/bin/env python3

"""
Pre-compute chapter metadata for all parts in the manuscript.
Generates a JSON file mapping each PART to its chapter count and starting chapter number.
This enables:
1. Each part to be exported with correct chapter numbers even in isolation
2. Combined exports to accumulate chapter numbers correctly
"""

from __future__ import annotations

import json
import pathlib
import re
import sys


PART_HEADING_RE = re.compile(
    r"^#\s+(?:PART|Part)\s+([IVXLCDM]+)\s*:\s*(.+?)\s*$",
    flags=re.IGNORECASE | re.MULTILINE,
)
CHAPTER_HEADING_RE = re.compile(r"^##\s+\{N\}\s*:\s*.+$", flags=re.MULTILINE)


def roman_to_int(s: str) -> int:
    """Convert Roman numeral to integer for sorting."""
    values = {'I': 1, 'V': 5, 'X': 10, 'L': 50, 'C': 100, 'D': 500, 'M': 1000}
    total = 0
    prev_val = 0
    for char in reversed(s.upper()):
        val = values.get(char, 0)
        if val < prev_val:
            total -= val
        else:
            total += val
        prev_val = val
    return total


def find_parts(text: str) -> list[tuple[str, str, int, int]]:
    """Returns [(roman, title, start, end), ...]"""
    matches = list(PART_HEADING_RE.finditer(text))
    parts = []
    for idx, match in enumerate(matches):
        start = match.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        parts.append((match.group(1).upper(), match.group(2).strip(), start, end))
    return parts


def count_chapters_in_range(text: str, start: int, end: int) -> int:
    """Count chapter headings in text[start:end]"""
    section = text[start:end]
    return len(CHAPTER_HEADING_RE.findall(section))


def compute_chapter_metadata(input_path: pathlib.Path) -> dict:
    """Returns {
        'parts': {
            'I': {'title': '...', 'chapter_count': 8, 'chapter_start': 1},
            'II': {'title': '...', 'chapter_count': 9, 'chapter_start': 9},
            ...
        },
        'total_chapters': 127
    }"""
    
    raw = input_path.read_text(encoding="utf-8")
    
    # Strip YAML front matter if present
    if raw.startswith("---\n"):
        end = raw.find("\n---\n", 4)
        if end != -1:
            raw = raw[end + 5:]
    
    parts = find_parts(raw)
    if not parts:
        raise ValueError("No PART headings found in manuscript")
    
    metadata = {
        'parts': {},
        'total_chapters': 0
    }
    
    current_chapter = 1
    for roman, title, start, end in parts:
        chapter_count = count_chapters_in_range(raw, start, end)
        metadata['parts'][roman] = {
            'title': title,
            'chapter_count': chapter_count,
            'chapter_start': current_chapter
        }
        metadata['total_chapters'] += chapter_count
        current_chapter += chapter_count
    
    return metadata


def main() -> int:
    parser_help = """
Compute chapter metadata for manuscript PART exports.
Generates 'chapter_metadata.json' in project root with chapter start/count for each part.
    """
    
    if len(sys.argv) > 1 and sys.argv[1] in ['-h', '--help']:
        print(parser_help)
        return 0
    
    input_path = pathlib.Path("manuscript/believe_in_me.md")
    if not input_path.exists():
        print(f"ERROR: manuscript not found at {input_path}", file=sys.stderr)
        return 2
    
    try:
        metadata = compute_chapter_metadata(input_path)
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    
    output_path = pathlib.Path("chapter_metadata.json")
    output_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    
    print(f"✓ Generated {output_path}")
    print(f"Total chapters: {metadata['total_chapters']}")
    for roman in sorted(metadata['parts'].keys(), key=roman_to_int):
        p = metadata['parts'][roman]
        chapter_end = p['chapter_start'] + p['chapter_count'] - 1 if p['chapter_count'] > 0 else p['chapter_start']
        print(f"  PART {roman} ({p['title'][:30]}...): chapters {p['chapter_start']}-{chapter_end}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
