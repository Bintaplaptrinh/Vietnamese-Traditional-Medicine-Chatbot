"""Generate the original looping thinking-face overlay. Requires Pillow."""
import math
from pathlib import Path

from PIL import Image, ImageDraw

size = 408
frames = []
for frame in range(24):
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    gaze = math.sin(frame / 24 * math.tau) * 7
    for x in (139, 269):
        draw.rounded_rectangle((x - 17 + gaze, 149, x + 17 + gaze, 204), radius=17, fill="white")
    draw.arc((184, 232, 224, 255), 15, 165, fill="white", width=5)
    for dot, x in enumerate((177, 204, 231)):
        alpha = 255 if (frame // 4) % 3 == dot else 110
        # GIF has binary transparency; pale blue dots communicate inactive phases.
        color = "white" if alpha == 255 else "#90b7ff"
        y = 289 - (5 if alpha == 255 else 0)
        draw.ellipse((x - 6, y - 6, x + 6, y + 6), fill=color)
    palette = image.convert("RGB").quantize(colors=254)
    # Reserve palette index 255 for transparent pixels, with full frame disposal.
    palette.paste(255, mask=image.getchannel("A").point(lambda a: 255 if a == 0 else 0))
    palette.info["transparency"] = 255
    frames.append(palette)

target = Path(__file__).resolve().parents[1] / "frontend" / "assets" / "thinking.gif"
target.parent.mkdir(parents=True, exist_ok=True)
frames[0].save(target, save_all=True, append_images=frames[1:], duration=80, loop=0, transparency=255, disposal=2, optimize=False)
print(f"Created {target.name} ({len(frames)} frames)")
