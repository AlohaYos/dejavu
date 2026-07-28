"""The hand-rolled config reader/writer.

dejavu parses its own config rather than importing tomllib, because tomllib is 3.11+ and
requires-python is 3.10. The cost of that choice is that these shapes have to be pinned
down by tests instead of by a library's own suite.
"""

from __future__ import annotations

from pathlib import Path

from dejavu import scope as scope_mod

SHIPPED = """# dejavu config
#
# Days before an entry is reported as stale.

[stale_days]
context = 7
plan = 14

[obsidian]
# Path to your Obsidian vault. Empty means the integration is off.
vault = "~/Documents/MyVault"
include = ["Knowledge", "UserInfo", "Research"]
research = "findings"
"""


def _write(tmp_path: Path, text: str = SHIPPED) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_reads_strings_arrays_and_integers(tmp_path: Path):
    data = scope_mod.load_config(_write(tmp_path))

    assert data["stale_days"]["context"] == 7
    assert data["obsidian"]["vault"] == "~/Documents/MyVault"
    assert data["obsidian"]["include"] == ["Knowledge", "UserInfo", "Research"]


def test_existing_stale_days_behaviour_is_unchanged(tmp_path: Path):
    days = scope_mod._load_stale_days(_write(tmp_path))

    assert days["context"] == 7
    assert days["plan"] == 14
    assert days["decision"] == 30  # untouched keys keep their default


def test_a_missing_or_unreadable_file_falls_back_to_defaults(tmp_path: Path):
    assert scope_mod.load_config(tmp_path / "nope.toml") == {}
    assert scope_mod._load_stale_days(None)["context"] == 7


def test_obsidian_config_defaults_and_expansion(tmp_path: Path):
    cfg = scope_mod.obsidian_config(_write(tmp_path))

    assert cfg.enabled
    assert cfg.vault == Path("~/Documents/MyVault").expanduser()
    assert cfg.research == "findings"
    assert (cfg.write_mode, cfg.promote) == ("auto", "ask")  # defaults
    assert cfg.knowledge_dir == "Knowledge"


def test_no_vault_means_the_integration_is_off(tmp_path: Path):
    cfg = scope_mod.obsidian_config(_write(tmp_path, "[stale_days]\ncontext = 7\n"))

    assert not cfg.enabled
    assert cfg.vault is None
    # include still defaults, so nothing downstream has to special-case the empty case.
    assert cfg.include == ["Knowledge", "UserInfo", "Research"]


def test_an_invalid_choice_falls_back_instead_of_breaking_the_run(tmp_path: Path):
    cfg = scope_mod.obsidian_config(_write(tmp_path, '[obsidian]\nresearch = "everything"\n'))

    assert cfg.research == "findings"


def test_writing_a_key_leaves_every_comment_intact(tmp_path: Path):
    path = _write(tmp_path)

    scope_mod.set_config_value(path, "obsidian", "research", "all")
    text = path.read_text(encoding="utf-8")

    assert "# Days before an entry is reported as stale." in text
    assert "# Path to your Obsidian vault. Empty means the integration is off." in text
    assert 'research = "all"' in text
    assert 'research = "findings"' not in text
    assert scope_mod.load_config(path)["obsidian"]["include"] == [
        "Knowledge",
        "UserInfo",
        "Research",
    ]


def test_a_new_key_joins_the_existing_section(tmp_path: Path):
    path = _write(tmp_path)

    scope_mod.set_config_value(path, "obsidian", "promote", "always")
    lines = path.read_text(encoding="utf-8").splitlines()

    assert 'promote = "always"' in lines
    assert lines.index('promote = "always"') > lines.index("[obsidian]")
    assert scope_mod.load_config(path)["stale_days"]["context"] == 7


def test_a_missing_section_is_appended(tmp_path: Path):
    path = _write(tmp_path, "[stale_days]\ncontext = 7\n")

    scope_mod.set_config_value(path, "obsidian", "vault", "/tmp/v")

    assert scope_mod.load_config(path)["obsidian"]["vault"] == "/tmp/v"
    assert scope_mod.load_config(path)["stale_days"]["context"] == 7


def test_writing_creates_the_file_when_there_is_none(tmp_path: Path):
    path = tmp_path / "sub" / "config.toml"

    scope_mod.set_config_value(path, "obsidian", "vault", "/tmp/v")

    assert scope_mod.obsidian_config(path).vault == Path("/tmp/v")


def test_the_key_of_a_later_section_is_not_mistaken_for_ours(tmp_path: Path):
    path = _write(tmp_path, '[obsidian]\nresearch = "manual"\n\n[other]\nresearch = "all"\n')

    scope_mod.set_config_value(path, "obsidian", "research", "findings")
    data = scope_mod.load_config(path)

    assert data["obsidian"]["research"] == "findings"
    assert data["other"]["research"] == "all"


def test_the_similarity_default_is_the_one_that_was_measured(project):
    """0.65 came from running it over real vaults; 0.6 let the top_k cap pick the links."""
    from dejavu import scope as scope_mod

    assert scope_mod.obsidian_config().relate_min_sim == 0.65
