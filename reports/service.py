"""Structured report construction, SQLite history, export, and comparison."""

import json
import logging
import platform
import sqlite3
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from core.diagnostic_engine import run_hardware_diagnostics
from core.severity import Severity
from modules.hardware import HardwareInfo
from modules.mantenimiento import MaintenanceDiagnostics
from modules.red import NetworkDiagnostics
from modules.security import SecurityAuditor


logger = logging.getLogger("hardware_diagnostico")
REPORT_FORMATS = ("txt", "json", "pdf")


def project_root():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


class ReportBuilder:
    """Collect existing diagnostic outputs into one serializable report."""

    def __init__(
        self,
        hardware=None,
        network=None,
        security=None,
        maintenance=None,
        diagnostic_runner=None,
        system_provider=None,
    ):
        self.hardware = hardware or HardwareInfo()
        self.network = network or NetworkDiagnostics()
        self.security = security or SecurityAuditor()
        self.maintenance = maintenance or MaintenanceDiagnostics()
        self.diagnostic_runner = diagnostic_runner or run_hardware_diagnostics
        self.system_provider = system_provider

    def build(self, mode="normal", advanced_tests=None):
        created_at = datetime.now().astimezone().isoformat(timespec="seconds")
        errors = []
        try:
            diagnosis_run = self.diagnostic_runner(mode=mode, collector=self.hardware)
            hardware = dict(diagnosis_run.data)
            findings = [finding.to_dict() for finding in diagnosis_run.results]
            diagnosis = diagnosis_run.to_dict(include_data=False)
        except Exception as error:
            logger.exception("No se pudo completar la recolección de hardware")
            errors.append({"component": "hardware", "error": str(error)})
            diagnosis_run = None
            hardware = {}
            findings = []
            diagnosis = {}

        for section, method_name in (
            ("motherboard", "motherboard"),
            ("bios", "bios"),
        ):
            try:
                hardware[section] = getattr(self.hardware, method_name)()
            except Exception as error:
                logger.exception("No se pudo consultar sección de hardware %s", section)
                errors.append({"component": section, "error": str(error)})

        try:
            system = (
                self.system_provider()
                if self.system_provider
                else self.hardware.system()
            )
            hardware["system"] = system
        except Exception as error:
            logger.exception("No se pudo consultar sistema operativo")
            errors.append({"component": "system", "error": str(error)})
            hardware.setdefault("system", {})

        sections = {}
        for name, operation in (
            ("network", self.network.automatic_diagnostic),
            ("security", self.security.audit),
            ("maintenance", self.maintenance.recommended_maintenance),
        ):
            try:
                result = operation()
                sections[name] = _serialize_result(result)
                findings.extend(_result_findings(result))
            except Exception as error:
                logger.exception("No se pudo recopilar sección %s del reporte", name)
                errors.append({"component": name, "error": str(error)})
                sections[name] = {"available": False, "error": str(error)}

        tests = _serialize_result(advanced_tests) if advanced_tests else None
        if advanced_tests:
            findings.extend(_result_findings(advanced_tests))

        findings = _deduplicate_findings(findings)
        summary = _summary(findings)
        user = _safe_user()
        system_data = hardware.get("system")
        if not isinstance(system_data, dict):
            system_data = {}
        computer = (
            system_data.get("computer_name")
            or platform.node()
            or "DESCONOCIDO"
        )
        return {
            "schema_version": 1,
            "created_at": created_at,
            "mode": mode,
            "equipment": {
                "computer": computer,
                "user": user,
                "windows": system_data,
            },
            "summary": summary,
            "hardware": hardware,
            "diagnosis": diagnosis,
            **sections,
            "tests": tests,
            "findings": findings,
            "recommendations": _recommendations(findings),
            "collection_errors": errors,
        }


