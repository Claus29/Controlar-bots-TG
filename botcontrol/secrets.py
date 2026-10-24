"""Cifrado de tokens. En Windows usa DPAPI (ligado a la cuenta del usuario)."""

from __future__ import annotations

import base64
import sys

_DPAPI = "dpapi:"
_PLAIN = "b64:"


def _dpapi(data: bytes, protect: bool) -> bytes:
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    buf = ctypes.create_string_buffer(data, len(data))
    blob_in = DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    blob_out = DATA_BLOB()
    CRYPTPROTECT_UI_FORBIDDEN = 0x01
    func = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    ok = func(
        ctypes.byref(blob_in), None, None, None, None,
        CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(blob_out),
    )
    if not ok:
        raise OSError("No se pudo (des)cifrar el token con DPAPI")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


def protect(token: str) -> str:
    token = token.strip()
    if not token:
        return ""
    raw = token.encode("utf-8")
    if sys.platform == "win32":
        try:
            return _DPAPI + base64.b64encode(_dpapi(raw, True)).decode("ascii")
        except OSError:
            pass
    return _PLAIN + base64.b64encode(raw).decode("ascii")


def unprotect(value: str) -> str:
    if not value:
        return ""
    try:
        if value.startswith(_DPAPI):
            return _dpapi(base64.b64decode(value[len(_DPAPI):]), False).decode("utf-8")
        if value.startswith(_PLAIN):
            return base64.b64decode(value[len(_PLAIN):]).decode("utf-8")
    except (OSError, ValueError, AttributeError):
        return ""
    return ""
