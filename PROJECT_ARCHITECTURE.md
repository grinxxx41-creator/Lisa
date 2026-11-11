# Архитектура SIRIUS v0.2 (LISA Workspace)

## Принципы

- Бизнес-логика (`core/`, `voice/`, `storage/`, `monitoring/`) **не импортирует PySide6 Widgets**. Исключения: `voice/` использует `QObject` и `QMediaPlayer`, `core/terminal_session.py` — `QProcess` (QtCore).
- Интерфейс (`interface/`) только показывает состояние и вызывает модули. Он не делает сетевых запросов и не пишет файлы напрямую.
- Сетевые вызовы и синтез речи выполняются в фоне, GUI-поток не ждёт их.
- Каждый компонент может отказать, не закрывая приложение.

## Структура

```
main.py                  точка входа: логирование, иконка, один экземпляр, ошибки запуска, MainWindow
tools/
  create_shortcut.py     ярлык запуска двойным кликом (pythonw, без консоли) и иконка sirius.ico
  prepare_lisa_avatar.py изображение LISA из референса пользователя
core/
  ai_engine.py           потоковый чат с Ollama (/api/chat), таймауты, отмена
  model_manager.py       проверка Ollama, запуск сервера, наличие и загрузка модели
  context_manager.py     системная инструкция LISA и обрезка истории по длине
  title_generator.py     название диалога по первому сообщению (запасной вариант — первые слова)
  single_instance.py     один экземпляр: QLockFile + QLocalServer, повторный запуск показывает окно
  code_blocks.py         v0.2: блоки кода из Markdown-ответов (язык, незакрытый блок)
  log_reader.py          v0.2: чтение только новых строк журнала, разбор, фильтр
  command_policy.py      v0.2: разбор команды консоли, запреты и подтверждения
  terminal_session.py    v0.2: QProcess без оболочки, декодирование вывода, остановка дерева процессов
monitoring/
  system_info.py         v0.2: снимок CPU/RAM (psutil) и GPU (nvidia-smi), None вместо выдуманных значений
voice/
  text_processing.py     очистка Markdown, разбиение потока на фразы (код не озвучивается, фраза не рвётся на «3.» и «т.»)
  silero_engine.py       v0.2.5: голос Silero v4 (xenia), основной; Piper — запасной
  numbers_ru.py          v0.2.5: числа словами для Silero
  (interface/boot_overlay.py — v0.2.6: экран запуска; interface/workers.BootWorker — загрузка при старте)
  speech_normalizer.py   v0.2.3: текст для произношения — латиница кириллицей, сокращения, символы, единицы
  audio_effects.py       v0.2.3: тембр — высота без изменения темпа, мягкость, плавные края, пауза
  tts_engine.py          синтез через Piper, WAV во временную папку
  audio_player.py        воспроизведение WAV (Qt Multimedia), громкость, стоп
  voice_controller.py    очередь фраз, состояние VOICE ON/OFF, немедленная остановка
storage/
  storage_manager.py     атомарная запись JSON и безопасное чтение
  settings_storage.py    настройки в storage/settings.json
  chat_storage.py        чаты в storage/chats/chat_NNN.json
interface/
  main_window.py         главное окно: связывает модули, регистрирует панели
  avatar_widget.py       аватар LISA, состояния (в т. ч. OFFLINE), нажатие для остановки речи
  chat_panel.py          содержимое панели CHAT: лента сообщений, поле ввода, индикаторы
  history_panel.py       содержимое панели HISTORY: список диалогов, поиск
  settings_panel.py      окно настроек
  workers.py             QThread: генерация, загрузка модели, Ollama, системная информация, журнал
  styles.py              палитра и общий QSS
  workspace/             v0.2: система плавающих панелей
    backdrop.py          фон окна: ночной город (программная отрисовка, кэш на размер окна)
    workspace_canvas.py  прозрачная рабочая область: аватар в центре, тени панелей, участок фона для панелей
    floating_panel.py    базовая панель: перетаскивание, размер, сворачивание, активность
    panel_titlebar.py    заголовок: индикатор, название, кнопки
    panel_registry.py    реестр панелей (id, название, фабрика содержимого, мин. размер)
    panel_layout.py      чистая логика: стандартная компоновка, привязка к краям, исправление координат, JSON
    workspace_manager.py жизненный цикл панелей, порядок наложения, сохранение и восстановление
    control_bar.py       панель управления рабочим пространством
  panels/                v0.2: содержимое новых панелей
    code_panel.py        CODE: блоки кода с подсветкой Pygments
    system_panel.py      SYSTEM: метрики, Ollama, модель, Piper
    logs_panel.py        LOGS: журнал в реальном времени
    terminal_panel.py    TERMINAL: ограниченная консоль
tests/                   pytest: хранилище, AI Engine, голос (заглушки), остановка генерации, окно, импорты, реальная модель
resources/voices/        голосовые модели Piper
logs/sirius.log          журнал
```

