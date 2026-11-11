#!/usr/bin/env python3
"""LLM Bridge — локальная модель для телефона через Wi-Fi Direct.

  ./run.sh              окно
  ./run.sh --minimized  сразу в трей (для автозапуска)
  ./run.sh --headless   без окна: модель и канал включаются сразу, лог в консоль
"""
import argparse
import signal
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from PyQt6.QtCore import QCoreApplication, QTimer  # noqa: E402

from config import Config  # noqa: E402
from core import BridgeCore  # noqa: E402


def check_migrated():
    """Чаты и настройки от прежней версии лежат в домашней папке, а в проекте их ещё нет —
    не создаём пустые (с новым токеном телефон пришлось бы сопрягать заново), а просим переехать."""
    from config import CONFIG_PATH, DATA_DIR
    home = Path.home()
    old = [p for p in (home / ".config/llm-bridge/config.json", home / ".local/share/llm-bridge/chats.db")
           if p.exists()]
    if old and not CONFIG_PATH.exists() and not (DATA_DIR / "chats.db").exists():
        root = Path(__file__).resolve().parent.parent
        sys.exit("Найдены настройки и чаты прежней версии: " + ", ".join(str(p) for p in old) + "\n"
                 "Перенесите их в папку проекта (мост при этом должен быть закрыт):\n"
                 f"  cd {root} && python3 scripts/migrate-layout.py --go")


def main():
    check_migrated()
    ap = argparse.ArgumentParser(description="LLM Bridge")
    ap.add_argument("--minimized", action="store_true", help="запуск в трей без окна")
    ap.add_argument("--headless", action="store_true", help="без GUI (например, как сервис)")
    args, qt_args = ap.parse_known_args()

    if args.headless:
        app = QCoreApplication([sys.argv[0], *qt_args])
    else:
        from PyQt6.QtWidgets import QApplication
        app = QApplication([sys.argv[0], *qt_args])
        app.setDesktopFileName("llm-bridge")
        app.setQuitOnLastWindowClosed(False)  # окно прячется в трей
    app.setApplicationName("llm-bridge")

    cfg = Config.load()
    core = BridgeCore(cfg)
    app.aboutToQuit.connect(core.shutdown)

    if args.headless:
        core.log.connect(lambda s, src: print(f"{time.strftime('%H:%M:%S')} [{src}] {s}", flush=True))
        core.start(model=True, link=True)
    else:
        from ui import MainWindow
        win = MainWindow(core)
        core.start()
        if args.minimized and win.tray:
            win.hide()
        else:
            win.show()

    signal.signal(signal.SIGINT, lambda *_: app.quit())
    signal.signal(signal.SIGTERM, lambda *_: app.quit())
    tick = QTimer()
    tick.start(300)
    tick.timeout.connect(lambda: None)  # даёт Python обработать сигнал

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
