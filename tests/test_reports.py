import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from core.severity import Severity
from reports.exportar import REPORTLAB_DISPONIBLE
from reports.service import (
    HistoryStore,
    ReportBuilder,
    ReportComparator,
    ReportExporter,
    ReportService,
    render_text,
)
from ui.reports import ReportsMenu


def _report(created_at="2026-09-27T18:40:00-06:00", status="NORMAL"):
    return {
        "schema_version": 1,
        "created_at": created_at,
        "mode": "normal",
        "equipment": {
            "computer": "PC-01",
            "user": "technician",
            "windows": {"version": "Windows"},
        },
        "summary": {
            "severity": status,
            "alerts": 1 if status == "ALERTA" else 0,
            "critical": 1 if status == "CRÍTICO" else 0,
            "problems": 1 if status in ("ALERTA", "CRÍTICO") else 0,
            "findings_count": 1,
        },
        "hardware": {
            "cpu": {"usage_percent": 25, "temperature_c": 60},
            "ram": {"usage_percent": 50, "available_gb": 8},
            "storage": {
                "volumes": [{"free_bytes": 20 * 1024 ** 3}],
                "physical_drives": [{"health": "normal", "temperature_c": 35}],
            },
            "gpu": {"cards": [{"usage_percent": 10, "temperature_c": 40}]},
            "battery": {"health_percent": 90, "percentage": 80},
        },
        "diagnosis": {"findings": []},
        "network": {"severity": "NORMAL", "diagnosis": "CONECTIVIDAD NORMAL"},
        "security": {"findings": []},
        "maintenance": {"recommendations": []},
        "tests": None,
        "findings": [],
        "recommendations": [],
        "collection_errors": [],
    }


class HistoryStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.database = Path(self.temporary.name) / "database" / "history.db"
        self.history = HistoryStore(self.database)

    def tearDown(self):
        self.temporary.cleanup()

    def test_save_get_latest_and_list_report_summaries(self):
        first = _report(status="NORMAL")
        first_id = self.history.save(first)
        first["id"] = first_id
        self.history.replace_payload(first_id, first)
        second = _report("2026-09-27T18:52:00-06:00", "ALERTA")
        second_id = self.history.save(second)

        loaded = self.history.get(first_id)
        latest = self.history.latest()
        rows = self.history.list()

        self.assertEqual(loaded["report"]["equipment"]["computer"], "PC-01")
        self.assertEqual(latest["id"], second_id)
        self.assertEqual(latest["status"], "ALERTA")
        self.assertNotIn("report", rows[0])
        self.assertEqual(len(rows), 2)

    def test_search_supports_equipment_user_date_and_status(self):
        normal_id = self.history.save(_report())
        alert = _report("2026-09-28T09:15:00-06:00", "ALERTA")
        alert["equipment"]["computer"] = "PC-02"
        alert["equipment"]["user"] = "support"
        self.history.save(alert)

        self.assertEqual(
            [row["id"] for row in self.history.search(computer="pc-02")],
            [normal_id + 1],
        )
        self.assertEqual(len(self.history.search(username="support")), 1)
        self.assertEqual(len(self.history.search(date="2026-09-28")), 1)
        self.assertEqual(len(self.history.search(status="ALERTA")), 1)

    def test_history_database_creation_failure_surfaces_to_caller(self):
        with tempfile.TemporaryDirectory() as directory:
            parent_file = Path(directory) / "not-a-directory"
            parent_file.write_text("test", encoding="utf-8")
            with self.assertRaises(OSError):
                HistoryStore(parent_file / "history.db")


class ReportExportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.exporter = ReportExporter(self.root)

    def tearDown(self):
        self.temporary.cleanup()

    def test_json_export_preserves_structured_report(self):
        report = _report()
        path = Path(self.exporter.export(report, "json", diagnostic_id=1))

        self.assertEqual(path.parent.name, "json")
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), report)

    def test_txt_export_contains_required_report_sections(self):
        path = Path(self.exporter.export(_report(), "txt", diagnostic_id=2))
        output = path.read_text(encoding="utf-8")

        for heading in (
            "HARDWARE DIAGNÓSTICO",
            "ESTADO GENERAL",
            "RESUMEN DEL EQUIPO",
            "DIAGNÓSTICO",
            "RED",
            "SEGURIDAD",
            "MANTENIMIENTO",
            "PRUEBAS",
            "RECOMENDACIONES",
        ):
            self.assertIn(heading, output)

    @unittest.skipUnless(REPORTLAB_DISPONIBLE, "reportlab no está instalado")
    def test_pdf_export_creates_technical_pdf(self):
        path = Path(self.exporter.export(_report(), "pdf", diagnostic_id=3))

        self.assertEqual(path.parent.name, "pdf")
        self.assertGreater(path.stat().st_size, 0)
        self.assertEqual(path.read_bytes()[:4], b"%PDF")

    def test_export_names_are_unique_and_do_not_overwrite(self):
        first = self.exporter.export(_report(), "json", diagnostic_id=5)
        second = self.exporter.export(_report(), "json", diagnostic_id=5)

        self.assertNotEqual(first, second)
        self.assertTrue(Path(first).exists())
        self.assertTrue(Path(second).exists())

    def test_unknown_export_format_is_rejected(self):
        with self.assertRaises(ValueError):
            self.exporter.export(_report(), "exe")

    def test_write_failure_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            exporter = ReportExporter(directory)
            with unittest.mock.patch.object(
                exporter,
                "_write_exclusive",
                side_effect=PermissionError("access denied"),
            ):
                with self.assertRaises(PermissionError):
                    exporter.export(_report(), "txt")


class ReportServiceTests(unittest.TestCase):
    def test_history_survives_export_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            history = HistoryStore(Path(directory) / "history.db")
            exporter = Mock()
            exporter.export.side_effect = PermissionError("write denied")
            service = ReportService(
                builder=Mock(build=Mock(return_value=_report())),
                history=history,
                exporter=exporter,
            )

            with self.assertLogs("hardware_diagnostico", level="ERROR"):
                created = service.create(mode="normal", file_format="pdf")

            self.assertIsNotNone(history.get(created["id"]))
            self.assertIsNone(created["report_path"])
            self.assertIn("write denied", created["export_error"])

    def test_export_saved_updates_database_path(self):
        with tempfile.TemporaryDirectory() as directory:
            history = HistoryStore(Path(directory) / "history.db")
            exporter = ReportExporter(Path(directory) / "output")
            service = ReportService(
                builder=Mock(build=Mock(return_value=_report())),
                history=history,
                exporter=exporter,
            )
            created = service.create()

            path, error = service.export_saved(created["id"], "txt")
            stored = history.get(created["id"])

            self.assertIsNone(error)
            self.assertTrue(Path(path).exists())
            self.assertEqual(stored["report_path"], path)
            self.assertEqual(stored["report"]["report_path"], path)

    def test_reports_menu_defers_database_access_until_a_report_action(self):
            menu = ReportsMenu(Mock())
            with unittest.mock.patch(
                "ui.reports.ReportService",
                side_effect=PermissionError("database unavailable"),
            ):
                self.assertIsNone(menu._service)

    def test_missing_report_id_is_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            service = ReportService(
                history=HistoryStore(Path(directory) / "history.db")
            )

            with self.assertRaisesRegex(LookupError, "No se encontró"):
                service.export_saved(50, "txt")


