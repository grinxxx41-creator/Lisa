"""Текст о состоянии компьютера для LISA: реальные данные мониторинга вместо догадок модели. Без Qt.

Данные добавляются к запросу, только если вопрос касается компьютера (is_system_question),
чтобы не тратить контекст модели на каждом сообщении.
"""

from __future__ import annotations

import re

from monitoring.history import MetricsHistory
from monitoring.session_stats import SessionStats, format_duration
from monitoring.system_info import SystemSnapshot

_SYSTEM_WORDS = re.compile(
    r"компьютер|\bпк\b|ноутбук|систем[аеуы]\b|нагрузк|загруж|процессор|\bцп\b|видеокарт|видеопамят|"
    r"оперативк|оперативн\w* памят|\bпамят[ьи]\b|температур|грее|перегре|горяч|диск|место на|"
    r"батаре|заряд|аккумулятор|ресурс|тормоз|лага|медленно работ|процесс|сеть\b|скорость интернет|"
    r"\b(cpu|gpu|ram|vram|ssd|hdd)\b|как там (комп|систем|железо)|железо",
    re.IGNORECASE,
)


def is_system_question(text: str) -> bool:
    return bool(_SYSTEM_WORDS.search(text or ""))


def _gb(b: float) -> str:
    return f"{b / 1024 ** 3:.1f} ГБ"


def _rate(bps: float | None) -> str:
    if bps is None:
        return "нет данных"
    if bps >= 1024 ** 2:
        return f"{bps / 1024 ** 2:.1f} МБ/с"
    return f"{bps / 1024:.0f} КБ/с"


def build_report(snap: SystemSnapshot | None, history: MetricsHistory | None = None,
                 stats: SessionStats | None = None, model_vram: float | None = None) -> str:
    """Краткая сводка обычным текстом. Недоступные датчики названы явно, чтобы модель их не выдумывала."""
    if snap is None:
        return "Данные мониторинга ещё не получены."
    lines = []
    if snap.cpu_percent is not None:
        avg = history.average("cpu", 60) if history else None
        extra = f", в среднем за минуту {avg:.0f}%" if avg is not None else ""
        lines.append(f"Процессор: загрузка {snap.cpu_percent:.0f}%{extra}.")
    lines.append("Температура процессора: " + (f"{snap.cpu_temp_c:.0f} °C." if snap.cpu_temp_c is not None
                                                else "датчик недоступен в Windows без прав администратора."))
    if snap.ram_total and snap.ram_used is not None:
        lines.append(f"Оперативная память: занято {_gb(snap.ram_used)} из {_gb(snap.ram_total)} ({snap.ram_percent:.0f}%).")
    g = snap.gpu
    if g is not None:
        parts = [f"Видеокарта {g.name}:"]
        if g.utilization is not None:
            parts.append(f"загрузка {g.utilization:.0f}%,")
        if g.memory_used_mb is not None and g.memory_total_mb:
            parts.append(f"видеопамять {g.memory_used_mb / 1024:.1f} из {g.memory_total_mb / 1024:.1f} ГБ,")
        if g.temperature_c is not None:
            parts.append(f"температура {g.temperature_c:.0f} °C")
        lines.append(" ".join(parts).rstrip(",") + ".")
    else:
        lines.append("Видеокарта: данные недоступны.")
    if model_vram:
        lines.append(f"Модель Qwen занимает в видеопамяти {_gb(model_vram)}.")
    if snap.disks:
        lines.append("Диски: " + "; ".join(f"{d.mount} свободно {_gb(d.free)} из {_gb(d.total)}" for d in snap.disks) + ".")
    if snap.net_recv_bps is not None:
        lines.append(f"Сеть: приём {_rate(snap.net_recv_bps)}, отправка {_rate(snap.net_sent_bps)}.")
    b = snap.battery
    if b is not None:
        power = "от сети" if b.plugged else "от батареи"
        left = f", осталось около {format_duration(b.seconds_left)}" if b.seconds_left else ""
        lines.append(f"Батарея: {b.percent:.0f}%, питание {power}{left}.")
    if snap.processes:
        by_cpu = sorted(snap.processes, key=lambda p: p.cpu_percent, reverse=True)[:2]
        by_ram = sorted(snap.processes, key=lambda p: p.rss, reverse=True)[:3]
        chosen = list({p.pid: p for p in by_cpu + by_ram}.values())
        top = ", ".join(f"{p.name} (CPU {p.cpu_percent:.0f}%, память {_gb(p.rss)})" for p in chosen)
        lines.append(f"Самые тяжёлые процессы: {top}.")
    if stats is not None:
        if stats.peaks:
            peaks = []
            for key, title, unit in (("cpu", "CPU", "%"), ("gpu", "GPU", "%"), ("gpu_temp", "GPU", " °C")):
                if key in stats.peaks:
                    peaks.append(f"{title} {stats.peaks[key]:.0f}{unit}")
            if peaks:
                lines.append(f"Пики за сессию ({format_duration(stats.uptime())}): " + ", ".join(peaks) + ".")
        if stats.avg_tokens_per_second:
            lines.append(f"Скорость модели: в среднем {stats.avg_tokens_per_second:.0f} токенов в секунду.")
    return "\n".join(lines)


def report_message(report: str) -> dict:
    """Системное сообщение для модели с реальными данными."""
    return {
        "role": "system",
        "content": "Актуальные данные мониторинга SIRIUS (измерены только что, это факты):\n" + report
        + "\nОтвечай о состоянии компьютера только по этим данным. Если нужного значения нет — скажи, что оно "
          "недоступно. Ты ничего не меняешь в системе.",
    }
