# 🖥️ Herramienta de Diagnóstico de Hardware — v2.0

Herramienta en Python para diagnosticar hardware y estado del sistema en equipos Windows. Permite obtener información detallada del sistema, CPU, RAM, discos, GPU, batería y temperatura de forma rápida desde la terminal.

<img src="img/preview.png" alt="Preview" width="700"/>

---

## 📁 Arquitectura del proyecto

```
diagnostico/
├── main.py                  # Punto de entrada
├── requirements.txt         # Dependencias
│
├── ui/
│   └── menu.py              # Interfaz de menú interactivo
│
├── modules/
│   ├── base.py              # Clase base para todos los módulos
│   ├── sistema.py           # Info del sistema operativo
│   ├── cpu.py               # Info del procesador
│   ├── ram.py               # Info de memoria RAM
│   ├── disco.py             # Info de discos + salud SMART
│   ├── bateria.py           # Estado de la batería
│   ├── temperatura.py       # Temperaturas del sistema
│   └── gpu.py               # Detección de GPU (NUEVO)
│
├── utils/
│   ├── logger.py            # Guardar y ver logs (NUEVO)
│   └── recomendaciones.py   # Recomendaciones inteligentes (MEJORADO)
│
├── reports/
│   └── exportar.py          # Exportar a PDF (NUEVO)
│
└── logs/                    # Logs JSON generados automáticamente
```

---

## 🚀 Instalación

```bash
git clone https://github.com/tu-usuario/hardware-diagnostico.git
cd hardware-diagnostico
pip install -r requirements.txt
python main.py
```

---

## 📦 Nuevas dependencias

| Librería | Para qué sirve | Instalar con |
|---|---|---|
| `GPUtil` | Detectar GPU NVIDIA (uso, VRAM, temperatura) | `pip install GPUtil` |
| `reportlab` | Exportar diagnóstico a PDF | `pip install reportlab` |

> `psutil`, `wmi` y `pywin32` ya eran requeridas en v1.0.