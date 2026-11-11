"""Главное окно llm-bridge и значок в трее."""
import os
import shlex
import time
from pathlib import Path

from PyQt6.QtCore import QPointF, QRectF, Qt, QUrl
from PyQt6.QtGui import (QAction, QColor, QDesktopServices, QFont, QIcon, QPainter, QPainterPath,
                         QPixmap)
from PyQt6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFormLayout, QGroupBox,
                             QHBoxLayout, QLabel, QListWidget, QMainWindow, QMenu, QMessageBox,
                             QPlainTextEdit, QPushButton, QSplitter, QSystemTrayIcon, QVBoxLayout,
                             QWidget)

from config import CONFIG_PATH
from llama import STATE_TEXT
from qr import pairing_uri, qr_pixmap, wifi_uri

OK, WARN, ERR, OFF = "#2e7d32", "#ef6c00", "#c62828", "#757575"
APP_DIR = Path(__file__).resolve().parent
AUTOSTART = Path.home() / ".config/autostart/llm-bridge.desktop"


def colored(label: QLabel, text: str, color: str):
    label.setText(text)
    label.setStyleSheet(f"color: {color}; font-weight: bold;")


def app_icon() -> QIcon:
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128):
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        s = size / 108
        path = QPainterPath()
        path.addRoundedRect(QRectF(22 * s, 26 * s, 64 * s, 44 * s), 10 * s, 10 * s)
        tail = QPainterPath()
        tail.moveTo(QPointF(36 * s, 66 * s))
        tail.lineTo(QPointF(32 * s, 84 * s))
        tail.lineTo(QPointF(52 * s, 68 * s))
        path = path.united(tail)
        p.fillPath(path, QColor("#2E5D8A"))
        p.setBrush(QColor("white"))
        p.setPen(Qt.PenStyle.NoPen)
        for x in (38, 54, 70):
            p.drawEllipse(QPointF(x * s, 48 * s), 5 * s, 5 * s)
        p.end()
        icon.addPixmap(pm)
    return icon


def autostart_enabled() -> bool:
    return AUTOSTART.exists()


def set_autostart(on: bool):
    if on:
        AUTOSTART.parent.mkdir(parents=True, exist_ok=True)
        run = shlex.quote(str(APP_DIR / "run.sh"))
        AUTOSTART.write_text(
            "[Desktop Entry]\nType=Application\nName=LLM Bridge\n"
            "Comment=Локальная модель для телефона через Wi-Fi Direct\n"
            f"Exec={run} --minimized\nIcon=network-wireless\nTerminal=false\n"
            "X-GNOME-Autostart-enabled=true\nX-GNOME-Autostart-Delay=5\n",
            encoding="utf-8")
    elif AUTOSTART.exists():
        AUTOSTART.unlink()


