"""Generate PWA icons for Стак brand."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "app" / "static" / "icons"
INK = (14, 26, 23)
ACCENT = (23, 107, 80)
MINT = (143, 212, 176)
SURFACE = (232, 239, 233)


def draw_icon(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad = int(size * 0.1)
    d.rounded_rectangle([pad, pad, size - pad, size - pad], radius=int(size * 0.22), fill=INK)

    # three stacked cards = "стак"
    w = int(size * 0.52)
    h = int(size * 0.14)
    cx = size // 2
    base_y = int(size * 0.58)
    for i, (dy, alpha) in enumerate([(0, 255), (-int(h * 0.85), 210), (-int(h * 1.7), 170)]):
        y0 = base_y + dy - h
        x0 = cx - w // 2 + i * int(size * 0.03)
        fill = SURFACE if i == 0 else (220, 235, 226, alpha)
        d.rounded_rectangle([x0, y0, x0 + w, y0 + h], radius=int(size * 0.04), fill=fill)
        if i == 0:
            d.rounded_rectangle(
                [x0 + int(w * 0.08), y0 + int(h * 0.35), x0 + int(w * 0.55), y0 + int(h * 0.55)],
                radius=2,
                fill=ACCENT,
            )
            d.ellipse(
                [x0 + int(w * 0.68), y0 + int(h * 0.28), x0 + int(w * 0.82), y0 + int(h * 0.62)],
                fill=MINT,
            )

    # accent dot top-right
    r = int(size * 0.055)
    d.ellipse([size - pad - r * 2, pad + r * 0.5, size - pad, pad + r * 2.5], fill=MINT)
    return img


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for size, name in [(192, "icon-192.png"), (512, "icon-512.png"), (180, "apple-touch-icon.png")]:
        draw_icon(size).save(OUT / name)
    print("icons written to", OUT)


if __name__ == "__main__":
    main()
