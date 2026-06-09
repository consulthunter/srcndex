from pathlib import Path

import pygit2

from srcndx.models import GitStatus


def load_repo(repo_path: Path) -> pygit2.Repository | None:
    try:
        return pygit2.Repository(str(repo_path))
    except pygit2.GitError:
        return None


def head_commit(repo: pygit2.Repository) -> str:
    try:
        return str(repo.head.target)
    except pygit2.GitError:
        return ""


def churn_map(repo: pygit2.Repository) -> dict[str, int]:
    """Single pass over commit history → per-file commit count."""
    churn: dict[str, int] = {}
    try:
        for commit in repo.walk(repo.head.target, pygit2.enums.SortMode.TIME):
            if not commit.parents:
                continue
            diff = repo.diff(commit.parents[0], commit)
            for delta in diff.deltas:
                path = delta.new_file.path
                churn[path] = churn.get(path, 0) + 1
    except pygit2.GitError:
        pass
    return churn


def file_status(repo: pygit2.Repository, rel_path: str) -> GitStatus:
    try:
        flags = repo.status_file(rel_path)
    except (pygit2.GitError, KeyError):
        return GitStatus.UNCHANGED

    if flags == pygit2.GIT_STATUS_CURRENT:
        return GitStatus.UNCHANGED
    if flags & (pygit2.GIT_STATUS_WT_NEW | pygit2.GIT_STATUS_INDEX_NEW):
        return GitStatus.NEW
    if flags & pygit2.GIT_STATUS_INDEX_DELETED:
        return GitStatus.DELETED
    return GitStatus.MODIFIED
