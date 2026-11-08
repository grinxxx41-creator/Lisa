"""Реестр панелей: какие панели есть в рабочем пространстве и как создаётся их содержимое."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PySide6.QtWidgets import QWidget


@dataclass(frozen=True)
class PanelSpec:
    panel_id: str
    title: str
    factory: Callable[[], QWidget]      # вызывается один раз, при первом открытии панели
    min_size: tuple[int, int] = (320, 200)
    tooltip: str = ""


class PanelRegistry:
    def __init__(self) -> None:
        self._specs: dict[str, PanelSpec] = {}

    def register(self, spec: PanelSpec) -> None:
        if spec.panel_id in self._specs:
            raise ValueError(f"Панель {spec.panel_id!r} уже зарегистрирована")
        self._specs[spec.panel_id] = spec

    def get(self, panel_id: str) -> PanelSpec:
        return self._specs[panel_id]

    def ids(self) -> list[str]:
        return list(self._specs)

    def specs(self) -> list[PanelSpec]:
        return list(self._specs.values())

    def __contains__(self, panel_id: object) -> bool:
        return panel_id in self._specs