## Взаимодействие модулей

```
          ┌─────────────────────────────── interface ───────────────────────────────┐
          │  MainWindow ── ChatPanel, AvatarWidget, HistoryPanel, SettingsPanel      │
          │      │                                                                  │
          │  GenerationWorker (QThread)     PullWorker (QThread)                     │
          └──────┼──────────────────────────────────────┼────────────────────────────┘
                 ▼                                      ▼
   core.AIEngine ── HTTP ──► Ollama (localhost:11434)  core.ModelManager
                 │                                      
                 │ токены                                
                 ▼                                      
   voice.VoiceController ── SentenceBuffer ── TTSEngine (Piper, фоновый поток)
                 │                                      
                 ▼                                      
             AudioPlayer (QMediaPlayer)                     
                                                         
   storage.ChatStorage / SettingsStorage ── storage_manager (атомарная запись)
```

### Поток одного ответа

1. `MainWindow` сохраняет реплику пользователя через `ChatStorage`.
2. `context_manager.build_messages` собирает системную инструкцию и историю.
3. `GenerationWorker` в `QThread` вызывает `AIEngine.stream_reply` и отдаёт токены сигналами. По окончании он выдаёт `finished_ok` (полный ответ) или `stopped` (ответ прерван пользователем).
4. Каждый токен попадает в `ChatPanel` (показ) и в `VoiceController.feed` (озвучивание).
5. `SentenceBuffer` выдаёт только завершённые фразы без Markdown. Каждая фраза синтезируется в фоне.
6. Готовые WAV ставятся в очередь `AudioPlayer`. По окончании фразы файл удаляется.
7. По окончании ответа `VoiceController.finish_message` озвучивает остаток текста.

### Остановка речи

Нажатие на аватар вызывает `VoiceController.stop()`:
- останавливает `AudioPlayer`,
- очищает очередь и отбрасывает результаты уже запущенного синтеза (по номеру токена),
- временные WAV удаляются; если файл ещё занят плеером, удаление повторяется позже (`_remove_later`),
- текущий ответ больше не озвучивается до следующего сообщения (`begin_message`),
- **не** трогает `AIEngine`. Генерация текста продолжается.

Сигналы «файл доигран» содержат путь файла. Сигнал от уже остановленного или заменённого файла игнорируется.

### Остановка генерации

Кнопка «Стоп» вызывает `GenerationWorker.stop()` и `VoiceController.stop()`:
- `stop()` закрывает открытый HTTP-поток из GUI-потока; чтение прекращается сразу после получения ответа сервера;
- если остановка пришла до открытия потока, поток закрывается сразу после получения ответа (`_on_response`);
- Ollama получает обрыв соединения и прекращает генерацию;
- прерванный текст показывается на экране, но в диалог **не сохраняется** (сигнал `stopped`).

До первого ответа сервера (обработка промпта) остановка ждёт ответа: обычно 1–2 с.

### Блокировки в TTS

- `TTSEngine._state_lock` защищает путь к модели и ссылку на голос. Его держат только короткие операции.
- `TTSEngine._work_lock` сериализует загрузку модели и синтез. Он нужен только рабочему потоку.
- `set_model_path` вызывается из GUI-потока и берёт только `_state_lock`, поэтому не ждёт синтеза.
- Если путь не изменился, модель не сбрасывается и не перезагружается.

### Завершение приложения

`MainWindow.closeEvent` завершает фоновые задачи по порядку:
1. генерация: `stop()` и ожидание потока (до 3 с);
2. голос: `VoiceController.shutdown()` — остановка, очистка очереди, ожидание текущего синтеза;
3. загрузка модели: отмена и ожидание (до 5 с);
4. проверка Ollama: отмена ожидания запуска сервера и ожидание (до 5 с);
5. название диалога: ожидание (до 5 с).

