"""
modules/base.py - Clase base para todos los módulos de diagnóstico
"""

from abc import ABC, abstractmethod


class ModuloBase(ABC):
    """Clase base que deben heredar todos los módulos de diagnóstico."""

    nombre: str = "modulo"

    @abstractmethod
    def obtener(self) -> dict:
        """Recopila y retorna los datos del módulo como diccionario."""
        pass

    @abstractmethod
    def mostrar(self, datos: dict, profesional: bool = False):
        """Imprime los datos en terminal."""
        pass

    def _seccion(self, titulo: str):
        print(f"\n{'=' * 50}")
        print(f"  {titulo}")
        print(f"{'=' * 50}")

    def _fila(self, clave: str, valor, unidad: str = ""):
        print(f"  {clave:<28} {valor} {unidad}".rstrip())
