"""
ui/menu.py - Interfaz de menú interactivo en terminal
"""

import os
import sys
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
from utils.auditoria_profesional import AuditoriaProfesional
from reports.exportar import ExportarPDF


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

    def _color(self, texto: str, codigo: int = 97) -> str:
        if not self.modo_profesional:
            return texto
        return f"\033[{codigo}m{texto}\033[0m"

    def limpiar(self):
        os.system("cls" if os.name == "nt" else "clear")

    def mostrar_encabezado(self):
        self.limpiar()
        print(self._color(TITULO, 94))
        if self.modo_profesional:
            print(self._color("  [ MODO PROFESIONAL ACTIVO ]", 94))
        print()

    def diagnostico_completo(self):
        self.mostrar_encabezado()
        self.logger.iniciar_sesion()

        modulos = [
            SistemaInfo(),
            CPUInfo(),
            RAMInfo(),
            DiscoInfo(),
            BateriaInfo(),
            TemperaturaInfo(),
            GPUInfo(),
        ]

        resultados = {}
        for modulo in modulos:
            datos = modulo.obtener()
            modulo.mostrar(datos, profesional=self.modo_profesional)
            resultados[modulo.nombre] = datos
            self.logger.registrar(modulo.nombre, datos)

        Recomendaciones.mostrar(resultados)
        if self.modo_profesional:
            AnalisisProfesional.mostrar(resultados)

        print(f"\n{SEPARADOR}")
        exportar = input("\n¿Deseas exportar el diagnóstico a PDF? (s/n): ").strip().lower()
        if exportar == "s":
            ExportarPDF.generar(resultados)

        input("\nPresiona ENTER para volver al menú...")

    def diagnostico_profesional(self):
        self.modo_profesional = True
        self.diagnostico_completo()

    def mostrar_menu_normal(self):
        print(f"  {SEPARADOR}")
        print("  1   Diagnóstico Completo")
        print("  2   Ver Sistema Operativo")
        print("  3   Ver CPU")
        print("  4   Ver RAM")
        print("  5   Ver Discos")
        print("  6   Ver Batería")
        print("  7   Ver Temperatura")
        print("  8   Ver GPU")
        print("  9   Ver Logs anteriores")
        print("  [P] Entrar a Modo Profesional")
        print("  [0] Salir")
        print(f"  {SEPARADOR}")

    def mostrar_menu_profesional(self):
        print(self._color(f"  {SEPARADOR}", 94))
        print(self._color("  1   Diagnóstico técnico completo", 94))
        print(self._color("  2   Análisis de salud del equipo", 94))
        print(self._color("  3   Diagnóstico de red", 94))
        print(self._color("  4   Auditoría básica de seguridad", 94))
        print(self._color("  5   Ver información avanzada de CPU", 94))
        print(self._color("  6   Ver información avanzada de discos", 94))
        print(self._color("  7   Ver logs anteriores", 94))
        print(self._color("  [N] Volver al menú normal", 94))
        print(self._color("  [0] Salir", 94))
        print(self._color(f"  {SEPARADOR}", 94))

    def analisis_salud(self):
        self.mostrar_encabezado()
        self.logger.iniciar_sesion()
        resultados = {}
        for modulo in (
            CPUInfo(), RAMInfo(), DiscoInfo(), BateriaInfo(), TemperaturaInfo(), GPUInfo()
        ):
            datos = modulo.obtener()
            resultados[modulo.nombre] = datos
            self.logger.registrar(modulo.nombre, datos)
        AnalisisProfesional.mostrar(resultados)
        input("\nPresiona ENTER para volver al menú profesional...")

    def diagnostico_red(self):
        self.mostrar_encabezado()
        datos = AuditoriaProfesional.diagnostico_red()
        AuditoriaProfesional.mostrar(datos, "DIAGNÓSTICO PROFESIONAL DE RED")
        input("\nPresiona ENTER para volver al menú profesional...")

    def auditoria_seguridad(self):
        self.mostrar_encabezado()
        datos = AuditoriaProfesional.auditoria_seguridad()
        AuditoriaProfesional.mostrar(datos, "AUDITORÍA BÁSICA DE SEGURIDAD")
        input("\nPresiona ENTER para volver al menú profesional...")

    def salir_modo_profesional(self):
        self.modo_profesional = False

    def menu_profesional(self):
        self.modo_profesional = True
        while self.modo_profesional:
            self.mostrar_encabezado()
            self.mostrar_menu_profesional()
            opcion = input("\n  Selecciona una opción profesional: ").strip().lower()
            opciones = {
                "1": self.diagnostico_completo,
                "2": self.analisis_salud,
                "3": self.diagnostico_red,
                "4": self.auditoria_seguridad,
                "5": lambda: self.ver_modulo(CPUInfo),
                "6": lambda: self.ver_modulo(DiscoInfo),
                "7": self.logger.mostrar_logs,
                "n": self.salir_modo_profesional,
            }
            if opcion == "0":
                raise SystemExit
            accion = opciones.get(opcion)
            if accion:
                accion()
            else:
                print("\n  Opción profesional inválida.")
                input("  Presiona ENTER para continuar...")

    def ver_modulo(self, ModuloClass):
        self.mostrar_encabezado()
        modulo = ModuloClass()
        datos = modulo.obtener()
        modulo.mostrar(datos, profesional=self.modo_profesional)
        self.logger.registrar(modulo.nombre, datos)
        input("\nPresiona ENTER para volver al menú...")

    def toggle_modo_profesional(self):
        self.menu_profesional()

    def run(self):
        while True:
            self.mostrar_encabezado()
            self.mostrar_menu_normal()

            opcion = input("\n  Selecciona una opción: ").strip().lower()

            opciones = {
                "1": self.diagnostico_completo,
                "2": lambda: self.ver_modulo(SistemaInfo),
                "3": lambda: self.ver_modulo(CPUInfo),
                "4": lambda: self.ver_modulo(RAMInfo),
                "5": lambda: self.ver_modulo(DiscoInfo),
                "6": lambda: self.ver_modulo(BateriaInfo),
                "7": lambda: self.ver_modulo(TemperaturaInfo),
                "8": lambda: self.ver_modulo(GPUInfo),
                "9": self.logger.mostrar_logs,
                "p": self.menu_profesional,
                "0": lambda: sys.exit(0),
            }

            accion = opciones.get(opcion)
            if accion:
                accion()
            else:
                print("\n    Opción inválida.")
                input("  Presiona ENTER para continuar...")
