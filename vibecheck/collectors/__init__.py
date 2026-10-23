"""Collectors look at one aspect of a project and emit Signals with evidence."""

from vibecheck.collectors import code, comments, git, repo

ALL = (comments, code, repo, git)
