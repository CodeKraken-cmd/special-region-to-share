"""Generate the application icon (assets/app.ico) from a simple glyph."""

from __future__ import annotations

import os

from PIL import Image, ImageDraw


def make_image(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = size
    d.rounded_rectangle([s * 0.03, s * 0.03, s * 0.97, s * 0.97],
                        radius=int(s * 0.16), fill=(24, 24, 32, 255))
    m = s * 0.22
    d.rectangle([m, m, s - m, s - m], outline=(0, 229, 255, 255),
                width=max(2, int(s * 0.06)))
    r = s * 0.14
    d.ellipse([s - r - s * 0.16, s - r - s * 0.16, s - s * 0.16, s - s * 0.16],
              fill=(255, 45, 45, 255))
    return img


def main() -> None:
    out_dir = os.path.join(os.path.dirname(__file__), "assets")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "app.ico")
    sizes = [16, 24, 32, 48, 64, 128, 256]
    base = make_image(256)
    imgs = [base.resize((s, s), Image.Resampling.LANCZOS) for s in sizes]
    imgs[0].save(out, format="ICO", sizes=[(s, s) for s in sizes], append_images=imgs[1:])
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
