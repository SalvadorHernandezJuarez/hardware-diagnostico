"""CMD menus for report generation, search, history, comparison, and export."""

import json
import logging
import sqlite3
from datetime import datetime

from core.severity import Severity
from reports.service import REPORT_FORMATS, ReportService, ReportComparator
from ui.components import pausar


logger = logging.getLogger("hardware_diagnostico")

FORMAT_LABELS = {"1": "txt", "2": "pdf", "3": "json"}
STATUS_MARKERS = {
    "NORMAL": "✓",
    "INFORMACIÓN": "ℹ",
    "ALERTA": "⚠",
    "CRÍTICO": "✖",
}


class ReportsMenu:
    def __init__(self, screens, service=None, advanced_tests_provider=None):
        self.screens = screens
        self._service = service
        self.advanced_tests_provider = advanced_tests_provider or (lambda: None)
        self.last_report_id = None

    @property
    def service(self):
        if self._service is None:
            self._service = ReportService()
        return self._service

    def mostrar(self, professional=False, initial="menu"):
        if initial == "history":
            self._history(professional)
            return
        handlers = {
            "1": self._generate,
            "2": self._latest,
            "3": self._history,
            "4": self._search,
            "5": self._compare,
            "6": self._export,
        }
        while True:
            self.screens.mostrar_encabezado()
            self._show_menu()
            option = input("\nSelecciona una opción: ").strip()
            if option == "0":
                return
            handler = handlers.get(option)
            if handler:
                handler(professional)
            else:
                print("Opción inválida.")
                pausar()

    @staticmethod
    def _show_menu():
        print("╔════════════════════════════════════╗")
        print("║           REPORTES                 ║")
        print("╚════════════════════════════════════╝")
        for number, label in (
            ("1", "Generar reporte actual"),
            ("2", "Ver último diagnóstico"),
            ("3", "Historial de diagnósticos"),
            ("4", "Buscar diagnóstico"),
            ("5", "Comparar diagnósticos"),
            ("6", "Exportar reporte"),
            ("0", "Volver"),
        ):
            print(f"[{number}] {label}")

    def _generate(self, professional):
        print("\nRecopilando información para el reporte...")
        try:
            result = self.service.create(
                mode="profesional" if professional else "normal",
                advanced_tests=self.advanced_tests_provider(),
            )
        except Exception:
            logger.exception("No se pudo guardar el diagnóstico en el historial SQLite")
            print("No fue posible guardar el diagnóstico en el historial.")
            pausar()
            return

        self.last_report_id = result["id"]
        report = result["report"]
        self._show_report_summary(report, professional)
        print(
            "\nEl diagnóstico quedó guardado en el historial SQLite "
            f"(ID {result['id']}) antes de exportar."
        )
        file_format = self._choose_format()
        if not file_format:
            self._pause()
            return
        path, error = self.service.export_saved(result["id"], file_format)
        if path:
            print(f"Reporte {file_format.upper()} generado: {path}")
        else:
            print(f"No se pudo generar el reporte: {error}")
            print("El diagnóstico sigue disponible en el historial SQLite.")
        self._pause()

    def _latest(self, professional):
        try:
            record = self.service.history.latest()
        except (OSError, sqlite3.Error):
            logger.exception("No se pudo consultar el último diagnóstico")
            print("No fue posible consultar la base de datos del historial.")
            self._pause()
            return
        if not record:
            print("Todavía no hay diagnósticos guardados.")
        else:
            self._show_report(record["report"], professional)
        self._pause()

    def _history(self, professional):
        try:
            records = self.service.history.list()
        except (OSError, sqlite3.Error):
            logger.exception("No se pudo consultar el historial de diagnósticos")
            print("No fue posible consultar la base de datos del historial.")
            self._pause()
            return
        if not records:
            print("No hay diagnósticos en el historial.")
            self._pause()
            return
        self._show_records(records)
        selection = input("\nID del diagnóstico para ver detalles (0 = volver): ").strip()
        if selection == "0":
            return
        record = self._get_by_id(selection)
        if record:
            self._show_report(record["report"], professional)
        self._pause()

    def _search(self, professional):
        print("Buscar por: [1] Equipo [2] Usuario [3] Fecha [4] Estado")
        field = input("Campo: ").strip()
        query = input("Valor de búsqueda: ").strip()
        if not query:
            print("La búsqueda está vacía.")
            self._pause()
            return
        filters = {
            "1": {"computer": query},
            "2": {"username": query},
            "3": {"date": _normalize_date(query)},
            "4": {"status": query},
        }.get(field)
        if filters is None:
            print("Campo de búsqueda inválido.")
            self._pause()
            return
        try:
            records = self.service.history.search(**filters)
        except (ValueError, OSError, sqlite3.Error):
            logger.exception("Falló la búsqueda de reportes")
            print("No fue posible consultar el historial.")
            self._pause()
            return
        if not records:
            print("No se encontraron diagnósticos coincidentes.")
        else:
            self._show_records(records)
            selection = input("\nID para ver detalles (ENTER = volver): ").strip()
            if selection:
                record = self._get_by_id(selection)
                if record:
                    self._show_report(record["report"], professional)
        self._pause()

    def _compare(self, professional):
        try:
            records = self.service.history.list()
        except (OSError, sqlite3.Error):
            logger.exception("No se pudo cargar el historial para comparar")
            print("No fue posible consultar la base de datos del historial.")
            self._pause()
            return
        if len(records) < 2:
            print("Se requieren al menos dos diagnósticos para comparar.")
            self._pause()
            return
        self._show_records(records)
        first_id = input("ID del diagnóstico anterior: ").strip()
        second_id = input("ID del diagnóstico reciente: ").strip()
        first = self._get_by_id(first_id)
        second = self._get_by_id(second_id)
        if not first or not second:
            self._pause()
            return
        comparison = ReportComparator.compare(first["report"], second["report"])
        print("\nCOMPARACIÓN")
        print("─" * 76)
        for metric, values in comparison["metrics"].items():
            change = (
                f" (cambio: {values['change']:+g})"
                if isinstance(values.get("change"), (int, float))
                else ""
            )
            print(
                f"{metric:<38} {_value(values.get('before'))} → "
                f"{_value(values.get('after'))}{change}"
            )
        if professional:
            print(f"\nEvidencia: {json.dumps(comparison, ensure_ascii=False, default=str)}")
        self._pause()

    def _export(self, professional):
        try:
            records = self.service.history.list()
        except (OSError, sqlite3.Error):
            logger.exception("No se pudo cargar el historial para exportar")
            print("No fue posible consultar la base de datos del historial.")
            self._pause()
            return
        if not records:
            print("No hay diagnósticos para exportar.")
            self._pause()
            return
        self._show_records(records)
        selection = input("\nID del diagnóstico a exportar: ").strip()
        record = self._get_by_id(selection)
        if not record:
            self._pause()
            return
        file_format = self._choose_format()
        if not file_format:
            self._pause()
            return
        path, error = self.service.export_saved(record["id"], file_format)
        if path:
            print(f"Reporte {file_format.upper()} generado: {path}")
        else:
            print(f"No se pudo generar el reporte: {error}")
            print("El diagnóstico permanece guardado en SQLite.")
        self._pause()

    @staticmethod
    def _choose_format():
        print("\nFormato: [1] TXT [2] PDF [3] JSON [0] Cancelar")
        selected = input("Selecciona formato: ").strip()
        if selected == "0":
            return None
        result = FORMAT_LABELS.get(selected)
        if result not in REPORT_FORMATS:
            print("Formato no válido.")
            return None
        return result

    def _get_by_id(self, value):
        if not str(value).isdigit():
            print("ID inválido.")
            return None
        try:
            record = self.service.history.get(int(value))
        except (ValueError, OSError, sqlite3.Error):
            logger.exception("No se pudo consultar el historial")
            print("No fue posible consultar el historial.")
            return None
        if record is None:
            print("No se encontró ese diagnóstico.")
        return record

    def _show_records(self, records):
        print(f"\n{'ID':<5} {'FECHA':<18} {'EQUIPO':<24} {'ESTADO'}")
        print("─" * 76)
        for record in records:
            try:
                date = datetime.fromisoformat(record["created_at"]).strftime(
                    "%d/%m/%Y %H:%M"
                )
            except (ValueError, TypeError):
                date = str(record.get("created_at") or "DESCONOCIDO")
            status = record.get("status") or "INFORMACIÓN"
            marker = STATUS_MARKERS.get(status.upper(), "ℹ")
            print(
                f"{record['id']:<5} {date:<18} "
                f"{str(record.get('computer') or 'DESCONOCIDO')[:23]:<24} "
                f"{marker} {status}"
            )

    def _show_report_summary(self, report, professional):
        summary = report.get("summary", {})
        print("\nRESUMEN DEL REPORTE")
        print("─" * 48)
        print(f"Fecha: {report.get('created_at')}")
        print(f"Equipo: {report.get('equipment', {}).get('computer')}")
        print(f"Estado: {summary.get('severity')}")
        print(f"Alertas: {summary.get('alerts', 0)}")
        print(f"Críticos: {summary.get('critical', 0)}")
        for finding in report.get("findings", []):
            if finding.get("severity") in ("ALERTA", "CRÍTICO"):
                print(f"{finding.get('severity')}: {finding.get('title')}")
        for recommendation in report.get("recommendations", [])[:8]:
            print(f"Recomendación: {recommendation['text']}")
        if professional:
            print(f"Hallazgos: {summary.get('findings_count', 0)}")

    def _show_report(self, report, professional):
        self._show_report_summary(report, professional)
        if professional:
            print("\nDETALLE TÉCNICO")
            print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
        else:
            findings = report.get("findings", [])
            if findings:
                print("\nProblemas principales:")
                for finding in findings:
                    if finding.get("severity") in ("ALERTA", "CRÍTICO"):
                        print(f"- {finding.get('title')}: {finding.get('description')}")
            if report.get("report_path"):
                print(f"\nArchivo: {report['report_path']}")

    @staticmethod
    def _pause():
        pausar()


def _normalize_date(value):
    for format_string in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, format_string).date().isoformat()
        except ValueError:
            continue
    return value[:10]


def _value(value):
    return "No disponible" if value is None else str(value)
