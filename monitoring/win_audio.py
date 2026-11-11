"""Громкость и уровень звука Windows (Core Audio) через ctypes — без сторонних зависимостей.

AudioEndpoint читает устройство вывода по умолчанию: общую громкость, признак «без звука» и
пиковый уровень сигнала (IAudioMeterInformation) — настоящий уровень того, что сейчас играет.
Только чтение: громкость SIRIUS не меняет. Вне Windows и без звукового устройства available == False.
"""

from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import POINTER, byref, c_float, c_int, c_long, c_uint, c_void_p

log = logging.getLogger("sirius.monitor")

_CLSCTX_ALL = 23
_E_RENDER, _E_MULTIMEDIA = 0, 1


class _GUID(ctypes.Structure):
    _fields_ = [("d1", ctypes.c_ulong), ("d2", ctypes.c_ushort), ("d3", ctypes.c_ushort), ("d4", ctypes.c_ubyte * 8)]


def _guid(text: str) -> _GUID:
    guid = _GUID()
    ctypes.oledll.ole32.CLSIDFromString(ctypes.c_wchar_p(text), byref(guid))
    return guid


def _call(pointer: c_void_p, index: int, *args, argtypes=()) -> int:
    """Вызов метода COM-интерфейса по номеру в таблице виртуальных функций. Возвращает HRESULT."""
    vtable = ctypes.cast(pointer, POINTER(c_void_p))[0]
    address = ctypes.cast(vtable, POINTER(c_void_p))[index]
    func = ctypes.WINFUNCTYPE(c_long, c_void_p, *argtypes)(address)
    return func(pointer, *args)


def _release(pointer: c_void_p | None) -> None:
    if pointer:
        _call(pointer, 2)


class AudioEndpoint:
    """Устройство вывода звука по умолчанию. Вызывать из одного потока (поток интерфейса)."""

    def __init__(self) -> None:
        self._volume: c_void_p | None = None
        self._meter: c_void_p | None = None
        self.available = False
        self.open()

    def open(self) -> bool:
        """Подключается к текущему устройству по умолчанию (повторный вызов — после смены устройства)."""
        self.close()
        if sys.platform != "win32":
            return False
        try:
            ctypes.windll.ole32.CoInitializeEx(None, 2)   # поток интерфейса Qt уже в STA; повтор безвреден
            enumerator, device = c_void_p(), c_void_p()
            hr = ctypes.windll.ole32.CoCreateInstance(
                byref(_guid("{BCDE0395-E52F-467C-8E3D-C4579291692E}")), None, _CLSCTX_ALL,
                byref(_guid("{A95664D2-9614-4F35-A746-DE8DB63617E6}")), byref(enumerator))
            if hr < 0 or not enumerator:
                return False
            try:
                hr = _call(enumerator, 4, _E_RENDER, _E_MULTIMEDIA, byref(device),
                           argtypes=(c_int, c_int, POINTER(c_void_p)))
                if hr < 0 or not device:
                    return False              # нет устройства вывода
                try:
                    self._volume = self._activate(device, "{5CDF2C82-841E-4546-9722-0CF74078229A}")
                    self._meter = self._activate(device, "{C02216F6-8C67-4B5B-9D00-D008E73E0064}")
                finally:
                    _release(device)
            finally:
                _release(enumerator)
        except (OSError, AttributeError, ValueError) as exc:
            log.warning("Звуковое устройство недоступно: %s", exc)
            self.close()
            return False
        self.available = self._volume is not None
        return self.available

    @staticmethod
    def _activate(device: c_void_p, iid: str) -> c_void_p | None:
        result = c_void_p()
        hr = _call(device, 3, byref(_guid(iid)), _CLSCTX_ALL, None, byref(result),
                   argtypes=(c_void_p, c_uint, c_void_p, POINTER(c_void_p)))
        return result if hr >= 0 and result else None

    def volume(self) -> tuple[float, bool] | None:
        """(громкость 0..100, без звука) или None, если устройство недоступно."""
        if self._volume is None:
            return None
        level, muted = c_float(), c_int()
        if _call(self._volume, 9, byref(level), argtypes=(POINTER(c_float),)) < 0:
            return None
        if _call(self._volume, 15, byref(muted), argtypes=(POINTER(c_int),)) < 0:
            return None
        return max(0.0, min(100.0, level.value * 100.0)), bool(muted.value)

    def set_volume(self, percent: float) -> bool:
        """Задаёт общую громкость устройства вывода, 0..100. False — устройство недоступно."""
        if self._volume is None:
            return False
        level = c_float(max(0.0, min(1.0, float(percent) / 100.0)))
        return _call(self._volume, 7, level, None, argtypes=(c_float, c_void_p)) >= 0

    def peak(self) -> float | None:
        """Пиковый уровень воспроизводимого звука 0..1 или None."""
        if self._meter is None:
            return None
        value = c_float()
        if _call(self._meter, 3, byref(value), argtypes=(POINTER(c_float),)) < 0:
            return None
        return max(0.0, min(1.0, value.value))

    def close(self) -> None:
        for pointer in (self._volume, self._meter):
            try:
                _release(pointer)
            except OSError:
                pass
        self._volume = self._meter = None
        self.available = False
