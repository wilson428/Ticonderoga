# Ticonderoga / Believe in Me Repository Migration Handoff

This handoff describes the desired repository architecture and a safe, inspect-first migration plan for separating the novel manuscript from its supporting project infrastructure.

Do not run destructive commands, rewrite live history, force-push, delete branches/tags, change remotes, or move the canonical copy until the current repository state has been inspected and the proposed plan has been shown to Chris for approval.

## Target Architecture

The intended end state is three independent repositories:

```text
Ticonderoga       -> desktop workbench/supporting project
believe-in-me     -> portable novel-only repository
Bigfootnote       -> independent Obsidian plugin repository
```

No Git submodules are desired. These repositories may coexist on disk and may reference one another operationally, but Git does not need to encode their relationship through submodules.

## Repository Roles

### Ticonderoga

`Ticonderoga` is the independent parent/workbench repo. It should contain the supporting infrastructure for the novel, including:

- scans and OCR PDFs
- extracted OCR text
- build and publishing outputs
- scripts and notebooks
- metadata
- research notes, maps, timelines, and sources
- calendars
- generated PDFs and EPUBs
- other desktop-only support files

The current path context is approximately:

```text
Ticonderoga/
└── manuscripts/
    └── believe-in-me/
        ├── build/
        ├── calendars/
        ├── chapter_metadata.json
        ├── chapters.list
        ├── data/
        │   ├── ocr/
        │   └── scans/
        ├── LFS
        ├── manuscript/
        │   └── believe_in_me.md
        ├── notes/
        ├── README.md
        ├── revisions/
        │   └── Believe in Me/
        │       └── believe_in_me.md
        ├── scripts/
        ├── text/
        └── venv/
```

There is substantial generated or local-only material that should be ignored rather than committed, including `venv`, `__pycache__`, generated caches, and similar junk.

### believe-in-me

`believe-in-me` is the existing Git repo that should become the small novel-only repository.

It should ultimately look approximately like:

```text
believe-in-me/
├── believe_in_me.md
└── .git/
```

The manuscript file should live at the repository root as:

```text
believe_in_me.md
```

The repository should retain exactly the two meaningful branches:

```text
revision
cleaning
```

The Git history of the manuscript is precious. Preserve the manuscript's meaningful history and especially the topology and relationship between `revision` and `cleaning` as faithfully as possible.

### Bigfootnote

`Bigfootnote` is already an independent Git repository inside the Obsidian `.obsidian/plugins` directory.

It should remain independent. Do not introduce a submodule merely to represent its relationship to `Ticonderoga` or `believe-in-me`.

## History Priorities

The manuscript Git history is precious.

The history of supporting files is not important.

For supporting material moving to or already living in `Ticonderoga` -- scripts, scans, OCR output, research material, build tooling, metadata, calendars, generated artifacts, and similar files -- the desired current state is more important than old provenance. If the safest and simplest migration is to copy the current versions into `Ticonderoga` and commit them there as new files, prefer that over complicating the manuscript-history rewrite.

Optimization principle:

When preserving supporting-file history conflicts with simplicity or manuscript safety, protect the manuscript history and accept fresh history for supporting files.

`git filter-repo` is acceptable if it is the safest or most efficient way to produce the lean `believe-in-me` repository. The goal is not to avoid history rewriting. The goal is to ensure that any rewriting preserves the manuscript history and the important `revision` / `cleaning` branch relationship.

## Inspect-Only First

Before proposing or executing any migration, inspect the current state and report findings. Do not mutate the live repository during this phase.

Determine:

- Current Git repository boundaries.
- Current remotes, branches, tags, and `HEAD` state.
- Merge base and graph relationship between `revision` and `cleaning`.
- Historical paths and renames for the manuscript.
- The relationship between:
  - `manuscript/believe_in_me.md`
  - `revisions/Believe in Me/believe_in_me.md`
