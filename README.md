# Herramienta de Diagnóstico de Hardware 

Herramienta en Python para diagnosticar hardware y estado del sistema en equipos Windows. Permite obtener información detallada del sistema, CPU, RAM, discos, GPU, batería y temperatura de forma rápida desde la terminal.

<img src="img/imagen.png" alt="Preview" width="700"/>

---

## Instalación

```bash
git clone https://github.com/tu-usuario/hardware-diagnostico.git
cd hardware-diagnostico
pip install -r requirements.txt
python main.py
```

## Crear el ejecutable de Windows

Con Python instalado, instala las dependencias y PyInstaller:

```bash
python -m pip install -r requirements.txt
python -m pip install pyinstaller
```

Después, desde la carpeta del proyecto, ejecuta:

```bash
pyinstaller --clean --noconfirm main.spec
```

El ejecutable se generará en `dist/DiagnosticoHardware.exe`. Puedes copiarlo a otra carpeta; los directorios `logs` y `reports` se crearán junto al ejecutable cuando se utilicen. Como la aplicación funciona mediante un menú de terminal, debe abrirse desde una consola o haciendo doble clic en el archivo.

---

## Dependencias

| Librería | Para qué sirve | Instalar con |
|---|---|---|
| `GPUtil` | Detectar GPU NVIDIA (uso, VRAM, temperatura) | `pip install GPUtil` |
| `reportlab` | Exportar diagnóstico a PDF | `pip install reportlab` |

> `psutil`, `wmi` y `pywin32` ya eran requeridas en v1.0.

---

## Modo profesional

En el menú principal existe un modo técnico para soporte:

- se activa con la opción `P` desde el menú normal
- muestra información adicional por módulo
- calcula un estado general del equipo (`OK`, `ALERTA`, `CRÍTICO`)
- prioriza problemas por nivel de riesgo
- recomienda acciones inmediatas según RAM, disco, temperatura, batería y GPU
- incluye un menú independiente con diagnóstico de red y auditoría básica de seguridad
- el menú profesional muestra información técnica en azul y conserva las respuestas del diagnóstico en el color normal de la terminal

---
## Autor

**Salvador Hernández Juárez**

[![GitHub](https://img.shields.io/badge/GitHub-SalvadorHernandezJuarez-181717?logo=github)](https://github.com/SalvadorHernandezJuarez)

---
