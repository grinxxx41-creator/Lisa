"""Логика расположения панелей: исправление координат, привязка к краям, стандартная компоновка, разбор состояния."""

from __future__ import annotations

import pytest

from interface.workspace.panel_layout import (
    COLLAPSED_HEIGHT, DEFAULT_VISIBLE, PANEL_IDS, Rect, anchor_rect, avatar_rect, clamp_rect, default_layout,
    parse_state, WorkspaceState, PanelState,
)

# размеры рабочей области (окно минус заголовок Windows, панель управления и строка состояния)
SCREENS = [(1240, 560), (1326, 610), (1880, 920), (2520, 1280), (1024, 520)]


def _inside(rect: Rect, w: int, h: int) -> bool:
    return rect.x >= 0 and rect.y >= 0 and rect.right <= w and rect.bottom <= h


def test_clamp_pulls_rect_back_inside():
    r = clamp_rect(Rect(-500, 9000, 400, 300), 1200, 700, 320, 200)
    assert r == Rect(0, 400, 400, 300)


def test_clamp_never_goes_below_minimum_or_negative():
    r = clamp_rect(Rect(10, 10, -50, 0), 1200, 700, 320, 200)
    assert (r.w, r.h) == (320, 200)
    assert r.x >= 0 and r.y >= 0


def test_clamp_shrinks_rect_larger_than_area():
    r = clamp_rect(Rect(0, 0, 3000, 2000), 1200, 700, 320, 200)
    assert r == Rect(0, 0, 1200, 700)


def test_clamp_in_area_smaller_than_minimum_keeps_title_reachable():
    r = clamp_rect(Rect(300, 300, 400, 300), 200, 100, 320, 200)
    assert (r.x, r.y) == (0, 0)


def test_anchor_keeps_right_panel_at_right_edge():
    r = anchor_rect(Rect(900, 14, 360, 600), 1280, 700, 1920, 1000)
    assert r.right == 1920 - (1280 - 1260)
    assert r.y == 14  # верхняя половина: отступ сверху сохраняется


def test_anchor_keeps_bottom_panel_at_bottom():
    r = anchor_rect(Rect(300, 450, 400, 230), 1280, 700, 1280, 900)
    assert r.bottom == 900 - (700 - 680)
    assert r.x == 300


@pytest.mark.parametrize("w,h", SCREENS)
def test_default_layout_fits_and_frees_avatar(w, h):
    layout = default_layout(w, h)
    assert set(layout) == set(PANEL_IDS)
    for rect in layout.values():
        fixed = clamp_rect(rect, w, h, 300, 160)
        assert _inside(fixed, w, h)
    # стандартно открытые панели не закрывают аватар
    avatar = avatar_rect(w, h)
    if w >= 1200:
        for panel_id in DEFAULT_VISIBLE:
            assert not layout[panel_id].intersects(avatar), (panel_id, w, h)


def test_rect_from_value_rejects_garbage():
    assert Rect.from_value([1, 2, 3, 4]) == Rect(1, 2, 3, 4)
    for bad in (None, "x", [1, 2, 3], [1, 2, "3", 4], [1, 2, 0, 4], [True, 1, 2, 3],
                [float("nan"), 1, 2, 3], [1, 2, 10**9, 4]):
        assert Rect.from_value(bad) is None


def test_parse_state_roundtrip():
    ws = WorkspaceState(active="chat", z_order=["system", "chat"])
    ws.panels["chat"] = PanelState(Rect(10, 20, 400, 500), (1280, 700), True, False)
    ws.panels["code"] = PanelState(None, None, False, True)
    parsed = parse_state(ws.to_dict())
    assert parsed is not None
    assert parsed.panels["chat"].rect == Rect(10, 20, 400, 500)
    assert parsed.panels["chat"].canvas == (1280, 700)
    assert parsed.panels["chat"].visible is True
    assert parsed.panels["code"].collapsed is True
    assert parsed.z_order == ["system", "chat"]
    assert parsed.active == "chat"


@pytest.mark.parametrize("raw", [None, [], "bad", {}, {"panels": []}, {"panels": {"unknown": {}}}])
def test_parse_state_invalid_returns_none(raw):
    assert parse_state(raw) is None


def test_parse_state_drops_bad_values():
    raw = {
        "panels": {
            "chat": {"rect": [1, 2, -5, 4], "canvas": [100, 100], "visible": "yes"},
            "logs": {"rect": [1, 2, 300, 200], "canvas": "big", "visible": True},
        },
        "z_order": ["chat", "chat", "evil", 5],
        "active": "evil",
    }
    parsed = parse_state(raw)
    assert parsed.panels["chat"].rect is None
    assert parsed.panels["chat"].visible is False
    assert parsed.panels["logs"].rect is None and parsed.panels["logs"].visible is True
    assert parsed.z_order == ["chat"]
    assert parsed.active is None


def test_collapsed_height_is_title_only():
    assert 30 <= COLLAPSED_HEIGHT <= 48
