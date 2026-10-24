# -*- mode: python ; coding: utf-8 -*-
# Compilar con:  pyinstaller --noconfirm botcontrol.spec

block_cipher = None

a = Analysis(
    ["run_botcontrol.py"],
    pathex=["."],
    datas=[("assets", "assets")],
    hiddenimports=["PySide6.QtNetwork"],
    excludes=["tkinter", "unittest", "pydoc", "PySide6.QtWebEngineCore", "PySide6.QtQml", "PySide6.QtQuick"],
    noarchive=False,
)
# Quita módulos de Qt que BotControl no usa (QML/Quick/PDF/teclado virtual) y traducciones ajenas.
UNUSED = ("Qt6Qml", "Qt6Quick", "Qt6Pdf", "Qt6VirtualKeyboard", "qpdf", "qtvirtualkeyboard", "Qt6Svg", "qsvg")


def keep(entry):
    name = entry[0].replace("\\", "/")
    if any(token.lower() in name.lower() for token in UNUSED):
        return False
    if "/translations/" in name and not name.rsplit("/", 1)[-1].startswith("qtbase_es"):
        return False
    return True


a.binaries = [b for b in a.binaries if keep(b)]
a.datas = [d for d in a.datas if keep(d)]

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="BotControl",
    console=False,
    icon="assets/icon.ico",
    version="installer/version_info.txt",
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="BotControl", upx=False)
