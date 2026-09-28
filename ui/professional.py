from ui.components import mostrar_menu
from ui.screens import Screens


class ProfessionalMenu:
    def __init__(self, screens: Screens):
        self.screens = screens

    def mostrar(self) -> str:
        self.screens.mostrar_encabezado()
        mostrar_menu(
            (
                ("Diagnóstico técnico", (
                    ("1", "Diagnóstico avanzado"),
                    ("2", "Diagnóstico guiado"),
                    ("3", "Pruebas avanzadas"),
                )),
                ("Equipo", (
                    ("4", "Hardware y catálogo de ampliación"),
                    ("5", "Procesos y rendimiento"),
                    ("6", "Almacenamiento"),
                )),
                ("Administración y soporte", (
                    ("7", "Red"),
                    ("8", "Seguridad"),
                    ("9", "Mantenimiento"),
                    ("10", "Controladores (en desarrollo)"),
                    ("11", "Herramientas del sistema"),
                )),
                ("Reportes", (
                    ("12", "Registro de diagnóstico"),
                    ("13", "Reportes e historial"),
                )),
            ),
            (("0", "Volver a modo normal"),),
        )
        return input("\nSelecciona una opción profesional: ").strip().lower()