class ReportBuilderTests(unittest.TestCase):
    def test_builder_reuses_structured_outputs_and_includes_recommendations(self):
        finding = {
            "code": "TEST_ALERT",
            "title": "Test alert",
            "component": "CPU",
            "severity": "ALERTA",
            "description": "Test evidence",
            "recommendation": "Inspect cooling",
        }
        hardware = Mock()
        hardware.system.return_value = {"computer_name": "PC-01", "windows_version": "11"}
        hardware.motherboard.return_value = {"model": "Board"}
        hardware.bios.return_value = {"version": "1.0"}
        run = Mock()
        run.data = {
            "cpu": {"usage_percent": 30},
            "ram": {"usage_percent": 40},
            "storage": {"volumes": [], "physical_drives": []},
            "gpu": {"cards": []},
            "battery": {"detected": False},
        }
        run.results = [SimpleFinding(finding)]
        run.to_dict.return_value = {"summary": {"severity": "ALERTA"}}
        network = Mock()
        network.automatic_diagnostic.return_value = SimpleFindingResult(
            {"severity": "NORMAL", "findings": []}
        )
        security = Mock()
        security.audit.return_value = SimpleFindingResult(
            {"severity": "NORMAL", "findings": []}
        )
        maintenance = Mock()
        maintenance.recommended_maintenance.return_value = SimpleFindingResult(
            {"severity": "NORMAL", "recommendations": []}
        )

        report = ReportBuilder(
            hardware=hardware,
            network=network,
            security=security,
            maintenance=maintenance,
            diagnostic_runner=Mock(return_value=run),
        ).build()

        self.assertEqual(report["equipment"]["computer"], "PC-01")
        self.assertEqual(report["hardware"]["motherboard"]["model"], "Board")
        self.assertEqual(report["summary"]["severity"], "ALERTA")
        self.assertEqual(report["recommendations"][0]["text"], "Inspect cooling")
        network.automatic_diagnostic.assert_called_once_with()
        security.audit.assert_called_once_with()
        maintenance.recommended_maintenance.assert_called_once_with()

    def test_section_errors_do_not_prevent_building_report(self):
        hardware = Mock()
        hardware.system.side_effect = RuntimeError("no system data")
        hardware.motherboard.side_effect = PermissionError("access denied")
        hardware.bios.side_effect = RuntimeError("no bios")
        runner = Mock(side_effect=RuntimeError("hardware failed"))
        report = ReportBuilder(
            hardware=hardware,
            network=Mock(automatic_diagnostic=Mock(side_effect=OSError("network unavailable"))),
            security=Mock(audit=Mock(side_effect=OSError("security unavailable"))),
            maintenance=Mock(recommended_maintenance=Mock(side_effect=OSError("maintenance unavailable"))),
            diagnostic_runner=runner,
        ).build()

        self.assertGreaterEqual(len(report["collection_errors"]), 6)
        self.assertTrue(report["equipment"]["computer"])
        self.assertTrue(report["equipment"]["user"])
        self.assertIn("network", report)
        self.assertFalse(report["network"]["available"])

    def test_comparator_returns_core_metrics_and_numeric_deltas(self):
        first = _report(status="NORMAL")
        second = _report(status="ALERTA")
        second["hardware"]["ram"]["usage_percent"] = 75

        comparison = ReportComparator.compare(first, second)

        self.assertEqual(
            comparison["metrics"]["RAM.usage_percent"]["change"],
            25,
        )
        self.assertEqual(
            comparison["metrics"]["Overall.severity"]["after"],
            "ALERTA",
        )

    def test_text_renderer_and_severity_counts(self):
        report = _report(status="CRÍTICO")
        report["findings"] = [
            {"code": "A", "severity": "ALERTA"},
            {"code": "B", "severity": "CRÍTICO"},
        ]
        from reports.service import _summary

        summary = _summary(report["findings"])
        output = render_text(report)

        self.assertEqual(summary["severity"], "CRÍTICO")
        self.assertEqual(summary["alerts"], 1)
        self.assertEqual(summary["critical"], 1)
        self.assertIn("Equipo: PC-01", output)


class SimpleFinding:
    def __init__(self, data):
        self.data = data

    def to_dict(self):
        return self.data


class SimpleFindingResult(SimpleFinding):
    @property
    def findings(self):
        return [
            SimpleFinding(item) for item in self.data.get("findings", [])
        ]

    @property
    def recommendations(self):
        return [
            SimpleFinding(item)
            for item in self.data.get("recommendations", [])
        ]


if __name__ == "__main__":
    unittest.main()