Если поток не завершился за отведённое время, в журнал пишется ошибка.

### Отказ компонентов

| Отказ | Поведение |
|---|---|
| Ollama не установлена или не запущена | Статус в окне, чат недоступен до запуска. Приложение открыто. |
| Модель не загружена | Предложение загрузки с подтверждением размера. |
| Голосовая модель не найдена | Ошибка через сигнал `error`, VOICE выключен, чат работает. |
| Повреждённый файл чата | Пропускается при чтении, приложение продолжает работу. |
| Ошибка синтеза одной фразы | Записывается в журнал, остальные фразы озвучиваются. |

## Рабочее пространство (v0.2)

```
MainWindow
 ├─ ControlBar ── toggle(id) / hide_all / reset ──► WorkspaceManager
 └─ WorkspaceCanvas (фон, AvatarWidget, тени)
       └─ FloatingPanel × 6 (дочерние виджеты) ◄── WorkspaceManager ◄── PanelRegistry (фабрики)
                                                      │
                                       PanelLayout (default_layout, anchor_rect, clamp_rect, parse_state)
                                                      │
                                       SettingsStorage: settings.json["workspace"]
```

- **Одна панель — один экземпляр.** `WorkspaceManager.open()` при повторном вызове показывает существующую панель. Закрытие только скрывает её: содержимое (диалог, вывод консоли) сохраняется.
- **Видимость и ресурсы.** Если содержимое панели реализует `panel_shown()` / `panel_hidden()`, менеджер вызывает эти методы при открытии, закрытии и сворачивании. SYSTEM и LOGS запускают и останавливают фоновые потоки только по этим вызовам. `title_widgets()` добавляет в заголовок индикаторы и кнопки.
- **Расположение.** У каждой панели есть «желаемый» прямоугольник и размер области, в которой он задан. Фактическое место получается так: перенос с привязкой к ближайшим краям (`anchor_rect`), затем вписывание в область (`clamp_rect`). Временное уменьшение окна поэтому не портит размеры. Панель на стандартном месте следует формуле `default_layout`.
- **Сохранение.** `state()` / `restore()`: версия, компоновка, активная панель, порядок наложения, а для каждой панели — rect, canvas, visible, collapsed. `MainWindow._save_settings()` всегда берёт компоновку из менеджера в момент записи. Запись выполняется через 1,5 с после изменения и при закрытии окна.
- **Отрисовка.** Фон-город рисует `WorkspaceBackdrop` — центральный виджет окна, поэтому город виден и под панелью управления. Тени рисует рабочая область (без `QGraphicsEffect`). Панель берёт у рабочей области участок фона под собой (`paint_background`) и кладёт поверх прозрачное «стекло» (`GLASS_ALPHA_*` в `floating_panel.py`): город виден сквозь панель, другие панели — нет.
- **Аватар.** `AvatarWidget` рисует `resources/images/lisa.png` (подготовлен `tools/prepare_lisa_avatar.py`). Варианты по состояниям (окраска и линии развёртки), подсвеченная копия для сканирующего луча и слой свечения готовятся один раз на размер. В кадре они только копируются, пульсация задаётся прозрачностью. Без изображения рисуется векторный силуэт v0.1.

### Потоки v0.2

| Задача | Где выполняется | Когда работает |
|---|---|---|
| Системная информация | `SystemInfoWorker` (QThread), nvidia-smi без окна консоли, таймаут 3 с, повтор после ошибки через 30 с | пока SYSTEM открыта и развёрнута |
| Журнал | `LogTailWorker` (QThread), раз в 0,7 с, только новые байты | пока LOGS открыта и развёрнута |
| Команда консоли | отдельный процесс QProcess, ввод закрыт | до завершения или «Стоп» |
| Проверка Ollama | `StatusWorker` раз в 10 с, без диалогов | всё время |

При закрытии окна к прежнему порядку добавляется шаг: панели → `SystemPanel.shutdown()` → `LogsPanel.shutdown()` → `TerminalPanel.shutdown()`. Каждый шаг дожидается своих потоков и процессов. Сигнал `finished` потоков подключается к методам QObject, а не к lambda: так обработчик выполняется в GUI-потоке после выхода из `run()`.

