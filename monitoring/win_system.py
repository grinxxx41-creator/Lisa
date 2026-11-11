"""Системные индикаторы Windows для островка: яркость встроенного экрана, Caps Lock и Num Lock,
состояние Wi-Fi и Bluetooth. Только чтение, без прав администратора и без сторонних зависимостей.
Каждая функция возвращает None, если данных нет (настольный монитор, нет адаптера, не Windows).
"""

from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import POINTER, byref, wintypes
from dataclasses import dataclass

log = logging.getLogger("sirius.monitor")

_IOCTL_QUERY_BRIGHTNESS = 0x230498
_INVALID_HANDLE = wintypes.HANDLE(-1).value
_VK_CAPITAL, _VK_NUMLOCK = 0x14, 0x90


class Brightness:
    """Яркость встроенного экрана ноутбука (устройство \\\\.\\LCD). На внешних мониторах недоступна."""

    def __init__(self) -> None:
        self._handle = None
        self.available = False
        if sys.platform != "win32":
            return
        try:
            self._k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            self._k32.CreateFileW.restype = wintypes.HANDLE
            self._k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                              wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
            self._k32.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                                                  ctypes.c_void_p, wintypes.DWORD, POINTER(wintypes.DWORD),
                                                  ctypes.c_void_p]
            self._k32.CloseHandle.argtypes = [wintypes.HANDLE]
            handle = self._k32.CreateFileW(r"\\.\LCD", 0x80000000, 3, None, 3, 0, None)
            if handle and handle != _INVALID_HANDLE:
                self._handle = handle
                self.available = self.get() is not None
        except (OSError, AttributeError) as exc:
            log.info("Яркость экрана недоступна: %s", exc)

    def get(self, on_battery: bool | None = None) -> int | None:
        """Яркость 0..100. on_battery выбирает значение для текущего источника питания."""
        if self._handle is None:
            return None
        buf = (ctypes.c_ubyte * 3)()          # DISPLAY_BRIGHTNESS: политика, от сети, от батареи
        returned = wintypes.DWORD()
        if not self._k32.DeviceIoControl(self._handle, _IOCTL_QUERY_BRIGHTNESS, None, 0, buf, 3,
                                         byref(returned), None) or returned.value < 3:
            return None
        value = buf[2] if on_battery else buf[1]
        return int(min(100, max(0, value)))

    def close(self) -> None:
        if self._handle is not None:
            self._k32.CloseHandle(self._handle)
            self._handle = None
            self.available = False


def lock_keys() -> dict[str, bool] | None:
    """Состояние Caps Lock и Num Lock."""
    if sys.platform != "win32":
        return None
    user32 = ctypes.windll.user32
    return {"caps": bool(user32.GetKeyState(_VK_CAPITAL) & 1), "num": bool(user32.GetKeyState(_VK_NUMLOCK) & 1)}


# --- Wi-Fi ---------------------------------------------------------------------------

@dataclass(frozen=True)
class WifiInfo:
    present: bool                 # есть беспроводной адаптер
    connected: bool = False
    ssid: str = ""                # может быть пустым: Windows 11 отдаёт имя сети только с доступом к геолокации
    signal: int | None = None     # качество сигнала, %


class _GUID(ctypes.Structure):
    _fields_ = [("d1", wintypes.DWORD), ("d2", wintypes.WORD), ("d3", wintypes.WORD), ("d4", ctypes.c_ubyte * 8)]


class _WlanInterfaceInfo(ctypes.Structure):
    _fields_ = [("guid", _GUID), ("description", ctypes.c_wchar * 256), ("state", wintypes.DWORD)]


class _WlanInterfaceList(ctypes.Structure):
    _fields_ = [("count", wintypes.DWORD), ("index", wintypes.DWORD), ("items", _WlanInterfaceInfo * 1)]


class _Dot11Ssid(ctypes.Structure):
    _fields_ = [("length", wintypes.ULONG), ("ssid", ctypes.c_ubyte * 32)]


class _WlanAssociation(ctypes.Structure):
    _fields_ = [("ssid", _Dot11Ssid), ("bss_type", wintypes.DWORD), ("bssid", ctypes.c_ubyte * 6),
                ("phy_type", wintypes.DWORD), ("phy_index", wintypes.ULONG), ("signal", wintypes.ULONG),
                ("rx_rate", wintypes.ULONG), ("tx_rate", wintypes.ULONG)]


class _WlanConnection(ctypes.Structure):
    _fields_ = [("state", wintypes.DWORD), ("mode", wintypes.DWORD), ("profile", ctypes.c_wchar * 256),
                ("association", _WlanAssociation)]


_WLAN_CONNECTED = 1
_WLAN_OPCODE_CURRENT_CONNECTION = 7


