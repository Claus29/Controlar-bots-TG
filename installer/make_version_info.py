"""Genera installer/version_info.txt (metadatos del .exe) a partir de botcontrol.__version__."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from botcontrol import APP_NAME, __version__  # noqa: E402

parts = [int(p) for p in __version__.split(".")[:3]] + [0]
while len(parts) < 4:
    parts.insert(-1, 0)
nums = tuple(parts[:4])

TEMPLATE = f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={nums}, prodvers={nums}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('0C0A04B0', [
      StringStruct('CompanyName', '{APP_NAME}'),
      StringStruct('FileDescription', '{APP_NAME} - Control de bots de Telegram'),
      StringStruct('FileVersion', '{__version__}'),
      StringStruct('InternalName', '{APP_NAME}'),
      StringStruct('OriginalFilename', '{APP_NAME}.exe'),
      StringStruct('ProductName', '{APP_NAME}'),
      StringStruct('ProductVersion', '{__version__}')])]),
    VarFileInfo([VarStruct('Translation', [3082, 1200])])
  ]
)
"""

(ROOT / "installer" / "version_info.txt").write_text(TEMPLATE, encoding="utf-8")
print(__version__)
