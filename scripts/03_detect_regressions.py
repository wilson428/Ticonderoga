#!/usr/bin/env python3

"""Detect likely manuscript regressions between two Git branches.

This script focuses on two high-value checks:
1) Duplicate long paragraphs in the target branch that are not duplicated in source.
2) Likely OCR regressions in target-only lines that are very close to source lines.

Default comparison is cleaning -> revision for:
manuscript/believe_in_me.md
"""

from __future__ import annotations

import argparse
import difflib
import re
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass


DEFAULT_FILE = "manuscript/believe_in_me.md"


def run_git_show(branch: str, file_path: str) -> str:
    try:
        result = subprocess.run(
            ["git", "show", f"{branch}:{file_path}"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        raise RuntimeError(f"Unable to read {branch}:{file_path}. {stderr}") from exc


def normalize_para(text: str) -> str:
    lowered = text.lower()
    lowered = re.sub(r"\s+", " ", lowered).strip()
    lowered = re.sub(r"[^a-z0-9 ]+", "", lowered)
    return lowered


def split_paragraphs_with_lines(text: str):
    paragraphs = []
    lines = text.splitlines()
    start = None
    buffer = []

    for idx, line in enumerate(lines, start=1):
        if line.strip():
            if start is None:
                start = idx
            buffer.append(line)
        else:
            if buffer:
                paragraphs.append((start, "\n".join(buffer).strip()))
                start = None
                buffer = []

    if buffer:
        paragraphs.append((start, "\n".join(buffer).strip()))

    return paragraphs


def suspicious_token(token: str) -> bool:
    # Example: "coursesz-It's" (hyphen followed by uppercase mid-token)
    if re.search(r"[a-z]-[A-Z]", token):
        return True
    # Example: "emporiuum" (three vowels in a row)
    if re.search(r"[aeiouy]{3,}", token, flags=re.IGNORECASE):
        return True
    # Any long punctuation+letter mashups are suspect in prose
    if len(token) >= 8 and re.search(r"[A-Za-z][^\w\s][A-Za-z]", token):
        return True
    return False


def token_diff(a: str, b: str):
    a_tokens = re.findall(r"[A-Za-z0-9'\-]+", a)
    b_tokens = re.findall(r"[A-Za-z0-9'\-]+", b)
    a_counts = Counter(a_tokens)
    b_counts = Counter(b_tokens)

    changed = []
    for token, count in b_counts.items():
        if count > a_counts[token]:
            changed.append(token)
    return changed


def detect_suspicious_branch_only_tokens(source_text: str, target_text: str):
    token_pattern = re.compile(r"[A-Za-z0-9'\-]+")

    source_vocab = set(token_pattern.findall(source_text))
    hits = []

    for idx, line in enumerate(target_text.splitlines(), start=1):
        tokens = token_pattern.findall(line)
        flagged = []
        for token in tokens:
            if token in source_vocab:
                continue
            if suspicious_token(token):
                flagged.append(token)

        if flagged:
            hits.append((idx, sorted(set(flagged)), line.strip()))

    return hits


@dataclass
class RegressionHit:
    line_no: int
    target_line: str
    source_line: str
    score: float
    tokens: list[str]


def detect_line_regressions(source_text: str, target_text: str, min_len: int, cutoff: float):
    source_lines = [ln for ln in source_text.splitlines() if ln.strip()]
    source_set = set(source_lines)
    target_lines = target_text.splitlines()

    hits = []
    for idx, line in enumerate(target_lines, start=1):
        stripped = line.strip()
        if len(stripped) < min_len:
            continue
        if stripped in source_set:
            continue

        matches = difflib.get_close_matches(stripped, source_lines, n=1, cutoff=cutoff)
        if not matches:
            continue

        source_line = matches[0]
        score = difflib.SequenceMatcher(None, stripped, source_line).ratio()
        changed_tokens = token_diff(source_line, stripped)
        flagged_tokens = [t for t in changed_tokens if suspicious_token(t)]
        if not flagged_tokens:
            continue

        hits.append(
            RegressionHit(
                line_no=idx,
                target_line=stripped,
                source_line=source_line,
                score=score,
                tokens=sorted(set(flagged_tokens)),
            )
        )

    return hits


def detect_duplicate_paragraphs(source_text: str, target_text: str, min_chars: int):
    source_paras = split_paragraphs_with_lines(source_text)
    target_paras = split_paragraphs_with_lines(target_text)

    source_counts = Counter()
    target_entries = defaultdict(list)

    for _line_no, para in source_paras:
        if len(para) >= min_chars:
            source_counts[normalize_para(para)] += 1

    for line_no, para in target_paras:
        if len(para) >= min_chars:
            target_entries[normalize_para(para)].append((line_no, para))

    duplicates = []
    for key, entries in target_entries.items():
        if len(entries) <= 1:
            continue
        if source_counts[key] >= len(entries):
            continue
        duplicates.append(entries)

    return duplicates


def main() -> int:
    parser = argparse.ArgumentParser(description="Detect likely OCR regressions between branches.")
    parser.add_argument("--source", default="cleaning", help="Source branch (expected-good)")
    parser.add_argument("--target", default="revision", help="Target branch (to inspect)")
    parser.add_argument("--file", default=DEFAULT_FILE, help="Path to manuscript file")
    parser.add_argument("--line-cutoff", type=float, default=0.92, help="Similarity cutoff for line matching")
    parser.add_argument("--min-line-len", type=int, default=45, help="Minimum line length to inspect")
    parser.add_argument("--min-para-len", type=int, default=220, help="Minimum paragraph chars for duplicate check")
    args = parser.parse_args()

    try:
        source_text = run_git_show(args.source, args.file)
        target_text = run_git_show(args.target, args.file)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    line_hits = detect_line_regressions(
        source_text=source_text,
        target_text=target_text,
        min_len=args.min_line_len,
        cutoff=args.line_cutoff,
    )
    token_hits = detect_suspicious_branch_only_tokens(source_text, target_text)
    para_hits = detect_duplicate_paragraphs(
        source_text=source_text,
        target_text=target_text,
        min_chars=args.min_para_len,
    )

    print(f"Scan: {args.source} -> {args.target}")
    print(f"File: {args.file}")
    print()

    if line_hits:
        print("Likely OCR regressions (target-only near-match lines):")
        for hit in line_hits:
            print(f"- line {hit.line_no} | score={hit.score:.3f} | tokens={', '.join(hit.tokens)}")
            print(f"  target: {hit.target_line}")
            print(f"  source: {hit.source_line}")
        print()
    else:
        print("Likely OCR regressions: none")
        print()

    if token_hits:
        print("Suspicious target-only tokens (not in source vocab):")
        for line_no, tokens, line in token_hits:
            print(f"- line {line_no} | tokens={', '.join(tokens)}")
            print(f"  text: {line}")
        print()
    else:
        print("Suspicious target-only tokens: none")
        print()

    if para_hits:
        print("Duplicate long paragraphs in target not duplicated in source:")
        for entries in para_hits:
            line_list = ", ".join(str(line_no) for line_no, _ in entries)
            sample = entries[0][1].replace("\n", " ")
            if len(sample) > 180:
                sample = sample[:180] + "..."
            print(f"- lines {line_list}")
            print(f"  sample: {sample}")
        print()
    else:
        print("Duplicate long paragraphs: none")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
