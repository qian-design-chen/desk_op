"""Generate the app icon (app.ico) and a preview PNG with Pillow."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent
ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)
TEAL = (15, 118, 110, 255)
TEAL_DARK = (10, 88, 82, 255)
WHITE = (255, 255, 255, 255)


def draw_icon(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    s = size / 256.0
    margin = max(1, round(8 * s))
    radius = max(2, round(52 * s))
    box = (margin, margin, size - margin, size - margin)
    draw.rounded_rectangle(box, radius=radius, fill=TEAL)

    # Subtle inner highlight near the top edge.
    highlight_box = (
        margin + round(6 * s),
        margin + round(6 * s),
        size - margin - round(6 * s),
        round(size * 0.62),
    )
    draw.rounded_rectangle(
        highlight_box,
        radius=max(2, round(46 * s)),
        fill=TEAL_DARK,
    )

    # White check mark.
    points = [
        (round(72 * s), round(134 * s)),
        (round(112 * s), round(174 * s)),
        (round(190 * s), round(84 * s)),
    ]
    width = max(3, round(22 * s))
    draw.line(points[:2], fill=WHITE, width=width, joint="curve")
    draw.line(points[1:], fill=WHITE, width=width, joint="curve")
    radius_dot = width / 2.0
    for x, y in points:
        draw.ellipse(
            [x - radius_dot, y - radius_dot, x + radius_dot, y + radius_dot],
            fill=WHITE,
        )
    return img


def main() -> None:
    icon = draw_icon(256)
    icon.save(ROOT / "app.ico", format="ICO", sizes=[(s, s) for s in ICON_SIZES])
    icon.save(ROOT / "app_icon_preview.png", format="PNG")
    print(f"icon saved: {ROOT / 'app.ico'}")


if __name__ == "__main__":
    main()