- Whether commits are mixed, meaning manuscript changes and supporting-file changes occur in the same commits.
- Current Git LFS usage and whether LFS content/configuration is still needed in the lean novel repo.
- Classification of files into:
  - `believe-in-me` novel repo
  - `Ticonderoga` support/workbench repo
  - `Bigfootnote` plugin repo
  - ignored/generated/local-only junk
- Existing `.gitignore` and `.gitattributes` behavior.

After inspection, show the proposed migration plan and wait for approval before making destructive or hard-to-reverse changes.

## Proposed Safe Migration Shape

This is the likely migration approach, but it should not be executed until after inspection and approval.

1. Create a frozen backup.

   Make a full, untouched backup of the current canonical state before rewriting or moving anything. The backup should preserve all branches, tags, remotes, LFS pointers/content as needed, and current working tree context.

2. Ensure the supporting state exists in `Ticonderoga`.

   Confirm that current supporting files are present in the `Ticonderoga` workbench repo under `Ticonderoga/manuscripts/believe-in-me/`. If needed, copy the current versions there and commit them fresh. Do not over-invest in preserving old supporting-file history.

3. Work in a disposable clone of the original `believe-in-me`.

   Perform filtering and history surgery only in a disposable clone until the result has been verified. Do not rewrite the live canonical repository in place.

4. Subtract unrelated paths from `believe-in-me`.

   Remove build outputs, scans, OCR data, notes, scripts, metadata, generated artifacts, virtual environments, caches, and other support/workbench material from the novel repo history.

   Retain manuscript history across both `revision` and `cleaning`.

5. Rewrite the surviving manuscript path to the root.

   Rewrite the surviving manuscript file so the final path is:

   ```text
   believe_in_me.md
   ```

   Be careful to preserve the meaningful manuscript history across historical paths and renames, including the relationship between `manuscript/believe_in_me.md` and `revisions/Believe in Me/believe_in_me.md`.

6. Preserve only meaningful branches.

   The lean `believe-in-me` repo should retain the meaningful branches:

   ```text
   revision
   cleaning
   ```

   Do not delete or rewrite live branches until the disposable result has been approved.

7. Remove obsolete LFS and config baggage.

   If the final novel-only repository no longer needs LFS, remove obsolete LFS configuration and attributes from the disposable result. Keep only the Git configuration needed for the manuscript repo.

8. Verify the result.

   Verify:

   - branch topology and merge base relationship between `revision` and `cleaning`
   - final file path is root-level `believe_in_me.md`
   - branch tips contain the expected manuscript content
   - no support/workbench files remain in the lean repo
   - repository size is appropriately small
   - no obsolete LFS baggage remains unless intentionally retained
   - `.gitignore` and `.gitattributes` are appropriate for a tiny manuscript repo

9. Only after approval, update the remote/canonical repository.

   Once the disposable clone has been verified and Chris approves the result, update the actual `believe-in-me` remote/canonical repository using the agreed method.

10. Eventually move lean `believe-in-me` into Obsidian/iCloud.

   After approval and remote/canonical update, the lean novel-only `believe-in-me` repository can eventually be moved into the desired Obsidian/iCloud location.

## Explicit Do-Not-Do List

Do not:

- force-push without approval
- delete branches or tags without approval
- rewrite the live/canonical repository in place
- move the canonical `believe-in-me` copy before approval
- introduce submodules
- prioritize supporting-file history over manuscript safety
- treat generated caches, virtual environments, OCR/build outputs, or local junk as novel-repo content

## Success Criteria

The migration is successful when:

- `Ticonderoga` is an independent parent/workbench repo containing the supporting project infrastructure.
- `believe-in-me` is a tiny novel-only repo.
- `believe-in-me` has root-level `believe_in_me.md`.
- `believe-in-me` retains the meaningful `revision` and `cleaning` branches.
- The manuscript history and especially the `revision` / `cleaning` topology are preserved as faithfully as possible.
- Supporting-file history has not complicated or endangered the manuscript migration.
- `Bigfootnote` remains an independent repo inside Obsidian's `.obsidian/plugins` directory.
- No submodules are introduced.
