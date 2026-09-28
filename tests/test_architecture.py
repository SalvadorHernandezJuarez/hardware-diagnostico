import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch

from core.actions import ActionRisk
from core.diagnostic_engine import DiagnosticEngine
from core.permissions import registrar_accion, solicitar_autorizacion
from core.result import DiagnosticResult
from core.severity import Severity
from ui.normal import NormalMenu
from ui.professional import ProfessionalMenu
from ui.screens import Screens
from ui.menu import Menu


class ModuloFalso:
    nombre = "Prueba"

    def obtener(self):
        return {"dato": "disponible"}


class ModuloConError:
    nombre = "Fallo"

    def obtener(self):
        raise RuntimeError("error de prueba")


class ArchitectureTests(unittest.TestCase):
    def test_normal_menu_is_labeled_and_omits_professional_system_tools(self):
        normal_menu = NormalMenu(Mock())
        with (
            patch("builtins.input", return_value=""),
            patch("builtins.print") as printer,
        ):
            normal_menu.mostrar()

        output = " ".join(
            str(call.args[0]) for call in printer.call_args_list if call.args
        )
        self.assertNotIn("Herramientas del sistema", output)
        self.assertNotIn("[15]", output)
        self.assertNotIn("Diagnóstico guiado", output)
        self.assertNotIn("Sistema operativo", output)
        self.assertIn("[3] Diagnóstico general", output)

    def test_professional_menu_groups_technical_tools_under_pro_mode(self):
        professional_menu = ProfessionalMenu(Mock())
        output = io.StringIO()
        with (
            patch("builtins.input", return_value="0"),
            redirect_stdout(output),
        ):
            professional_menu.mostrar()

        rendered = output.getvalue()
        self.assertIn("ADMINISTRACIÓN Y SOPORTE", rendered)
        self.assertIn("Herramientas del sistema", rendered)
        visible_options = [
            line.strip()
            for line in rendered.splitlines()
            if line.strip().startswith("[")
        ]
        self.assertEqual(
            [line.split("]", 1)[0][1:] for line in visible_options],
            [str(number) for number in range(1, 14)] + ["0"],
        )

    def test_all_screens_identify_the_current_mode(self):
        screens = Screens.__new__(Screens)
        screens.estado = Severity.INFORMATION
        screens.modo_profesional = False
        output = io.StringIO()
        with (
            patch.object(Screens, "limpiar"),
            redirect_stdout(output),
        ):
            screens.mostrar_encabezado()
        normal_lines = output.getvalue().splitlines()
        self.assertIn(
            "SOPORTE TÉCNICO PARA WINDOWS [MODO NORMAL]",
            next(line for line in normal_lines if "SOPORTE TÉCNICO" in line),
        )
        self.assertNotIn("MODO NORMAL", normal_lines)
        self.assertNotIn("Equipo:", output.getvalue())
        self.assertNotIn("Windows:", output.getvalue())
        self.assertNotIn("Estado:", output.getvalue())

        screens.modo_profesional = True
        output = io.StringIO()
        with (
            patch.object(Screens, "limpiar"),
            redirect_stdout(output),
        ):
            screens.mostrar_encabezado()
        professional_lines = output.getvalue().splitlines()
        mode_line = next(
            line for line in professional_lines if "SOPORTE TÉCNICO" in line
        )
        self.assertIn(
            "SOPORTE TÉCNICO PARA WINDOWS [MODO PROFESIONAL]", mode_line
        )
        self.assertNotIn("MODO PROFESIONAL", professional_lines)
        self.assertIn("\033[38;5;183m", output.getvalue())

    def test_resultado_serializa_severidad_estandarizada(self):
        resultado = DiagnosticResult(
            code="TEST",
            title="Prueba",
            description="Resultado de prueba",
            severity=Severity.ALERT,
        )

        self.assertEqual(resultado.to_dict()["severity"], "ALERTA")
        self.assertEqual(Severity.CRITICAL.display, "✖ CRÍTICO")

    def test_motor_ejecuta_modulos_y_normaliza_estado(self):
        ejecucion = DiagnosticEngine().ejecutar((ModuloFalso(),), "normal")

        self.assertEqual(ejecucion.data["Prueba"]["dato"], "disponible")
        self.assertEqual(ejecucion.results[0].severity, Severity.INFORMATION)
        self.assertEqual(ejecucion.mode, "normal")

    def test_motor_registra_error_de_modulo_como_critico(self):
        with self.assertLogs("hardware_diagnostico", level="ERROR"):
            ejecucion = DiagnosticEngine().ejecutar((ModuloConError(),), "normal")

        self.assertEqual(ejecucion.severity, Severity.CRITICAL)
        self.assertEqual(ejecucion.results[1].code, "MODULE_ERROR")

    def test_autorizacion_exige_confirmacion_y_modo_profesional(self):
        self.assertTrue(solicitar_autorizacion(ActionRisk.SAFE, "Consultar RAM"))
        self.assertFalse(
            solicitar_autorizacion(
                ActionRisk.CONFIRMATION,
                "Cerrar aplicación",
                input_func=lambda _prompt: "n",
            )
        )
        with self.assertLogs("hardware_diagnostico", level="WARNING"):
            self.assertFalse(
                solicitar_autorizacion(
                    ActionRisk.PROFESSIONAL,
                    "Modificar servicios",
                    modo_profesional=False,
                    input_func=Mock(),
                )
            )
        self.assertTrue(
            solicitar_autorizacion(
                ActionRisk.PROFESSIONAL,
                "Modificar servicios",
                modo_profesional=True,
                input_func=lambda _prompt: "CONFIRMAR",
            )
        )

    def test_registro_de_accion_incluye_riesgo_y_modo(self):
        with self.assertLogs("hardware_diagnostico", level="INFO") as registros:
            registrar_accion(
                "Cerrar aplicación",
                ActionRisk.CONFIRMATION,
                modo_profesional=False,
            )

        self.assertIn("riesgo=CONFIRMACIÓN", registros.output[0])
        self.assertIn("modo=normal", registros.output[0])

    @patch("ui.menu.CatalogoAmpliacion.detectar_equipo", return_value=None)
    def test_navegacion_normal_abre_y_regresa_de_modo_profesional(self, _detectar):
        menu = Menu()
        menu.menu_normal.mostrar = Mock(side_effect=("p", "0"))
        menu.menu_profesional = Mock()

        menu.run()

        menu.menu_profesional.assert_called_once_with()

    @patch("ui.menu.CatalogoAmpliacion.detectar_equipo", return_value=None)
    def test_menu_profesional_abre_mantenimiento_y_regresa(self, _detectar):
        menu = Menu()
        menu.mostrar_menu_profesional = Mock(side_effect=("9", "0"))
        menu.mantenimiento = Mock()

        menu.menu_profesional()

        menu.mantenimiento.assert_called_once_with()

    @patch("ui.menu.CatalogoAmpliacion.detectar_equipo", return_value=None)
    def test_normal_memory_process_entry_opens_maintenance_menu(self, _detectar):
        menu = Menu()
        menu.menu_normal.mostrar = Mock(side_effect=("7", "0"))
        menu.mantenimiento = Mock()

        menu.run()

        menu.mantenimiento.assert_called_once_with()

    @patch("ui.menu.CatalogoAmpliacion.detectar_equipo", return_value=None)
    def test_normal_menu_does_not_dispatch_professional_system_tools(self, _detectar):
        menu = Menu()
        menu.menu_normal.mostrar = Mock(side_effect=("15", "0"))
        menu.herramientas_sistema = Mock()

        with (
            patch("builtins.input", return_value=""),
            patch("ui.menu.logger.warning"),
            patch("builtins.print"),
        ):
            menu.run()

        menu.herramientas_sistema.assert_not_called()

    @patch("ui.menu.CatalogoAmpliacion.detectar_equipo", return_value=None)
    def test_professional_system_tools_entry_opens_module(self, _detectar):
        menu = Menu()
        menu.mostrar_menu_profesional = Mock(side_effect=("11", "0"))
        menu.herramientas_sistema = Mock()

        menu.menu_profesional()

        menu.herramientas_sistema.assert_called_once_with()

    @patch("ui.menu.CatalogoAmpliacion.detectar_equipo", return_value=None)
    def test_normal_advanced_tests_entry_opens_module(self, _detectar):
        menu = Menu()
        menu.menu_normal.mostrar = Mock(side_effect=("4", "0"))
        menu.pruebas_avanzadas = Mock()

        menu.run()

        menu.pruebas_avanzadas.assert_called_once_with()

    @patch("ui.menu.CatalogoAmpliacion.detectar_equipo", return_value=None)
    def test_professional_advanced_tests_entry_opens_module(self, _detectar):
        menu = Menu()
        menu.mostrar_menu_profesional = Mock(side_effect=("3", "0"))
        menu.pruebas_avanzadas = Mock()

        menu.menu_profesional()

        menu.pruebas_avanzadas.assert_called_once_with()

    @patch("ui.menu.CatalogoAmpliacion.detectar_equipo", return_value=None)
    def test_normal_reports_entry_opens_reports_menu(self, _detectar):
        menu = Menu()
        menu.menu_normal.mostrar = Mock(side_effect=("11", "0"))
        menu.reportes = Mock()

        menu.run()

        menu.reportes.assert_called_once_with()

    @patch("ui.menu.CatalogoAmpliacion.detectar_equipo", return_value=None)
    def test_normal_history_entry_opens_sqlite_history(self, _detectar):
        menu = Menu()
        menu.menu_normal.mostrar = Mock(side_effect=("12", "0"))
        menu.historial_diagnosticos = Mock()

        menu.run()

        menu.historial_diagnosticos.assert_called_once_with()

    @patch("ui.menu.CatalogoAmpliacion.detectar_equipo", return_value=None)
    def test_professional_reports_entry_opens_reports_menu(self, _detectar):
        menu = Menu()
        menu.mostrar_menu_profesional = Mock(side_effect=("13", "0"))
        menu.reportes = Mock()

        menu.menu_profesional()

        menu.reportes.assert_called_once_with()

    @patch("ui.menu.CatalogoAmpliacion.detectar_equipo", return_value=None)
    def test_professional_guided_diagnostic_is_option_two(self, _detectar):
        menu = Menu()
        menu.mostrar_menu_profesional = Mock(side_effect=("2", "0"))
        menu.diagnostico_guiado = Mock()

        menu.menu_profesional()

        menu.diagnostico_guiado.assert_called_once_with()

    @patch("ui.menu.CatalogoAmpliacion.detectar_equipo", return_value=None)
    def test_normal_menu_does_not_dispatch_guided_diagnostic(self, _detectar):
        menu = Menu()
        menu.menu_normal.mostrar = Mock(side_effect=("13", "0"))
        menu.diagnostico_guiado = Mock()
        with patch("builtins.input", return_value=""), patch("builtins.print"):
            menu.run()

        menu.diagnostico_guiado.assert_not_called()


if __name__ == "__main__":
    unittest.main()
