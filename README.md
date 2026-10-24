# BotControl

Programa para **Windows 10/11** que te deja controlar, de forma gráfica y sencilla, todos tus
**bots de Telegram**: verlos, iniciarlos, detenerlos, ver lo que escriben en tiempo real,
programarlos por horario y elegir cuáles se abren solos al encender el PC.

![icono](assets/icon.png)

## Qué hace

- **Panel con todos tus bots**: estado (en ejecución, detenido, caído…), `@usuario`, PID,
  tiempo activo, CPU, RAM y número de reinicios.
- **Iniciar / Detener / Reiniciar** cada bot o todos a la vez, **sin ventanas de consola**.
- **Detectar bots abiertos**: encuentra los bots de Telegram que ya tienes ejecutándose en el
  PC y toma el control de ellos **sin reiniciarlos**.
- **Buscar en carpeta**: localiza los scripts de bots dentro de una carpeta y los añade de golpe.
- **Inicio automático**: marca la casilla *Inicio auto* de los bots que quieres que se abran al
  encender el PC. BotControl se inicia con Windows, espera a tener Internet y los lanza
  (con retraso opcional para escalonarlos).
- **Programación horaria** por bot: días de la semana y hora de inicio/parada (también franjas
  nocturnas, p. ej. 22:00-06:00).
- **Reinicio automático** si un bot se cae, con espera creciente y límite de intentos, y
  **aviso** en la bandeja del sistema.
- **Registro en vivo** de cada bot (con búsqueda), guardado en archivo y rotado
  automáticamente.
- **Antiduplicados**: avisa si intentas abrir un bot que ya está en marcha (evita el error
  `409 Conflict` de Telegram).
- **Token** opcional: se guarda cifrado con tu cuenta de Windows (DPAPI), se puede pasar al
  bot como variable de entorno y se comprueba contra Telegram para mostrar su `@usuario`.
- **Librerías gestionadas automáticamente**: instala el `requirements.txt` del bot y, si se
  cae por `No module named '...'`, instala la librería que falta y lo reinicia solo.
- **Entorno aislado por bot** (un clic): cada bot con sus propias librerías y versiones, sin
  romper a los demás.
- Admite bots en **Python** (detecta su `venv`/`.venv`), **Node.js**, **ejecutables** o
  **cualquier comando**.
- Si cierras BotControl puedes **dejar los bots funcionando**; al volver a abrirlo los
  reconoce.
- Icono en la **bandeja del sistema**, instancia única, exportar/importar la lista de bots.

## Instalación

1. Descarga `BotControl-Setup-X.Y.Z.exe` desde la pestaña **Releases** del repositorio
   (o desde los *artifacts* de la última ejecución de **Actions → Windows build**).
2. Ejecútalo. No necesita permisos de administrador. Marca **"Iniciar BotControl al
   encender el PC"** si quieres que tus bots arranquen solos.
3. Abre BotControl desde el menú Inicio o el escritorio.

> Windows SmartScreen puede avisar de que el programa no está firmado: pulsa
> **"Más información" → "Ejecutar de todas formas"**.

También hay una versión **portable** (`BotControl-Portable-X.Y.Z.zip`): descomprímela y
ejecuta `BotControl.exe`.

**Requisitos de tus bots:** BotControl no necesita Python, pero tus bots sí: ten instalado el
Python (o Node.js) que ya usan. Si el bot tiene un entorno virtual (`venv`, `.venv` o `env`)
en su carpeta, se usa automáticamente.

## Uso rápido

1. **Primera vez**: pulsa **Detectar** para adoptar los bots que ya tienes abiertos, o
   **Carpeta** para buscarlos en disco, o **Añadir** para configurarlos a mano.
2. Selecciona un bot y usa **Iniciar / Detener / Reiniciar**. Abajo verás su registro en vivo.
3. Marca **Inicio auto** en los bots que deben abrirse al encender el PC.
4. Doble clic en un bot para editarlo: token, retraso de arranque, reinicio automático,
   programación horaria, variables de entorno y notas.
5. **Ajustes**: inicio con Windows, arrancar minimizado, esperar a Internet, avisos y qué
   hacer con los bots al salir.

Atajos: `Ctrl+N` añadir · `F5` detectar · `Ctrl+R` iniciar · `Ctrl+T` detener ·
`Ctrl+Shift+R` reiniciar · `Ctrl+E` editar · `Supr` eliminar · `Ctrl+Q` salir.

### Librerías de tus bots

Cada bot usa las librerías **del Python con el que se ejecuta** (BotControl no las lleva
dentro). Para que nunca falten:

- **Automático** (activado por defecto, pestaña *Librerías* al editar el bot):
  - Antes de iniciar, si cambió el `requirements.txt` (o `package.json`) o las *librerías
    adicionales*, se instalan.
  - Si el bot se cae con `ModuleNotFoundError: No module named 'X'`, BotControl busca el
    paquete correcto (p. ej. `cv2 → opencv-python`, `PIL → Pillow`,
    `telebot → pyTelegramBotAPI`), lo instala y reinicia el bot. Un intento por librería.
