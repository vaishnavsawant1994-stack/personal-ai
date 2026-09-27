from __future__ import annotations

import html

from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, QThread, QTimer, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from agent.executor import ConfirmationRequired
from ui.control_panel import ControlPanel
from ui.memory_panel import MemoryPanel
from ui.pulse import PulseWidget
from ui.settings_panel import SettingsPanel


class Worker(QThread):
    done = pyqtSignal(str)
    failed = pyqtSignal(object)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        try:
            self.done.emit(self.fn())
        except Exception as exc:
            self.failed.emit(exc)


class MainWindow(QMainWindow):
    """Personal AI Home V1.

    The application keeps one persistent intelligence at the centre of the UI.
    Dashboard and Main Menu are shortcuts; the rest of the product expands away
    from Home without turning Home into a card dashboard.
    """

    NAV = (
        "Home",
        "Conversation",
        "Memory",
        "Knowledge",
        "Activities",
        "Dashboard",
        "Apps & Tools",
        "Settings",
    )
    STATE_COPY = {
        "idle": ("Idle", "I am here."),
        "active": ("Ready", "I am ready."),
        "listening": ("Listening", "I am listening to you."),
        "understanding": ("Understanding", "I am interpreting what you mean."),
        "thinking": ("Thinking", "I am reasoning."),
        "memory": ("Remembering", "I am recalling relevant memory."),
        "knowledge": ("Retrieving", "I am retrieving knowledge."),
        "acting": ("Acting", "I am doing something for you."),
        "speaking": ("Responding", "I am communicating the result."),
        "approval": ("Needs approval", "I need your decision before continuing."),
        "error": ("Interrupted", "Something prevented me from completing this."),
        "background": ("Background", "I am available without demanding attention."),
    }

    def __init__(self, *, events, executor, memory, runtime=None):
        super().__init__()
        self.events = events
        self.executor = executor
        self.memory = memory
        self.runtime = runtime or {}
        self.worker = None
        self.pending_text = None
        self.voice_running = False
        self.current_page = "Home"

        self.setWindowTitle("Personal AI")
        self.resize(1380, 860)
        self.setMinimumSize(1040, 700)

        prefs = self.runtime.get("preferences")
        high = bool(prefs.get("high_contrast")) if prefs else False
        muted = "#9badb7" if high else "#71818b"
        border = "#2b4350" if high else "#17242c"

        self.setStyleSheet(
            f"""
            QMainWindow, QWidget {{
                background: #030405;
                color: #edf3f6;
                font-family: Inter, "Segoe UI", Arial;
            }}
            QLabel#brand {{
                color: #d4e0e5;
                font-size: 14px;
                font-weight: 700;
                letter-spacing: 3px;
            }}
            QLabel#muted {{
                color: {muted};
            }}
            QLabel#heroState {{
                color: #eef7fa;
                font-size: 20px;
                font-weight: 620;
            }}
            QLabel#heroHint {{
                color: #64757f;
                font-size: 12px;
            }}
            QLabel#attention {{
                color: #d8cfab;
                font-size: 12px;
            }}
            QLineEdit {{
                background: transparent;
                border: 0;
                padding: 11px 5px;
                color: #eef5f8;
                font-size: 15px;
                selection-background-color: #244656;
            }}
            QPushButton {{
                background: transparent;
                border: 1px solid transparent;
                border-radius: 12px;
                padding: 9px 13px;
                color: #92a3ac;
            }}
            QPushButton:hover {{
                background: #0a0f13;
                color: #edf6fa;
                border-color: #17252d;
            }}
            QPushButton:checked {{
                background: #0b1217;
                color: #eef7fa;
                border-color: #223640;
            }}
            QPushButton#navAction {{
                border: 1px solid #15242c;
                background: #070b0e;
                color: #a9b8bf;
                padding: 8px 14px;
            }}
            QPushButton#navAction:hover {{
                border-color: #29434f;
                color: #eff8fb;
            }}
            QPushButton#send {{
                background: #dcebef;
                color: #071015;
                border: 0;
                border-radius: 17px;
                font-weight: 700;
                min-width: 34px;
                max-width: 34px;
                min-height: 34px;
                max-height: 34px;
                padding: 0;
            }}
            QPushButton#mic {{
                color: #90a4ae;
                min-width: 36px;
                max-width: 36px;
                min-height: 34px;
                max-height: 34px;
                padding: 0;
            }}
            QPushButton#indicator {{
                background: #05080a;
                border: 1px solid #111c22;
                border-radius: 14px;
                padding: 8px 14px;
                color: #788a94;
                font-size: 12px;
            }}
            QPushButton#indicator:hover {{
                color: #d5e2e7;
                border-color: #223640;
            }}
            QTextBrowser#homeConversation {{
                background: rgba(6, 9, 11, 0.72);
                border: 1px solid #101b21;
                border-radius: 16px;
                padding: 10px 14px;
                color: #cbd7dc;
            }}
            QTextBrowser {{
                background: #05080a;
                border: 1px solid #131f27;
                border-radius: 16px;
                padding: 14px;
            }}
            QFrame#composer {{
                background: #070a0d;
                border: 1px solid #17252d;
                border-radius: 22px;
            }}
            QFrame#card {{
                background: #06090b;
                border: 1px solid {border};
                border-radius: 16px;
            }}
            QFrame#menuDrawer {{
                background: #05080a;
                border-left: 1px solid #111b21;
                border-radius: 18px;
            }}
            QLabel#menuCaption {{
                color: #5f7079;
                font-size: 10px;
                font-weight: 700;
                letter-spacing: 2px;
            }}
            """
        )

        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(26, 18, 26, 20)
        outer.setSpacing(12)
        outer.addLayout(self._build_top_nav())

        shell = QHBoxLayout()
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(12)

        self.stack = QStackedWidget()
        self.pages = {}
        for name in self.NAV:
            page = self._build_page(name)
            self.pages[name] = page
            self.stack.addWidget(page)
        shell.addWidget(self.stack, 1)

        self.menu_drawer = self._build_main_menu()
        self.menu_drawer.setMinimumWidth(0)
        self.menu_drawer.setMaximumWidth(0)
        shell.addWidget(self.menu_drawer)

        outer.addLayout(shell, 1)

        self.menu_anim = QPropertyAnimation(self.menu_drawer, b"maximumWidth", self)
        self.menu_anim.setDuration(260)
        self.menu_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._show_page("Home", close_menu=False)

        events.subscribe("state", self.on_state)
        events.subscribe("voice.transcript", self._on_voice_transcript)
        events.subscribe("voice.reply", self._on_voice_reply)
        events.subscribe(
            "voice.wake",
            lambda event: self._append_chat(
                "System",
                f"Wake phrase detected: {event.get('phrase', 'Hey Personal')}",
            ),
        )

    def _build_top_nav(self):
        nav = QHBoxLayout()
        brand = QLabel("PERSONAL AI")
        brand.setObjectName("brand")
        nav.addWidget(brand)
        nav.addStretch(1)

        self.dashboard_btn = QPushButton("Dashboard")
        self.dashboard_btn.setObjectName("navAction")
        self.dashboard_btn.setCheckable(True)
        self.dashboard_btn.clicked.connect(lambda _checked=False: self._show_page("Dashboard"))
        nav.addWidget(self.dashboard_btn)

        self.menu_btn = QPushButton("Main Menu  ☰")
        self.menu_btn.setObjectName("navAction")
        self.menu_btn.setCheckable(True)
        self.menu_btn.clicked.connect(self._toggle_main_menu)
        nav.addSpacing(6)
        nav.addWidget(self.menu_btn)
        return nav

    def _build_main_menu(self):
        drawer = QFrame()
        drawer.setObjectName("menuDrawer")
        layout = QVBoxLayout(drawer)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(5)

        caption = QLabel("PERSONAL AI")
        caption.setObjectName("menuCaption")
        layout.addWidget(caption)
        layout.addSpacing(8)

        self.menu_buttons = {}
        for name in self.NAV:
            button = QPushButton(name)
            button.setCheckable(True)
            button.setMinimumWidth(220)
            button.clicked.connect(lambda checked=False, target=name: self._show_page(target))
            self.menu_buttons[name] = button
            layout.addWidget(button)

        layout.addStretch(1)
        footer = QLabel("One intelligence · one continuous environment")
        footer.setObjectName("muted")
        footer.setWordWrap(True)
        layout.addWidget(footer)
        return drawer

    def _toggle_main_menu(self, checked):
        self.menu_anim.stop()
        self.menu_anim.setStartValue(self.menu_drawer.maximumWidth())
        self.menu_anim.setEndValue(280 if checked else 0)
        self.menu_anim.start()

    def _close_main_menu(self):
        if not self.menu_btn.isChecked() and self.menu_drawer.maximumWidth() == 0:
            return
        self.menu_btn.setChecked(False)
        self._toggle_main_menu(False)

    def _build_page(self, name):
        if name == "Home":
            return self._home_page()
        if name == "Conversation":
            return self._conversation_page()

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 18, 12, 12)
        title = QLabel(name)
        title.setStyleSheet("font-size:28px;font-weight:650")
        layout.addWidget(title)
        subtitle = QLabel(self._subtitle(name))
        subtitle.setObjectName("muted")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)
        layout.addSpacing(8)

        if name == "Memory":
            self._memory_content(layout)
        elif name == "Knowledge":
            self._knowledge_content(layout)
        elif name == "Activities":
            self._activities_content(layout)
        elif name == "Dashboard":
            self._dashboard_content(layout)
        elif name == "Apps & Tools":
            self._apps_tools_content(layout)
        elif name == "Settings":
            self._settings_content(layout)

        layout.addStretch(1)
        return page

    def _home_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(6, 2, 6, 0)
        layout.setSpacing(6)

        self.needs_label = QLabel("")
        self.needs_label.setObjectName("attention")
        self.needs_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.needs_label.setVisible(False)
        layout.addWidget(self.needs_label)

        self.pulse = PulseWidget()
        self.pulse.setMinimumHeight(350)
        prefs = self.runtime.get("preferences")
        if prefs and hasattr(self.pulse, "set_reduce_motion"):
            self.pulse.set_reduce_motion(bool(prefs.get("reduce_motion")))
        layout.addWidget(self.pulse, 1)

        self.state = QLabel("Idle")
        self.state.setObjectName("heroState")
        self.state.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.state)

        self.state_hint = QLabel("I am here.")
        self.state_hint.setObjectName("heroHint")
        self.state_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.state_hint)

        self.chat = QTextBrowser()
        self.chat.setObjectName("homeConversation")
        self.chat.setMaximumHeight(116)
        self.chat.setVisible(False)
        layout.addWidget(self.chat)

        composer = QFrame()
        composer.setObjectName("composer")
        composer_row = QHBoxLayout(composer)
        composer_row.setContentsMargins(8, 3, 8, 3)
        composer_row.setSpacing(4)

        self.mic_btn = QPushButton("●")
        self.mic_btn.setObjectName("mic")
        self.mic_btn.setAccessibleName("Start voice")
        self.mic_btn.clicked.connect(self.toggle_voice)
        composer_row.addWidget(self.mic_btn)

        self.input = QLineEdit()
        self.input.setAccessibleName("Ask Personal AI")
        self.input.setPlaceholderText("Speak or type…")
        self.input.returnPressed.connect(lambda: self.submit(self.input))
        composer_row.addWidget(self.input, 1)

        send_btn = QPushButton("↑")
        send_btn.setObjectName("send")
        send_btn.setAccessibleName("Send")
        send_btn.clicked.connect(lambda _checked=False: self.submit(self.input))
        composer_row.addWidget(send_btn)
        layout.addWidget(composer)

        indicators = QHBoxLayout()
        indicators.addStretch(1)

        self.memory_indicator = QPushButton("")
        self.memory_indicator.setObjectName("indicator")
        self.memory_indicator.clicked.connect(lambda _checked=False: self._show_page("Memory"))
        indicators.addWidget(self.memory_indicator)

        self.context_indicator = QPushButton("")
        self.context_indicator.setObjectName("indicator")
        self.context_indicator.clicked.connect(lambda _checked=False: self._show_page("Conversation"))
        indicators.addWidget(self.context_indicator)

        self.activity_indicator = QPushButton("")
        self.activity_indicator.setObjectName("indicator")
        self.activity_indicator.clicked.connect(lambda _checked=False: self._show_page("Activities"))
        indicators.addWidget(self.activity_indicator)

        indicators.addStretch(1)
        layout.addLayout(indicators)

        self._refresh_home_indicators()
        return page

    def _conversation_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 18, 12, 12)

        title = QLabel("Conversation")
        title.setStyleSheet("font-size:28px;font-weight:650")
        layout.addWidget(title)

        subtitle = QLabel(
            "The expanded thread. Home remains the primary environment; this view is for history, sources and detailed work."
        )
        subtitle.setObjectName("muted")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        self.conversation_chat = QTextBrowser()
        layout.addWidget(self.conversation_chat, 1)

        composer = QFrame()
        composer.setObjectName("composer")
        row = QHBoxLayout(composer)
        row.setContentsMargins(8, 3, 8, 3)

        self.conversation_mic_btn = QPushButton("●")
        self.conversation_mic_btn.setObjectName("mic")
        self.conversation_mic_btn.clicked.connect(self.toggle_voice)
        row.addWidget(self.conversation_mic_btn)

        self.conversation_input = QLineEdit()
        self.conversation_input.setPlaceholderText("Continue the conversation…")
        self.conversation_input.returnPressed.connect(
            lambda: self.submit(self.conversation_input)
        )
        row.addWidget(self.conversation_input, 1)

        send_btn = QPushButton("↑")
        send_btn.setObjectName("send")
        send_btn.clicked.connect(lambda _checked=False: self.submit(self.conversation_input))
        row.addWidget(send_btn)
        layout.addWidget(composer)
        return page

    def _card(self, title, value, detail=""):
        frame = QFrame()
        frame.setObjectName("card")
        layout = QVBoxLayout(frame)
        label = QLabel(title)
        label.setObjectName("muted")
        value_label = QLabel(str(value))
        value_label.setStyleSheet("font-size:25px;font-weight:650")
        layout.addWidget(label)
        layout.addWidget(value_label)
        if detail:
            detail_label = QLabel(detail)
            detail_label.setObjectName("muted")
            detail_label.setWordWrap(True)
            layout.addWidget(detail_label)
        return frame

    def _memory_content(self, layout):
        graph = self._graph()
        grid = QGridLayout()
        grid.addWidget(
            self._card("Memory", len(graph.get("nodes", [])), "Second Brain objects"),
            0,
            0,
        )
        grid.addWidget(
            self._card(
                "Relationships",
                len(graph.get("edges", [])),
                "Graph connections between memories",
            ),
            0,
            1,
        )
        layout.addLayout(grid)

        button = QPushButton("Open Memory — Ambient / Graph / Tree / Detail")
        button.setObjectName("navAction")
        button.clicked.connect(self.open_memory)
        layout.addWidget(button)

    def _knowledge_content(self, layout):
        graph = self._graph()
        integrations = self.runtime.get("integrations")
        linked = integrations.list() if integrations and hasattr(integrations, "list") else []
        grid = QGridLayout()
        grid.addWidget(
            self._card(
                "Connected sources",
                len(linked),
                "External knowledge sources available to Personal AI",
            ),
            0,
            0,
        )
        grid.addWidget(
            self._card(
                "Memory links",
                len(graph.get("edges", [])),
                "Knowledge stays distinct from personal memory",
            ),
            0,
            1,
        )
        layout.addLayout(grid)

    def _activities_content(self, layout):
        automations = self.runtime.get("automations")
        rows = automations.list() if automations and hasattr(automations, "list") else []
        running = sum(1 for item in rows if item.get("enabled"))
        handled = sum(1 for item in rows if item.get("last_run_at"))
        grid = QGridLayout()
        grid.addWidget(self._card("Running", running, "Active automated work"), 0, 0)
        grid.addWidget(self._card("Completed", handled, "Work handled for you"), 0, 1)
        layout.addLayout(grid)

    def _dashboard_content(self, layout):
        graph = self._graph()
        telemetry = self.runtime.get("telemetry")
        snapshot = telemetry.snapshot() if telemetry else {"metrics": {}, "counters": {}}
        grid = QGridLayout()
        grid.addWidget(
            self._card("Second Brain", len(graph.get("nodes", [])), "memory nodes"),
            0,
            0,
        )
        grid.addWidget(
            self._card("Devices", self._device_count(), "registered identities"),
            0,
            1,
        )
        grid.addWidget(
            self._card(
                "Voice",
                "Ready" if self.runtime.get("voice") else "Unavailable",
                "Realtime + fallback runtime",
            ),
            1,
            0,
        )
        grid.addWidget(
            self._card(
                "Security",
                "Enforced",
                "permissions · approvals · vault · audit · device trust",
            ),
            1,
            1,
        )
        grid.addWidget(
            self._card(
                "Local telemetry",
                len(snapshot.get("metrics", {})),
                "timed operations; never uploaded",
            ),
            2,
            0,
        )
        grid.addWidget(
            self._card(
                "Recovery",
                "Ready" if self.runtime.get("backups") else "Unavailable",
                "integrity-checked backup/restore",
            ),
            2,
            1,
        )
        layout.addLayout(grid)

        button = QPushButton("Open Detailed Control Dashboard")
        button.setObjectName("navAction")
        button.clicked.connect(self.open_control)
        layout.addWidget(button)

    def _apps_tools_content(self, layout):
        automations = self.runtime.get("automations")
        auto_rows = automations.list() if automations and hasattr(automations, "list") else []
        integrations = self.runtime.get("integrations")
        linked = integrations.list() if integrations and hasattr(integrations, "list") else []
        plugins = self.runtime.get("plugins")
        plugin_rows = plugins.list() if plugins and hasattr(plugins, "list") else []
        grid = QGridLayout()
        grid.addWidget(
            self._card(
                "Active automations",
                sum(1 for item in auto_rows if item.get("enabled")),
                "Scheduled and conditional work",
            ),
            0,
            0,
        )
        grid.addWidget(
            self._card(
                "Linked integrations",
                len(linked),
                "Permission-scoped accounts and services",
            ),
            0,
            1,
        )
        grid.addWidget(
            self._card(
                "Trusted devices",
                self._device_count(),
                "Desktop and companion-device control plane",
            ),
            1,
            0,
        )
        grid.addWidget(
            self._card(
                "Extensions",
                len(plugin_rows),
                "Declarative manifests; no arbitrary Python execution",
            ),
            1,
            1,
        )
        layout.addLayout(grid)

    def _settings_content(self, layout):
        text = QLabel(
            "Personal AI · Identity · Voice · Appearance · Memory · Privacy · Permissions · Connected Apps · Notifications · Automation · Data · Security · Devices · Models · Advanced"
        )
        text.setObjectName("muted")
        text.setWordWrap(True)
        layout.addWidget(text)

        button = QPushButton("Open Settings")
        button.setObjectName("navAction")
        button.clicked.connect(self.open_settings)
        layout.addWidget(button)

    def _subtitle(self, name):
        return {
            "Memory": "Your personal context, relationships and recall surfaces.",
            "Knowledge": "Documents, research, files and connected information Personal AI can retrieve.",
            "Activities": "What Personal AI has done, is doing, or needs from you.",
            "Dashboard": "Overview and system evidence without turning Home into a dashboard.",
            "Apps & Tools": "Capabilities behind Personal AI for visibility, configuration and manual control.",
            "Settings": "Control Personal AI, identity, privacy, permissions, devices and models.",
        }[name]

    def _show_page(self, name, close_menu=True):
        if name not in self.pages:
            return
        self.current_page = name
        self.stack.setCurrentWidget(self.pages[name])
        self.dashboard_btn.setChecked(name == "Dashboard")
        for target, button in self.menu_buttons.items():
            button.setChecked(target == name)
        if close_menu:
            self._close_main_menu()
        if name == "Home":
            self._refresh_home_indicators()

    def _graph(self):
        try:
            return self.memory.graph()
        except Exception:
            second_brain = self.runtime.get("second_brain")
            if second_brain and hasattr(second_brain, "graph"):
                try:
                    return second_brain.graph()
                except Exception:
                    pass
        return {"nodes": [], "edges": []}

    def _memory_count(self):
        return len(self._graph().get("nodes", []))

    def _device_count(self):
        registry = self.runtime.get("device_registry")
        return len(registry.list()) if registry and hasattr(registry, "list") else 0

    def _context_count(self):
        count = self._device_count()
        integrations = self.runtime.get("integrations")
        if integrations and hasattr(integrations, "list"):
            try:
                count += len(integrations.list())
            except Exception:
                pass
        if self.pending_text:
            count += 1
        return count

    def _activity_count(self):
        automations = self.runtime.get("automations")
        if not automations or not hasattr(automations, "list"):
            return 0
        try:
            return sum(1 for item in automations.list() if item.get("last_run_at"))
        except Exception:
            return 0

    def _refresh_home_indicators(self):
        if hasattr(self, "memory_indicator"):
            self.memory_indicator.setText(f"Memory · {self._memory_count():02d}")
        if hasattr(self, "context_indicator"):
            self.context_indicator.setText(f"Context · {self._context_count():02d}")
        if hasattr(self, "activity_indicator"):
            self.activity_indicator.setText(f"Activity · {self._activity_count():02d}")

    def open_memory(self):
        MemoryPanel(self.memory, self).exec()

    def open_control(self):
        if self.runtime:
            ControlPanel(self.runtime, self).exec()

    def open_settings(self):
        if self.runtime:
            SettingsPanel(self.runtime, self).exec()

    def _update_voice_buttons(self):
        label = "■" if self.voice_running else "●"
        accessible = "Stop voice" if self.voice_running else "Start voice"
        for attr in ("mic_btn", "conversation_mic_btn"):
            button = getattr(self, attr, None)
            if button:
                button.setText(label)
                button.setAccessibleName(accessible)
                button.setChecked(self.voice_running)

    def toggle_voice(self):
        voice = self.runtime.get("voice")
        if not voice:
            return
        if self.voice_running:
            voice.stop()
            self.voice_running = False
            self._set_state("idle")
        else:
            voice.start()
            self.voice_running = True
            self._set_state("active")
        self._update_voice_buttons()

    def _set_state(self, state):
        normalized = PulseWidget.normalize_state(state)
        label, hint = self.STATE_COPY.get(normalized, self.STATE_COPY["idle"])
        self.state.setText(label)
        self.state_hint.setText(hint)
        self.pulse.set_state(normalized)
        if normalized == "approval":
            self.needs_label.setText("Your approval is required")
            self.needs_label.setVisible(True)
        elif normalized != "error":
            self.needs_label.setVisible(False)
        self._refresh_home_indicators()

    def on_state(self, event):
        self._set_state(event.get("state", "idle"))

    def _on_voice_transcript(self, event):
        text = event.get("text", "")
        if text:
            self._set_state("listening")
            self._append_chat("You", text)

    def _on_voice_reply(self, event):
        text = event.get("text", "")
        if text:
            self._append_chat("AI", text)
            self._set_state("speaking")
            QTimer.singleShot(1000, lambda: self._set_state("idle"))

    def _append_chat(self, who, text):
        if not text:
            return
        safe_who = html.escape(str(who))
        safe_text = html.escape(str(text)).replace("\n", "<br>")
        block = (
            f'<div style="margin:4px 0 8px 0;">'
            f'<span style="color:#71838d;font-size:11px;">{safe_who}</span><br>'
            f'<span style="color:#d8e2e6;">{safe_text}</span></div>'
        )
        if hasattr(self, "chat"):
            self.chat.append(block)
            self.chat.setVisible(True)
        if hasattr(self, "conversation_chat"):
            self.conversation_chat.append(block)

    def submit(self, source=None):
        field = source if isinstance(source, QLineEdit) else self.input
        text = field.text().strip()
        if not text:
            return
        field.clear()
        self.pending_text = text
        self._append_chat("You", text)
        self._set_state("listening")
        QTimer.singleShot(
            180,
            lambda: self._set_state("thinking")
            if self.worker and self.worker.isRunning()
            else None,
        )
        self._run(lambda: self.executor.chat(text))

    def _run(self, fn):
        self.worker = Worker(fn)
        self.worker.done.connect(self.answer)
        self.worker.failed.connect(self.error)
        self.worker.start()

    def answer(self, text):
        self._append_chat("AI", text)
        self.pending_text = None
        self._set_state("speaking")
        QTimer.singleShot(1100, lambda: self._set_state("idle"))

    def error(self, exc):
        if isinstance(exc, ConfirmationRequired):
            self._set_state("approval")
            choice = QMessageBox.question(
                self,
                "Approve once",
                (
                    "Personal AI wants to run:\n\n"
                    f"{exc.tool_name}\n{exc.description}\n{exc.parameters}\n\n"
                    "This approval is one-use and bound to these exact parameters. Allow it?"
                ),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if choice == QMessageBox.StandardButton.Yes:
                approval_id = exc.approval_id
                self.pending_text = None
                self._set_state("acting")
                self._run(lambda: self.executor.approve(approval_id))
                return
            self.executor.reject(exc.approval_id)
            self._append_chat("AI", "Action cancelled.")
            self.pending_text = None
            self._set_state("idle")
            return

        self._append_chat("Error", str(exc))
        self.pending_text = None
        self.needs_label.setText("Something interrupted the request")
        self.needs_label.setVisible(True)
        self._set_state("error")
        QTimer.singleShot(
            1800,
            lambda: (
                self.needs_label.setVisible(False),
                self._set_state("idle"),
            ),
        )
