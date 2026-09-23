"""Tests for trade-booking/scripts/portfolio_access.py — pure-logic functions.

The DB round-trip is smoke-tested manually (`python scripts/portfolio_access.py`);
everything that decides who sees what is exercised here.

Cases ported from ace-run/tests/test_access.py, which already proves these
semantics against the same refdata table.
"""
from pathlib import Path
import sys

import pytest

# Make the trade-booking scripts importable
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import portfolio_access  # noqa: E402


# ── split_emails ──────────────────────────────────────────────────────

def test_emails_are_trimmed_and_lowercased():
    assert portfolio_access.split_emails(" A@x.com ,b@X.COM") == {
        "a@x.com", "b@x.com",
    }


def test_blank_and_null_usernames_yield_no_members():
    assert portfolio_access.split_emails(None) == set()
    assert portfolio_access.split_emails("") == set()
    assert portfolio_access.split_emails("  ,  , ") == set()


# ── build_map ─────────────────────────────────────────────────────────

def test_a_member_gets_their_portfolios():
    by_email, names = portfolio_access.build_map([
        (8041, "TOKKA - 8041", "francis@x.com,danny@x.com"),
        (8043, "TOKKA - 8043", "francis@x.com"),
        (8888, "TREASURY", "danny@x.com"),
    ])
    assert by_email["francis@x.com"] == [8041, 8043]
    assert by_email["danny@x.com"] == [8041, 8888]
    assert names["8041"] == "TOKKA - 8041"


def test_email_match_is_case_insensitive():
    by_email, _ = portfolio_access.build_map([
        (8041, "p", "Francis.Xu@Tokkalabs.com"),
    ])
    assert by_email["francis.xu@tokkalabs.com"] == [8041]


def test_an_unknown_email_gets_nothing():
    by_email, _ = portfolio_access.build_map([(8041, "p", "francis@x.com")])
    assert by_email.get("stranger@x.com") is None


def test_a_portfolio_with_no_members_grants_nobody():
    by_email, names = portfolio_access.build_map([
        (8041, "has members", "francis@x.com"),
        (8099, "no members", ""),
    ])
    assert 8099 not in by_email["francis@x.com"]
    # ...but it is still a known portfolio, so its name can be displayed.
    assert names["8099"] == "no members"


def test_an_all_empty_usernames_result_refuses_to_load():
    """Fail closed. A successful query against broken or empty refdata must
    not read as 'nobody has access to anything' -- that locks the firm out."""
    with pytest.raises(RuntimeError, match="refusing to load"):
        portfolio_access.build_map([
            (8041, "p", ""),
            (8043, "q", None),
        ])


def test_a_row_without_a_number_is_skipped():
    by_email, names = portfolio_access.build_map([
        (None, "no number", "francis@x.com"),
        (8041, "real", "francis@x.com"),
    ])
    assert by_email["francis@x.com"] == [8041]
    assert list(names) == ["8041"]


def test_portfolio_numbers_are_ints_and_sorted():
    by_email, _ = portfolio_access.build_map([
        (8888, "c", "francis@x.com"),
        ("8041", "a", "francis@x.com"),
        (8043, "b", "francis@x.com"),
    ])
    assert by_email["francis@x.com"] == [8041, 8043, 8888]


# ── fetch_rows: the query is the security boundary ────────────────────

class FakeCursor:
    def __init__(self):
        self.sql = ""

    def execute(self, sql, args=None):
        self.sql = " ".join(sql.split())

    def fetchall(self):
        return []


def test_a_soft_deleted_portfolio_is_excluded_by_the_query():
    """A deleted portfolio still lists its old `usernames`, so reading it would
    keep granting the book MO retired."""
    cur = FakeCursor()
    portfolio_access.fetch_rows(cur)
    assert "deletedAt IS NULL" in cur.sql


def test_a_status_deleted_portfolio_is_excluded_but_dormant_is_not():
    """DORMANT is a live grant -- it just is not trading today."""
    cur = FakeCursor()
    portfolio_access.fetch_rows(cur)
    assert "status <> 'DELETED'" in cur.sql
    assert "DORMANT" not in cur.sql


# ── credentials ───────────────────────────────────────────────────────

def test_env_vars_take_precedence_over_the_env_file(monkeypatch):
    monkeypatch.setenv("T2X_RO_MYSQL_HOST", "h")
    monkeypatch.setenv("T2X_RO_MYSQL_USERNAME", "u")
    monkeypatch.setenv("T2X_RO_MYSQL_PASSWORD", "p")
    assert portfolio_access.load_mysql_creds() == {
        "host": "h", "username": "u", "password": "p",
    }


def test_creds_parse_from_the_env_block_above_the_marker(tmp_path: Path,
                                                         monkeypatch):
    """The real .env shape: keys ABOVE the marker, a header comment further up
    that NAMES the marker, and a second MySQL block below it. Matching the
    marker as a substring lands on the header comment and parses nothing --
    the bug that broke this module's first real run."""
    for k in ("HOST", "USERNAME", "PASSWORD"):
        monkeypatch.delenv(f"T2X_RO_MYSQL_{k}", raising=False)
    fake_env = tmp_path / ".env"
    fake_env.write_text(
        "# Notes: keys go BEFORE the `# sg-ro-mysql` marker.\n"
        "\n"
        "# MO DB UAT\n"
        "MO_DB_HOST: other.example.com\n"
        "\n"
        "host: refdata.example.com\n"
        "username: ro_user\n"
        "password: ro_secret\n"
        "# sg-ro-mysql\n"
        "\n"
        "# MYSQL TOKEN PRICE DB\n"
        "username: wrong\n"
        "password: wrong\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(portfolio_access, "ENV", fake_env)
    c = portfolio_access.load_mysql_creds()
    assert c["host"] == "refdata.example.com"
    assert c["username"] == "ro_user"
    assert c["password"] == "ro_secret"


def test_missing_creds_raise_rather_than_returning_a_partial(
    tmp_path: Path, monkeypatch
):
    for k in ("HOST", "USERNAME", "PASSWORD"):
        monkeypatch.delenv(f"T2X_RO_MYSQL_{k}", raising=False)
    fake_env = tmp_path / ".env"
    fake_env.write_text("host: only.example.com\n# sg-ro-mysql\n",
                        encoding="utf-8")
    monkeypatch.setattr(portfolio_access, "ENV", fake_env)
    with pytest.raises(RuntimeError, match="credentials missing"):
        portfolio_access.load_mysql_creds()


def test_a_header_comment_naming_the_marker_is_not_the_marker(
    tmp_path: Path, monkeypatch
):
    """The .env documents its own marker by name. A substring match finds that
    comment, parses nothing, and then blames missing credentials."""
    for k in ("HOST", "USERNAME", "PASSWORD"):
        monkeypatch.delenv(f"T2X_RO_MYSQL_{k}", raising=False)
    fake_env = tmp_path / ".env"
    fake_env.write_text(
        "# lookback window around `# sg-ro-mysql` marker.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(portfolio_access, "ENV", fake_env)
    with pytest.raises(RuntimeError, match="marker line"):
        portfolio_access.load_mysql_creds()
