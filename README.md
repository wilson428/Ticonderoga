<<<<<<< Updated upstream
# believe-in-me
A novel
=======
# Believe in Me
A novel manuscript with custom Obsidian tooling

## Document Format

### Marginalia (Editorial Notes)
- **HTML comments**: `<!-- note text -->` — Displays in left margin in Live Preview
- **Inline highlights**: `==text=={note}` — Highlights text + margin note
- Both formats hide the syntax and render cleanly

### Chapter Numbering
- **Placeholder format**: `## {N}: Chapter Title`
- **Live Preview**: Displays actual sequential number (1, 2, 3...)
- **Source file**: Remains unchanged with `{N}` variable
- **Export**: Use command "Renumber chapters (for export)" to create numbered version

### Structure
- Chapters numbered sequentially across entire text (no reset between parts)
- Part divisions: `PART ONE`, `PART TWO`, etc.
- Page markers: `[[[PAGE nnnn CH=Part_nn CP=nnnn]]]`

## Bigfootnote Plugin

Custom Obsidian plugin (`.obsidian/plugins/bigfootnote/`) providing:

### Editorial Features
- **Margin notes**: Comments display in left margin while editing
- **Highlight annotations**: Inline highlights with associated notes
- **Chapter numbering**: Auto-displays sequential chapter numbers from `{N}` placeholders

### Git Workflow
- **Branch switching**: Toggle between `cleaning` and `revision` branches
- **Auto-commit**: Optional auto-commit when switching branches
- **Smart commit messages**: Generates descriptive messages from git diff stats
- **Status bar**: Shows current branch

### Commands
- `Git: Toggle cleaning/revision` — Switch between branches
- `Git: Switch to cleaning branch` — Direct switch
- `Git: Switch to revision branch` — Direct switch
- `Renumber chapters (for export)` — Creates `_numbered.md` with actual chapter numbers
- `Analytics: Visualize part lengths` — Wordcount bars by part, segmented by chapter where present

## Publishing Workflow

1. **Edit with placeholders**: Use `{N}` for chapter numbers during editing
2. **Export command**: Run "Renumber chapters (for export)" on your file
3. **Output**: Creates `filename_numbered.md` with actual numbers
4. **PDF generation**: Use numbered version, strip `<!-- comments -->` if needed
5. **Source preservation**: Original files keep `{N}` placeholders for continued editing

## Part-By-Part Publishing

For "discreet" exports by PART heading (`# PART I: ...`, `# PART II: ...`), use:

`scripts/04_export_part.py`

It does all of the following in one pass:
- Extracts one PART section from `manuscript/believe_in_me.md`
- Hides marginalia by default:
	- removes HTML comments like `<!-- page:0001:01 -->`
	- converts `==text=={note}` to plain `text`
- Bakes chapter numbers by replacing `## {N}: Title` with `## 1: Title`, `## 2: Title`, etc.
- Writes clean Markdown, with optional PDF and EPUB rendering through Pandoc

Safety/assumptions:
- The source manuscript is never modified by this workflow.
- Exports are written only to `build/publish/`.
- This workflow assumes you're already on the correct branch (for you: `revision`).

### Part I examples

Markdown only:

```bash
python3 scripts/04_export_part.py --part I --formats md
```

Markdown + PDF:

```bash
python3 scripts/04_export_part.py --part I --formats md,pdf
```

Markdown + EPUB:

```bash
python3 scripts/04_export_part.py --part I --formats md,epub
```

All three:

```bash
python3 scripts/04_export_part.py --part I --formats md,pdf,epub
```

One-command wrapper (defaults to PART I + md,pdf,epub):

```bash
./scripts/publish_part.sh
```

Obsidian command palette options (Bigfootnote plugin):
- `Publish: Export PART(s) (md/pdf/epub)`
- `Publish: Dry-run PART export`

Both commands open a text box where you can enter parts as comma-delimited values, for example:

```text
I,II,III
```

Specific PART and formats:

```bash
./scripts/publish_part.sh II md,epub
```

Dry run (no files written):

```bash
./scripts/publish_part.sh I md,pdf --dry-run
```

2-up landscape handout PDF (separate output file):

```bash
./scripts/publish_part.sh I pdf --two-up
```

This writes `build/publish/part_i_2up.pdf` and does not overwrite `build/publish/part_i.pdf`.

Output files are written to `build/publish/` by default:
- `build/publish/part_i.md`
- `build/publish/part_i.pdf` (if requested)
- `build/publish/part_i.epub` (if requested)

Notes:
- PDF and EPUB generation requires `pandoc` on your PATH.
- PDF additionally needs a PDF engine. Example on macOS: `brew install tectonic` then add `--pdf-engine tectonic`.
- PDF exports use a light typography preset by default (1in margins, 11pt, relaxed line spacing). Use `--plain-pdf` to disable it.
- If you want to preserve comments or inline marginalia syntax, add:
	- `--keep-html-comments`
	- `--keep-inline-marginalia`
>>>>>>> Stashed changes