### Безопасность консоли

Команды поступают только из поля ввода TERMINAL. Ни чат, ни модель не вызывают `TerminalPanel.execute()`, это проверяет тест. `command_policy.check_command` запрещает повышение прав и закодированные команды PowerShell, а для изменяющих команд требует подтверждения. При запуске SIRIUS от администратора консоль отключена. В журнал пишется только имя программы и код возврата.

## Точки расширения для будущих версий

Код v0.1 не реализует функции следующих версий, но не мешает им:

- **v0.2 (сделано):** рабочее пространство, шесть панелей.
- **Компактный режим (перенесён в v0.3):** отдельная компоновка в `panel_layout` и режим окна в `MainWindow`.
- **v0.3 (мониторинг):** `monitoring/system_info.py` уже собирает снимок; v0.3 добавит историю значений, графики, диски и температуру CPU.
- **v0.4–v0.5 (агент, инструменты):** `core/` получит реестр инструментов; текущий `AIEngine` остаётся обёрткой над Ollama.
- **v0.6 (голос «Лиса»):** новый модуль распознавания рядом с `voice/`, использует тот же `VoiceController` для ответов.

## Хранение данных

- Настройки: `storage/settings.json`, неизвестные ключи игнорируются. Ключ `workspace` (v0.2) хранит компоновку. В старом файле его нет — используется стандартная компоновка.
- Чаты: по одному файлу `storage/chats/chat_NNN.json`. Идентификатор внутри файла (`id`) независим от имени файла.
- Временные WAV: `storage/tmp/`, файлы удаляются после воспроизведения, папка в `.gitignore`.
- Запись всех JSON-файлов: во временный файл в той же папке, затем `os.replace`.


## v0.3 — Мониторинг

```
monitoring/
  system_info.py      снимок: CPU (+ядра), RAM, GPU (nvidia-smi), диски, сеть, батарея, процессы
  history.py          история значений за 5 минут (в памяти)
  alerts.py           предупреждения: пороги, гистерезис, пауза; настроение LISA (system_mood)
  session_stats.py    сводка сессии, разбор статистики Ollama (ток/с, первый токен)
  system_report.py    текст о компьютере для LISA, распознавание вопросов о системе
core/autostart.py     автозапуск через HKCU\...\Run
interface/
  monitor_service.py  постоянный сбор (QThread) → history, stats, alerts, сигналы для панелей
  charts.py           LineChart, CoreBars (QPainter)
  compact_bar.py      компактный режим (полоска поверх окон)
  window_v03.py       примесь MainWindow: трей, горячие клавиши, режим ресурсов, компактный режим, предупреждения
```

Поток данных: SystemInfoWorker → MonitorService → (MetricsHistory, SessionStats, AlertMonitor)
→ сигналы updated / alert / generation → SystemPanel, CompactBar, AvatarWidget.set_system_mood, MainWindow.
Вопрос о компьютере: MainWindow._on_send → system_context() → build_messages(extra_system=…).

## Островок (Living Island)

```
island/                     логика без Qt
  states.py                 IslandState, приоритеты временных состояний
  settings.py               ISLAND_DEFAULTS, normalize (settings.json["island"])
  notifications.py          NotificationCenter: очередь, приоритет, повторы, защита от спама
  pomodoro.py               таймер по часам системы, snapshot/restore
  clipboard.py              ClipboardHistory, looks_secret
  shelf.py                  QuickShelf: только ссылки на файлы
  actions.py                встроенные и свои действия, launch_target (os.startfile, без командной строки)
monitoring/
  win_audio.py              громкость и пиковый уровень звука (Core Audio через ctypes), только чтение
  win_system.py             яркость (\\.\LCD), Caps/Num Lock, Wi-Fi (wlanapi), Bluetooth
  winrt_bridge.py           поток asyncio: медиа GSMTC (события) и уведомления Windows (опрос раз в 3 с)
storage/island_storage.py   storage/island.json: полка, Pomodoro, история буфера
interface/
  compact_bar.py            окно островка: строка капсулы (прежняя компактная полоска) + раскрываемая часть
  island/state_manager.py   IslandStateManager: open / flash / pin / hold, сигнал changed
  island/animator.py        геометрия окна, скругление, прозрачность
  island/controller.py      IslandController: сервисы и данные → окно, уведомления, Pomodoro, буфер, полка
  island/views.py           NavBar, HubView (LISA), MediaView, SystemView, NoteToast, NoteList, IndicatorView
  island/tools_views.py     ToolsView: ShelfPage, ClipboardPage, PomodoroPage, ActionsPage
  island/widgets.py         значки, кнопки, шкалы, Gauge, Visualizer, Cover
  island/settings_tab.py    вкладка «Островок» окна настроек
```

