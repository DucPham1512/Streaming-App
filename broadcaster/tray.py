import threading
import sys
import traceback
import os
from PIL import Image, ImageDraw
import pystray


def _create_icon_image():
    img = Image.new("RGB", (64, 64), color=(220, 50, 50))
    draw = ImageDraw.Draw(img)
    draw.ellipse([16, 16, 48, 48], fill=(255, 255, 255))
    return img


def run_tray(stop_event: threading.Event):
    def on_quit(icon, item):
        stop_event.set()
        icon.stop()

    menu = pystray.Menu(pystray.MenuItem("Quit", on_quit))
    icon = pystray.Icon("Broadcaster", _create_icon_image(), "Broadcaster", menu)
    icon.run()


def main():
    log_path = os.path.join(os.path.expanduser("~"), "broadcaster.log")
    try:
        from broadcaster.__main__ import main as broadcaster_main

        stop_event = threading.Event()

        broadcast_thread = threading.Thread(
            target=broadcaster_main, kwargs={"stop_event": stop_event}, daemon=True
        )
        broadcast_thread.start()

        run_tray(stop_event)
        broadcast_thread.join(timeout=5)
    except Exception:
        with open(log_path, "w") as f:
            traceback.print_exc(file=f)
        raise


if __name__ == "__main__":
    main()
