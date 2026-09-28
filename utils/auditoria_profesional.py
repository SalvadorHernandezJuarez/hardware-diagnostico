"""
utils/auditoria_profesional.py - Herramientas de diagnóstico para soporte técnico
"""

from modules.security import SecurityAuditor


class AuditoriaProfesional:
    """Recopila información para la auditoría de seguridad sin modificar Windows."""

    @staticmethod
    def auditoria_seguridad() -> dict:
        """Compatibilidad para llamadas existentes; devuelve el nuevo resultado estructurado."""
        return SecurityAuditor().audit().to_dict()

    @staticmethod
    def mostrar(datos: dict, titulo: str):
        print("\n" + "=" * 60)
        print(f"  {titulo}")
        print("=" * 60)
        AuditoriaProfesional._mostrar_valores(datos)

    @staticmethod
    def _mostrar_valores(datos: dict, prefijo=""):
        for clave, valor in datos.items():
            if isinstance(valor, list):
                print(f"\n  {prefijo}{clave}:")
                for indice, elemento in enumerate(valor, 1):
                    print(f"\n    #{indice}")
                    AuditoriaProfesional._mostrar_valores(elemento, "  ")
            elif isinstance(valor, dict):
                print(f"\n  {prefijo}{clave}:")
                AuditoriaProfesional._mostrar_valores(valor, "  ")
            else:
                print(f"  {prefijo}{clave:<32} {valor}")
