"""Lanzador usado por PyInstaller (y útil para ejecutar desde el código fuente)."""

import sys

from botcontrol.app import main

if __name__ == "__main__":
    sys.exit(main())
