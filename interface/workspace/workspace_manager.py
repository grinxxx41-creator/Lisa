"""Жизненный цикл панелей: открытие без копий, закрытие, сворачивание, порядок наложения, компоновка.

Содержимое панели может реализовать необязательные методы:
- panel_shown() — панель стала видна (например, запустить опрос);
- panel_hidden() — панель закрыта или свёрнута (остановить фоновую работу и освободить ресурсы).
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal

from interface.motion import fade_in
from interface.workspace.floating_panel import FloatingPanel
from interface.workspace.panel_layout import (
    DEFAULT_PRESET, DEFAULT_VISIBLE, PanelState, Rect, WorkspaceState, anchor_rect, default_layout, parse_state,
)
from interface.workspace.panel_registry import PanelRegistry
from interface.workspace.workspace_canvas import WorkspaceCanvas

log = logging.getLogger("sirius.workspace")


class WorkspaceManager(QObject):
    panels_changed = Signal()   # открытие, закрытие, сворачивание — для панели управления
    layout_changed = Signal()   # что-то из сохраняемого состояния изменилось

    def __init__(self, canvas: WorkspaceCanvas, registry: PanelRegistry, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.canvas = canvas
        self.registry = registry
        self._panels: dict[str, FloatingPanel] = {}
        # желаемое место панели и размер области, в которой оно задано; None — стандартное место
        self._desired: dict[str, tuple[Rect, tuple[int, int]] | None] = {}
        self._collapsed: dict[str, bool] = {}
        self._z_order: list[str] = []
        self._active: str | None = None
        self._preset = DEFAULT_PRESET
        self._status: dict[str, tuple[str, str]] = {}
        canvas.resized.connect(self._on_canvas_resized)

    # --- доступ -------------------------------------------------------------

    def panel(self, panel_id: str) -> FloatingPanel | None:
        return self._panels.get(panel_id)

    def is_open(self, panel_id: str) -> bool:
        panel = self._panels.get(panel_id)
        return panel is not None and not panel.isHidden()

    def is_collapsed(self, panel_id: str) -> bool:
        return self._collapsed.get(panel_id, False)

    def open_ids(self) -> list[str]:
        return [pid for pid in self.registry.ids() if self.is_open(pid)]

    @property
    def active_panel(self) -> str | None:
        return self._active

    @property
    def z_order(self) -> list[str]:
        return list(self._z_order)

    # --- открытие и закрытие ----------------------------------------------------

    def _ensure(self, panel_id: str) -> FloatingPanel:
        panel = self._panels.get(panel_id)
        if panel is not None:
            return panel
        spec = self.registry.get(panel_id)
        panel = FloatingPanel(panel_id, spec.title, spec.min_size, self.canvas)
        panel.hide()
        content = spec.factory()
        panel.set_content(content)
        # содержимое может добавить свои индикаторы и кнопки в заголовок панели
        title_widgets = getattr(content, "title_widgets", None)
        if callable(title_widgets):
            for widget in title_widgets():
                panel.titlebar.add_widget(widget)
        if panel_id in self._status:
            panel.set_status(*self._status[panel_id])
        panel.set_collapsed(self._collapsed.get(panel_id, False))
        panel.activated.connect(self.activate)
        panel.close_requested.connect(self.close)
        panel.collapse_requested.connect(self.toggle_collapsed)
        panel.geometry_committed.connect(self._on_geometry_committed)
        self._panels[panel_id] = panel
        self._desired.setdefault(panel_id, None)
        self._z_order.append(panel_id)
        log.info("Создана панель %s", panel_id)
        return panel

    def open(self, panel_id: str, activate: bool = True) -> FloatingPanel:
        """Открывает панель. Повторный вызов не создаёт копию, а показывает существующую панель."""
        panel = self._ensure(panel_id)
        was_hidden = panel.isHidden()
        self._place(panel_id)
        panel.show()
        if activate:
            self.activate(panel_id)
        if was_hidden:
            fade_in(panel)
            self._notify_content(panel_id)
            self.panels_changed.emit()
            self.layout_changed.emit()
        return panel

    def close(self, panel_id: str) -> None:
        panel = self._panels.get(panel_id)
        if panel is None or panel.isHidden():
            return
        panel.hide()
        if self._active == panel_id:
            self._set_active(None)
        self._notify_content(panel_id)
        self.panels_changed.emit()
        self.layout_changed.emit()

    def toggle(self, panel_id: str) -> None:
        if self.is_open(panel_id):
            self.close(panel_id)
        else:
            self.open(panel_id)

    def hide_all(self) -> None:
        for panel_id in list(self._panels):
            self.close(panel_id)

    def toggle_collapsed(self, panel_id: str) -> None:
        self.set_collapsed(panel_id, not self.is_collapsed(panel_id))

    def set_collapsed(self, panel_id: str, collapsed: bool) -> None:
        self._collapsed[panel_id] = collapsed
        panel = self._panels.get(panel_id)
        if panel is None:
            return
        if panel.is_collapsed() != collapsed:
            panel.set_collapsed(collapsed)
            self._place(panel_id)
            self._notify_content(panel_id)
            self.panels_changed.emit()
            self.layout_changed.emit()

    def set_status(self, panel_id: str, color: str, tooltip: str = "") -> None:
        """Цвет индикатора в заголовке панели. Запоминается, если панель ещё не создана."""
        self._status[panel_id] = (color, tooltip)
        panel = self._panels.get(panel_id)
        if panel is not None:
            panel.set_status(color, tooltip)

    def close_all_resources(self) -> None:
        """Перед закрытием окна: всем панелям сообщается, что они скрыты (остановка фоновой работы)."""
        for panel_id, panel in self._panels.items():
            content = panel.content()
            hook = getattr(content, "panel_hidden", None)
            if callable(hook):
                try:
                    hook()
                except Exception:
                    log.exception("Ошибка при остановке панели %s", panel_id)

    # --- порядок наложения и активная панель --------------------------------------

    def activate(self, panel_id: str) -> None:
        panel = self._panels.get(panel_id)
        if panel is None or panel.isHidden():
            return
        if self._z_order and self._z_order[-1] != panel_id:
            self._z_order.remove(panel_id)
            self._z_order.append(panel_id)
            self.layout_changed.emit()
        panel.raise_()
        self._set_active(panel_id)

    def _set_active(self, panel_id: str | None) -> None:
        if panel_id == self._active:
            return
        self._active = panel_id
        for pid, panel in self._panels.items():
            panel.set_active(pid == panel_id)

    # --- расположение --------------------------------------------------------------

    def _canvas_size(self) -> tuple[int, int]:
        return max(self.canvas.width(), 1), max(self.canvas.height(), 1)

    def target_rect(self, panel_id: str) -> Rect:
        """Где панель должна стоять в текущей области (до вписывания в границы)."""
        w, h = self._canvas_size()
        desired = self._desired.get(panel_id)
        if desired is None:
            return default_layout(w, h).get(panel_id, Rect(40, 40, 420, 320))
        rect, (from_w, from_h) = desired
        return anchor_rect(rect, from_w, from_h, w, h)

    def _place(self, panel_id: str) -> None:
        panel = self._panels.get(panel_id)
        if panel is not None:
            panel.apply_rect(self.target_rect(panel_id))

    def _on_canvas_resized(self, _w: int, _h: int) -> None:
        for panel_id in self._panels:
            self._place(panel_id)

    def _on_geometry_committed(self, panel_id: str) -> None:
        panel = self._panels.get(panel_id)
        if panel is None:
            return
        rect = panel.rect_now()
        if panel.is_collapsed():
            # у свёрнутой панели сохраняем прежнюю высоту
            rect = Rect(rect.x, rect.y, rect.w, self.target_rect(panel_id).h)
        self._desired[panel_id] = (rect, self._canvas_size())
        self.layout_changed.emit()

    def reset_layout(self) -> None:
        """Стандартная компоновка: открыты CHAT и SYSTEM, все панели на стандартных местах."""
        for panel_id in self.registry.ids():
            self._desired[panel_id] = None
            self._collapsed[panel_id] = False
            panel = self._panels.get(panel_id)
            if panel is not None and panel.is_collapsed():
                panel.set_collapsed(False)
        self._preset = DEFAULT_PRESET
        for panel_id in self.registry.ids():
            if panel_id in DEFAULT_VISIBLE:
                self.open(panel_id, activate=False)
            else:
                self.close(panel_id)
        for panel_id in self._panels:
            self._place(panel_id)
        if "chat" in self._panels:
            self.activate("chat")
        self.panels_changed.emit()
        self.layout_changed.emit()

    # --- сохранение -----------------------------------------------------------------

    def state(self) -> dict:
        ws = WorkspaceState(preset=self._preset, active=self._active, z_order=list(self._z_order))
        for panel_id in self.registry.ids():
            desired = self._desired.get(panel_id)
            ws.panels[panel_id] = PanelState(
                rect=desired[0] if desired else None,
                canvas=desired[1] if desired else None,
                visible=self.is_open(panel_id),
                collapsed=self._collapsed.get(panel_id, False),
            )
        return ws.to_dict()

    def restore(self, raw: object) -> None:
        """Восстанавливает сохранённую компоновку. Без сохранения — стандартная компоновка."""
        state = parse_state(raw, tuple(self.registry.ids()))
        if state is None:
            self.reset_layout()
            return
        self._preset = state.preset
        for panel_id in self.registry.ids():
            st = state.panels.get(panel_id)
            if st is not None and st.rect is not None and st.canvas is not None:
                self._desired[panel_id] = (st.rect, st.canvas)
            else:
                self._desired[panel_id] = None
            self._collapsed[panel_id] = bool(st and st.collapsed)
        ordered = [pid for pid in state.z_order if pid in state.panels]
        ordered += [pid for pid in self.registry.ids() if pid not in ordered]
        for panel_id in ordered:
            st = state.panels.get(panel_id)
            if st is not None and st.visible:
                self.open(panel_id, activate=False)
            else:
                self.close(panel_id)
        active = state.active if state.active and self.is_open(state.active) else None
        if active:
            self.activate(active)
        self.panels_changed.emit()

    # --- внутреннее -----------------------------------------------------------------

    def _notify_content(self, panel_id: str) -> None:
        panel = self._panels.get(panel_id)
        if panel is None:
            return
        content = panel.content()
        visible = not panel.isHidden() and not panel.is_collapsed()
        hook = getattr(content, "panel_shown" if visible else "panel_hidden", None)
        if callable(hook):
            try:
                hook()
            except Exception:
                log.exception("Ошибка обработчика видимости панели %s", panel_id)