- **Botón «Librerías»** (`Ctrl+L`) de la ventana principal:
  - **Analizar librerías del bot**: lee sus `import` y te dice cuáles faltan.
  - **Añadir librería**: escribe `matplotlib` o `pandas==2.2.2` y pulsa *Instalar*;
    puedes guardarla como librería del bot para que se compruebe siempre.
  - Ver las instaladas, desinstalar e instalar el `requirements.txt`.
  - **Crear entorno aislado (recomendado)**: crea un `.venv` sólo para ese bot con todo lo que
    necesita. Así las librerías o versiones de un bot no afectan a los demás.
- Al editar un bot puedes elegir el Python en **«Pythons instalados ▾»**.

Las variables de entorno del bot (pestaña *Avanzado*) también se aplican a `pip`, por ejemplo
`PIP_INDEX_URL` para un repositorio privado.

### Dónde se guardan los datos

`%APPDATA%\BotControl\`

- `config.json` — tus bots y ajustes.
- `logs\<id>.log` — registro de cada bot.
- `runtime.json` — procesos en marcha (para reconocerlos al reabrir).
- `botcontrol.log` — registro del propio programa.

## Preguntas frecuentes

**Sale `ModuleNotFoundError: No module named 'matplotlib'` (u otra librería).** Al Python
que usa ese bot le falta la librería. Con *Gestionar las librerías automáticamente* activado,
BotControl la instala y reinicia el bot solo. Si quieres hacerlo a mano: selecciona el bot →
**Librerías** → escribe `matplotlib` → **Instalar**. Si varios bots comparten el mismo Python
y chocan entre sí, pulsa **Crear entorno aislado**.

**¿Cómo detecta que un proceso es un bot de Telegram?** Mira los procesos de Python/Node y
revisa si su script usa `python-telegram-bot`, `aiogram`, `pyTelegramBotAPI (telebot)`,
`pyrogram`, `telethon`, `telegraf`, `grammy`, `node-telegram-bot-api` o `api.telegram.org`.

**Mi bot lee el token de una variable de entorno.** Pon el token en la pestaña *Telegram*,
marca *Pasar el token al bot como variable de entorno* y escribe el nombre de la variable
(por defecto `BOT_TOKEN`). Otras variables van en *Avanzado*.

**No veo lo que imprime mi bot.** BotControl ya fuerza la salida sin búfer en Python
(`-u`, `PYTHONUNBUFFERED`). Si usas `logging`, asegúrate de que escribe en consola.

**Un bot "Caído" no se reinicia más.** Si se cae más veces de las permitidas en el periodo
configurado, se deja parado para no entrar en un bucle. Revisa su registro, corrígelo y pulsa
**Iniciar**.

**¿Qué pasa al apagar el PC?** Windows cierra los bots; al volver a encender, BotControl
(si está en el inicio de Windows) vuelve a abrir los que tengan *Inicio auto* o estén en su
franja horaria.

## Compilar desde el código

En Windows, con Python 3.10+ e [Inno Setup 6](https://jrsoftware.org/isdl.php):

```bat
build.bat
```

Genera `dist\BotControl\BotControl.exe` y `dist\installer\BotControl-Setup-X.Y.Z.exe`.

Ejecutar sin compilar:

```bat
pip install -r requirements.txt
python -m botcontrol
```

Tests: `pip install -r requirements-dev.txt` y `python -m pytest`.

**Publicar una versión:** cambia `__version__` en `botcontrol/__init__.py`, crea un tag
`vX.Y.Z` y súbelo; GitHub Actions compila, prueba la instalación y adjunta el instalador a la
*release*.

## Estructura

```
botcontrol/
  app.py              arranque, instancia única, argumentos (--autostart, --minimized)
  models.py           bots, programación y ajustes
  storage.py          guardado atómico de la configuración, exportar/importar
  launcher.py         línea de comandos de cada bot (venv, Python, Node…)
  deps.py             librerías: análisis de imports, pip/npm, entornos aislados
  proc_utils.py       procesos sin ventana (bots, pip)
  process_manager.py  iniciar/detener/adoptar, reinicio automático, CPU/RAM
  scanner.py          detección de bots en procesos y carpetas
  scheduler.py        programación horaria
  startup.py          inicio con Windows (registro HKCU\...\Run)
  secrets.py          cifrado del token (DPAPI)
  telegram_api.py     getMe y comprobación de Internet
  ui/                 interfaz (PySide6)
installer/            script de Inno Setup
tests/                pruebas automáticas
docs/PROMPT.md        especificación completa del programa
docs/PROMPT-2-librerias.md  especificación de la gestión de librerías
```
