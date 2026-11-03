# @author Cursor
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app_storage import AppStore, GuiSettings, ProjectRow, build_review_settings
from config import ConfigError


class AppStorageTests(unittest.TestCase):
    def test_settings_round_trip_and_rules_file_persist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = AppStore(Path(tmp))
            saved = store.save_settings(
                GuiSettings(
                    gitlab_token="token",
                    openai_api_key="sk-test",
                    gitlab_url="https://gitlab.example.com/",
                    log_level="debug",
                    summary_max_lines=12,
                    summary_max_chars=800,
                )
            )
            loaded = store.load_settings()
            self.assertEqual(loaded.gitlab_url, "https://gitlab.example.com")
            self.assertEqual(loaded.log_level, "DEBUG")
            self.assertEqual(saved.summary_max_lines, 12)

            row = ProjectRow.create()
            row.name = "Project A"
            row.project_id = "95"
            row.mr_iid = "7"
            source = Path(tmp) / "rules.md"
            source.write_text("# rules\n", encoding="utf-8")
            row.rules_filename = store.store_rules(row.id, source)
            store.save_projects([row])

            restored = store.load_projects()
            self.assertEqual(restored[0].rules_filename, "rules.md")
            self.assertEqual(store.rules_path(row.id).read_text(encoding="utf-8"), "# rules\n")

            store.delete_rules(row.id)
            self.assertFalse(store.has_rules(row.id))

    def test_build_review_settings_uses_gui_defaults(self) -> None:
        settings = build_review_settings(
            GuiSettings(
                gitlab_token="token",
                openai_api_key="sk-test",
                gitlab_url="https://gitlab.example.com",
            ),
            project_id=95,
            mr_iid=7,
        )
        self.assertEqual(settings.review_language, "ja")
        self.assertFalse(settings.dry_run)
        self.assertEqual(settings.output_mode, "both")
        self.assertEqual(settings.summary_max_lines, 30)
        self.assertEqual(settings.gitlab_allowed_hosts, ("gitlab.example.com",))

    def test_save_settings_rejects_invalid_log_level(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = AppStore(Path(tmp))
            with self.assertRaises(ConfigError):
                store.save_settings(
                    GuiSettings(
                        gitlab_token="token",
                        openai_api_key="sk-test",
                        gitlab_url="https://gitlab.example.com",
                        log_level="verbose",
                    )
                )


if __name__ == "__main__":
    unittest.main()
