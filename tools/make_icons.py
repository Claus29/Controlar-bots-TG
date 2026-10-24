"""Genera assets/icon.png, assets/icon.ico y assets/check.png (requiere Pillow)."""

from pathlib import Path

from PIL import Image, ImageDraw

ASSETS = Path(__file__).resolve().parent.parent / "assets"
S = 1024


def app_icon() -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    grad = Image.new("RGBA", (S, S))
    top, bottom = (55, 190, 245), (22, 130, 210)
    gd = ImageDraw.Draw(grad)
    for y in range(S):
        t = y / (S - 1)
        gd.line([(0, y), (S, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(top, bottom)) + (255,))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([40, 40, S - 40, S - 40], radius=230, fill=255)
    img.paste(grad, (0, 0), mask)
    d = ImageDraw.Draw(img)
    # Avión de papel (Telegram)
    plane = [(210, 500), (800, 260), (690, 790), (520, 650), (450, 760), (430, 600)]
    d.polygon(plane, fill=(255, 255, 255, 255))
    d.polygon([(430, 600), (800, 260), (520, 650)], fill=(205, 230, 248, 255))
    # Indicador "en marcha"
    d.ellipse([640, 640, 900, 900], fill=(255, 255, 255, 255))
    d.ellipse([665, 665, 875, 875], fill=(62, 207, 110, 255))
    d.polygon([(740, 715), (740, 825), (830, 770)], fill=(255, 255, 255, 255))
    return img


def check_mark() -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    ImageDraw.Draw(img).line([(14, 33), (27, 46), (51, 19)], fill=(255, 255, 255, 255), width=8, joint="curve")
    return img.resize((32, 32), Image.LANCZOS)


def arrow(up: bool) -> Image.Image:
    img = Image.new("RGBA", (36, 36), (0, 0, 0, 0))
    pts = [(6, 26), (18, 12), (30, 26)] if up else [(6, 12), (18, 26), (30, 12)]
    ImageDraw.Draw(img).line(pts, fill=(200, 214, 228, 255), width=5, joint="curve")
    return img.resize((18, 18), Image.LANCZOS)


if __name__ == "__main__":
    ASSETS.mkdir(exist_ok=True)
    icon = app_icon()
    icon.resize((256, 256), Image.LANCZOS).save(ASSETS / "icon.png")
    icon.save(ASSETS / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    check_mark().save(ASSETS / "check.png")
    arrow(True).save(ASSETS / "up.png")
    arrow(False).save(ASSETS / "down.png")
    print("Iconos generados en", ASSETS)
