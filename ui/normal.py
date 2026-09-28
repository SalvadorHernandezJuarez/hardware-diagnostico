from ui.components import mostrar_menu
from ui.screens import Screens


class NormalMenu:
    def __init__(self, screens: Screens):
        self.screens = screens

    def mostrar(self) -> str:
        self.screens.mostrar_encabezado()
        mostrar_menu(
            (
                ("Información", (("1", "Resumen del equipo"), ("2", "Hardware"))),
                ("Diagnóstico", (("3", "Diagnóstico general"), ("4", "Pruebas"), ("5", "Diagnóstico de red"), ("6", "Diagnóstico de seguridad"))),
                ("Mantenimiento", (("7", "Mantenimiento"), ("8", "Almacenamiento"), ("9", "Batería y energía"), ("10", "Temperatura y rendimiento"))),
                ("Reportes", (("11", "Reportes e historial"), ("12", "Historial de diagnósticos"))),
            ),
            (("P", "Modo profesional"), ("A", "Acerca del programa"), ("0", "Salir")),
        )
        return input("\nSelecciona una opción: ").strip().lower()
