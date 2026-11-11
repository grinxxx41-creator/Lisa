"""Мост к Windows Runtime для островка: что сейчас играет (Global System Media Transport Controls)
и уведомления Windows (UserNotificationListener).

Один фоновый поток с циклом asyncio обслуживает обе задачи. Медиа приходит по событиям Windows,
без опроса. Подписка на уведомления у приложения без пакета недоступна, поэтому их список
запрашивается раз в несколько секунд — и только если пользователь включил это в настройках.

Нужны пакеты winrt-* (см. requirements.txt). Без них available() == False, и островок работает
без музыки и уведомлений Windows. Результаты отдаются через обычные функции обратного вызова,
которые вызываются из фонового потока.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

log = logging.getLogger("sirius.island")

NOTES_POLL_SECONDS = 3.0
_KNOWN_APPS = {
    "spotify": "Spotify", "chrome": "Google Chrome", "msedge": "Microsoft Edge", "firefox": "Firefox",
    "vlc": "VLC", "aimp": "AIMP", "foobar2000": "foobar2000", "zunemusic": "Медиаплеер", "zunevideo": "Кино и ТВ",
    "yandex": "Яндекс Музыка", "opera": "Opera", "brave": "Brave", "telegram": "Telegram", "itunes": "iTunes",
    "applemusic": "Apple Music", "musicbee": "MusicBee", "mpc-hc": "MPC-HC", "potplayer": "PotPlayer",
    "308046b0af4a39cb": "Firefox", "wmplayer": "Windows Media Player", "discord": "Discord",
}


@dataclass(frozen=True)
class MediaInfo:
    app_id: str
    app_name: str
    title: str
    artist: str
    album: str
    status: str                    # playing | paused | stopped
    position: float                # секунды на момент updated_at
    duration: float                # 0 — плеер не сообщает длительность
    updated_at: float              # время системы, когда позиция была верной
    thumbnail: bytes | None = None
    can_toggle: bool = False
    can_next: bool = False
    can_prev: bool = False
    can_seek: bool = False

    @property
    def playing(self) -> bool:
        return self.status == "playing"

    def live_position(self, now: float | None = None) -> float:
        """Текущая позиция: плеер сообщает её редко, между сообщениями она досчитывается по часам."""
        pos = self.position
        if self.playing:
            pos += max(0.0, (now if now is not None else time.time()) - self.updated_at)
        return max(0.0, min(pos, self.duration) if self.duration > 0 else pos)


@dataclass(frozen=True)
class WinNote:
    id: int
    app: str
    title: str
    text: str
    time: float
    icon: bytes | None = None


def available() -> bool:
    """Установлены ли привязки WinRT."""
    if sys.platform != "win32":
        return False
    try:
        import winrt.windows.media.control  # noqa: F401
    except ImportError:
        return False
    return True


def app_title(app_id: str) -> str:
    """Понятное имя плеера по идентификатору приложения Windows."""
    raw = (app_id or "").strip()
    if not raw:
        return "Медиа"
    low = raw.lower()
    for key, name in _KNOWN_APPS.items():
        if key in low:
            return name
    name = raw.split("!")[0].split("\\")[-1]
    if name.lower().endswith(".exe"):
        name = name[:-4]
    if "_" in name and "." in name:          # имя пакета: Издатель.Приложение_хэш
        name = name.split("_")[0].split(".")[-1]
    return name[:40] or "Медиа"


class WinRtBridge:
    def __init__(self, on_media: Callable[[MediaInfo | None], None],
                 on_notes: Callable[[list[WinNote]], None],
                 on_status: Callable[[str, str], None] | None = None) -> None:
        self._on_media = on_media
        self._on_notes = on_notes
        self._on_status = on_status or (lambda kind, text: None)
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._wake: asyncio.Event | None = None
        self._stopping = False
        self._want_media = False
        self._want_notes = False
        self._commands: list[tuple[str, Any]] = []
        self._lock = threading.Lock()
        # состояние фонового потока
        self._manager = None
        self._session = None
        self._tokens: list[tuple[str, Any]] = []
        self._manager_tokens: list[tuple[str, Any]] = []
        self._session_dirty = self._props_dirty = self._media_dirty = False
        self._thumb_key: tuple | None = None
        self._thumb: bytes | None = None
        self._seen: set[int] | None = None
        self._notes_blocked = False
        self._icons: dict[str, bytes | None] = {}

    # --- управление (любой поток) ------------------------------------------------------

    def start(self, media: bool, notifications: bool) -> bool:
        self._want_media, self._want_notes = media, notifications
        if not (media or notifications) or not available():
            return False
        if self.is_running():
            self._poke()
            return True
        self._stopping = False
        self._thread = threading.Thread(target=self._run, daemon=True, name="sirius-winrt")
        self._thread.start()
        return True

    def set_features(self, media: bool, notifications: bool) -> None:
        if not (media or notifications):
            self.stop()
            self._want_media = self._want_notes = False
            return
        if notifications and not self._want_notes:
            self._notes_blocked = False
        self.start(media, notifications)

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def command(self, name: str, value: Any = None) -> None:
        """toggle | next | prev | seek (секунды)."""
        with self._lock:
            self._commands.append((name, value))
        self._poke()

    def stop(self, timeout: float = 3.0) -> None:
        thread = self._thread
        if thread is None:
            return
        self._stopping = True
        self._poke()
        thread.join(timeout)
        if thread.is_alive():
            log.error("Поток WinRT не завершился за %.0f с", timeout)
        self._thread = None

    def _poke(self) -> None:
        loop, wake = self._loop, self._wake
        if loop is not None and wake is not None and not loop.is_closed():
            try:
                loop.call_soon_threadsafe(wake.set)
            except RuntimeError:
                pass   # цикл уже закрывается

    # --- фоновый поток -----------------------------------------------------------------

    def _run(self) -> None:
        try:
            import winrt.runtime as rt
            try:
                rt.init_apartment(rt.MTA)
            except OSError:
                pass
            asyncio.run(self._main())
        except Exception:  # noqa: BLE001 — поток не должен падать молча: причина уходит в журнал
            log.exception("Мост WinRT остановлен из-за ошибки")
            self._on_status("error", "Служба медиа и уведомлений Windows остановлена из-за ошибки")
        finally:
            self._loop = self._wake = None

    async def _main(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._wake = asyncio.Event()
        media_ready = False
        next_notes = 0.0
        while not self._stopping:
            if self._want_media and not media_ready:
                media_ready = await self._setup_media()
            elif not self._want_media and media_ready:
                self._teardown_media()
                media_ready = False
                self._on_media(None)
            if self._want_notes and not self._notes_blocked and time.monotonic() >= next_notes:
                await self._poll_notes()
                next_notes = time.monotonic() + NOTES_POLL_SECONDS
            await self._run_commands()
            if media_ready and (self._media_dirty or self._session_dirty):
                await self._refresh_media()
            timeout = None
            if self._want_notes and not self._notes_blocked:
                timeout = max(0.05, next_notes - time.monotonic())
            try:
                await asyncio.wait_for(self._wake.wait(), timeout)
            except asyncio.TimeoutError:
                pass
            self._wake.clear()
            if media_ready and self._media_dirty:
                await asyncio.sleep(0.06)      # плееры шлют несколько событий подряд — собираем их в одно
        self._teardown_media()

    # --- медиа -------------------------------------------------------------------------

    async def _setup_media(self) -> bool:
        try:
            from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as Manager

            self._manager = await Manager.request_async()
            self._manager_tokens = [
                ("current_session_changed", self._manager.add_current_session_changed(self._on_sessions_event)),
                ("sessions_changed", self._manager.add_sessions_changed(self._on_sessions_event)),
            ]
        except Exception as exc:  # noqa: BLE001 — WinRT бросает OSError и собственные типы
            log.warning("Медиа Windows недоступны: %s", exc)
            self._on_status("media", "Медиа Windows недоступны")
            self._want_media = False
            return False
        self._session_dirty = self._props_dirty = self._media_dirty = True
        return True

    def _teardown_media(self) -> None:
        self._bind_session(None)
        if self._manager is not None:
            for name, token in self._manager_tokens:
                self._safe(getattr(self._manager, f"remove_{name}"), token)
        self._manager_tokens = []
        self._manager = None

    @staticmethod
    def _safe(func, *args) -> None:
        try:
            func(*args)
        except Exception as exc:  # noqa: BLE001
            log.debug("WinRT: %s", exc)

    def _mark(self, session: bool = False, props: bool = False) -> None:
        self._media_dirty = True
        self._session_dirty = self._session_dirty or session
        self._props_dirty = self._props_dirty or props
        if self._wake is not None:
            self._wake.set()

    def _threadsafe(self, **flags) -> None:
        loop = self._loop
        if loop is not None and not loop.is_closed():
            try:
                loop.call_soon_threadsafe(lambda: self._mark(**flags))
            except RuntimeError:
                pass

    # обработчики событий Windows вызываются из потоков WinRT
    def _on_sessions_event(self, *_args) -> None:
        self._threadsafe(session=True, props=True)

    def _on_props_event(self, *_args) -> None:
        self._threadsafe(props=True)

    def _on_playback_event(self, *_args) -> None:
        self._threadsafe()

    def _bind_session(self, session) -> None:
        if self._session is not None:
            for name, token in self._tokens:
                self._safe(getattr(self._session, f"remove_{name}"), token)
        self._tokens = []
        self._session = session
        if session is None:
            return
        try:
            self._tokens = [
                ("media_properties_changed", session.add_media_properties_changed(self._on_props_event)),
                ("playback_info_changed", session.add_playback_info_changed(self._on_playback_event)),
                ("timeline_properties_changed", session.add_timeline_properties_changed(self._on_playback_event)),
            ]
        except Exception as exc:  # noqa: BLE001
            log.warning("Не удалось подписаться на события плеера: %s", exc)

    async def _refresh_media(self) -> None:
        self._media_dirty = False
        try:
            if self._session_dirty:
                self._session_dirty = False
                self._bind_session(self._manager.get_current_session())
            session = self._session
            if session is None:
                self._thumb_key = self._thumb = None
                self._on_media(None)
                return
            props = await session.try_get_media_properties_async()
            playback = session.get_playback_info()
            timeline = session.get_timeline_properties()
            title, artist, album = props.title or "", props.artist or "", props.album_title or ""
            key = (session.source_app_user_model_id, title, artist, album)
            if self._props_dirty or key != self._thumb_key:
                self._props_dirty = False
                self._thumb_key = key
                self._thumb = await self._read_stream(props.thumbnail)
            status = self._status_name(playback.playback_status)
            duration = max(0.0, (timeline.end_time - timeline.start_time).total_seconds())
            position = max(0.0, (timeline.position - timeline.start_time).total_seconds())
            updated = timeline.last_updated_time
            updated_at = updated.timestamp() if updated.year > 2000 else time.time()
            controls = playback.controls
            info = MediaInfo(
                app_id=session.source_app_user_model_id, app_name=app_title(session.source_app_user_model_id),
                title=title, artist=artist, album=album, status=status, position=position, duration=duration,
                updated_at=updated_at, thumbnail=self._thumb,
                can_toggle=bool(controls.is_play_pause_toggle_enabled or controls.is_play_enabled
                                or controls.is_pause_enabled),
                can_next=bool(controls.is_next_enabled), can_prev=bool(controls.is_previous_enabled),
                can_seek=bool(controls.is_playback_position_enabled) and duration > 0)
        except Exception as exc:  # noqa: BLE001 — плеер мог закрыться между событием и чтением
            log.info("Сведения о воспроизведении недоступны: %s", exc)
            self._session_dirty = True
            self._on_media(None)
            return
        self._on_media(info)

    @staticmethod
    def _status_name(status) -> str:
        from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionPlaybackStatus as S

        if status == S.PLAYING:
            return "playing"
        if status == S.PAUSED:
            return "paused"
        return "stopped"

    @staticmethod
    async def _read_stream(reference, limit: int = 4 * 1024 * 1024) -> bytes | None:
        """Читает обложку или значок из потока WinRT."""
        if reference is None:
            return None
        try:
            from winrt.windows.storage.streams import Buffer, InputStreamOptions

            stream = await reference.open_read_async()
            size = int(stream.size)
            if size <= 0 or size > limit:
                return None
            buffer = Buffer(size)
            result = await stream.read_async(buffer, size, InputStreamOptions.READ_AHEAD)
            data = bytes(memoryview(result))
            stream.close()
            return data or None
        except Exception as exc:  # noqa: BLE001
            log.debug("Не удалось прочитать изображение: %s", exc)
            return None

    async def _run_commands(self) -> None:
        with self._lock:
            commands, self._commands = self._commands, []
        session = self._session
        for name, value in commands:
            if session is None:
                continue
            try:
                if name == "toggle":
                    await session.try_toggle_play_pause_async()
                elif name == "next":
                    await session.try_skip_next_async()
                elif name == "prev":
                    await session.try_skip_previous_async()
                elif name == "seek":
                    await session.try_change_playback_position_async(int(max(0.0, float(value)) * 10_000_000))
                self._media_dirty = True
            except Exception as exc:  # noqa: BLE001
                log.warning("Команда плееру «%s» не выполнена: %s", name, exc)

    # --- уведомления Windows -----------------------------------------------------------

    async def _poll_notes(self) -> None:
        try:
            from winrt.windows.ui.notifications import NotificationKinds
            from winrt.windows.ui.notifications.management import (
                UserNotificationListener, UserNotificationListenerAccessStatus as Access)

            listener = UserNotificationListener.current
            status = listener.get_access_status()
            if status == Access.UNSPECIFIED:
                status = await listener.request_access_async()
            if status != Access.ALLOWED:
                self._notes_blocked = True
                self._on_status("notifications", "Windows не разрешила SIRIUS читать уведомления. Разрешение: "
                                "Параметры → Конфиденциальность и защита → Уведомления.")
                return
            current = await listener.get_notifications_async(NotificationKinds.TOAST)
            first = self._seen is None
            seen = self._seen or set()
            fresh: list[WinNote] = []
            ids: set[int] = set()
            for item in current:
                ids.add(item.id)
                if item.id in seen or first:
                    continue
                note = await self._parse_note(item)
                if note is not None and time.time() - note.time < 60:
                    fresh.append(note)      # старые уведомления (островок был скрыт) не всплывают заново
            self._seen = ids
            if fresh:
                self._on_notes(fresh)
        except Exception as exc:  # noqa: BLE001
            log.warning("Уведомления Windows недоступны: %s", exc)
            self._notes_blocked = True
            self._on_status("notifications", "Уведомления Windows недоступны на этом компьютере")

    async def _parse_note(self, item) -> WinNote | None:
        try:
            app, icon = "Windows", None
            try:
                display = item.app_info.display_info
                app = display.display_name or app
                if app not in self._icons:
                    from winrt.windows.foundation import Size

                    self._icons[app] = await self._read_stream(display.get_logo(Size(64, 64)), 512 * 1024)
                icon = self._icons[app]
            except Exception as exc:  # noqa: BLE001 — у классических приложений сведений может не быть
                log.debug("Нет сведений о приложении уведомления: %s", exc)
            binding = item.notification.visual.get_binding("ToastGeneric")
            texts = [t.text for t in binding.get_text_elements()] if binding is not None else []
            texts = [t for t in texts if t]
            if not texts:
                return None
            return WinNote(item.id, app, texts[0], "\n".join(texts[1:]), item.creation_time.timestamp(), icon)
        except Exception as exc:  # noqa: BLE001
            log.debug("Уведомление Windows не разобрано: %s", exc)
            return None
