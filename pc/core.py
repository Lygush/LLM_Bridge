"""Ядро моста без GUI: модель, канал Wi-Fi Direct, сервер.

Используется и окном (ui.py), и режимом без окна (main.py --headless).
"""
from PyQt6.QtCore import QMetaObject, QObject, Qt, QThread, QTimer, pyqtSignal

from config import new_token
from llama import LlamaProcess
from p2p import P2PWorker
from server import BridgeServer

LINK_RETRY_MS = 10_000


class BridgeCore(QObject):
    log = pyqtSignal(str, str)            # текст, источник
    llama_state = pyqtSignal(str)
    bg_state = pyqtSignal(str)            # состояние фоновой модели
    link_state = pyqtSignal(str, object)  # off | starting | on | stopping | error, группа
    api_state = pyqtSignal(str)           # адреса сервера
    clients = pyqtSignal(list)            # устройства в группе
    ws_clients = pyqtSignal(int)          # подключённые приложения
    token_changed = pyqtSignal()

    _p2p_start = pyqtSignal()
    _p2p_stop = pyqtSignal()

    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.group = None
        self.link_wanted = False
        self.link = "off"

        self.llama = LlamaProcess(cfg, self)
        self.llama.log.connect(lambda s: self.log.emit(s, "llama"))
        self.llama.state_changed.connect(self.llama_state)
        self.llama.state_changed.connect(self._after_llama_state)
        self._restart_pending = False

        # фоновая маленькая модель на процессоре: память, отношения, состояние квеста
        self.bg = LlamaProcess(cfg, self, role="bg")
        self.bg.log.connect(lambda s: self.log.emit(s, "фон"))
        self.bg.state_changed.connect(self.bg_state)

        self.p2p_thread = QThread(self)
        self.p2p = P2PWorker(cfg)
        self.p2p.moveToThread(self.p2p_thread)
        self._p2p_start.connect(self.p2p.start)
        self._p2p_stop.connect(self.p2p.stop)
        self.p2p.log.connect(lambda s: self.log.emit(s, "p2p"))
        self.p2p.started.connect(self._on_group_up)
        self.p2p.stopped.connect(self._on_group_down)
        self.p2p.failed.connect(self._on_group_failed)
        self.p2p.clients.connect(self.clients)
        self.p2p_thread.start()

        self.server = BridgeServer(cfg)
        self.server.log.connect(lambda s: self.log.emit(s, "api"))
        self.server.failed.connect(lambda s: self.log.emit(s, "api"))
        self.server.listening.connect(self.api_state)
        self.server.clients_changed.connect(self.ws_clients)
        self.server.llama_control.connect(self._llama_control)

        self._retry = QTimer(self)
        self._retry.setSingleShot(True)
        self._retry.timeout.connect(self._retry_link)

    # ----------------------------------------------------------------- старт
    def start(self, model: bool = None, link: bool = None):
        self.server.start()
        if self.cfg.autostart_model if model is None else model:
            self.llama.start()
        if self.cfg.bg_autostart and self.bg.available():
            self.bg.start()
        if self.cfg.autostart_link if link is None else link:
            self.link_on()

    # ---------------------------------------------------------------- модель
    def toggle_model(self):
        if self.llama.state in ("stopped", "error"):
            self.llama.start()
        else:
            self.llama.stop()

    def switch_model(self, path: str):
        """Выбрать текстовую модель; mmproj (зрение) подбирается сам. Работающая модель перезапускается."""
        from models import guess_mmproj
        self.cfg.model = path
        self.cfg.mmproj = guess_mmproj(path)
        self.cfg.save()
        self.log.emit(f"Текстовая модель: {path}" +
                      (f" + {self.cfg.mmproj}" if self.cfg.mmproj else " (без зрения: mmproj не найден)"), "app")
        if self.llama.state in ("ready", "loading", "starting"):
            self._restart_pending = True
            self.llama.stop()

    def toggle_bg(self):
        if self.bg.state in ("stopped", "error"):
            self.bg.start()
        else:
            self.bg.stop()

    def _after_llama_state(self, state: str):
        if self._restart_pending and state in ("stopped", "error"):
            self._restart_pending = False
            self.llama.start()

    def _llama_control(self, on: bool):
        """Запрос сервера: освободить видеопамять для рисования или вернуть модель."""
        if on:
            if self.llama.state in ("stopped", "error"):
                self.llama.start()
        elif self.llama.state not in ("stopped", "error", "external"):
            self.llama.stop()

    # ----------------------------------------------------------------- канал
    def _set_link(self, state: str):
        self.link = state
        self.link_state.emit(state, self.group)

    def link_on(self):
        self.link_wanted = True
        self._retry.stop()
        self._set_link("starting")
        self._p2p_start.emit()

    def link_off(self):
        self.link_wanted = False
        self._retry.stop()
        if self.group:
            self.server.unbind(self.group["ip"])
        self._set_link("stopping")
        self._p2p_stop.emit()

    def _on_group_up(self, group: dict):
        self.group = group
        self._set_link("on")
        self.server.bind(group["ip"])

    def _on_group_down(self):
        self.group = None
        self._set_link("off")

    def _on_group_failed(self, msg: str):
        self.log.emit(msg, "p2p")
        if self.group:
            self.server.unbind(self.group["ip"])
        self.group = None
        self._set_link("error")
        if self.link_wanted:
            self.log.emit(f"Повтор через {LINK_RETRY_MS // 1000} с", "p2p")
            self._retry.start(LINK_RETRY_MS)

    def _retry_link(self):
        if self.link_wanted:
            self._set_link("starting")
            self._p2p_start.emit()

    # ------------------------------------------------------------------ токен
    def regenerate_token(self):
        self.cfg.token = new_token()
        self.cfg.save()
        self.log.emit("Токен заменён — телефон нужно сопрячь заново", "app")
        self.token_changed.emit()

    # ------------------------------------------------------------------ выход
    def shutdown(self):
        self._retry.stop()
        self.server.stop(wait=True)
        if self.p2p.group:
            QMetaObject.invokeMethod(self.p2p, "stop", Qt.ConnectionType.BlockingQueuedConnection)
        self.p2p_thread.quit()
        self.p2p_thread.wait(3000)
        self.llama.stop(wait=True)
        self.bg.stop(wait=True)
