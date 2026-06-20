"""Generate pomodoro.ico — the app/shortcut icon.

Recreates the app's signature at icon scale: a cream rounded tile with the
caramel progress ring (~75% filled), so the desktop shortcut reads as the same
product as the window and tray icon. Run by setup.bat; safe to run by hand to
regenerate after a palette change. Requires Pillow.
"""
import os

from PIL import Image, ImageDraw

# Mirrors the palette in countdown_timer.py.
BG        = (255, 243, 232, 255)   # #FFF3E8 cream
RING_BG   = (237, 216, 195, 255)   # #EDD8C3 track
FOCUS_CLR = (204, 168, 130, 255)   # #CCA882 caramel progress

ICO_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pomodoro.ico")
SS = 1024  # supersample, then downscale for smooth edges


def build():
    img  = Image.new("RGBA", (SS, SS), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Cream rounded tile
    m = int(SS * 0.06)
    draw.rounded_rectangle([m, m, SS - m, SS - m],
                           radius=int(SS * 0.22), fill=BG)

    # Ring geometry
    pad = int(SS * 0.24)
    box = [pad, pad, SS - pad, SS - pad]
    w   = int(SS * 0.085)

    # Track (full circle) then progress arc from the top, sweeping 270°.
    draw.arc(box, start=0,   end=360, fill=RING_BG,   width=w)
    draw.arc(box, start=-90, end=180, fill=FOCUS_CLR, width=w)

    base = img.resize((256, 256), Image.LANCZOS)
    base.save(ICO_PATH, format="ICO",
              sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
    return ICO_PATH


if __name__ == "__main__":
    print("Wrote", build())
