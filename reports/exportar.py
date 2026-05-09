"""
reports/exportar.py - Exportación del diagnóstico a PDF
Requiere: reportlab
"""

import os
from datetime import datetime

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
    REPORTLAB_DISPONIBLE = True
except ImportError:
    REPORTLAB_DISPONIBLE = False


RUTA_REPORTES = os.path.join(os.path.dirname(os.path.dirname(__file__)), "reports")


class ExportarPDF:

    @staticmethod
    def generar(resultados: dict):
        if not REPORTLAB_DISPONIBLE:
            print("\n  ⚠️  reportlab no está instalado.")
            print("  Instálalo con: pip install reportlab")
            input("\n  Presiona ENTER para continuar...")
            return

        os.makedirs(RUTA_REPORTES, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        nombre = f"diagnostico_{timestamp}.pdf"
        ruta = os.path.join(RUTA_REPORTES, nombre)

        doc = SimpleDocTemplate(
            ruta,
            pagesize=A4,
            rightMargin=2*cm,
            leftMargin=2*cm,
            topMargin=2*cm,
            bottomMargin=2*cm,
        )

        estilos = getSampleStyleSheet()
        historia = []

        # Título
        titulo_estilo = ParagraphStyle(
            "Titulo",
            parent=estilos["Title"],
            fontSize=20,
            textColor=colors.HexColor("#1a1a2e"),
            spaceAfter=6,
        )
        sub_estilo = ParagraphStyle(
            "Sub",
            parent=estilos["Normal"],
            fontSize=10,
            textColor=colors.gray,
            spaceAfter=16,
        )
        seccion_estilo = ParagraphStyle(
            "Seccion",
            parent=estilos["Heading2"],
            fontSize=13,
            textColor=colors.HexColor("#16213e"),
            spaceBefore=14,
            spaceAfter=6,
        )

        historia.append(Paragraph("DIAGNÓSTICO DE HARDWARE", titulo_estilo))
        historia.append(Paragraph(f"Generado el {datetime.now().strftime('%d/%m/%Y a las %H:%M:%S')}", sub_estilo))
        historia.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#cccccc")))
        historia.append(Spacer(1, 12))

        for modulo, datos in resultados.items():
            historia.append(Paragraph(f"▸ {modulo.upper()}", seccion_estilo))

            filas = ExportarPDF._aplanar(datos)
            if filas:
                tabla_datos = [[Paragraph(f"<b>{k}</b>", estilos["Normal"]),
                                Paragraph(str(v), estilos["Normal"])]
                               for k, v in filas]

                tabla = Table(tabla_datos, colWidths=[6*cm, 11*cm])
                tabla.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f0f4ff")),
                    ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, colors.HexColor("#f9f9f9")]),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#dddddd")),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ]))
                historia.append(tabla)

            historia.append(Spacer(1, 8))

        doc.build(historia)
        print(f"\n  ✅ PDF exportado correctamente:")
        print(f"  📄 {ruta}")
        input("\n  Presiona ENTER para continuar...")

    @staticmethod
    def _aplanar(datos, prefijo="") -> list:
        """Convierte un dict (posiblemente anidado) en lista de (clave, valor) para la tabla."""
        filas = []
        if isinstance(datos, dict):
            for k, v in datos.items():
                if k == "slots" and isinstance(v, list):
                    for i, slot in enumerate(v, 1):
                        filas += ExportarPDF._aplanar(slot, prefijo=f"Módulo #{i} - ")
                elif k == "gpus" and isinstance(v, list):
                    for i, gpu in enumerate(v, 1):
                        filas += ExportarPDF._aplanar(gpu, prefijo=f"GPU #{i} - ")
                elif k in ("discos_fisicos", "particiones") and isinstance(v, list):
                    for i, item in enumerate(v, 1):
                        filas += ExportarPDF._aplanar(item, prefijo=f"#{i} - ")
                elif isinstance(v, dict):
                    filas += ExportarPDF._aplanar(v, prefijo=f"{k} - ")
                else:
                    filas.append((f"{prefijo}{k}", str(v)))
        return filas