class HistoryStore:
    """Small local database for report summaries and their structured payloads."""

    def __init__(self, database_path=None):
        self.database_path = Path(database_path or project_root() / "database" / "history.db")
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(str(self.database_path), timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def _session(self):
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self):
        with self._session() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS diagnostics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    computer TEXT NOT NULL,
                    username TEXT NOT NULL,
                    status TEXT NOT NULL,
                    alerts INTEGER NOT NULL,
                    critical INTEGER NOT NULL,
                    report_path TEXT,
                    payload_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_diagnostics_created "
                "ON diagnostics(created_at DESC)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_diagnostics_computer "
                "ON diagnostics(computer COLLATE NOCASE)"
            )

    def save(self, report):
        summary = report.get("summary", {})
        equipment = report.get("equipment", {})
        with self._session() as connection:
            cursor = connection.execute(
                """
                INSERT INTO diagnostics (
                    created_at, computer, username, status, alerts, critical,
                    report_path, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, NULL, ?)
                """,
                (
                    report.get("created_at") or _timestamp(),
                    str(equipment.get("computer") or "DESCONOCIDO"),
                    str(equipment.get("user") or "DESCONOCIDO"),
                    str(summary.get("severity") or Severity.INFORMATION.label),
                    int(summary.get("alerts") or 0),
                    int(summary.get("critical") or 0),
                    "{}",
                ),
            )
            diagnostic_id = int(cursor.lastrowid)
            report["id"] = diagnostic_id
            payload = json.dumps(report, ensure_ascii=False, default=str)
            connection.execute(
                "UPDATE diagnostics SET payload_json=? WHERE id=?",
                (payload, diagnostic_id),
            )
            return diagnostic_id

    def update_report_path(self, diagnostic_id, path):
        with self._session() as connection:
            connection.execute(
                "UPDATE diagnostics SET report_path=? WHERE id=?",
                (str(path), int(diagnostic_id)),
            )

    def replace_payload(self, diagnostic_id, report):
        payload = json.dumps(report, ensure_ascii=False, default=str)
        with self._session() as connection:
            connection.execute(
                "UPDATE diagnostics SET payload_json=? WHERE id=?",
                (payload, int(diagnostic_id)),
            )

    def update_export(self, diagnostic_id, path, report):
        payload = json.dumps(report, ensure_ascii=False, default=str)
        with self._session() as connection:
            connection.execute(
                "UPDATE diagnostics SET report_path=?, payload_json=? WHERE id=?",
                (str(path), payload, int(diagnostic_id)),
            )

    def get(self, diagnostic_id):
        with self._session() as connection:
            row = connection.execute(
                "SELECT * FROM diagnostics WHERE id=?",
                (int(diagnostic_id),),
            ).fetchone()
        return _row_to_dict(row)

    def latest(self):
        with self._session() as connection:
            row = connection.execute(
                "SELECT * FROM diagnostics ORDER BY id DESC LIMIT 1"
            ).fetchone()
        return _row_to_dict(row)

    def list(self, limit=100):
        bounded_limit = min(500, max(1, int(limit)))
        with self._session() as connection:
            rows = connection.execute(
                "SELECT id, created_at, computer, username, status, alerts, "
                "critical, report_path FROM diagnostics "
                "ORDER BY id DESC LIMIT ?",
                (bounded_limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def search(self, computer=None, username=None, date=None, status=None, limit=100):
        clauses = []
        values = []
        for field, value in (
            ("computer", computer),
            ("username", username),
            ("status", status),
        ):
            if value:
                clauses.append(f"{field} LIKE ? COLLATE NOCASE")
                values.append(f"%{value}%")
        if date:
            clauses.append("substr(created_at, 1, 10)=?")
            values.append(str(date)[:10])
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        values.append(min(500, max(1, int(limit))))
        with self._session() as connection:
            rows = connection.execute(
                "SELECT id, created_at, computer, username, status, alerts, "
                "critical, report_path FROM diagnostics"
                + where
                + " ORDER BY id DESC LIMIT ?",
                values,
            ).fetchall()
        return [dict(row) for row in rows]


class ReportExporter:
    def __init__(self, root=None):
        self.root = Path(root or project_root()) / "reports"

    def export(self, report, file_format, diagnostic_id=None):
        normalized = str(file_format).casefold().lstrip(".")
        if normalized not in REPORT_FORMATS:
            raise ValueError("Formato de reporte no permitido.")
        directory = self.root / normalized
        directory.mkdir(parents=True, exist_ok=True)
        created = _filename_timestamp(report.get("created_at"))
        suffix = f"{diagnostic_id or 'report'}_{uuid.uuid4().hex[:8]}"
        path = directory / f"diagnostico_{created}_{suffix}.{normalized}"
        if normalized == "json":
            self._write_exclusive(
                path,
                json.dumps(report, ensure_ascii=False, indent=2, default=str),
            )
        elif normalized == "txt":
            self._write_exclusive(path, render_text(report))
        else:
            self._write_pdf_exclusive(report, path)
        return str(path)

    @staticmethod
    def _write_exclusive(path, content):
        created = False
        try:
            output = path.open("x", encoding="utf-8", newline="\n")
            created = True
            with output:
                output.write(content)
        except Exception:
            if created:
                try:
                    path.unlink()
                except OSError:
                    logger.exception("No se pudo limpiar el archivo incompleto: %s", path)
            raise

    @staticmethod
    def _write_pdf_exclusive(report, path):
        from reports.exportar import ExportarPDF

        path.touch(exist_ok=False)
        try:
            ExportarPDF.generar_reporte_tecnico(report, str(path))
        except Exception:
            logger.exception("No se pudo generar el PDF: %s", path)
            try:
                path.unlink()
            except OSError:
                logger.exception("No se pudo limpiar el PDF incompleto: %s", path)
            raise


class ReportService:
    """Persist a diagnostic before export so export failures never lose history."""

    def __init__(self, builder=None, history=None, exporter=None):
        self.builder = builder or ReportBuilder()
        self.history = history or HistoryStore()
        self.exporter = exporter or ReportExporter()

    def create(self, mode="normal", file_format=None, advanced_tests=None):
        report = self.builder.build(mode=mode, advanced_tests=advanced_tests)
        diagnostic_id = self.history.save(report)
        report["id"] = diagnostic_id
        export_path = None
        export_error = None
        if file_format:
            export_path, export_error = self.export_saved(
                diagnostic_id, file_format
            )
            report["report_path"] = export_path
        return {
            "id": diagnostic_id,
            "report": report,
            "report_path": export_path,
            "export_error": export_error,
        }

    def export_saved(self, diagnostic_id, file_format):
        record = self.history.get(diagnostic_id)
        if not record:
            raise LookupError("No se encontró ese diagnóstico.")
        report = record["report"]
        try:
            export_path = self.exporter.export(
                report,
                file_format,
                diagnostic_id=diagnostic_id,
            )
            report["report_path"] = export_path
            self.history.update_export(diagnostic_id, export_path, report)
            return export_path, None
        except Exception as error:
            logger.exception(
                "El diagnóstico %s se guardó, pero falló la exportación",
                diagnostic_id,
            )
            return None, str(error)


def render_text(report):
    lines = [
        "HARDWARE DIAGNÓSTICO",
        "Reporte Técnico",
        "",
        f"Equipo: {report.get('equipment', {}).get('computer', 'DESCONOCIDO')}",
        f"Usuario: {report.get('equipment', {}).get('user', 'DESCONOCIDO')}",
        f"Fecha: {report.get('created_at', 'DESCONOCIDO')}",
        "",
        "ESTADO GENERAL",
        str(report.get("summary", {}).get("severity", "INFORMACIÓN")),
        "",
    ]
    for key, title in (
        ("hardware", "RESUMEN DEL EQUIPO"),
        ("diagnosis", "DIAGNÓSTICO"),
        ("network", "RED"),
        ("security", "SEGURIDAD"),
        ("maintenance", "MANTENIMIENTO"),
        ("tests", "PRUEBAS"),
        ("recommendations", "RECOMENDACIONES"),
        ("collection_errors", "ERRORES DE RECOLECCIÓN"),
    ):
        lines.append(title)
        lines.extend(_flatten_lines(report.get(key)))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


class ReportComparator:
    """Extract common metrics from report payloads for later comparison."""

    @staticmethod
    def compare(first, second):
        before = _comparison_values(first)
        after = _comparison_values(second)
        metrics = {}
        for key in sorted(set(before) | set(after)):
            old = before.get(key)
            new = after.get(key)
            if isinstance(old, (int, float)) and isinstance(new, (int, float)):
                change = round(new - old, 2)
            else:
                change = None
            metrics[key] = {
                "before": old,
                "after": new,
                "change": change,
            }
        return {
            "first_id": first.get("id"),
            "second_id": second.get("id"),
            "metrics": metrics,
        }


def _comparison_values(report):
    hardware = report.get("hardware") or {}
    cpu = hardware.get("cpu") or {}
    ram = hardware.get("ram") or {}
    storage = hardware.get("storage") or {}
    gpu = hardware.get("gpu") or {}
    battery = hardware.get("battery") or {}
    drives = storage.get("physical_drives") or []
    volumes = storage.get("volumes") or []
    cards = gpu.get("cards") or []
    network = report.get("network") or {}
    return {
        "CPU.usage_percent": cpu.get("usage_percent"),
        "CPU.temperature_c": cpu.get("temperature_c"),
        "RAM.usage_percent": ram.get("usage_percent"),
        "RAM.available_gb": ram.get("available_gb"),
        "Storage.first_volume_free_gb": (
            round(volumes[0]["free_bytes"] / (1024 ** 3), 2)
            if volumes and isinstance(volumes[0].get("free_bytes"), (int, float))
            else None
        ),
        "Storage.first_drive_health": drives[0].get("health") if drives else None,
        "Storage.first_drive_temperature_c": (
            drives[0].get("temperature_c") if drives else None
        ),
        "GPU.first_usage_percent": cards[0].get("usage_percent") if cards else None,
        "GPU.first_temperature_c": cards[0].get("temperature_c") if cards else None,
        "Battery.health_percent": battery.get("health_percent"),
        "Battery.percentage": battery.get("percentage"),
        "Network.severity": network.get("severity"),
        "Network.diagnosis": network.get("diagnosis"),
        "Overall.severity": (report.get("summary") or {}).get("severity"),
    }


def _summary(findings):
    counts = {
        Severity.NORMAL: 0,
        Severity.INFORMATION: 0,
        Severity.ALERT: 0,
        Severity.CRITICAL: 0,
    }
    for finding in findings:
        severity = _severity(finding.get("severity"))
        counts[severity] += 1
    actionable = [level for level in counts if level >= Severity.ALERT and counts[level]]
    if actionable:
        overall = max(actionable)
    elif counts[Severity.NORMAL]:
        overall = Severity.NORMAL
    else:
        overall = Severity.INFORMATION
    return {
        "severity": overall.label,
        "alerts": counts[Severity.ALERT],
        "critical": counts[Severity.CRITICAL],
        "problems": counts[Severity.ALERT] + counts[Severity.CRITICAL],
        "information": counts[Severity.INFORMATION],
        "normal": counts[Severity.NORMAL],
        "findings_count": len(findings),
    }


def _severity(value):
    if isinstance(value, Severity):
        return value
    normalized = str(value or "").upper()
    for item in Severity:
        if normalized in (item.label.upper(), item.name):
            return item
    return Severity.INFORMATION


def _result_findings(result):
    if hasattr(result, "diagnostic") and hasattr(result.diagnostic, "to_dict"):
        return [result.diagnostic.to_dict()]
    findings = getattr(result, "findings", None)
    if findings is None:
        findings = getattr(result, "recommendations", None)
    if findings is None and hasattr(result, "results"):
        serialized = []
        for item in result.results:
            if hasattr(item, "diagnostic") and hasattr(item.diagnostic, "to_dict"):
                serialized.append(item.diagnostic.to_dict())
            elif hasattr(item, "to_dict"):
                serialized.append(item.to_dict())
        return serialized
    return [
        item.to_dict() if hasattr(item, "to_dict") else item
        for item in (findings or [])
        if isinstance(item, dict) or hasattr(item, "to_dict")
    ]


def _serialize_result(result):
    if result is None:
        return None
    if hasattr(result, "to_dict"):
        return result.to_dict()
    if isinstance(result, dict):
        return result
    return {"value": str(result)}


def _deduplicate_findings(findings):
    unique = {}
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        code = str(finding.get("code") or "")
        identity = (code, str(finding.get("title") or ""))
        unique.setdefault(identity, finding)
    return list(unique.values())


def _recommendations(findings):
    recommendations = []
    seen = set()
    for finding in findings:
        value = str(finding.get("recommendation") or "").strip()
        if value and value not in seen:
            recommendations.append(
                {
                    "code": finding.get("code"),
                    "component": finding.get("component"),
                    "text": value,
                }
            )
            seen.add(value)
    return recommendations


def _flatten_lines(value, prefix=""):
    lines = []
    if isinstance(value, dict):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            lines.extend(_flatten_lines(item, path))
    elif isinstance(value, list):
        if not value:
            lines.append(f"{prefix}: []")
        else:
            for index, item in enumerate(value, 1):
                lines.extend(_flatten_lines(item, f"{prefix}[{index}]"))
    elif value is not None:
        rendered = json.dumps(value, ensure_ascii=False, default=str) if isinstance(
            value, (bool, int, float)
        ) else str(value)
        lines.append(f"{prefix}: {rendered}")
    else:
        lines.append(f"{prefix}: No disponible")
    return lines


def _row_to_dict(row):
    if row is None:
        return None
    result = dict(row)
    result["report"] = json.loads(result.pop("payload_json"))
    return result


def _filename_timestamp(value):
    raw = str(value or _timestamp())
    return "".join(character for character in raw if character.isdigit())[:14] or "diagnostico"


def _timestamp():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _safe_user():
    try:
        import getpass

        return getpass.getuser() or "DESCONOCIDO"
    except (OSError, RuntimeError):
        return "DESCONOCIDO"