Правило: виджеты и сервисы не меняют интерфейс островка напрямую. Они вызывают
`states.open(состояние)` (действие пользователя) или `states.flash(состояние, …)` (событие), а окно
подписано на `states.changed` и само выбирает экран, высоту и анимацию. Событие с меньшим
приоритетом не вытесняет более важное; после события возвращается прежнее состояние.

Время жизни: контроллер создаётся в `WindowV03Mixin._setup_island` и живёт всё время работы SIRIUS —
Pomodoro, история буфера и журнал уведомлений не зависят от окна. Окно создаётся при первом показе
(`_ensure_compact_bar`). Поток WinRT, опрос громкости, яркости и клавиш, уровень звука работают
только пока островок на экране (`IslandController._set_active`).

Потоки: `sirius-winrt` (asyncio, результаты приходят в поток интерфейса сигналами Qt) и короткий
`sirius-connectivity` (Wi-Fi и Bluetooth, пока открыт режим «Система»). Остальное — таймеры Qt.

Данные мониторинга островок получает от MonitorService через `MainWindow._on_monitor_update`
(`island.on_snapshot`, `compact_bar.set_metrics`); своего сбора CPU/GPU/RAM у него нет.

## Темы и смена темы на лету (заготовка)

Тема задаётся в `interface/styles.py`: палитра (`BG`, `CYAN`, …), шрифты и флаги строения окна
(`NAV_SIDE` — боковая навигация, `DOT_MATRIX` — точечные надписи, `SHOW_AVATAR`, `ISLAND_IOS`, `PANEL_RADIUS`, `BACKDROP`).
Сейчас тема применяется один раз: `main.py` вызывает `apply_theme()` до импорта окна, смена — после перезапуска.

Что уже готово для смены без перезапуска:

- `styles.set_theme(name)` — новая палитра, таблица стилей приложения, сигнал `styles.notifier().changed(name)`,
  перерисовка всех виджетов.
- `MainWindow._apply_theme_layout()` по этому сигналу переключает навигацию (боковая панель создаётся всегда и
  просто показывается или скрывается), логотип (точечный и обычный существуют оба), кнопку настроек и аватар.
- `WorkspaceBackdrop` перестраивает фон; `SideRail`, `backdrop`, `dotmatrix`, `motion` читают цвета в момент рисования.
- `MainWindow._apply_settings` вызывает `set_theme()`, если `styles.LIVE_SWITCH = True`.

Что осталось (поэтому `LIVE_SWITCH = False`):

1. Модули, которые запоминают цвета при импорте (`from interface.styles import CYAN`). Их список печатает
   `tools/theme_audit.py` — сейчас 21 модуль. В каждом нужно заменить имя на `styles.CYAN` в месте использования;
   словари и константы уровня модуля (`_STATE_COLORS`, `THEMES` островка, `RADIUS` панелей) превратить в функции.
2. Виджеты, которые выбирают строение при создании: в островке — `DotLabel` или `QLabel` для времени, градусов и таймера
   (`weather_view.MiniView`, `_big_temp`, `tools_views.PomodoroPage`), таблица стилей `CompactBar._style()`,
   радиус раскрытой капсулы. Им нужен метод `apply_theme()` и подписка на `notifier().changed`, как у `ControlBar`.
3. Подсветка кода (`panels/code_panel.py`) и цвета строк журнала и консоли: уже выведенный текст окрашен старыми цветами.

Порядок работы: править модули по списку аудита, после каждого — `pytest tests/test_theme.py`; когда аудит пуст и пункт 2
закрыт, включить `LIVE_SWITCH` и убрать из настроек подсказку о перезапуске.

