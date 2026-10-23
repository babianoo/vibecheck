# vibecheck

Estimates how vibe-coded a C/C++ project is.

"Vibe-coded" is not the same as "written with AI". vibecheck scores two
separate axes and combines them:

- **AI involvement**: how much of the project looks machine-generated
  (agent co-author trailers, LLM commit-message style, narrated comments,
  emoji in output, an emoji-heavy README…).
- **Oversight deficit**: how much it looks like nobody read the output
  (`// ... rest of the code` leftovers, `IMPLEMENTATION_SUMMARY.md` files,
  `main_old.cpp`, "in a real application you would…" caveats, chains of
  "fix build again" commits, dead functions, duplicated functions…).

The **vibe score** needs involvement: messy hand-written code is not
vibe-coded. Missing oversight amplifies it:

```
vibe = involvement × (0.4 + 0.6 × oversight / 100)
```

Each axis combines its signals as a noisy-OR, so one overwhelming signal is
enough on its own, and many weak ones add up without passing 100. Every
point in the report comes with evidence (`file:line` or a commit hash), so
you can check the claim instead of trusting a number.

## Usage

No dependencies beyond Python 3.10+ and git.

```sh
python -m vibecheck path/to/project            # from this directory
pipx install -e . && vibecheck ~/code/*        # or install the command
```

```
vibecheck PATH...          scan one or more projects (a summary table follows)
  -n N                     evidence lines per signal (default 3)
  -v                       show all evidence
  --json                   machine-readable output
  --no-git                 ignore git history, scan files on disk
  -x GLOB                  exclude paths (repeatable)
  --color auto|always|never
```

Paths listed in a `.vibecheckignore` file at the project root (fnmatch
globs, one per line) are skipped. This is useful for course-provided starter
code that you didn't write.

## What it skips

- Build output and vendored directories (`build/`, `third_party/`,
  `external/`, `_deps/`, …).
- Well-known single-header libraries (`json.hpp`, `stb_*.h`, `doctest.h`, …).
- Files marked as generated.
- In git repos, only tracked and untracked-but-not-ignored files are read.

## Signals

| Axis | Signal | Weight |
|---|---|---|
| involvement | Commits with AI co-author trailers or agent authors | 0.90 |
| involvement | Emoji in output strings or comments | 0.45 |
| involvement | README in LLM house style (emoji headings, tree diagrams, buzzwords) | 0.40 |
| involvement | LLM-style commit messages (bulleted bodies, "comprehensive", "enhance") | 0.40 |
| involvement | Agent config files (`CLAUDE.md`, `.cursorrules`, `AGENTS.md`, …) | 0.35 |
| involvement | Tutorial narration ("Let's…", "Now we…", "Step 1:") | 0.30 |
| involvement | Typeset punctuation in comments (— → “ ”) | 0.30 |
| involvement | Files repeatedly rewritten wholesale | 0.30 |
| involvement | Comments restating the next statement | 0.25 |
| involvement | `CRITICAL:` / `IMPORTANT:` annotations | 0.25 |
| involvement | Huge commits after the first | 0.20 |
| involvement | Implausible lines-per-week | 0.20 |
| involvement | Doxygen on nearly every function | 0.15 |
| involvement | `#pragma once` *and* an include guard | 0.15 |
| involvement | Decorative banner comments | 0.10 |
| oversight | Elided-code leftovers (`// ... existing code`) | 0.60 |
| oversight | Placeholder caveats ("in a real application…") | 0.50 |
| oversight | Agent status reports (`IMPLEMENTATION_SUMMARY.md`, `FIXES_APPLIED.md`) | 0.50 |
| oversight | Abandoned copies and scratch files (`main_old.cpp`, `debug_x.py`) | 0.40 |
| oversight | Comments narrating edits ("FIXED:", "now correctly…") | 0.35 |
| oversight | Near-duplicate functions | 0.35 |
| oversight | Null checks after plain `new` | 0.30 |
| oversight | Unused file-local functions | 0.30 |
| oversight | Chains of fix/try-again commits | 0.30 |
| oversight | C and C++ idioms mixed in one file | 0.15 |

The weight is the most a signal can add to its axis. Density-based signals
are measured per kLOC and discounted when only a handful of hits back them.

## Caveats

- The weights are hand-tuned against a few known-human and known-generated
  repos, not fitted to a labelled dataset. Treat scores as a reasoned
  opinion with receipts.
- Squashed or missing git history removes the strongest signals. The
  `confidence` field says how much there was to go on.
- Beginner code and generated code share habits (restating comments,
  defensive checks). Those signals are deliberately weak.
- All of this is trivially gameable. vibecheck is a mirror, not a lie detector.

## Development

```sh
python -m pytest
```

Layout: `vibecheck/cpp.py` (lexer and function finder), `discover.py` (which
files count), `collectors/` (one module per signal family), `scoring.py`,
`report.py`, `cli.py`.
