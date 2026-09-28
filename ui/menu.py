"""
ui/menu.py - Interfaz de menú interactivo en terminal
"""

import os
import logging
from datetime import datetime
from modules.sistema import SistemaInfo
from modules.cpu import CPUInfo
from modules.ram import RAMInfo
from modules.disco import DiscoInfo
from modules.bateria import BateriaInfo
from modules.temperatura import TemperaturaInfo
from modules.gpu import GPUInfo
from utils.logger import Logger
from utils.recomendaciones import Recomendaciones
from utils.profesional import AnalisisProfesional
from utils.ampliacion_hardware import CatalogoAmpliacion
from reports.exportar import ExportarPDF
from modules.procesos import ProcesosInfo
from core.diagnostic_engine import DiagnosticEngine
from core.result import DiagnosticResult
from core.severity import Severity
from ui.normal import NormalMenu
from ui.professional import ProfessionalMenu
from ui.screens import Screens
from ui.hardware import HardwareMenu
from ui.components import pausar
from ui.diagnostics import DiagnosticsMenu
from ui.red import NetworkMenu
from ui.security import SecurityMenu
from ui.mantenimiento import MaintenanceMenu
from ui.herramientas_sistema import SystemToolsMenu
from ui.pruebas_avanzadas import AdvancedTestsMenu
from ui.reports import ReportsMenu


logger = logging.getLogger("hardware_diagnostico")


TITULO = r"""
    ██████╗ ██╗ █████╗  ██████╗ ███╗   ██╗ ██████╗ ███████╗████████╗██╗ ██████╗ ██████╗ 
    ██╔══██╗██║██╔══██╗██╔════╝ ████╗  ██║██╔═══██╗██╔════╝╚══██╔══╝██║██╔════╝██╔═══██╗
    ██║  ██║██║███████║██║  ███╗██╔██╗ ██║██║   ██║███████╗   ██║   ██║██║     ██║   ██║
    ██║  ██║██║██╔══██║██║   ██║██║╚██╗██║██║   ██║╚════██║   ██║   ██║██║     ██║   ██║
    ██████╔╝██║██║  ██║╚██████╔╝██║ ╚████║╚██████╔╝███████║   ██║   ██║╚██████╗╚██████╔╝
    ╚═════╝ ╚═╝╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═══╝ ╚═════╝ ╚══════╝   ╚═╝   ╚═╝ ╚═════╝ ╚═════╝

              HERRAMIENTA DE DIAGNÓSTICO DE HARDWARE  |  v2.0
"""

SEPARADOR = "=" * 65


