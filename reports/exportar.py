"""
reports/exportar.py - Exportación del diagnóstico a PDF
Requiere: reportlab
"""

import os
import sys
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


if getattr(sys, "frozen", False):
    RUTA_PROYECTO = os.path.dirname(sys.executable)
else:
    RUTA_PROYECTO = os.path.dirname(os.path.dirname(__file__))

RUTA_REPORTES = os.path.join(RUTA_PROYECTO, "reports")


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
            rightMargin=1.8 * cm,
            leftMargin=1.8 * cm,
            topMargin=1.6 * cm,
            bottomMargin=1.6 * cm,
        )

        estilos = getSampleStyleSheet()
        historia = []
        azul = colors.HexColor("#1e88e5")
        azul_oscuro = colors.HexColor("#0d47a1")
        gris = colors.HexColor("#eef4ff")
        gris_linea = colors.HexColor("#dfe8f7")

        titulo_estilo = ParagraphStyle(
            "Titulo",
            parent=estilos["Title"],
            fontName="Helvetica-Bold",
            fontSize=22,
            textColor=azul_oscuro,
            spaceAfter=4,
            alignment=1,
        )
        sub_estilo = ParagraphStyle(
            "Sub",
            parent=estilos["Normal"],
            fontSize=9,
            textColor=colors.HexColor("#5f6c7b"),
            spaceAfter=12,
            alignment=1,
        )
        seccion_estilo = ParagraphStyle(
            "Seccion",
            parent=estilos["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=12,
            textColor=azul,
            spaceBefore=14,
            spaceAfter=8,
            borderPadding=0,
        )
        info_estilo = ParagraphStyle(
            "Info",
            parent=estilos["Normal"],
            fontSize=9,
            textColor=colors.black,
            leading=12,
        )

        historia.append(Paragraph("DIAGNÓSTICO DE HARDWARE", titulo_estilo))
        historia.append(Paragraph(f"Generado el {datetime.now().strftime('%d/%m/%Y a las %H:%M:%S')}", sub_estilo))
        historia.append(HRFlowable(width="100%", thickness=1.4, color=azul, spaceBefore=0, spaceAfter=8))

        resumen = ExportarPDF._resumen(resultados)
        if resumen:
            tabla_resumen = Table(resumen, colWidths=[5 * cm, 11 * cm])
            tabla_resumen.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), gris),
                ("GRID", (0, 0), (-1, -1), 0.5, gris_linea),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("TEXTCOLOR", (0, 0), (-1, 0), azul_oscuro),
            ]))
            historia.append(Paragraph("RESUMEN", seccion_estilo))
            historia.append(tabla_resumen)
            historia.append(Spacer(1, 10))

        for modulo, datos in resultados.items():
            historia.append(Paragraph(f"▸ {modulo.upper()}", seccion_estilo))
            filas = ExportarPDF._aplanar(datos)
            if filas:
                tabla_datos = [[Paragraph(f"<b>{k}</b>", info_estilo), Paragraph(str(v), info_estilo)] for k, v in filas]
                tabla = Table(tabla_datos, colWidths=[6 * cm, 10.5 * cm])
                tabla.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), gris),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#fafcff")]),
                    ("GRID", (0, 0), (-1, -1), 0.45, gris_linea),
                    ("FONTSIZE", (0, 0), (-1, -1), 8.2),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("WORDBREAK", (0, 0), (-1, -1), 1),
                ]))
                historia.append(tabla)
            historia.append(Spacer(1, 8))

        doc.build(historia)
        print(f"\n  ✅ PDF exportado correctamente:")
        print(f"  📄 {ruta}")
        input("\n  Presiona ENTER para continuar...")

    @staticmethod
    def _resumen(resultados: dict):
        fila = []
        cpu = resultados.get("CPU", {})
        ram = resultados.get("RAM", {})
        discos = resultados.get("Discos", {})
        bateria = resultados.get("Batería", {})
        gpu = resultados.get("GPU", {})

        def _porcentaje(dato: dict, clave: str, default=0):
            valor = dato.get(clave, default)
            try:
                return float(str(valor).replace("%", "").replace(",", "."))
            except Exception:
                return 0.0

        cpu_uso = _porcentaje(cpu, "Uso actual")
        ram_uso = _porcentaje(ram, "Porcentaje de uso")

        disco_max = 0
        disco_unidad = "-"
        for item in discos.get("particiones", []):
            valor = _porcentaje(item, "Uso")
            if valor > disco_max:
                disco_max = valor
                disco_unidad = item.get("Unidad", "-")

        battery_pct = 100.0
        if isinstance(bateria, dict) and "estado" not in bateria:
            battery_pct = _porcentaje(bateria, "Porcentaje")

        gpu_temp = 0
        if isinstance(gpu, dict):
            for item in gpu.get("gpus", []):
                temp = item.get("Temperatura", "0 °C")
                try:
                    temp_val = float(str(temp).replace("°C", "").replace("C", "").replace(",", "."))
                    gpu_temp = max(gpu_temp, temp_val)
                except Exception:
                    pass

        resumen = [
            ["CPU", f"{cpu_uso:.0f}% en uso"],
            ["RAM", f"{ram_uso:.0f}% en uso"],
            ["Disco", f"{disco_unidad} ({disco_max:.0f}%)"],
            ["Batería", f"{battery_pct:.0f}%"],
            ["GPU", f"{gpu_temp:.0f}°C max"],
        ]
        return resumen

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
