"""Compatibility entry point; the shared app owns tray and dashboard lifecycle."""
from .app import main

def icon_image():
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (64, 64), "white")
    d = ImageDraw.Draw(img)
    d.ellipse((6, 6, 58, 58), outline="black", width=4)
    d.line((32, 12, 32, 52), fill="black", width=3)
    d.arc((15, 16, 34, 38), 70, 290, fill="black", width=3)
    d.arc((30, 16, 49, 38), 250, 110, fill="black", width=3)
    d.arc((15, 28, 34, 50), 70, 290, fill="black", width=3)
    d.arc((30, 28, 49, 50), 250, 110, fill="black", width=3)
    return img


if __name__ == "__main__":
    main()