class Menu:
    def __init__(self):
        self.logger = Logger()
        self.modo_profesional = False
        self.estado = Severity.INFORMATION
        self.screens = Screens(self.estado)
        self.menu_normal = NormalMenu(self.screens)
        self.menu_profesional_ui = ProfessionalMenu(self.screens)
        self.hardware_ui = HardwareMenu(
            self.screens, catalog_callback=self.mostrar_ampliacion_hardware
        )
        self.diagnostics_ui = DiagnosticsMenu(
            self.screens,
            self.logger,
            network_diagnostic=lambda professional: self.network_ui.diagnostico_automatico(
                professional
            ),
        )
        self.network_ui = NetworkMenu(self.screens, self.logger)
        self.security_ui = SecurityMenu(self.screens, self.logger)
        self.maintenance_ui = MaintenanceMenu(self.screens, self.logger)
        self.system_tools_ui = SystemToolsMenu(self.screens, self.logger)
        self.advanced_tests_ui = AdvancedTestsMenu(self.screens)
        self.reports_ui = ReportsMenu(
            self.screens,
            advanced_tests_provider=lambda: self.advanced_tests_ui.last_result,
        )

    def _color(self, texto: str, codigo: str = "38;5;183") -> str:
        if not self.modo_profesional:
            return texto
        return f"\033[{codigo}m{texto}\033[0m"

    def limpiar(self):
        self.screens.limpiar()

    def mostrar_encabezado(self):
        self.screens.mostrar_encabezado()

    def diagnostico_completo(self):
        self.mostrar_encabezado()
        resultados = self._ejecutar_diagnostico(
            [
                SistemaInfo(),
                CPUInfo(),
                RAMInfo(),
                DiscoInfo(),
                BateriaInfo(),
                TemperaturaInfo(),
                GPUInfo(),
            ],
            recomendaciones=True,
        )
        if self.modo_profesional:
            AnalisisProfesional.mostrar(resultados)

        print(f"\n{SEPARADOR}")
        exportar = input("\n¿Deseas exportar el diagnóstico a PDF? (s/n): ").strip().lower()
        if exportar == "s":
            ExportarPDF.generar(resultados)

        input("\nPresiona ENTER para volver al menú...")

    def diagnostico_profesional(self):
        self.modo_profesional = True
        self.screens.modo_profesional = True
        self.diagnostico_completo()

    def mostrar_menu_normal(self):
        return self.menu_normal.mostrar()

    def mostrar_menu_profesional(self):
        return self.menu_profesional_ui.mostrar()

    def analisis_salud(self):
        self.mostrar_encabezado()
        resultados = self._ejecutar_diagnostico(
            (CPUInfo(), RAMInfo(), DiscoInfo(), BateriaInfo(), TemperaturaInfo(), GPUInfo())
        )
        AnalisisProfesional.mostrar(resultados)
        input("\nPresiona ENTER para volver al menú profesional...")

    def _ejecutar_diagnostico(self, modulos, recomendaciones=False):
        self.logger.iniciar_sesion()
        modo = "profesional" if self.modo_profesional else "normal"
        ejecucion = DiagnosticEngine().ejecutar(modulos, modo)
        for modulo in modulos:
            datos = ejecucion.data.get(modulo.nombre)
            if datos is None:
                continue
            modulo.mostrar(datos, profesional=self.modo_profesional)
            self.logger.registrar(modulo.nombre, datos)

        for resultado in ejecucion.results:
            print(f"\n  {resultado.severity.display}: {resultado.description}")
            if resultado.recommendation:
                print(f"  Recomendación: {resultado.recommendation}")
        self.estado = ejecucion.severity
        self.screens.estado = self.estado
        self.logger.registrar(
            "Resultado",
            {
                "fecha": ejecucion.timestamp,
                "modo": ejecucion.mode,
                "estado": ejecucion.severity.label,
                "resultados": [resultado.to_dict() for resultado in ejecucion.results],
            },
        )
        logger.info(
            "Diagnóstico ejecutado | modo=%s | módulos=%s | estado=%s",
            modo,
            len(modulos),
            ejecucion.severity.label,
        )
        if recomendaciones:
            Recomendaciones.mostrar(ejecucion.data)
        return ejecucion.data

    def diagnostico_red(self):
        return self.network_ui.mostrar(self.modo_profesional)

    def auditoria_seguridad(self):
        return self.security_ui.mostrar(self.modo_profesional)

    def mantenimiento(self):
        return self.maintenance_ui.mostrar(self.modo_profesional)

    def herramientas_sistema(self):
        return self.system_tools_ui.mostrar(self.modo_profesional)

    def pruebas_avanzadas(self):
        return self.advanced_tests_ui.mostrar(self.modo_profesional)

    def reportes(self):
        return self.reports_ui.mostrar(self.modo_profesional)

    def historial_diagnosticos(self):
        return self.reports_ui.mostrar(self.modo_profesional, initial="history")

    def _registrar_resultado_informativo(self, codigo, titulo, evidencia):
        resultado = DiagnosticResult(
            code=codigo,
            title=titulo,
            description=(
                "La recolección finalizó; revisa la evidencia. "
                "Esta operación no modificó el equipo."
            ),
            evidence=evidencia,
            severity=Severity.INFORMATION,
        )
        self.estado = resultado.severity
        self.screens.estado = self.estado
        self.logger.iniciar_sesion()
        self.logger.registrar(titulo, evidencia)
        self.logger.registrar(
            "Resultado",
            {
                "fecha": datetime.now().astimezone().isoformat(timespec="seconds"),
                "modo": self._modo_actual(),
                "estado": resultado.severity.label,
                "resultados": [resultado.to_dict()],
            },
        )
        logger.info(
            "%s ejecutado | modo=%s | estado=%s",
            titulo,
            self._modo_actual(),
            resultado.severity.label,
        )
        print(f"\n  {resultado.severity.display}: {resultado.description}")

    def _modo_actual(self):
        return "profesional" if self.modo_profesional else "normal"

    def salir_modo_profesional(self):
        self.modo_profesional = False
        self.screens.modo_profesional = False

    def mostrar_hardware(self):
        return self.hardware_ui.mostrar(self.modo_profesional)

    def diagnostico_general(self):
        return self.diagnostics_ui.mostrar(self.modo_profesional)

    def diagnostico_guiado(self):
        return self.diagnostics_ui.mostrar(self.modo_profesional, guided=True)

    def ver_procesos_y_rendimiento(self):
        self.mostrar_encabezado()
        self._ejecutar_diagnostico((CPUInfo(), RAMInfo(), ProcesosInfo()))
        pausar()

    def generar_reporte(self):
        self.mostrar_encabezado()
        resultados = self._ejecutar_diagnostico(
            [
                SistemaInfo(),
                CPUInfo(),
                RAMInfo(),
                DiscoInfo(),
                BateriaInfo(),
                TemperaturaInfo(),
                GPUInfo(),
            ],
            recomendaciones=True,
        )
        logger.info("Generación de reporte solicitada | modo=%s", self._modo_actual())
        ExportarPDF.generar(resultados)

    def resumen_equipo(self):
        self._ejecutar_diagnostico(
            (SistemaInfo(), CPUInfo(), RAMInfo(), DiscoInfo(), GPUInfo(), BateriaInfo())
        )
        pausar()

    def temperatura_y_rendimiento(self):
        self._ejecutar_diagnostico((CPUInfo(), TemperaturaInfo()))
        pausar()

    def acerca_del_programa(self):
        self.mostrar_encabezado()
        print("Hardware Diagnóstico")
        print("Herramienta de soporte técnico para Windows ejecutada desde terminal.")
        print("Modo Normal y Modo Profesional.")
        print("Las opciones todavía no implementadas se indican como en desarrollo.")
        pausar()

    def _en_desarrollo(self, funcionalidad):
        self.mostrar_encabezado()
        self.screens.en_desarrollo(funcionalidad)
        pausar()

    def mostrar_ampliacion_hardware(self):
        catalogo = CatalogoAmpliacion()
        while True:
            self.mostrar_encabezado()
            print(self._color(f"  {SEPARADOR}", "38;5;51"))
            print(self._color("  AMPLIACIÓN DE HARDWARE"))
            print(self._color("  [D] Revisar el equipo actual"))
            print(self._color("  [B] Buscar por marca o modelo"))
            print(self._color("  [I] Importar o actualizar desde Excel"))
            print(self._color("  [P] Crear plantilla Excel", "38;5;51"))
            print(self._color("  [N] Volver al menú profesional"))
            print(self._color(f"  {SEPARADOR}", "38;5;51"))
            opcion = input("\n  Selecciona una opción: ").strip().lower()

            if opcion == "n":
                return
            if opcion == "d":
                self._consultar_equipo_actual(catalogo)
            elif opcion == "b":
                self._buscar_ampliacion(catalogo)
            elif opcion == "i":
                self._importar_catalogo(catalogo)
            elif opcion == "p":
                self._crear_plantilla(catalogo)
            else:
                print("\n  Opción inválida.")
            input("\nPresiona ENTER para continuar...")

    def _consultar_equipo_actual(self, catalogo):
        equipo = catalogo.detectar_equipo()
        if not equipo:
            print("\n  No fue posible detectar marca y modelo mediante WMI.")
            return
        print(f"\n  Equipo detectado: {equipo['marca']} {equipo['modelo']}")
        resultado = catalogo.buscar_equipo(equipo["marca"], equipo["modelo"])
        if resultado:
            self._mostrar_capacidades(resultado)
        else:
            print("  Aún no hay una coincidencia exacta verificada en el catálogo.")
            print("  Busca el modelo manualmente o agrega el dato desde Excel.")

    def _buscar_ampliacion(self, catalogo):
        consulta = input("\n  Marca o modelo para buscar: ").strip()
        resultados = catalogo.buscar(consulta)
        if not resultados:
            print("  No hay coincidencias en el catálogo local.")
            return
        for resultado in resultados:
            self._mostrar_capacidades(resultado)

    @staticmethod
    def _mostrar_capacidades(equipo):
        def mostrar(valor, unidad=""):
            return f"{valor:g} {unidad}".strip() if valor is not None else "Sin dato"

        print(f"\n  {equipo['marca']} {equipo['modelo']}")
        print(f"  RAM máxima: {mostrar(equipo['ram_max_gb'], 'GB')}")
        print(f"  Tipo de RAM: {equipo['tipo_ram'] or 'Sin dato'}")
        print(f"  Ranuras de RAM: {equipo['ranuras_ram'] or 'Sin dato'}")
        print(f"  RAM soldada: {mostrar(equipo['ram_soldada_gb'], 'GB')}")
        print(f"  SSD máximo: {mostrar(equipo['ssd_max_gb'], 'GB')}")
        print(
            "  Interfaces de almacenamiento: "
            f"{equipo['interfaces_almacenamiento'] or 'Sin dato'}"
        )
        print(f"  Notas: {equipo['notas'] or 'Sin dato'}")
        print(f"  Fuente: {equipo['fuente'] or 'Sin dato'}")
        print(f"  Verificado el: {equipo['verificado_el'] or 'Sin dato'}")

    @staticmethod
    def _importar_catalogo(catalogo):
        ruta_predeterminada = os.path.join(catalogo.directorio, "catalogo_ampliacion.xlsx")
        ruta = input(
            "\n  Ruta del archivo Excel "
            f"(ENTER para {ruta_predeterminada}): "
        ).strip().strip('"')
        ruta = ruta or ruta_predeterminada
        try:
            cantidad = catalogo.importar_excel(ruta)
        except (OSError, ValueError) as error:
            print(f"\n  No se pudo importar el catálogo: {error}")
            return
        print(f"\n  Catálogo actualizado: {cantidad} equipos procesados.")

    @staticmethod
    def _crear_plantilla(catalogo):
        sobrescribir = False
        if os.path.exists(catalogo.ruta_plantilla):
            respuesta = input("  La plantilla ya existe. ¿Reemplazarla? (s/n): ")
            if respuesta.strip().lower() != "s":
                return
            sobrescribir = True
        try:
            ruta = catalogo.crear_plantilla(sobrescribir=sobrescribir)
        except OSError as error:
            print(f"\n  No se pudo crear la plantilla: {error}")
            return
        print(f"\n  Plantilla creada: {ruta}")

    def menu_profesional(self):
        self.modo_profesional = True
        self.screens.modo_profesional = True
        logger.info("Modo profesional iniciado")
        while self.modo_profesional:
            opcion = self.mostrar_menu_profesional()
            opciones = {
                "1": self.diagnostico_general,
                "2": self.diagnostico_guiado,
                "3": self.pruebas_avanzadas,
                "4": self.mostrar_hardware,
                "5": self.ver_procesos_y_rendimiento,
                "6": lambda: self.ver_modulo(DiscoInfo),
                "7": self.diagnostico_red,
                "8": self.auditoria_seguridad,
                "9": self.mantenimiento,
                "10": lambda: self._en_desarrollo("Controladores"),
                "11": self.herramientas_sistema,
                "12": self.logger.mostrar_logs,
                "13": self.reportes,
            }
            if opcion == "0":
                self.salir_modo_profesional()
                logger.info("Modo profesional finalizado")
                continue
            accion = opciones.get(opcion)
            if accion:
                accion()
            else:
                print("\n  Opción profesional inválida.")
                input("  Presiona ENTER para continuar...")

    def ver_modulo(self, ModuloClass):
        self.mostrar_encabezado()
        modulo = ModuloClass()
        self._ejecutar_diagnostico((modulo,))
        input("\nPresiona ENTER para volver al menú...")

    def toggle_modo_profesional(self):
        self.menu_profesional()

    def run(self):
        logger.info("Modo normal iniciado")
        while True:
            opcion = self.mostrar_menu_normal()
            opciones = {
                "1": self.resumen_equipo,
                "2": self.mostrar_hardware,
                "3": self.diagnostico_general,
                "4": self.pruebas_avanzadas,
                "5": self.diagnostico_red,
                "6": self.auditoria_seguridad,
                "7": self.mantenimiento,
                "8": lambda: self.ver_modulo(DiscoInfo),
                "9": lambda: self.ver_modulo(BateriaInfo),
                "10": self.temperatura_y_rendimiento,
                "11": self.reportes,
                "12": self.historial_diagnosticos,
                "a": self.acerca_del_programa,
                "p": self.menu_profesional,
            }
            if opcion == "0":
                logger.info("Aplicación finalizada")
                return
            accion = opciones.get(opcion)
            if accion:
                accion()
            else:
                print("\n    Opción inválida.")
                input("  Presiona ENTER para continuar...")
