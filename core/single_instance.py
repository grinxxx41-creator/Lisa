"""Один экземпляр SIRIUS: повторный запуск (например, второй двойной клик по ярлыку) не открывает
второе окно, а просит уже запущенное окно показаться.

Первый экземпляр захватывает файл-замок и слушает локальный канал. Следующий не получает замок,
отправляет в канал команду «show» и завершается. Замок, оставшийся после аварийного завершения,
Qt распознаёт по номеру процесса и освобождает.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from PySide6.QtCore import QLockFile, QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

log = logging.getLogger("sirius.instance")

SHOW_COMMAND = b"show"


def channel_name(base_dir: Path) -> str:
    """Имя канала зависит от папки проекта: две копии SIRIUS в разных папках не мешают друг другу."""
    digest = hashlib.sha1(str(Path(base_dir).resolve()).lower().encode("utf-8")).hexdigest()[:12]
    return f"SIRIUS-LISA-{digest}"


class SingleInstance(QObject):
    activation_requested = Signal()   # другой запуск попросил показать окно

    def __init__(self, lock_path: Path, name: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        Path(lock_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = QLockFile(str(lock_path))
        self._name = name
        self._server: QLocalServer | None = None
        self._buffers: dict[QLocalSocket, bytes] = {}

    def acquire(self) -> bool:
        """True — это первый экземпляр. False — SIRIUS уже запущен (ему отправлена просьба показаться)."""
        if self._lock.tryLock(200):
            QLocalServer.removeServer(self._name)
            server = QLocalServer(self)
            if not server.listen(self._name):
                log.warning("Канал одного экземпляра недоступен: %s", server.errorString())
            server.newConnection.connect(self._on_connection)
            self._server = server
            return True
        self._notify_running()
        return False

    def release(self) -> None:
        if self._server is not None:
            self._server.close()
            self._server = None
        self._lock.unlock()

    def _notify_running(self) -> None:
        socket = QLocalSocket()
        socket.connectToServer(self._name)
        if socket.waitForConnected(1000):
            socket.write(SHOW_COMMAND)
            socket.flush()
            socket.waitForBytesWritten(1000)
            socket.disconnectFromServer()
        else:
            log.warning("SIRIUS уже запущен, но не отвечает: %s", socket.errorString())

    def _on_connection(self) -> None:
        server = self._server
        if server is None:
            return
        socket = server.nextPendingConnection()
        if socket is None:
            return
        self._buffers[socket] = b""
        socket.readyRead.connect(lambda s=socket: self._on_data(s))
        socket.disconnected.connect(lambda s=socket: self._on_closed(s))
        if socket.bytesAvailable():  # команда могла прийти раньше, чем подключён readyRead
            self._on_data(socket)

    def _on_data(self, socket: QLocalSocket) -> None:
        data = self._buffers.get(socket, b"") + bytes(socket.readAll())
        if SHOW_COMMAND in data:
            self._buffers[socket] = b""
            self.activation_requested.emit()
        else:
            self._buffers[socket] = data[-len(SHOW_COMMAND):]

    def _on_closed(self, socket: QLocalSocket) -> None:
        if socket.bytesAvailable():
            self._on_data(socket)
        self._buffers.pop(socket, None)
        socket.deleteLater()
