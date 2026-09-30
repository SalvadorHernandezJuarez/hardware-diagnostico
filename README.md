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
- incluye menús independientes con diagnóstico de red y auditoría de seguridad de Windows
- usa una paleta morada y cian para identificar el modo profesional
- incluye un catálogo local de ampliación de hardware: puede detectar el modelo del equipo, buscar modelos y consultar capacidades máximas de RAM y SSD
- el catálogo se puede cargar desde Excel y se conserva en una base SQLite local

### Catálogo de ampliación de hardware

En el menú Hardware del modo profesional, selecciona **C. Catálogo de ampliación por modelo**. Puedes buscar modelos del catálogo, consultar el equipo detectado por Windows o crear una plantilla de Excel. Captura los datos en la hoja `Catalogo`, conserva los encabezados y selecciona **Importar o actualizar desde Excel**. Los registros se guardan en `datos_ampliacion/compatibilidad.db`, junto al proyecto o ejecutable.

La plantilla admite marca, modelo, RAM máxima y soldada, tipo y ranuras de RAM, SSD máximo, interfaces de almacenamiento, notas, fuente y fecha de verificación. Cada fila debe incluir al menos una capacidad máxima y su fuente y fecha de verificación. La consulta automática solo muestra coincidencias exactas de marca y modelo; si no encuentra una, permite buscar el modelo manualmente. Verifica capacidades y variantes contra fuentes del fabricante antes de incorporarlas.

## Módulo de hardware

La opción **Hardware** está disponible en modo Normal y Profesional. Presenta procesador, RAM, almacenamiento, GPU, placa base, BIOS/UEFI, batería, pantalla, audio, dispositivos conectados, un resumen completo y capacidad de expansión. La tecla **T** conserva la vista de temperatura; en modo Profesional, **C** abre el catálogo local de ampliación por modelo.

`modules/hardware.py` concentra la recolección en funciones que devuelven diccionarios estructurados, independientes de la presentación CMD. Usa `psutil`, WMI y, si el paquete `wmi` no está instalado, consultas CIM de PowerShell en Windows. La información ausente se representa como `None` y los errores de consulta se registran en `logs/hardware_diagnostico.log`. La interfaz normal prioriza indicadores básicos; la profesional incluye identificadores, números de serie y campos SMBIOS/controladores disponibles.

La capacidad máxima SMBIOS se etiqueta como reportada, no como confirmada. Los conectores libres M.2/SATA no se deducen de las unidades detectadas: solo se muestran cuando una fuente del catálogo informa interfaces; de otro modo aparecen como desconocidos. Los datos completos quedan disponibles como diccionarios para la futura capa de diagnóstico y reportes.

## Diagnóstico de red

La opción **5. Diagnóstico de red** en modo Normal y **7. Red** en modo Profesional ofrecen adaptadores, configuración IP, gateway, DNS, conectividad externa, ping, traceroute y diagnóstico automático por capas. `modules/red.py` devuelve estructuras `NetworkAdapter`, `NetworkConfiguration`, `PingResult`, `DnsResult`, `GatewayResult` y `NetworkDiagnosticResult`; `ui/red.py` las presenta en CMD y guarda diagnósticos/acciones en el historial.

La inspección usa `psutil`, PowerShell `Get-NetIPConfiguration`/`Get-NetAdapter`, `netsh wlan show interfaces`, `ping`, `tracert`, resolución DNS UDP y sockets TCP. DNS/IP/gateway se prueban antes de las conexiones externas; gateway inaccesible detiene las pruebas posteriores. La conectividad externa se verifica con conexiones TCP a destinos IP en puerto 443 y DNS se comprueba independientemente. Un salto `* * *` no se trata como fallo.

La latencia y pérdida de paquetes se miden con cuatro pings; los límites se centralizan en `modules/red.py` (`150 ms` de latencia promedio y `10%` de pérdida). `169.254.x.x` se presenta como indicio de posible problema DHCP, no como causa confirmada. Los errores o proveedores ausentes no detienen las otras pruebas.

`[9] Renovar configuración IP` solicita confirmación explícita antes de `ipconfig /release` y `ipconfig /renew`. `[10] Restablecimiento de red` solo aparece en el submenú de red del modo Profesional y requiere escribir literalmente `CONFIRMAR`; ejecuta `netsh winsock reset` y `netsh int ip reset` y puede requerir reiniciar Windows. Estas acciones no se ejecutan desde el diagnóstico automático.

---
## Autor

**Salvador Hernández Juárez**

[![GitHub](https://img.shields.io/badge/GitHub-SalvadorHernandezJuarez-181717?logo=github)](https://github.com/SalvadorHernandezJuarez)

---
