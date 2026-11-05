"""Tạo icon app (PNG 16/32/48/128 cho extension, ICO 16/32/48/256 cho Windows) từ một thiết kế đơn giản tự vẽ.
Không dùng logo YouTube/Google/VieNeu (docs/10 §Asset manifest)."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]


def draw(size: int) -> Image.Image:
    s = size * 4
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, s - 1, s - 1), radius=int(s * 0.22), fill=(22, 30, 46, 255))
    # sóng âm + tam giác phát
    d.polygon([(s * 0.26, s * 0.24), (s * 0.26, s * 0.76), (s * 0.62, s * 0.5)], fill=(88, 196, 130, 255))
    w = max(2, int(s * 0.055))
    for i, r in enumerate((0.17, 0.27)):
        box = (s * (0.60 - r), s * (0.5 - r), s * (0.60 + r), s * (0.5 + r))
        d.arc(box, start=-50, end=50, fill=(233, 238, 245, 255 - i * 60), width=w)
    return img.resize((size, size), Image.LANCZOS)


out = ROOT / "apps/extension/public/icons"
out.mkdir(parents=True, exist_ok=True)
for n in (16, 32, 48, 128):
    draw(n).save(out / f"icon{n}.png")
ico = ROOT / "assets/vietdub.ico"
ico.parent.mkdir(exist_ok=True)
draw(256).save(ico, sizes=[(16, 16), (32, 32), (48, 48), (256, 256)])
(ROOT / "assets/icon.svg").write_text('''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128" role="img" aria-label="VietDub Local">
<rect width="128" height="128" rx="28" fill="#161e2e"/><polygon points="33,31 33,97 79,64" fill="#58c482"/>
<path d="M 90 47 A 22 22 0 0 1 90 81" fill="none" stroke="#e9eef5" stroke-width="7" stroke-linecap="round"/>
<path d="M 99 36 A 35 35 0 0 1 99 92" fill="none" stroke="#e9eef5" stroke-opacity=".75" stroke-width="7" stroke-linecap="round"/></svg>
''', encoding="utf-8")
print("icons ok")
