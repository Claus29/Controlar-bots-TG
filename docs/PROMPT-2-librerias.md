# Prompt refinado (2) — Librerías de los bots

> Versión editada y ampliada de:
>
> *"Dentro del programa me sale el siguiente error cuando voy a abrir un bot:
> `ModuleNotFoundError: No module named 'matplotlib'`. Quiero que lo soluciones
> y crees la forma perfecta para poder añadir otras librerías al programa, y
> hacerlo dinámicamente para no tener problemas con otros bots."*

---

## 1. Diagnóstico del error

- El error **no es de BotControl**: lo lanza el bot porque el **intérprete de
  Python con el que se ejecuta no tiene instalada esa librería**.
- Causa principal detectada en el código: al **adoptar** un bot que ya estaba
  abierto ("Detectar bots abiertos"), BotControl **no guardaba el Python con el
  que se ejecutaba**. Al reiniciarlo desde el programa, la autodetección podía
  elegir **otro Python** (otra versión u otra instalación) sin esas librerías.
- Causas secundarias: el bot no tiene `venv` propio y usa el Python global; o
  el usuario instaló la librería en un Python distinto al que usa el bot.
- Las librerías no se pueden "meter dentro" de BotControl: cada bot necesita
  tenerlas en **su propio intérprete**. La solución correcta es que BotControl
  **gestione las librerías de cada bot en el Python que usa ese bot**.

## 2. Objetivo

1. Corregir el error de raíz (que se use siempre el Python correcto).
2. Que BotControl **detecte, instale y mantenga automáticamente** las librerías
   que necesita cada bot, sin que el usuario use la consola.
3. Que cada bot pueda tener su **entorno aislado** (`venv`) para que las
   librerías o versiones de un bot **no rompan a otros bots**.

## 3. Requisitos funcionales

### 3.1 Corrección de raíz
- Al adoptar un bot en ejecución se guarda **el ejecutable real de Python**
  del proceso (si se lanzó con `py.exe`, el `python.exe` hijo).
- En la edición del bot se puede elegir el Python de una **lista de Pythons
  instalados** detectados (lanzador `py`, PATH, carpetas típicas, venvs).

### 3.2 Gestión automática (por bot, activada por defecto)
- **Antes de iniciar**: si existe `requirements.txt` en la carpeta del bot o
  hay "librerías adicionales" configuradas, y han cambiado desde la última
  vez, se instalan con `pip` en el Python del bot y luego se arranca. (Para
  Node.js: `npm install` si cambió `package.json`).
- **Si el bot se cae por una librería que falta** (`ModuleNotFoundError: No
  module named 'X'` / Node: `Cannot find module 'X'`): se identifica el
  paquete correcto (tabla `import → pip`, p. ej. `cv2 → opencv-python`,
  `PIL → Pillow`, `telebot → pyTelegramBotAPI`), se instala y se reinicia el
  bot solo. **Un intento por librería** para evitar bucles; si falla, se avisa
  con la opción de abrir el gestor de librerías.
- Todo en segundo plano, sin congelar la interfaz, con el progreso en el
  registro del bot.

### 3.3 Gestor de librerías del bot (ventana "Librerías")
- Muestra el Python del bot (ruta, versión) y si es **aislado** o
  **compartido** (y con cuántos bots se comparte), con aviso si es compartido.
- **Analizar librerías del bot**: lee los `import` de todos sus `.py`
  (sin ejecutarlos), descarta la biblioteca estándar y los módulos propios del
  bot, comprueba en su Python cuáles faltan y propone instalarlas (las que
  están dentro de `try/except ImportError` se marcan como opcionales).
- **Instalar `requirements.txt`**, **instalar cualquier paquete** escribiendo
  su nombre (admite versiones: `matplotlib==3.9.2`), **ver los paquetes
  instalados** y **desinstalar**.
- **Crear entorno aislado (recomendado)**: crea `.venv` en la carpeta del bot
  (o en `%APPDATA%\BotControl\envs\<bot>` si la carpeta no se puede escribir),
  instala `requirements.txt`, las adicionales y las detectadas, y configura el
  bot para usarlo.
- Salida de `pip` en vivo y botón **Cancelar**. Si el bot está en marcha,
  ofrece reiniciarlo al terminar.

### 3.4 Configuración por bot
- Pestaña **Librerías** en la edición del bot: casilla "Gestionar librerías
  automáticamente" y lista de **librerías adicionales** (una por línea).
- Las variables de entorno del bot también se aplican a `pip` (permite
  índices privados o *proxies* con `PIP_INDEX_URL`, etc.).

## 4. Requisitos técnicos
- Lógica en un módulo nuevo sin interfaz (`botcontrol/deps.py`) y reutilizable
  por la UI y el gestor de procesos.
- `pip` se ejecuta siempre como `<python del bot> -m pip`, sin ventana, con el
  entorno limpio del ejecutable empaquetado; si falta `pip` se usa
  `ensurepip`.
- El análisis de imports usa `ast` (no ejecuta código del bot) y la
  comprobación usa `importlib.util.find_spec` en el Python del bot.
- Los hilos de instalación nunca tocan la interfaz: se comunican con el hilo
  principal mediante una cola.
- Configuración compatible con la anterior (los bots ya guardados obtienen la
  gestión automática activada).

## 5. Criterios de aceptación
- Un bot que falla por `No module named 'matplotlib'` se recupera solo:
  BotControl instala `matplotlib` en su Python y lo reinicia.
- Un bot adoptado se reinicia con **el mismo Python** con el que estaba
  abierto.
- "Crear entorno aislado" deja el bot funcionando con su propio `.venv` y sin
  afectar a otros bots.
- Tests automáticos (sin Internet) de: análisis de imports, detección del
  error, tabla de nombres, instalación en un venv real con un paquete local,
  y recuperación automática del bot.