def wifi_status() -> WifiInfo | None:
    """Состояние Wi-Fi через WLAN API. None — служба WLAN недоступна."""
    if sys.platform != "win32":
        return None
    try:
        wlan = ctypes.WinDLL("wlanapi")
    except OSError:
        return None
    wlan.WlanFreeMemory.argtypes = [ctypes.c_void_p]
    handle, version = wintypes.HANDLE(), wintypes.DWORD()
    if wlan.WlanOpenHandle(2, None, byref(version), byref(handle)) != 0:
        return None
    try:
        listing = POINTER(_WlanInterfaceList)()
        if wlan.WlanEnumInterfaces(handle, None, byref(listing)) != 0 or not listing:
            return None
        try:
            count = listing.contents.count
            if count == 0:
                return WifiInfo(present=False)
            items = ctypes.cast(ctypes.addressof(listing.contents.items),
                                POINTER(_WlanInterfaceInfo * count)).contents
            best = WifiInfo(present=True)
            for item in items:
                if item.state != _WLAN_CONNECTED:
                    continue
                size, data, kind = wintypes.DWORD(), ctypes.c_void_p(), wintypes.DWORD()
                if wlan.WlanQueryInterface(handle, byref(item.guid), _WLAN_OPCODE_CURRENT_CONNECTION, None,
                                           byref(size), byref(data), byref(kind)) != 0 or not data:
                    best = WifiInfo(present=True, connected=True)
                    continue
                try:
                    conn = ctypes.cast(data, POINTER(_WlanConnection)).contents
                    raw = bytes(conn.association.ssid.ssid[:min(32, conn.association.ssid.length)])
                    return WifiInfo(True, True, raw.decode("utf-8", "replace"),
                                    int(min(100, conn.association.signal)))
                finally:
                    wlan.WlanFreeMemory(data)
            return best
        finally:
            wlan.WlanFreeMemory(listing)
    except (OSError, ValueError) as exc:
        log.info("Состояние Wi-Fi недоступно: %s", exc)
        return None
    finally:
        wlan.WlanCloseHandle(handle, None)


# --- Bluetooth -----------------------------------------------------------------------

@dataclass(frozen=True)
class BluetoothInfo:
    enabled: bool                 # радиомодуль есть и включён
    connected: int = 0            # подключённые устройства


class _BtFindRadio(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD)]


class _SystemTime(ctypes.Structure):
    _fields_ = [(n, wintypes.WORD) for n in ("y", "mo", "dow", "d", "h", "mi", "s", "ms")]


class _BtDeviceInfo(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("address", ctypes.c_ulonglong), ("device_class", wintypes.ULONG),
                ("connected", wintypes.BOOL), ("remembered", wintypes.BOOL), ("authenticated", wintypes.BOOL),
                ("last_seen", _SystemTime), ("last_used", _SystemTime), ("name", ctypes.c_wchar * 248)]


class _BtSearch(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("authenticated", wintypes.BOOL), ("remembered", wintypes.BOOL),
                ("unknown", wintypes.BOOL), ("connected", wintypes.BOOL), ("inquiry", wintypes.BOOL),
                ("timeout", ctypes.c_ubyte), ("radio", wintypes.HANDLE)]


def bluetooth_status() -> BluetoothInfo | None:
    """Включён ли Bluetooth и сколько устройств подключено (без поиска новых устройств)."""
    if sys.platform != "win32":
        return None
    try:
        bt = ctypes.WinDLL("bthprops.cpl")
    except OSError:
        return None
    try:
        bt.BluetoothFindFirstRadio.restype = wintypes.HANDLE
        bt.BluetoothFindRadioClose.argtypes = [wintypes.HANDLE]
        bt.BluetoothFindFirstDevice.restype = wintypes.HANDLE
        bt.BluetoothFindNextDevice.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
        bt.BluetoothFindDeviceClose.argtypes = [wintypes.HANDLE]
        radio = wintypes.HANDLE()
        params = _BtFindRadio(ctypes.sizeof(_BtFindRadio))
        find = bt.BluetoothFindFirstRadio(byref(params), byref(radio))
        if not find:
            return BluetoothInfo(enabled=False)
        bt.BluetoothFindRadioClose(find)
        connected = 0
        try:
            search = _BtSearch(ctypes.sizeof(_BtSearch), 0, 0, 0, 1, 0, 0, radio)
            info = _BtDeviceInfo()
            info.size = ctypes.sizeof(_BtDeviceInfo)
            device = bt.BluetoothFindFirstDevice(byref(search), byref(info))
            if device:
                try:
                    while True:
                        connected += 1 if info.connected else 0
                        if not bt.BluetoothFindNextDevice(device, byref(info)):
                            break
                finally:
                    bt.BluetoothFindDeviceClose(device)
        finally:
            ctypes.windll.kernel32.CloseHandle(radio)
        return BluetoothInfo(enabled=True, connected=connected)
    except (OSError, AttributeError, ValueError) as exc:
        log.info("Состояние Bluetooth недоступно: %s", exc)
        return None
