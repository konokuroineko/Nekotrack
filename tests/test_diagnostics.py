import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import diagnostics


class DiagnosticRedactionTests(unittest.TestCase):
    def test_redacts_credentials_in_headers_assignments_and_urls(self):
        source = (
            "Authorization: Bearer abcdefghijklmnopqrstuvwxyz123456 "
            "api_key=API_SECRET_VALUE password='PASSWORD VALUE' "
            "https://example.test/items?access_token=URL_SECRET_VALUE "
            "tmdb_api_token=TMDB_SECRET_VALUE "
            "https://example.test/items?api_token=API_TOKEN_SECRET "
            "'tmdb_api_token': 'SERIALIZED_TOKEN_SECRET' "
            "'Authorization': 'Bearer SERIALIZED_AUTH_SECRET'"
        )
        result = diagnostics.redact_text(source)
        for secret in (
            "abcdefghijklmnopqrstuvwxyz123456",
            "API_SECRET_VALUE",
            "PASSWORD VALUE",
            "URL_SECRET_VALUE",
            "TMDB_SECRET_VALUE",
            "API_TOKEN_SECRET",
            "SERIALIZED_TOKEN_SECRET",
            "SERIALIZED_AUTH_SECRET",
        ):
            self.assertNotIn(secret, result)
        self.assertIn("<redacted>", result)

    def test_event_fields_omit_payloads_and_redact_secret_named_fields(self):
        fields = {
            "tmdb_api_token": "do-not-log-this",
            "query": "a possibly private search term",
            "work_id": 123,
        }
        safe = {key: diagnostics._safe_value(key, value) for key, value in fields.items()}
        self.assertEqual(safe["tmdb_api_token"], "<redacted>")
        self.assertEqual(safe["query"], "<omitted>")
        self.assertEqual(safe["work_id"], 123)

    def test_export_collects_old_and_current_logs_and_redacts_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "repo"
            data = Path(directory) / "appdata" / "NekoTrack"
            (root / "logs").mkdir(parents=True)
            (data / "logs").mkdir(parents=True)
            (root / "main.py").write_text('APP_VERSION = "test-version"\n', encoding="utf-8")
            (data / "logs" / "nekotrack.log.1").write_text(
                'older event api_key=BACKUP_SECRET\n', encoding="utf-8"
            )
            (data / "logs" / "nekotrack.log").write_text(
                'newer event password=CURRENT_SECRET\n', encoding="utf-8"
            )
            output = diagnostics.export_diagnostics(
                app_data_dir=data,
                project_root=root,
            )
            report = output.read_text(encoding="utf-8")
            self.assertEqual(output, root / "nekotrack_diagnostics.txt")
            self.assertIn("test-version", report)
            self.assertIn("older event", report)
            self.assertIn("newer event", report)
            self.assertLess(report.index("older event"), report.index("newer event"))
            self.assertNotIn("BACKUP_SECRET", report)
            self.assertNotIn("CURRENT_SECRET", report)
            self.assertIn("<redacted>", report)

    def test_diagnostic_context_is_inherited_and_explicit_fields_win(self):
        with diagnostics.diagnostic_context(workflow="bundle", work_id=55):
            payload = diagnostics._event_payload(
                "api.request",
                {"operation": "provider_request", "provider": "AniList"},
            )
        self.assertEqual(payload["workflow"], "bundle")
        self.assertEqual(payload["work_id"], 55)
        self.assertEqual(payload["operation"], "provider_request")
        self.assertEqual(payload["provider"], "AniList")
        self.assertNotIn("work_id", diagnostics._event_payload("outside.context", {}))

    def test_operation_logs_failure_context_and_reraises(self):
        failure = ValueError("expected test failure")
        with patch.object(diagnostics, "log_event") as event, \
             patch.object(diagnostics, "log_exception") as exception:
            with self.assertRaisesRegex(ValueError, "expected test failure"):
                with diagnostics.log_operation("unit.test", work_id=42):
                    raise failure
        self.assertEqual(event.call_args.args[0], "operation.started")
        exception.assert_called_once()
        self.assertEqual(exception.call_args.args[0], "operation.failed")
        self.assertEqual(exception.call_args.kwargs["operation"], "unit.test")
        self.assertEqual(exception.call_args.kwargs["work_id"], 42)


if __name__ == "__main__":
    unittest.main()
