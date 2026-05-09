"""
ui/menu.py - Interfaz de menú interactivo en terminal
"""

import os
from modules.sistema import SistemaInfo
from modules.cpu import CPUInfo
from modules.ram import RAMInfo
from modules.disco import DiscoInfo
from modules.bateria import BateriaInfo
from modules.temperatura import TemperaturaInfo
from modules.gpu import GPUInfo
from utils.logger import Logger
from utils.recomendaciones import Recomendaciones
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

    def limpiar(self):
        os.system("cls" if os.name == "nt" else "clear")

    def mostrar_encabezado(self):
        self.limpiar()
        print(TITULO)
        if self.modo_profesional:
            print("  [ MODO PROFESIONAL ACTIVO ]")
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

        print(f"\n{SEPARADOR}")
        exportar = input("\n¿Deseas exportar el diagnóstico a PDF? (s/n): ").strip().lower()
        if exportar == "s":
            ExportarPDF.generar(resultados)

        input("\nPresiona ENTER para volver al menú...")

    def ver_modulo(self, ModuloClass):
        self.mostrar_encabezado()
        modulo = ModuloClass()
        datos = modulo.obtener()
        modulo.mostrar(datos, profesional=self.modo_profesional)
        self.logger.registrar(modulo.nombre, datos)
        input("\nPresiona ENTER para volver al menú...")

    def toggle_modo_profesional(self):
        self.modo_profesional = not self.modo_profesional
        estado = "ACTIVADO" if self.modo_profesional else "DESACTIVADO"
        print(f"\n  Modo profesional {estado}.")
        input("  Presiona ENTER para continuar...")

    def run(self):
        while True:
            self.mostrar_encabezado()
            print(f"  {SEPARADOR}")
            print("  1️⃣   Diagnóstico Completo")
            print("  2️⃣   Ver Sistema Operativo")
            print("  3️⃣   Ver CPU")
            print("  4️⃣   Ver RAM")
            print("  5️⃣   Ver Discos")
            print("  6️⃣   Ver Batería")
            print("  7️⃣   Ver Temperatura")
            print("  8️⃣   Ver GPU")
            print("  9️⃣   Ver Logs anteriores")
            print(f"  🔧   [P] Modo Profesional ({'ON' if self.modo_profesional else 'OFF'})")
            print("  🚪  [0] Salir")
            print(f"  {SEPARADOR}")

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
                "p": self.toggle_modo_profesional,
                "0": lambda: exit(0),
            }

            accion = opciones.get(opcion)
            if accion:
                accion()
            else:
                print("\n  ⚠️  Opción inválida.")
                input("  Presiona ENTER para continuar...")
