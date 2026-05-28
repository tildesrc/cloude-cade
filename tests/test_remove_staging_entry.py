"""Tests for ``bin/cloude-remove-staging-entry``.

CLI-surface tests; the underlying ``remove_staging_entry`` is covered
deeply in ``test_cloude_org.py``. Here we verify: happy path drops the
heading and writes the body, missing file exits 2, heading-not-found
exits 2, missing required flag exits 30.
"""

from __future__ import annotations

from pathlib import Path


_STAGING_FIXTURE = """\
* Example project
  :PROPERTIES:
  :REPO: https://github.com/example/example
  :END:
** First idea
   Some body text.
** Second idea
   Other body.
"""


class TestRemoveStagingEntry:
    def test_drops_heading_and_writes_body(self, run_script, tmp_path: Path):
        staging = tmp_path / "staging.org"
        staging.write_text(_STAGING_FIXTURE)
        body_out = tmp_path / "body.txt"

        result = run_script(
            "cloude-remove-staging-entry", str(staging),
            "--heading", "First idea",
            "--body-out", str(body_out),
        )
        assert result.returncode == 0, result.stderr
        # The "First idea" entry is gone, "Second idea" remains.
        new_content = staging.read_text()
        assert "** First idea" not in new_content
        assert "** Second idea" in new_content
        # Body file captured the dedented entry body.
        assert "Some body text." in body_out.read_text()

    def test_body_out_optional(self, run_script, tmp_path: Path):
        staging = tmp_path / "staging.org"
        staging.write_text(_STAGING_FIXTURE)
        result = run_script(
            "cloude-remove-staging-entry", str(staging),
            "--heading", "First idea",
        )
        assert result.returncode == 0, result.stderr
        assert "** First idea" not in staging.read_text()

    def test_missing_file_exits_2(self, run_script, tmp_path: Path):
        result = run_script(
            "cloude-remove-staging-entry", str(tmp_path / "no.org"),
            "--heading", "x",
        )
        assert result.returncode == 2
        assert "staging file not found" in result.stderr

    def test_heading_not_found_exits_2(self, run_script, tmp_path: Path):
        staging = tmp_path / "staging.org"
        staging.write_text(_STAGING_FIXTURE)
        result = run_script(
            "cloude-remove-staging-entry", str(staging),
            "--heading", "Nonexistent idea",
        )
        assert result.returncode == 2
        assert "heading not found" in result.stderr
        # File left untouched.
        assert staging.read_text() == _STAGING_FIXTURE

    def test_missing_heading_flag_exits_30(self, run_script, tmp_path: Path):
        staging = tmp_path / "staging.org"
        staging.write_text(_STAGING_FIXTURE)
        result = run_script(
            "cloude-remove-staging-entry", str(staging),
            # no --heading
        )
        assert result.returncode == 30
