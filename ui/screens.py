TITULO = r"""
    ██████╗ ██╗ █████╗  ██████╗ ███╗   ██╗ ██████╗ ███████╗████████╗██╗ ██████╗ ██████╗
    ██╔══██╗██║██╔══██╗██╔════╝ ████╗  ██║██╔═══██╗██╔════╝╚══██╔══╝██║██╔════╝██╔═══██╗
    ██║  ██║██║███████║██║  ███╗██╔██╗ ██║██║   ██║███████╗   ██║   ██║██║     ██║   ██║
    ██║  ██║██║██╔══██║██║   ██║██║╚██╗██║██║   ██║╚════██║   ██║   ██║██║     ██║   ██║
    ██████╔╝██║██║  ██║╚██████╔╝██║ ╚████║╚██████╔╝███████║   ██║   ██║╚██████╗╚██████╔╝
    ╚═════╝ ╚═╝╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═══╝ ╚═════╝ ╚══════╝   ╚═╝   ╚═╝ ╚═════╝ ╚═════╝

                 SOPORTE TÉCNICO PARA WINDOWS
"""


class Screens:
    def __init__(self, estado):
        self.estado = estado
        self.modo_profesional = False

    @staticmethod
    def limpiar():
        import os

        os.system("cls" if os.name == "nt" else "clear")

    def mostrar_encabezado(self):
        self.limpiar()
        modo = "MODO PROFESIONAL" if self.modo_profesional else "MODO NORMAL"
        titulo = TITULO.replace(
            "SOPORTE TÉCNICO PARA WINDOWS",
            f"SOPORTE TÉCNICO PARA WINDOWS [{modo}]",
        )
        if self.modo_profesional:
            print(f"\033[38;5;183m{titulo}\033[0m")
        else:
            print(titulo)

    @staticmethod
    def en_desarrollo(nombre):
        print(f"\n{nombre}: módulo en desarrollo.")
