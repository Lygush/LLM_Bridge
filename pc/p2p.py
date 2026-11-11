"""Управление группой Wi-Fi Direct (wpa_cli) и DHCP (через привилегированный helper).

Работает в отдельном QThread: все вызовы wpa_cli блокирующие.
"""
import glob
import os
import re
import subprocess
import time

from PyQt6.QtCore import QObject, QTimer, pyqtSignal, pyqtSlot

LEASE_FILE = "/run/llm-bridge/dnsmasq.leases"
MAC_RE = re.compile(r"^[0-9a-f]{2}(:[0-9a-f]{2}){5}$")


class P2PError(RuntimeError):
    pass


def wpa(iface: str, *args: str, timeout: float = 5.0) -> str:
    try:
        r = subprocess.run(["wpa_cli", "-i", iface, *args],
                           capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        raise P2PError("wpa_cli не найден (пакет wpasupplicant)")
    except subprocess.TimeoutExpired:
        raise P2PError(f"wpa_cli {' '.join(args)}: нет ответа")
    out = (r.stdout + r.stderr).strip()
    if "Failed to connect" in out:
        if "Permission denied" in out:
            raise P2PError("Нет доступа к wpa_supplicant: пользователь не в группе netdev "
                           "(выполните install.sh и перелогиньтесь)")
        raise P2PError(f"wpa_supplicant недоступен на {iface}: {out}")
    return out


def wpa_ok(iface: str, *args: str) -> bool:
    out = wpa(iface, *args)
    return bool(out) and out.splitlines()[-1].strip() == "OK"


def wpa_status(iface: str) -> dict:
    st = {}
    for line in wpa(iface, "status").splitlines():
        k, sep, v = line.partition("=")
        if sep:
            st[k.strip()] = v.strip()
    return st


class P2PWorker(QObject):
    log = pyqtSignal(str)
    started = pyqtSignal(dict)      # {"iface","ssid","passphrase","freq","ip"}
    stopped = pyqtSignal()
    failed = pyqtSignal(str)
    clients = pyqtSignal(list)      # [{"mac","ip","name","signal"}]

    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self.group = None
        self._created_group = False
        self._timer = None

    # ---------------------------------------------------------------- slots
    @pyqtSlot()
    def start(self):
        if self.group:
            self.started.emit(self.group)
            return
        try:
            iface, st, passphrase = self._ensure_go()
            self.log.emit(f"Группа {st.get('ssid')} на {iface}, {st.get('freq')} МГц")
            self._helper("up", iface, self.cfg.p2p_ip, self.cfg.dhcp_start, self.cfg.dhcp_end)
            self.log.emit(f"Адрес {self.cfg.p2p_ip} и DHCP подняты на {iface}")
            self.group = {
                "iface": iface,
                "ssid": st.get("ssid", ""),
                "passphrase": passphrase,
                "freq": st.get("freq", ""),
                "ip": self.cfg.p2p_ip,
            }
            if self._timer is None:
                self._timer = QTimer(self)
                self._timer.setInterval(3000)
                self._timer.timeout.connect(self._poll)
            self._timer.start()
            self.started.emit(self.group)
        except P2PError as e:
            self.failed.emit(str(e))

    @pyqtSlot()
    def stop(self):
        if self._timer:
            self._timer.stop()
        if not self.group:
            self.stopped.emit()
            return
        iface = self.group["iface"]
        try:
            self._helper("down", iface, self.cfg.p2p_ip)
        except P2PError as e:
            self.log.emit(f"helper down: {e}")
        if self.cfg.remove_group_on_stop:
            try:
                wpa(self.cfg.wifi_iface, "p2p_group_remove", iface)
                self.log.emit("Группа Wi-Fi Direct удалена")
            except P2PError as e:
                self.log.emit(f"p2p_group_remove: {e}")
        self.group = None
        self.clients.emit([])
        self.stopped.emit()

    # ------------------------------------------------------------- internals
    def _find_go(self):
        """Ищет уже работающий GO: на самом интерфейсе или на p2p-<iface>-N."""
        base = self.cfg.wifi_iface
        cands = [base] + sorted(os.path.basename(p) for p in glob.glob(f"/sys/class/net/p2p-{base}-*"))
        for c in cands:
            try:
                st = wpa_status(c)
            except P2PError:
                continue
            if st.get("mode") == "P2P GO" and st.get("wpa_state") == "COMPLETED":
                return c, st
        return None

    def _networks(self) -> list:
        """[(id, ssid, flags)] из list_networks."""
        out = wpa(self.cfg.wifi_iface, "list_networks")
        res = []
        for line in out.splitlines()[1:]:
            parts = line.split("\t")
            if len(parts) >= 2 and parts[0].strip().isdigit():
                res.append((parts[0].strip(), parts[1], parts[3] if len(parts) > 3 else ""))
        return res

    def _fixed_network(self):
        """Сеть постоянной группы с SSID и паролем из конфига.

        wpa_supplicant NetworkManager'а не хранит сети между перезагрузками,
        поэтому блок сети каждый раз создаётся заново с одними и теми же данными —
        телефону не нужно повторно сопрягаться.
        """
        base, ssid, psk = self.cfg.wifi_iface, self.cfg.p2p_ssid, self.cfg.p2p_psk
        for nid, s, _ in self._networks():
            if s == ssid:
                wpa(base, "remove_network", nid)  # пароль не прочитать — пересоздаём
        out = wpa(base, "add_network").splitlines()
        nid = out[-1].strip() if out else ""
        if not nid.isdigit():
            raise P2PError(f"add_network: {out}")
        steps = [("ssid", f'"{ssid}"'), ("psk", f'"{psk}"'), ("proto", "RSN"),
                 ("key_mgmt", "WPA-PSK"), ("pairwise", "CCMP"),
                 ("mode", "3"),        # P2P Group Owner
                 ("disabled", "2")]    # 2 = постоянная группа P2P
        for key, val in steps:
            if not wpa_ok(base, "set_network", nid, key, val):
                wpa(base, "remove_network", nid)
                raise P2PError(f"set_network {key} отклонён")
        return nid

    def _wait_go(self, want_ssid=None, timeout=15.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            found = self._find_go()
            if found and (want_ssid is None or found[1].get("ssid") == want_ssid):
                return found
            time.sleep(0.5)
        return None

    def _ensure_go(self):
        base = self.cfg.wifi_iface
        if not os.path.isdir(f"/sys/class/net/{base}"):
            raise P2PError(f"Интерфейс {base} не найден (wifi_iface в конфиге)")
        if not wpa_ok(base, "set", "device_name", self.cfg.p2p_device_name):
            self.log.emit("Не удалось задать device_name (не критично)")

        want = self.cfg.p2p_ssid
        freq = f"freq={self.cfg.p2p_freq}"
        found = self._find_go()
        if found and found[1].get("ssid") == want:
            self.log.emit("Используется уже работающая группа")
        else:
            if found:
                self.log.emit(f"Остановка группы {found[1].get('ssid')} — у нас постоянная {want}")
                wpa(base, "p2p_group_remove", found[0])
                deadline = time.monotonic() + 5
                while self._find_go() and time.monotonic() < deadline:
                    time.sleep(0.3)
            found = None
            try:
                nid = self._fixed_network()
                self.log.emit(f"Запуск постоянной группы {want}")
                if wpa_ok(base, "p2p_group_add", f"persistent={nid}", freq):
                    found = self._wait_go(want)
            except P2PError as e:
                self.log.emit(f"Постоянная группа: {e}")
            if not found:
                self.log.emit("Не удалось поднять группу с постоянным именем — создаётся случайная "
                              "(телефон придётся сопрячь заново)")
                if not wpa_ok(base, "p2p_group_add", "persistent", freq):
                    raise P2PError("wpa_supplicant отказал в p2p_group_add")
                found = self._wait_go()
            if not found:
                raise P2PError("Группа не поднялась за 15 с (см. journalctl -u wpa_supplicant)")

        iface, st = found
        passphrase = ""
        for i in (iface, base):
            try:
                out = wpa(i, "p2p_get_passphrase").strip()
            except P2PError:
                continue
            if out and out != "FAIL" and "\n" not in out:
                passphrase = out
                break
        if not passphrase:
            raise P2PError("Не удалось получить пароль группы")
        return iface, st, passphrase

    def _helper(self, *args: str):
        cmd = ["sudo", "-n", self.cfg.helper, *args]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        except FileNotFoundError:
            raise P2PError("sudo не найден")
        except subprocess.TimeoutExpired:
            raise P2PError("helper: нет ответа")
        if r.returncode != 0:
            msg = (r.stderr or r.stdout).strip()
            if "password" in msg.lower() or "пароль" in msg.lower():
                msg = "sudo требует пароль: helper не установлен (выполните install.sh)"
            raise P2PError(f"helper {args[0]}: {msg}")

    @staticmethod
    def _leases() -> dict:
        res = {}
        try:
            with open(LEASE_FILE, encoding="utf-8") as f:
                for line in f:
                    p = line.split()
                    if len(p) >= 4:
                        res[p[1].lower()] = (p[2], "" if p[3] == "*" else p[3])
        except OSError:
            pass
        return res

    @pyqtSlot()
    def _poll(self):
        if not self.group:
            return
        iface = self.group["iface"]
        try:
            st = wpa_status(iface)
            if st.get("mode") != "P2P GO":
                self._timer.stop()
                self.group = None
                self.clients.emit([])
                self.failed.emit("Группа Wi-Fi Direct пропала")
                return
            out = wpa(iface, "all_sta")
        except P2PError as e:
            self.log.emit(f"Опрос клиентов: {e}")
            return
        leases = self._leases()
        stas, cur = [], None
        for line in out.splitlines():
            line = line.strip()
            if MAC_RE.match(line.lower()):
                cur = {"mac": line.lower(), "ip": "", "name": "", "signal": ""}
                ip, name = leases.get(cur["mac"], ("", ""))
                cur["ip"], cur["name"] = ip, name
                stas.append(cur)
            elif cur and line.startswith("signal="):
                cur["signal"] = line.split("=", 1)[1]
        # вход и уход телефона из группы Wi-Fi — в лог: видно, оборвался Wi-Fi или только приложение
        now = {x["mac"]: x for x in stas}
        old = getattr(self, "_seen", {})
        for mac, x in now.items():
            if mac not in old:
                self.log.emit(f"Wi-Fi: вошёл {x['name'] or mac} (сигнал {x['signal'] or '?'})")
        for mac, x in old.items():
            if mac not in now:
                self.log.emit(f"Wi-Fi: вышел из группы {x['name'] or mac} "
                              f"(последний сигнал {x['signal'] or '?'})")
        self._seen = now
        self.clients.emit(stas)
