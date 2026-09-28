"""Terminal interface for bounded advanced hardware tests."""

import logging
import threading

from core.severity import Severity
from modules.pruebas_avanzadas import (
    ADVANCED_TEST_THRESHOLDS,
    AdvancedDiagnostics,
)
from ui.components import pausar


logger = logging.getLogger("hardware_diagnostico")

MENU_OPTIONS = (
    ("1", "Prueba de CPU"),
    ("2", "Prueba de RAM"),
    ("3", "Prueba de almacenamiento"),
    ("4", "Prueba de GPU"),
    ("5", "Prueba de batería"),
    ("6", "Prueba de red"),
    ("7", "Prueba de estabilidad"),
    ("8", "Ejecutar diagnóstico completo"),
    ("0", "Volver"),
)


class AdvancedTestsMenu:
    def __init__(self, screens, diagnostics=None):
        self.screens = screens
        self.diagnostics = diagnostics or AdvancedDiagnostics()
        self.last_result = None

    def mostrar(self, professional=False):
        handlers = {
            "1": self._cpu,
            "2": self._ram,
            "3": self._storage,
            "4": self._gpu,
            "5": self._battery,
            "6": self._network,
            "7": self._stability,
            "8": self._complete,
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
        print("║        PRUEBAS AVANZADAS           ║")
        print("╚════════════════════════════════════╝")
        for number, label in MENU_OPTIONS:
            print(f"[{number}] {label}")

    def _cpu(self, professional):
        seconds = input(
            f"Duración de carga controlada en segundos "
            f"(1-{ADVANCED_TEST_THRESHOLDS['cpu_test_max_seconds']}, predeterminado 5): "
        ).strip()
        seconds = seconds or 5
        if not self._confirm_load(
            "La prueba genera una carga moderada en un hilo durante un periodo limitado. "
            "Puede elevar temporalmente el uso y la temperatura."
        ):
            self._pause()
            return
        cancel = threading.Event()
        result = self._execute(
            "CPU",
            lambda: self.diagnostics.cpu_test(seconds, cancel_event=cancel),
            cancel,
        )
        if result:
            self._present(result, professional)
        self._pause()

    def _ram(self, professional):
        result = self._execute("RAM", self.diagnostics.ram_test)
        if result:
            self._present(result, professional)
        self._pause()

    def _storage(self, professional):
        result = self._execute("almacenamiento", self.diagnostics.storage_test)
        if result:
            self._present(result, professional)
        self._pause()

    def _gpu(self, professional):
        result = self._execute("GPU", self.diagnostics.gpu_test)
        if result:
            self._present(result, professional)
        self._pause()

    def _battery(self, professional):
        result = self._execute("batería", self.diagnostics.battery_test)
        if result:
            self._present(result, professional)
        self._pause()

    def _network(self, professional):
        result = self._execute("red", self.diagnostics.network_test)
        if result:
            self._present(result, professional)
        self._pause()

    def _stability(self, professional):
        seconds = input(
            f"Duración en segundos "
            f"({ADVANCED_TEST_THRESHOLDS['stability_min_seconds']}-"
            f"{ADVANCED_TEST_THRESHOLDS['stability_max_seconds']}, predeterminado 30): "
        ).strip()
        seconds = seconds or 30
        if not self._confirm_load(
            "La prueba supervisa CPU, memoria, temperaturas, GPU y disco. "
            "No aplica overclock ni una carga sintética sostenida. "
            "Puede cancelarse con Ctrl+C."
        ):
            self._pause()
            return
        cancel = threading.Event()
        result = self._execute(
            "estabilidad",
            lambda: self.diagnostics.stability_test(
                seconds,
                cancel_event=cancel,
            ),
            cancel,
        )
        if result:
            self._present(result, professional)
        self._pause()

    def _complete(self, professional):
        if not self._confirm_load(
            "El diagnóstico completo ejecuta CPU con carga moderada, una prueba "
            "pequeña de RAM, lectura/escritura temporal y consultas de hardware/red. "
            "Puede tardar y elevar temporalmente el uso del procesador."
        ):
            self._pause()
            return
        cancel = threading.Event()
        run = self._execute(
            "diagnóstico completo",
            lambda: self.diagnostics.complete_test(cancel_event=cancel),
            cancel,
        )
        if run:
            self.last_result = run
            self.screens.estado = run.severity
            print("PRUEBAS AVANZADAS\n")
            for result in run.results:
                print(f"{result.diagnostic.component:<18} {result.severity.display}")
                if result.severity >= Severity.ALERT:
                    print(f"  {result.diagnostic.description}")
                    if result.diagnostic.recommendation:
                        print(f"  Recomendación: {result.diagnostic.recommendation}")
            print(f"\nRESULTADO GENERAL: {run.severity.display}")
            if professional:
                print(f"Inicio: {run.started_at}")
                print(f"Fin: {run.finished_at}")
                print(f"Duración total: {run.duration_seconds:.2f} s")
                print(f"Cancelado: {'Sí' if run.cancelled else 'No'}")
                for result in run.results:
                    self._show_technical(result)
        self._pause()

    def _execute(self, label, operation, cancel_event=None):
        print(f"\nIniciando prueba: {label}. Ctrl+C cancela cuando sea posible.")
        try:
            result = operation()
            self.last_result = result
            if hasattr(result, "severity"):
                self.screens.estado = result.severity
            return result
        except KeyboardInterrupt:
            if cancel_event:
                cancel_event.set()
            print("\nCancelación solicitada; deteniendo la prueba de forma segura.")
            return None
        except Exception:
            logger.exception("Falló la prueba avanzada: %s", label)
            print("No fue posible completar esta prueba. El resto del programa sigue disponible.")
            return None

    def _present(self, result, professional):
        diagnostic = result.diagnostic
        self.screens.estado = diagnostic.severity
        print(f"\n{diagnostic.title}")
        print(f"Resultado: {diagnostic.severity.display}")
        print(f"Problema: {diagnostic.description}")
        if diagnostic.recommendation:
            print(f"Recomendación: {diagnostic.recommendation}")
        if professional:
            self._show_technical(result)

    @staticmethod
    def _show_technical(result):
        diagnostic = result.diagnostic
        print(f"\nCódigo: {diagnostic.code}")
        print(f"Componente: {diagnostic.component}")
        print(f"Inicio: {result.started_at}")
        print(f"Fin: {result.finished_at}")
        print(f"Duración: {result.duration_seconds:.2f} s")
        print(f"Confianza: {diagnostic.confidence}")
        print(f"Mediciones: {result.measurements}")
        if result.errors:
            print(f"Errores: {result.errors}")

    @staticmethod
    def _confirm_load(warning):
        print(f"\nADVERTENCIA: {warning}")
        return input("¿Iniciar? [s/N]: ").strip().casefold() == "s"

    @staticmethod
    def _pause():
        pausar()
