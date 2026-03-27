---
name: docs-hygiene
description: Use when auditing repository documentation for stale paths, outdated architecture claims, invalid startup instructions, or plan drift, especially before handoff, release, onboarding improvements, or after major implementation changes.
---

# Docs Hygiene

## Overview

Treat documentation like code: verify claims, remove stale guidance, and leave a clear follow-up trail for anything you cannot safely fix in the same pass.

Core principle: documentation is only useful if a new collaborator can trust it.

## When to Use

Use this skill when:

- `README.md` or `docs/` may no longer match the implementation
- plan docs have drifted from shipped behavior
- startup, verification, or testing commands in docs may be stale
- recipes in the root `justfile` or package-level `justfile`'s don't work
- onboarding is confusing or contradictory
- a milestone has landed and the docs need consolidation

Do not use this skill for narrow copy edits or typo-only changes.

## Required Inputs

At minimum, read all of the following if they exist:

- `README.md`
- `docs/ROADMAP.md`
- `docs/plans/**/*.md`
- `justfile`
- `layersense_*/justfile`

Also read any adjacent guidance file that shapes contributor behavior if it affects doc expectations:

- `AGENTS.md`

## Audit Workflow

Follow this checklist in order.

### 1. Build the docs map

- Enumerate `docs/**/*.md`
- Identify the canonical entrypoints (`README.md`, `docs/ROADMAP.md`)
- Note duplicates, moved files, and likely historical docs

### 2. Read for claims, not prose

For each document, extract concrete claims such as:

- architecture statements
- service names and ports
- startup instructions
- Docker assumptions
- command examples
- status words like "implemented", "working", "current", "approved"
- file paths and links

### 3. Verify commands and paths

Test commands that the docs present as current or recommended, when safe and available. Prefer representative verification over blindly running everything.

Typical checks:

- repo quality commands such as `just lint`, `just test`, `just check`
- documented frontend commands such as `npm --prefix layersense_frontend run build`
- startup/health commands if they are central to the doc claim and safe to run

Verify file references and linked docs still exist.

### 4. Classify findings

For each issue, classify it as one of:

- `patch-now`: clearly stale and safe to fix immediately
- `historical-keep`: outdated as current guidance, but useful as historical context if relabeled
- `todo-later`: real issue, but fixing it would require broader product or implementation decisions
- `delete`: no longer useful, misleading, or duplicative

### 5. Patch ruthlessly

Preferred actions:

- remove stale sections instead of hedging around them
- rewrite active docs to reflect the actual current state
- relabel drifted plans as historical or partially superseded
- fix stale paths and broken cross-references
- collapse duplicate guidance into canonical docs
- collapse duplicate just commands into a single source of truth
- fix stale commands or remove them if they are no longer relevant to the current implementation

Do not preserve misleading text just because it was once true.

### 6. Write a follow-up TODO report

Always create or update a dated report in `docs/` capturing anything left unresolved.

Filename pattern:

- `docs/YYYY-MM-DD-docs-hygiene-followups.md`

The report must include:

- what was audited
- what was patched
- what remains stale or risky
- which items need code or product decisions rather than doc edits

## Output Contract

When finishing a docs hygiene pass, leave behind:

1. Patched docs
2. A dated follow-up report in `docs/`
3. A concise summary of:
   - files changed
   - commands verified
   - remaining unresolved issues

## Quick Reference

Use these heuristics aggressively:

- "current", "working", "approved", "production-ready" -> verify
- paths under `docs/` -> confirm existence
- startup instructions -> confirm they still match the repo
- architecture sections -> compare against actual implementation direction
- plan docs -> relabel if implementation has drifted

## Common Mistakes

- Keeping stale sections with weak caveats instead of deleting them
- Trusting plan documents as current truth without checking the repo
- Forgetting to verify linked paths after moving files
- Updating only `README.md` while leaving contradictory `docs/plans/*` files intact
- Claiming docs are clean without testing at least the core documented commands

## Minimum Verification Before Claiming Success

Run the strongest relevant commands you can safely justify from the current docs. In this repo, that usually includes:

- `just lint`
- `just test`

If docs reference narrower commands as part of active guidance, run those too when feasible.

Then re-read changed docs to ensure they no longer contradict one another.