class MainWindow(QMainWindow):
    def __init__(self, core):
        super().__init__()
        self.core = core
        self.cfg = core.cfg
        self._quitting = False
        self._last_seen = {}
        self.setWindowTitle("LLM Bridge")
        self.setWindowIcon(app_icon())
        self.resize(1000, 720)

        self._build_ui()
        self._build_tray()

        core.log.connect(self._log)
        core.llama_state.connect(self._on_llama_state)
        core.bg_state.connect(self._on_bg_state)
        core.link_state.connect(self._on_link_state)
        core.api_state.connect(self._on_api)
        core.clients.connect(self._on_clients)
        core.ws_clients.connect(self._on_ws_clients)
        core.token_changed.connect(self._refresh_qr)
        core.server.request_seen.connect(self._on_request)

        self._on_llama_state("stopped")
        self._on_bg_state("stopped")
        self._on_link_state("off", None)
        self._refresh_qr()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        self.lbl_model = QLabel()
        self.lbl_bg = QLabel()
        self.lbl_bg.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.lbl_link = QLabel()
        self.lbl_api = QLabel()
        self.lbl_app = QLabel()
        colored(self.lbl_api, "не запущен", OFF)
        colored(self.lbl_app, "нет", OFF)

        self.model_box = QComboBox()
        self.model_box.setToolTip("Текстовые модели из models/llm")
        self._fill_models()
        self.model_box.activated.connect(self._pick_model)

        form = QFormLayout()
        form.addRow("Текстовая модель:", self.model_box)
        form.addRow("Состояние модели:", self.lbl_model)
        form.addRow("Фоновая модель:", self.lbl_bg)
        form.addRow("Wi-Fi Direct:", self.lbl_link)
        form.addRow("API:", self.lbl_api)
        form.addRow("Приложение:", self.lbl_app)

        self.btn_model = QPushButton()
        self.btn_model.clicked.connect(self.core.toggle_model)
        self.btn_link = QPushButton()
        self.btn_link.clicked.connect(self._toggle_link)
        btns = QHBoxLayout()
        btns.addWidget(self.btn_model)
        btns.addWidget(self.btn_link)

        self.clients = QListWidget()
        self.clients.setMaximumHeight(90)

        self.cb_model = QCheckBox("Запускать модель при старте")
        self.cb_model.setChecked(self.cfg.autostart_model)
        self.cb_model.toggled.connect(lambda v: self._set_cfg("autostart_model", v))
        self.cb_link = QCheckBox("Включать канал при старте")
        self.cb_link.setChecked(self.cfg.autostart_link)
        self.cb_link.toggled.connect(lambda v: self._set_cfg("autostart_link", v))
        self.cb_login = QCheckBox("Запускать при входе в систему (свёрнутым в трей)")
        self.cb_login.setChecked(autostart_enabled())
        self.cb_login.toggled.connect(self._toggle_login)

        btn_token = QPushButton("Новый токен")
        btn_token.setToolTip("Старые сопряжения перестанут работать")
        btn_token.clicked.connect(self._new_token)
        btn_cfg = QPushButton("Открыть конфиг")
        btn_cfg.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(CONFIG_PATH))))
        btn_img = QPushButton("Профили изображений")
        btn_img.setToolTip("data/image_profiles.json — модели для рисования")
        btn_img.clicked.connect(self._open_profiles)
        extra = QHBoxLayout()
        extra.addWidget(btn_token)
        extra.addWidget(btn_cfg)
        extra.addWidget(btn_img)

        status_box = QGroupBox("Состояние")
        sl = QVBoxLayout(status_box)
        sl.addLayout(form)
        sl.addLayout(btns)
        sl.addWidget(QLabel("Устройства в группе:"))
        sl.addWidget(self.clients)
        sl.addWidget(self.cb_model)
        sl.addWidget(self.cb_link)
        sl.addWidget(self.cb_login)
        sl.addLayout(extra)
        sl.addStretch(1)

        self.qr_kind = QComboBox()
        self.qr_kind.addItems(["Для приложения", "Wi-Fi (проверка из настроек)"])
        self.qr_kind.currentIndexChanged.connect(self._refresh_qr)
        self.qr_label = QLabel()
        self.qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qr_label.setMinimumSize(320, 320)
        self.qr_info = QLabel()
        self.qr_info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.qr_info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qr_info.setMinimumHeight(self.qr_info.fontMetrics().lineSpacing() * 2 + 4)
        self.show_secret = QCheckBox("Показать пароль и токен")
        self.show_secret.toggled.connect(self._refresh_qr)

        qr_box = QGroupBox("Сопряжение")
        ql = QVBoxLayout(qr_box)
        ql.addWidget(self.qr_kind)
        ql.addWidget(self.qr_label, 1)
        ql.addWidget(self.qr_info)
        ql.addWidget(self.show_secret)

        top = QWidget()
        tl = QHBoxLayout(top)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.addWidget(status_box, 1)
        tl.addWidget(qr_box, 1)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(5000)
        mono = QFont("Monospace")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        mono.setPointSize(9)
        self.log_view.setFont(mono)

        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(top)
        split.addWidget(self.log_view)
        split.setStretchFactor(1, 1)
        split.setSizes([500, 220])
        self.setCentralWidget(split)

    def _build_tray(self):
        self.tray = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(app_icon(), self)
        self.tray.setToolTip("LLM Bridge")
        menu = QMenu()
        act_show = QAction("Показать окно", menu)
        act_show.triggered.connect(self.show_normal)
        self.act_link = QAction("Включить канал", menu)
        self.act_link.triggered.connect(self._toggle_link)
        act_quit = QAction("Выход", menu)
        act_quit.triggered.connect(self.quit)
        menu.addAction(act_show)
        menu.addAction(self.act_link)
        menu.addSeparator()
        menu.addAction(act_quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda r: self.show_normal() if r == QSystemTrayIcon.ActivationReason.Trigger else None)
        self.tray.show()

    def show_normal(self):
        self.show()
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.raise_()
        self.activateWindow()

    def quit(self):
        self._quitting = True
        QApplication.quit()

    def closeEvent(self, ev):
        if self._quitting or not self.tray or not self.cfg.close_to_tray:
            self._quitting = True
            QApplication.quit()
            ev.accept()
            return
        ev.ignore()
        self.hide()
        self.tray.showMessage("LLM Bridge", "Работает в фоне. Выход — через меню значка.",
                              QSystemTrayIcon.MessageIcon.Information, 3000)

    def _fill_models(self):
        from models import ensure_dirs, text_models
        ensure_dirs(self.cfg)
        self.model_box.clear()
        current = 0
        for i, p in enumerate(text_models(self.cfg)):
            self.model_box.addItem(p.name, str(p))
            if str(p) == self.cfg.model:
                current = i
        if self.model_box.count() == 0:
            self.model_box.addItem(Path(self.cfg.model).name + " (вне models/llm)", self.cfg.model)
        elif all(self.model_box.itemData(i) != self.cfg.model for i in range(self.model_box.count())):
            self.model_box.insertItem(0, Path(self.cfg.model).name + " (вне models/llm)", self.cfg.model)
            current = 0
        self.model_box.setCurrentIndex(current)

    def _pick_model(self, index: int):
        path = self.model_box.itemData(index)
        if path and path != self.cfg.model:
            self.core.switch_model(path)

    def _open_profiles(self):
        from imagegen import PROFILES_PATH, load_profiles, profile_info
        profiles = load_profiles()   # создаёт файл с шаблонами, если его нет
        for p in profiles:
            info = profile_info(p)
            state = "готов" if info["ready"] else "нет файлов: " + ", ".join(info["missing"])
            self._log(f"Профиль «{info['name']}»: {state}", "img")
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(PROFILES_PATH)))

    def _set_cfg(self, key, value):
        setattr(self.cfg, key, value)
        self.cfg.save()

    def _toggle_login(self, on):
        try:
            set_autostart(on)
            self._log(f"Автозапуск при входе {'включён' if on else 'выключен'}", "app")
        except OSError as e:
            self._log(f"Автозапуск: {e}", "app")

    def _log(self, text: str, src: str = "app"):
        self.log_view.appendPlainText(f"{time.strftime('%H:%M:%S')} [{src}] {text}")

    # -------------------------------------------------------------- модель
    def _on_llama_state(self, state):
        color = {"ready": OK, "external": OK, "error": ERR, "stopped": OFF}.get(state, WARN)
        colored(self.lbl_model, STATE_TEXT.get(state, state), color)
        self.btn_model.setText("Запустить модель" if state in ("stopped", "error")
                               else "Остановить модель")

    def _on_bg_state(self, state):
        if state == "stopped" and not self.core.bg.available():
            colored(self.lbl_bg, "нет файла — ./scripts/setup-helper.sh (работает и без неё, медленнее)", OFF)
            return
        color = {"ready": OK, "external": OK, "error": ERR, "stopped": OFF}.get(state, WARN)
        name = os.path.basename(self.core.bg.model)
        colored(self.lbl_bg, f"{STATE_TEXT.get(state, state)} — {name}", color)

    # --------------------------------------------------------------- канал
    def _toggle_link(self):
        if self.core.link_wanted:
            self.core.link_off()
        else:
            self.core.link_on()

    def _on_link_state(self, state, group):
        if state == "on" and group:
            colored(self.lbl_link, f"{group['ssid']}  ({group.get('freq', '')} МГц, {group['iface']})", OK)
        else:
            text = {"off": "выключен", "starting": "поднимается…", "stopping": "выключается…",
                    "error": "ошибка — см. лог"}.get(state, state)
            colored(self.lbl_link, text, ERR if state == "error" else OFF if state == "off" else WARN)
        wanted = self.core.link_wanted
        self.btn_link.setText("Выключить канал" if wanted else "Включить канал")
        if self.tray:
            self.act_link.setText("Выключить канал" if wanted else "Включить канал")
            self.tray.setToolTip(f"LLM Bridge — канал: {self.lbl_link.text()}")
        if state in ("on", "off", "error"):
            self._refresh_qr()
            if state != "on":
                self.clients.clear()

    def _on_clients(self, stas):
        self.clients.clear()
        for s in stas:
            name = s["name"] or "устройство"
            ip = s["ip"] or "нет IP"
            sig = f", {s['signal']} dBm" if s["signal"] else ""
            self.clients.addItem(f"{name}  {ip}  ({s['mac']}{sig})")

    # ----------------------------------------------------------------- API
    def _on_api(self, where):
        if where:
            colored(self.lbl_api, where, OK)
        else:
            colored(self.lbl_api, "не запущен", OFF)

    def _on_ws_clients(self, n):
        colored(self.lbl_app, f"подключено: {n}" if n else "нет", OK if n else OFF)

    def _on_request(self, ip, path):
        if ip == "127.0.0.1":
            return
        now = time.monotonic()
        if now - self._last_seen.get(ip, 0) > 60:
            self._log(f"запрос от {ip}: {path}", "api")
        self._last_seen[ip] = now

    # ------------------------------------------------------------------ QR
    def _refresh_qr(self):
        g = self.core.group
        if not g:
            self.qr_label.clear()
            self.qr_label.setText("QR появится, когда канал будет включён")
            self.qr_info.setText("")
            return
        text = pairing_uri(self.cfg, g) if self.qr_kind.currentIndex() == 0 else wifi_uri(g)
        self.qr_label.setPixmap(qr_pixmap(text, 320))
        if self.show_secret.isChecked():
            info = f"Сеть: {g['ssid']}   Пароль: {g['passphrase']}\nТокен: {self.cfg.token}"
        else:
            info = f"Сеть: {g['ssid']}   Адрес: {g['ip']}:{self.cfg.bridge_port}"
        self.qr_info.setText(info)

    def _new_token(self):
        if QMessageBox.question(self, "Новый токен",
                                "Сгенерировать новый токен? Телефон придётся заново "
                                "сопрячь по QR-коду.") != QMessageBox.StandardButton.Yes:
            return
        self.core.regenerate_token()
