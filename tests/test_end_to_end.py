import json

from vibecheck.cli import main
from vibecheck.scoring import analyze, axis_score, vibe_score
from vibecheck.model import INVOLVEMENT, Signal


def ids(result):
    return {s.id for s in result.fired()}


def test_axis_score_is_noisy_or():
    signals = [Signal("a", "", INVOLVEMENT, 0.5, 1.0), Signal("b", "", INVOLVEMENT, 0.5, 1.0)]
    assert axis_score(signals, INVOLVEMENT) == 75.0
    assert axis_score([], INVOLVEMENT) == 0.0


def test_vibe_needs_involvement():
    assert vibe_score(0, 100) == 0
    assert vibe_score(100, 0) == 40
    assert vibe_score(100, 100) == 100


def test_vibey_repo(vibey_repo):
    r = analyze(vibey_repo.root)
    assert r.stats["commits"] == 7
    assert r.verdict in ("Vibe-coded", "Pure vibes"), (r.vibe, r.involvement, r.oversight)
    expected = {
        "ai-commits", "llm-commit-messages", "agent-config", "readme-style", "emoji", "reader-address",
        "restating-comments", "placeholder-comments", "elision-leftovers", "changelog-comments",
        "shouty-annotations", "status-reports", "leftover-files", "fix-chains", "new-null-check",
        "double-include-guard", "mixed-idioms", "duplicate-functions", "dead-static-functions",
    }
    assert expected <= ids(r), expected - ids(r)


def test_clean_repo(clean_repo):
    r = analyze(clean_repo.root)
    assert r.verdict == "Artisanal", (r.vibe, [(s.id, s.contribution) for s in r.fired()])
    assert r.vibe < 10


def test_no_git(vibey_repo):
    r = analyze(vibey_repo.root, use_git=False)
    assert not r.stats["git"]
    assert not {"ai-commits", "fix-chains"} & ids(r)
    assert "elision-leftovers" in ids(r)


def test_ignore_file_and_exclude(vibey_repo):
    (vibey_repo.root / ".vibecheckignore").write_text("# comment\nmain_old.cpp\n")
    r = analyze(vibey_repo.root, exclude=("debug_*.py",))
    leftovers = next(s for s in r.signals if s.id == "leftover-files")
    assert leftovers.metrics["count"] == 0


def test_cli_json(vibey_repo, clean_repo, capsys):
    assert main([str(vibey_repo.root), str(clean_repo.root), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert len(data) == 2 and data[0]["vibe"] > data[1]["vibe"]
    assert {"involvement", "oversight", "verdict", "signals", "stats"} <= set(data[0])


def test_cli_text(vibey_repo, capsys):
    assert main([str(vibey_repo.root), "--color", "never"]) == 0
    out = capsys.readouterr().out
    assert "Vibe score" in out and "IMPLEMENTATION_SUMMARY.md" in out
    assert "\x1b[" not in out


def test_cli_rejects_missing_dir(tmp_path, capsys):
    assert main([str(tmp_path / "nope")]) == 2
