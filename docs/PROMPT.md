# Prompt refinado — BotControl

> Versión editada, organizada y ampliada del prompt original:
>
> *"Quiero que me crees un programa para Windows, instalable y perfectamente
> funcionando, para poder controlar de manera gráfica, lógica y sencilla todos
> los bots de Telegram que tengo abiertos o poder programarlos desde el
> programa para elegir cuáles se abren o cuáles quiero que se abran en cuanto
> inicie el PC."*

---

## 1. Objetivo

Crear **BotControl**, una aplicación de escritorio para **Windows 10/11**,
distribuida como **instalador `.exe`** (con desinstalador), que permita
gestionar desde una interfaz gráfica sencilla, en español, todos los bots de
Telegram que el usuario ejecuta en su PC (scripts Python, Node.js, `.exe` o
cualquier comando), sin abrir ventanas de consola.

## 2. Contexto y supuestos

- Los bots son **procesos locales** (normalmente `python bot.py`), cada uno en
  su carpeta, a veces con su propio entorno virtual (`venv`/`.venv`).
- Algunos bots **ya están abiertos** cuando se instala el programa: hay que
  poder **detectarlos y tomar el control** de ellos sin reiniciarlos.
- El usuario no es necesariamente programador: todo debe poder hacerse con
  clics, con mensajes claros y valores por defecto razonables.
- Python u otros intérpretes los aporta el usuario (son los que usan sus bots);
  BotControl en sí no necesita Python instalado (se empaqueta con PyInstaller).

## 3. Requisitos funcionales

### 3.1 Gestión de bots
- Añadir / editar / duplicar / eliminar bots con un formulario:
  - Nombre, tipo (**Python**, **Node.js**, **Ejecutable**, **Comando**),
    archivo o comando, argumentos, carpeta de trabajo.
  - Intérprete: **autodetección** (venv de la carpeta del bot → `py`/`python`
    del sistema) o ruta manual.
  - Variables de entorno (`CLAVE=valor`, una por línea).
  - **Token** opcional: se guarda **cifrado (DPAPI de Windows)**, se puede
    inyectar como variable de entorno (nombre configurable, p. ej.
    `BOT_TOKEN`) y se valida contra la API de Telegram (`getMe`) para mostrar
    el `@usuario` del bot.
  - Notas libres.
- Los bots se ejecutan **sin ventana de consola** y su salida (stdout/stderr)
  se guarda en un **log por bot** (con rotación).

### 3.2 Control
- Por bot: **Iniciar, Detener, Reiniciar**, abrir carpeta, abrir log, abrir
  el bot en Telegram (`t.me/usuario`).
- Global: **Iniciar todos / Detener todos**.
- Detener = cerrar el **árbol completo de procesos** (terminar con espera y
  luego forzar).
- **Antiduplicados**: antes de iniciar, comprobar que ese mismo script no está
  ya en ejecución fuera del programa (evita el error 409 *Conflict* de
  Telegram); si lo está, ofrecer tomar el control.

### 3.3 Detección de bots abiertos
- **"Detectar bots abiertos"**: escanear los procesos del sistema y listar los
  que parecen bots de Telegram (scripts que importan `telegram`, `aiogram`,
  `telebot`, `pyrogram`, `telethon`, `telegraf`, `node-telegram-bot-api`, o
  que contienen `api.telegram.org`). El usuario elige cuáles **añadir y
  adoptar** (pasan a mostrarse como "En ejecución (externo)").
- **"Buscar bots en carpeta"**: recorrer una carpeta y proponer los scripts de
  bots que encuentre para añadirlos de golpe.
- Al abrir BotControl, los bots configurados que ya estén en ejecución se
  **reconocen automáticamente** (por PID guardado o por línea de comandos).

### 3.4 Arranque automático y programación
- Ajuste **"Iniciar BotControl con Windows"** (registro `HKCU\...\Run`), que
  arranca minimizado en la bandeja.
- Por bot: **"Abrir al iniciar"** (un clic en la tabla) + **retardo** en
  segundos para escalonar el arranque.
- Opción **esperar a tener Internet** (hasta N segundos) antes de lanzar los
  bots automáticos.
- **Programación horaria** por bot: días de la semana + hora de inicio y de
  parada (admite franjas que cruzan medianoche). Se actúa sólo en los cambios
  de franja, así una acción manual del usuario no se "pisa" cada minuto.

### 3.5 Robustez
- **Reinicio automático si el bot se cae**, con espera creciente y límite de
  intentos en una ventana de tiempo (evita bucles infinitos).
- Si se cierra BotControl, el usuario elige **detener los bots o dejarlos
  funcionando**; al volver a abrirlo los recupera (los bots escriben su log a
  archivo, no dependen del programa).
- **Instancia única**: abrir el programa otra vez muestra la ventana existente.
- Guardado de configuración **atómico** en `%APPDATA%\BotControl`.

### 3.6 Interfaz
- Tema oscuro moderno, en español.
- Tabla: estado (color), nombre, @usuario, inicio automático, programación,
  PID, tiempo activo, CPU, RAM, reinicios.
- Panel inferior con el **log en vivo** del bot seleccionado (seguir, buscar,
  limpiar, abrir archivo).
- **Icono en la bandeja** con menú (mostrar, iniciar/detener todos, salir) y
  avisos cuando un bot se cae.
- Doble clic = editar; menú contextual con todas las acciones.
- Exportar / importar la configuración (JSON, sin tokens).

## 4. Requisitos técnicos

| Aspecto | Decisión |
|---|---|
| Lenguaje | Python 3.12 |
| GUI | PySide6 (Qt 6) |
| Procesos | `subprocess` + `psutil` |
| Empaquetado | PyInstaller (modo carpeta, sin consola) |
| Instalador | Inno Setup 6 (accesos directos, "iniciar con Windows", desinstalador) |
| CI | GitHub Actions en `windows-latest`: tests + build + instalador como artefacto; *release* automática al publicar un tag `v*` |
| Tests | `pytest` sobre la lógica (config, procesos, programación, detección) |

## 5. Entregables

1. Código fuente organizado (`botcontrol/`), con la lógica separada de la UI.
2. `BotControl-Setup-<versión>.exe` generado por CI (y `build.bat` para
   compilarlo localmente).
3. Tests automatizados.
4. `README.md` en español: instalación, uso, compilación y preguntas
   frecuentes.

## 6. Criterios de aceptación

- Se instala con doble clic, crea accesos directos y se desinstala limpio.
- Añadir un bot Python e iniciarlo no abre ninguna consola y su log aparece en
  vivo.
- "Detectar bots abiertos" encuentra un bot lanzado a mano y lo adopta sin
  reiniciarlo.
- Con "Iniciar con Windows" + "Abrir al iniciar", tras reiniciar el PC los
  bots marcados están en marcha y BotControl queda en la bandeja.
- Un bot que se cae se reinicia solo y se notifica.
- Los tests pasan en Windows en CI.
