"""QR-коды для сопряжения телефона."""
from urllib.parse import urlencode

import qrcode
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QImage, QPainter, QPixmap


def pairing_uri(cfg, group: dict) -> str:
    """Ссылка для Android-приложения: всё, что нужно для подключения и доступа к API."""
    return "llmbridge://pair?" + urlencode({
        "v": 1,
        "ssid": group["ssid"],
        "psk": group["passphrase"],
        "host": group["ip"],
        "port": cfg.bridge_port,
        "token": cfg.token,
        "name": cfg.p2p_device_name,
    })


def _esc(s: str) -> str:
    for ch in '\\;,:"':
        s = s.replace(ch, "\\" + ch)
    return s


def wifi_uri(group: dict) -> str:
    """Стандартный Wi-Fi QR — подключение из настроек Android, для проверки."""
    return f"WIFI:T:WPA;S:{_esc(group['ssid'])};P:{_esc(group['passphrase'])};;"


def qr_pixmap(text: str, size: int = 300) -> QPixmap:
    # border=4 — стандартная «тихая зона»: без неё камеры Android часто не распознают код
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=4)
    qr.add_data(text)
    qr.make(fit=True)
    matrix = qr.get_matrix()
    n = len(matrix)
    scale = max(1, size // n)
    img = QImage(n * scale, n * scale, QImage.Format.Format_RGB32)
    img.fill(QColor("white"))
    p = QPainter(img)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("black"))
    for y, row in enumerate(matrix):
        for x, v in enumerate(row):
            if v:
                p.drawRect(x * scale, y * scale, scale, scale)
    p.end()
    return QPixmap.fromImage(img)
