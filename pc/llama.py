"""Запуск llama-server как дочернего процесса и отслеживание его готовности."""
import os
import socket

from PyQt6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, QUrl, pyqtSignal

import paths
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

# Состояния: stopped / starting / loading / ready / external / error
STATE_TEXT = {
    "stopped": "остановлена",
    "starting": "запуск…",
    "loading": "загрузка в память…",
    "ready": "готова",
    "external": "готова (внешний llama-server)",
    "error": "ошибка",
}


def port_busy(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


class LlamaProcess(QObject):
    log = pyqtSignal(str)
    state_changed = pyqtSignal(str)

    def __init__(self, cfg, parent=None, role: str = "main"):
        super().__init__(parent)
        self.cfg = cfg
        self.role = role   # main — большая модель на видеокарте, bg — фоновая маленькая
        self.state = "stopped"
        self.proc = None
        self._nam = QNetworkAccessManager(self)
        self._timer = QTimer(self)
        self._timer.setInterval(1500)
        self._timer.timeout.connect(self._check_health)
        self._buf = b""

    def _set(self, state):
        if state != self.state:
            self.state = state
            self.state_changed.emit(state)

    @property
    def port(self) -> int:
        return self.cfg.bg_port if self.role == "bg" else self.cfg.llama_port

    @property
    def model(self) -> str:
        return os.path.expanduser(self.cfg.bg_model if self.role == "bg" else self.cfg.model)

    def available(self) -> bool:
        return bool(self.model) and os.path.exists(self.model) and os.path.exists(self.cfg.llama_bin)

    # ---------------------------------------------------------------- start
    def start(self):
        if self.proc or self.state == "external":
            return
        cfg = self.cfg
        if port_busy(self.port):
            self.log.emit(f"Порт {self.port} уже занят — используется уже запущенный llama-server")
            self._set("external")
            self._timer.start()
            return
        for path, what in ((cfg.llama_bin, "llama-server"), (self.model, "модель")):
            if not os.path.exists(path):
                self.log.emit(f"Не найден файл ({what}): {path}")
                self._set("error")
                return

        args = ["-m", self.model]
        if self.role == "bg":
            args += ["-ngl", str(cfg.bg_ngl), "-c", str(cfg.bg_ctx), "-np", "1",
                     "--host", "127.0.0.1", "--port", str(cfg.bg_port), "--jinja"]
            if cfg.bg_threads:
                args += ["-t", str(cfg.bg_threads)]
        else:
            if cfg.mmproj:
                if os.path.exists(cfg.mmproj):
                    args += ["--mmproj", cfg.mmproj]
                else:
                    self.log.emit(f"mmproj не найден, запуск без картинок: {cfg.mmproj}")
            args += ["-ngl", str(cfg.ngl), "-c", str(cfg.ctx),
                     "--host", "127.0.0.1", "--port", str(cfg.llama_port),
                     "--jinja"]   # шаблон модели целиком — нужен для вызова инструментов (рисование)
            args += [str(a) for a in cfg.llama_extra_args]

        self.proc = QProcess(self)
        env = QProcessEnvironment.systemEnvironment()   # библиотеки llama.cpp лежат рядом с программой
        env.insert("LD_LIBRARY_PATH", paths.lib_env(cfg.llama_bin)["LD_LIBRARY_PATH"])
        self.proc.setProcessEnvironment(env)
        self.proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.proc.readyReadStandardOutput.connect(self._read_output)
        self.proc.finished.connect(self._finished)
        self.proc.errorOccurred.connect(self._error)
        self.log.emit("Запуск: " + " ".join([cfg.llama_bin] + args))
        self._set("starting")
        self.proc.start(cfg.llama_bin, args)
        self._timer.start()

    # ----------------------------------------------------------------- stop
    def stop(self, wait: bool = False):
        self._timer.stop()
        if self.state == "external":
            self._set("stopped")
            return
        if not self.proc:
            return
        if self.proc.state() != QProcess.ProcessState.NotRunning:
            self.log.emit("Остановка llama-server…")
            self.proc.terminate()
            if wait:
                if not self.proc.waitForFinished(8000):
                    self.proc.kill()
                    self.proc.waitForFinished(2000)
            else:
                proc = self.proc
                QTimer.singleShot(8000, lambda: self._kill_if_running(proc))

    def _kill_if_running(self, proc):
        # к этому времени процесс обычно уже завершён и объект удалён
        if proc is not self.proc:
            return
        try:
            if proc.state() != QProcess.ProcessState.NotRunning:
                proc.kill()
        except RuntimeError:
            pass

    # ------------------------------------------------------------ internals
    def _read_output(self):
        # сигнал может прийти уже после завершения процесса — читаем у того, кто прислал
        proc = self.sender() or self.proc
        if proc is None:
            return
        try:
            self._buf += bytes(proc.readAllStandardOutput())
        except RuntimeError:   # объект процесса уже удалён
            return
        *lines, self._buf = self._buf.split(b"\n")
        for line in lines:
            text = line.decode(errors="replace").rstrip()
            if text:
                self.log.emit(text)

    def _finished(self, code, status):
        self._timer.stop()
        try:
            if self.proc is not None:
                self._buf += bytes(self.proc.readAllStandardOutput())   # остаток вывода
        except RuntimeError:
            pass
        if self._buf:
            self.log.emit(self._buf.decode(errors="replace"))
            self._buf = b""
        crashed = status == QProcess.ExitStatus.CrashExit or code not in (0, 15, -15)
        self.log.emit(f"llama-server завершился (код {code})")
        self.proc.deleteLater()
        self.proc = None
        self._set("error" if crashed and self.state != "stopped" else "stopped")

    def _error(self, err):
        if err == QProcess.ProcessError.FailedToStart:
            self.log.emit(f"Не удалось запустить {self.cfg.llama_bin}")
            self._timer.stop()
            self.proc.deleteLater()
            self.proc = None
            self._set("error")

    def _check_health(self):
        req = QNetworkRequest(QUrl(f"http://127.0.0.1:{self.port}/health"))
        req.setTransferTimeout(1200)
        reply = self._nam.get(req)
        reply.finished.connect(lambda r=reply: self._on_health(r))

    def _on_health(self, reply: QNetworkReply):
        code = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        reply.deleteLater()
        if self.state == "external":
            if code != 200:
                self.log.emit("Внешний llama-server перестал отвечать")
                self._timer.stop()
                self._set("stopped")
            return
        if self.proc is None:
            return
        if code == 200:
            self._set("ready")
        elif code == 503:
            self._set("loading")
