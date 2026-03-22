"""
Firmware Upload Dialog — step-by-step wizard matching dexter_arm_base.sh
Steps:
  0 - Select firmware file
  1 - Select flash method  (Serial / OTA)
  2 - Select board type    (ESP32 / Arduino Mega 2560)
    3 - Connection config    (serial port OR OTA ip)
  4 - Confirmation summary
  5 - Flash / live output
"""

from pathlib import Path
import shutil
import json
import socket

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QLineEdit, QRadioButton,
    QButtonGroup, QTextEdit, QWidget, QStackedWidget, QFrame,
    QCheckBox, QSizePolicy
)
from PyQt6.QtCore import Qt, QProcess, QObject, QEvent, QSize, QTimer
from PyQt6.QtGui import QColor, QTextCharFormat

# ── HUD palette ───────────────────────────────────────────────────────────────
_BG       = "#000a1a"
_BG2      = "#001020"
_BG3      = "#001830"
_CYAN     = "#00F3FF"
_CYAN_DIM = "#007a80"
_CYAN_BG  = "#00263a"
_WHITE    = "#e0f8ff"
_GREY     = "#3a5060"
_RED      = "#ff4444"
_GREEN    = "#00ff88"
_YELLOW   = "#f5c211"

_FLASH_TIMEOUT_MS = 15000

_PREFS_PATH = Path.home() / ".dexter_arm_dashboard" / "config" / "firmware_prefs.json"

_BASE_STYLE = f"""
    QDialog#firmware_dialog {{
        background: #0d1626;
        color: {_WHITE};
        font-family: 'Courier New', monospace;
        font-size: 15px;
    }}
    QFrame#fw_main_panel {{
        background: #16263d;
        border: 1px solid #2f4b72;
        border-radius: 14px;
    }}
    QWidget {{
        background: {_BG};
        color: {_WHITE};
        font-family: 'Courier New', monospace;
        font-size: 15px;
    }}
    QLabel {{ color: {_WHITE}; font-size: 15px; }}
    QLabel#title  {{ color: {_CYAN}; font-size: 21px; font-weight: bold; letter-spacing: 2px; }}
    QLabel#step   {{ color: {_CYAN_DIM}; font-size: 13px; letter-spacing: 1px; }}
    QLabel#hint   {{ color: {_GREY}; font-size: 13px; }}
    QLabel#ok     {{ color: {_GREEN}; font-size: 14px; }}
    QLabel#warn   {{ color: {_YELLOW}; font-size: 14px; }}
    QLabel#err    {{ color: {_RED}; font-size: 14px; }}
    QLabel#badge_ino  {{ color: {_CYAN}; font-size: 12px; font-weight: bold;
                         background: #002233; border: 1px solid {_CYAN_DIM};
                         border-radius: 3px; padding: 1px 6px; }}
    QLabel#badge_bin  {{ color: {_YELLOW}; font-size: 12px; font-weight: bold;
                         background: #1a1200; border: 1px solid {_YELLOW};
                         border-radius: 3px; padding: 1px 6px; }}
    QLabel#filename_active   {{ color: {_CYAN}; font-size: 15px; font-weight: bold; }}
    QLabel#filename_inactive {{ color: {_WHITE}; font-size: 15px; }}
    QLabel#filesize  {{ color: {_GREY}; font-size: 12px; }}
    QFrame#file_item_active {{
        background: {_CYAN_BG};
        border: 1px solid {_CYAN};
        border-radius: 5px;
    }}
    QFrame#file_item_inactive {{
        background: {_BG2};
        border: 1px solid {_GREY};
        border-radius: 5px;
    }}
    QListWidget {{
        background: {_BG};
        border: none;
        padding: 4px;
    }}
    QListWidget::item {{ background: transparent; border: none; padding: 2px 0px; }}
    QListWidget::item:selected {{ background: transparent; }}
    QRadioButton {{ color: {_WHITE}; font-size: 15px; spacing: 10px; }}
    QRadioButton::indicator {{
        width: 18px; height: 18px;
        border: 2px solid {_CYAN}; border-radius: 9px;
        background: {_BG2};
    }}
    QRadioButton::indicator:checked {{ background: {_CYAN}; border-color: {_CYAN}; }}
    QRadioButton:disabled {{ color: {_GREY}; }}
    QCheckBox {{ color: {_CYAN_DIM}; font-size: 13px; spacing: 8px; }}
    QCheckBox::indicator {{
        width: 15px; height: 15px;
        border: 1px solid {_CYAN_DIM}; border-radius: 3px;
        background: {_BG2};
    }}
    QCheckBox::indicator:checked {{ background: {_CYAN_DIM}; }}
    QCheckBox:hover {{ color: {_CYAN}; }}
    QCheckBox::indicator:hover {{ border-color: {_CYAN}; }}
    QLineEdit {{
        background: {_BG2}; color: {_CYAN};
        border: 1px solid {_CYAN_DIM};
        border-radius: 4px; padding: 8px 12px;
        font-size: 15px;
        selection-background-color: #003344;
    }}
    QLineEdit:focus {{ border: 1px solid {_CYAN}; }}
    QTextEdit {{
        background: #000812; color: {_GREEN};
        border: 1px solid {_CYAN_DIM}; border-radius: 4px;
        font-family: 'Courier New', monospace; font-size: 13px;
        padding: 8px;
    }}
    QFrame#divider {{ background: {_CYAN_DIM}; }}
    QPushButton {{
        background: {_BG2}; color: {_CYAN};
        border: 1px solid {_CYAN}; border-radius: 4px;
        padding: 8px 28px; font-size: 15px; letter-spacing: 1px;
    }}
    QPushButton:hover   {{ background: #003355; }}
    QPushButton:pressed {{ background: #004466; }}
    QPushButton:disabled {{ color: {_GREY}; border-color: {_GREY}; }}
    QPushButton#cancel {{ color: {_GREY}; border-color: {_GREY}; }}
    QPushButton#cancel:hover {{ color: {_RED}; border-color: {_RED}; }}
    QPushButton#flash {{
        color: {_GREEN}; border-color: {_GREEN};
        font-weight: bold; font-size: 16px;
    }}
    QPushButton#flash:hover {{ background: #002211; }}
    QPushButton#check_btn {{
        padding: 6px 14px; font-size: 13px;
        color: {_CYAN_DIM}; border-color: {_CYAN_DIM};
    }}
    QPushButton#check_btn:hover {{ color: {_CYAN}; border-color: {_CYAN}; }}
"""


def _divider():
    f = QFrame()
    f.setObjectName("divider")
    f.setFrameShape(QFrame.Shape.HLine)
    f.setFixedHeight(1)
    return f


def _fmt_size(path: Path) -> str:
    try:
        b = path.stat().st_size
        return f"{b/1024:.1f} KB" if b >= 1024 else f"{b} B"
    except Exception:
        return ""


class _ListEnterFilter(QObject):
    """Forward Enter/Return key on the file list to _go_next."""
    def __init__(self, callback):
        super().__init__()
        self._cb = callback

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._cb()
                return True
        return False


class FirmwareDialog(QDialog):
    """Multi-step firmware flash wizard."""

    PAGE_SELECT  = 0
    PAGE_METHOD  = 1
    PAGE_BOARD   = 2
    PAGE_CONN    = 3
    PAGE_CONFIRM = 4
    PAGE_FLASH   = 5

    _STEP_LABELS = [
        "STEP 1 / 5   ──   SELECT FIRMWARE FILE",
        "STEP 2 / 5   ──   FLASH METHOD",
        "STEP 3 / 5   ──   BOARD TYPE",
        "STEP 4 / 5   ──   CONNECTION SETTINGS",
        "STEP 5 / 5   ──   CONFIRM & FLASH",
        "FLASHING IN PROGRESS",
    ]

    def __init__(self, workspace_dir: str, esp32_port: str, parent=None):
        super().__init__(parent)
        self.workspace_dir = Path(workspace_dir)
        self.default_port  = esp32_port

        self.firmware_files: list = []
        self.selected_file        = None
        self.flash_method         = "serial"
        self.board_fqbn           = "esp32:esp32:esp32"
        self.board_name           = "ESP32"
        self.serial_port          = esp32_port
        self.ota_ip               = ""
        self.ota_password         = "dexter123"

        self._process             = None
        self._flash_done          = False
        self._item_frames: dict   = {}
        self._timeout_timer       = QTimer(self)
        self._timeout_timer.setSingleShot(True)
        self._timeout_timer.timeout.connect(self._on_timeout)

        self.setWindowTitle("Firmware Upload")
        self.setObjectName("firmware_dialog")
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setWindowFlag(Qt.WindowType.WindowMinMaxButtonsHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setModal(False)
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setMinimumSize(920, 700)
        self.resize(980, 760)
        self.setSizeGripEnabled(True)
        self.setStyleSheet(_BASE_STYLE)

        self._load_prefs()
        self._build_ui()
        self._scan_firmware()

    # ── preferences ──────────────────────────────────────────────────────────

    def _load_prefs(self):
        self._prefs: dict = {}
        if _PREFS_PATH.exists():
            try:
                self._prefs = json.loads(_PREFS_PATH.read_text())
            except Exception:
                pass

    def _save_prefs(self):
        try:
            _PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)
            _PREFS_PATH.write_text(json.dumps(self._prefs, indent=2))
        except Exception as e:
            print(f"[WARN] Could not save firmware prefs: {e}")

    def _remember(self, key: str, value: str):
        self._prefs[key] = value
        self._save_prefs()

    def _forget(self, key: str):
        self._prefs.pop(key, None)
        self._save_prefs()

    def _pref(self, key: str, default: str = "") -> str:
        return self._prefs.get(key, default)

    # ── UI build ──────────────────────────────────────────────────────────────

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(0)

        panel = QFrame(self)
        panel.setObjectName("fw_main_panel")
        panel.setMinimumSize(860, 660)
        outer.addWidget(panel, 1)

        root = QVBoxLayout(panel)
        root.setContentsMargins(24, 18, 24, 18)
        root.setSpacing(0)

        hdr = QLabel("\u26a1  FIRMWARE UPLOAD")
        hdr.setObjectName("title")
        root.addWidget(hdr)

        self._step_label = QLabel("")
        self._step_label.setObjectName("step")
        root.addWidget(self._step_label)
        root.addSpacing(6)
        root.addWidget(_divider())
        root.addSpacing(14)

        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)

        self.stack.addWidget(self._page_select())
        self.stack.addWidget(self._page_method())
        self.stack.addWidget(self._page_board())
        self.stack.addWidget(self._page_conn())
        self.stack.addWidget(self._page_confirm())
        self.stack.addWidget(self._page_flash())

        root.addSpacing(12)
        root.addWidget(_divider())
        root.addSpacing(10)

        nav = QHBoxLayout()
        nav.setSpacing(10)
        self._btn_cancel = QPushButton("Cancel")
        self._btn_cancel.setObjectName("cancel")
        self._btn_back   = QPushButton("\u25c4  Back")
        self._btn_next   = QPushButton("Next  \u25ba")
        self._btn_flash  = QPushButton("\u26a1  FLASH NOW")
        self._btn_flash.setObjectName("flash")
        self._btn_done   = QPushButton("Close")

        self._btn_cancel.clicked.connect(self.reject)
        self._btn_back.clicked.connect(self._go_back)
        self._btn_next.clicked.connect(self._go_next)
        self._btn_done.clicked.connect(self.accept)
        self._btn_flash.clicked.connect(self._do_flash)

        nav.addWidget(self._btn_cancel)
        nav.addStretch()
        nav.addWidget(self._btn_back)
        nav.addWidget(self._btn_next)
        nav.addWidget(self._btn_flash)
        nav.addWidget(self._btn_done)
        root.addLayout(nav)

        self._go_to(self.PAGE_SELECT)

    # ── pages ─────────────────────────────────────────────────────────────────

    def _page_select(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(10)

        banner = QLabel(
            "  Select the firmware file you want to upload.\n"
            "  Use \u2191 \u2193 arrow keys or click to highlight, "
            "then press Enter or click  Next  \u25ba"
        )
        banner.setStyleSheet(
            f"background: #001830; border: 1px solid {_CYAN_DIM}; border-radius: 4px;"
            f" padding: 10px 14px; color: {_GREY}; font-size: 13px;"
        )
        lay.addWidget(banner)

        self._file_list = QListWidget()
        self._file_list.setSpacing(3)
        self._file_list.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._file_list.itemSelectionChanged.connect(self._on_file_selected)
        self._file_list.itemDoubleClicked.connect(lambda _: self._go_next())
        self._list_enter_filter = _ListEnterFilter(self._go_next)
        self._file_list.installEventFilter(self._list_enter_filter)
        lay.addWidget(self._file_list, 1)

        self._no_fw_label = QLabel("")
        self._no_fw_label.setObjectName("err")
        lay.addWidget(self._no_fw_label)
        return w

    def _page_method(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(16)
        lay.addWidget(QLabel("Select flash method:"))
        grp = QButtonGroup(w)
        self._rb_serial = QRadioButton("\U0001f50c  Serial (USB)   \u2014   direct cable connection")
        self._rb_ota    = QRadioButton("\U0001f4e1  OTA (WiFi)     \u2014   over-the-air upload")
        self._rb_serial.setChecked(True)
        grp.addButton(self._rb_serial)
        grp.addButton(self._rb_ota)
        lay.addWidget(self._rb_serial)
        lay.addWidget(self._rb_ota)
        self._ota_note = QLabel("  \u26a0  OTA is not supported for Arduino Mega 2560.")
        self._ota_note.setObjectName("warn")
        self._ota_note.hide()
        lay.addWidget(self._ota_note)
        lay.addStretch()
        self._rb_serial.toggled.connect(self._on_method_changed)
        self._rb_ota.toggled.connect(self._on_method_changed)
        return w

    def _page_board(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(16)
        lay.addWidget(QLabel("Select board type:"))
        grp = QButtonGroup(w)
        self._rb_esp32 = QRadioButton("ESP32   (default)")
        self._rb_mega  = QRadioButton("Arduino Mega 2560")
        self._rb_esp32.setChecked(True)
        grp.addButton(self._rb_esp32)
        grp.addButton(self._rb_mega)
        lay.addWidget(self._rb_esp32)
        lay.addWidget(self._rb_mega)
        lay.addStretch()
        self._rb_esp32.toggled.connect(self._on_board_changed)
        self._rb_mega.toggled.connect(self._on_board_changed)
        return w

    def _page_conn(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(16)

        # ── serial ──────────────────────────────────────────────────────────
        self._serial_section = QWidget()
        sl = QVBoxLayout(self._serial_section)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(8)
        sl.addWidget(QLabel("Serial port:"))

        port_row = QHBoxLayout()
        self._port_edit = QLineEdit(self._pref("serial_port") or self.default_port)
        self._port_edit.returnPressed.connect(self._go_next)
        port_row.addWidget(self._port_edit, 1)
        btn_auto = QPushButton("Auto")
        btn_auto.setObjectName("check_btn")
        btn_auto.clicked.connect(lambda: self._auto_fill_port(force=True))
        port_row.addWidget(btn_auto)
        btn_chk = QPushButton("Check")
        btn_chk.setObjectName("check_btn")
        btn_chk.clicked.connect(self._check_port)
        port_row.addWidget(btn_chk)
        sl.addLayout(port_row)

        self._port_status = QLabel("")
        sl.addWidget(self._port_status)

        self._chk_port = QCheckBox("\U0001f4be  Remember this port")
        self._chk_port.setChecked("serial_port" in self._prefs)
        self._chk_port.toggled.connect(self._on_chk_port)
        sl.addWidget(self._chk_port)
        sl.addStretch()
        lay.addWidget(self._serial_section)

        # ── OTA ──────────────────────────────────────────────────────────────
        self._ota_section = QWidget()
        ol = QVBoxLayout(self._ota_section)
        ol.setContentsMargins(0, 0, 0, 0)
        ol.setSpacing(8)

        ol.addWidget(QLabel("ESP32 IP address:"))
        ip_row = QHBoxLayout()
        self._ip_edit = QLineEdit(self._pref("ota_ip"))
        self._ip_edit.setPlaceholderText("e.g.  192.168.1.42")
        self._ip_edit.returnPressed.connect(self._go_next)
        ip_row.addWidget(self._ip_edit, 1)
        self._btn_auto_ip = QPushButton("Auto")
        self._btn_auto_ip.setObjectName("check_btn")
        self._btn_auto_ip.clicked.connect(lambda: self._auto_fill_ip(force=True))
        ip_row.addWidget(self._btn_auto_ip)
        ol.addLayout(ip_row)
        self._ota_ip_status = QLabel("")
        ol.addWidget(self._ota_ip_status)
        hint_lbl = QLabel("  Tip: mDNS hostname is dexter-esp32.local")
        hint_lbl.setObjectName("hint")
        ol.addWidget(hint_lbl)
        self._chk_ip = QCheckBox("\U0001f4be  Remember this IP")
        self._chk_ip.setChecked("ota_ip" in self._prefs)
        self._chk_ip.toggled.connect(self._on_chk_ip)
        ol.addWidget(self._chk_ip)

        self._ota_espota_status = QLabel("")
        ol.addWidget(self._ota_espota_status)
        ol.addStretch()
        lay.addWidget(self._ota_section)

        self._ota_section.hide()
        return w

    def _page_confirm(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(8)
        lay.addWidget(QLabel("Review your selection before flashing:"))
        lay.addSpacing(10)

        self._confirm_rows: dict = {}
        for key in ["File", "Method", "Board", "Port / IP"]:
            row = QHBoxLayout()
            lbl_k = QLabel(f"  {key}:")
            lbl_k.setFixedWidth(120)
            lbl_k.setStyleSheet(f"color: {_CYAN_DIM}; font-size: 14px;")
            lbl_v = QLabel("")
            lbl_v.setStyleSheet(f"color: {_WHITE}; font-weight: bold; font-size: 15px;")
            self._confirm_rows[key] = lbl_v
            row.addWidget(lbl_k)
            row.addWidget(lbl_v)
            row.addStretch()
            lay.addLayout(row)

        lay.addSpacing(14)
        lay.addWidget(_divider())
        lay.addSpacing(10)
        self._prereq_label = QLabel("")
        self._prereq_label.setWordWrap(True)
        lay.addWidget(self._prereq_label)
        lay.addStretch()
        return w

    def _page_flash(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(8)
        self._flash_title = QLabel("Flashing\u2026")
        self._flash_title.setObjectName("title")
        lay.addWidget(self._flash_title)
        self._output = QTextEdit()
        self._output.setReadOnly(True)
        lay.addWidget(self._output, 1)
        return w

    # ── navigation ────────────────────────────────────────────────────────────

    def _go_to(self, page: int):
        self.stack.setCurrentIndex(page)
        self._step_label.setText(self._STEP_LABELS[page])

        on_select  = page == self.PAGE_SELECT
        on_confirm = page == self.PAGE_CONFIRM
        on_flash   = page == self.PAGE_FLASH

        self._btn_cancel.setVisible(not on_flash)
        self._btn_back.setVisible(not on_select and not on_flash)
        self._btn_next.setVisible(not on_confirm and not on_flash)
        self._btn_flash.setVisible(on_confirm)
        self._btn_done.setVisible(on_flash)

        if on_confirm:
            self._refresh_confirm()

        if page == self.PAGE_CONN:
            is_ota = self.flash_method == "ota"
            self._serial_section.setVisible(not is_ota)
            self._ota_section.setVisible(is_ota)
            if is_ota:
                self._check_espota()
                self._auto_fill_ip(force=False)
                self._ip_edit.setFocus()
                self._ip_edit.selectAll()
            else:
                self._auto_fill_port(force=False)
                self._port_edit.setFocus()
                self._port_edit.selectAll()

        if on_select:
            self._file_list.setFocus()

    def _go_next(self):
        cur = self.stack.currentIndex()

        if cur == self.PAGE_SELECT:
            if not self.selected_file:
                return

        elif cur == self.PAGE_METHOD:
            self.flash_method = "ota" if self._rb_ota.isChecked() else "serial"

        elif cur == self.PAGE_BOARD:
            if self._rb_mega.isChecked():
                self.board_fqbn = "arduino:avr:mega:cpu=atmega2560"
                self.board_name = "Arduino Mega 2560"
            else:
                self.board_fqbn = "esp32:esp32:esp32"
                self.board_name = "ESP32"

        elif cur == self.PAGE_CONN:
            if self.flash_method == "serial":
                self.serial_port = self._port_edit.text().strip() or self.default_port
                if self._chk_port.isChecked():
                    self._remember("serial_port", self.serial_port)
            else:
                ip = self._ip_edit.text().strip()
                if not ip:
                    self._set_status(self._ota_espota_status, "\u26a0  IP address is required.", "err")
                    self._ip_edit.setFocus()
                    return
                self.ota_ip       = ip
                self.ota_password = "dexter123"
                if self._chk_ip.isChecked():
                    self._remember("ota_ip", self.ota_ip)

        self._go_to(cur + 1)

    def _go_back(self):
        self._go_to(max(0, self.stack.currentIndex() - 1))

    # ── file scan / list ─────────────────────────────────────────────────────

    def _scan_firmware(self):
        fw_dir = self.workspace_dir / "src" / "dexter_arm_hardware" / "firmware"
        self._file_list.clear()
        self._item_frames.clear()
        self.firmware_files = []

        if not fw_dir.exists():
            self._no_fw_label.setText(f"\u26a0  Firmware directory not found:\n   {fw_dir}")
            self._btn_next.setEnabled(False)
            return

        files = sorted(fw_dir.rglob("*.ino")) + sorted(fw_dir.rglob("*.bin"))
        self.firmware_files = files

        if not files:
            self._no_fw_label.setText("\u26a0  No .ino or .bin files found.")
            self._btn_next.setEnabled(False)
            return

        self._no_fw_label.setText("")
        for row, f in enumerate(files):
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, str(f))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
            self._file_list.addItem(item)

            frame = QFrame()
            frame.setObjectName("file_item_inactive")
            h = QHBoxLayout(frame)
            h.setContentsMargins(14, 10, 14, 10)
            h.setSpacing(14)

            badge = QLabel(f.suffix.upper().lstrip("."))
            badge.setObjectName("badge_ino" if f.suffix == ".ino" else "badge_bin")
            badge.setFixedWidth(38)
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            h.addWidget(badge)

            text_col = QVBoxLayout()
            text_col.setSpacing(3)
            fname_lbl = QLabel(f.name)
            fname_lbl.setObjectName("filename_inactive")
            try:
                rel = str(f.relative_to(fw_dir.parent))
            except ValueError:
                rel = str(f)
            dir_lbl = QLabel(rel)
            dir_lbl.setObjectName("hint")
            text_col.addWidget(fname_lbl)
            text_col.addWidget(dir_lbl)
            h.addLayout(text_col, 1)

            size_lbl = QLabel(_fmt_size(f))
            size_lbl.setObjectName("filesize")
            size_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            h.addWidget(size_lbl)

            item.setSizeHint(QSize(0, 72))
            self._file_list.setItemWidget(item, frame)
            self._item_frames[row] = (frame, fname_lbl)

        self._file_list.setCurrentRow(0)
        self._on_file_selected()

    def _on_file_selected(self):
        items = self._file_list.selectedItems()
        for row, (frame, fname_lbl) in self._item_frames.items():
            if row < self._file_list.count():
                is_sel = self._file_list.item(row).isSelected()
                obj_frame = "file_item_active" if is_sel else "file_item_inactive"
                obj_fname = "filename_active" if is_sel else "filename_inactive"
                frame.setObjectName(obj_frame)
                fname_lbl.setObjectName(obj_fname)
                for w in (frame, fname_lbl):
                    w.style().unpolish(w)
                    w.style().polish(w)

        if items:
            self.selected_file = Path(items[0].data(Qt.ItemDataRole.UserRole))
            self._btn_next.setEnabled(True)
            self._on_method_changed()
        else:
            self.selected_file = None
            self._btn_next.setEnabled(False)

    # ── remember checkboxes ──────────────────────────────────────────────────

    def _on_chk_port(self, checked: bool):
        if checked:
            self._remember("serial_port", self._port_edit.text().strip() or self.default_port)
        else:
            self._forget("serial_port")

    def _on_chk_ip(self, checked: bool):
        if checked:
            self._remember("ota_ip", self._ip_edit.text().strip())
        else:
            self._forget("ota_ip")

    # ── option callbacks ─────────────────────────────────────────────────────

    def _on_method_changed(self):
        self._ota_note.setVisible(self._rb_ota.isChecked() and self._rb_mega.isChecked())

    def _on_board_changed(self):
        self._on_method_changed()

    # ── port / espota checks ─────────────────────────────────────────────────

    def _check_port(self):
        port = self._port_edit.text().strip() or self.default_port
        if Path(port).exists():
            self._set_status(self._port_status, f"\u2714  {port} \u2014 found", "ok")
        else:
            self._set_status(self._port_status,
                             f"\u2718  {port} \u2014 not found. Check USB connection.", "err")

    def _auto_fill_port(self, force: bool = False):
        if not force and self._port_edit.text().strip():
            return
        ports = self._detect_serial_ports()
        if not ports:
            self._set_status(self._port_status, "\u2718  No serial ports found.", "err")
            return
        port = ports[0]
        self._port_edit.setText(port)
        if len(ports) == 1:
            self._set_status(self._port_status, f"\u2714  {port} \u2014 auto-detected", "ok")
        else:
            plist = ", ".join(ports)
            self._set_status(self._port_status,
                             f"\u26a0  Multiple ports found: {plist}. Using {port}.", "warn")

    def _detect_serial_ports(self) -> list:
        patterns = ["ttyUSB*", "ttyACM*", "ttyAMA*", "ttyS*"]
        dev = Path("/dev")
        found = []
        for pat in patterns:
            for p in dev.glob(pat):
                if p.exists():
                    found.append(str(p))
        return sorted(set(found))

    def _check_espota(self):
        import subprocess as sp
        res = sp.run(
            "find ~/.arduino15 /usr /opt -name espota.py 2>/dev/null | head -n1",
            shell=True, capture_output=True, text=True
        )
        path = res.stdout.strip()
        if path:
            self._set_status(self._ota_espota_status, f"\u2714  espota.py found: {path}", "ok")
        else:
            self._set_status(self._ota_espota_status,
                             "\u2718  espota.py not found \u2014 install Arduino ESP32 core first.", "err")

    def _auto_fill_ip(self, force: bool = False):
        if not force and self._ip_edit.text().strip():
            return
        try:
            ip = socket.gethostbyname("dexter-esp32.local")
        except Exception:
            self._set_status(self._ota_ip_status,
                             "\u26a0  mDNS lookup failed for dexter-esp32.local.", "warn")
            return
        self._ip_edit.setText(ip)
        self._set_status(self._ota_ip_status, f"\u2714  {ip} \u2014 auto-detected", "ok")

    def _set_status(self, label: QLabel, text: str, kind: str):
        label.setText(text)
        label.setObjectName(kind)
        label.style().unpolish(label)
        label.style().polish(label)

    # ── confirm summary ───────────────────────────────────────────────────────

    def _refresh_confirm(self):
        fname = (
            f"{self.selected_file.parent.name}/{self.selected_file.name}"
            if self.selected_file else "\u2014"
        )
        method = "Serial (USB)" if self.flash_method == "serial" else "OTA (WiFi)"
        conn   = self.serial_port if self.flash_method == "serial" else self.ota_ip or "(not set)"

        self._confirm_rows["File"].setText(fname)
        self._confirm_rows["Method"].setText(method)
        self._confirm_rows["Board"].setText(self.board_name)
        self._confirm_rows["Port / IP"].setText(conn)

        issues = []
        if self.flash_method == "serial":
            if not shutil.which("arduino-cli") and self.selected_file and self.selected_file.suffix == ".ino":
                issues.append("\u26a0  arduino-cli not found \u2014 install before flashing .ino files.")
            if not shutil.which("esptool.py") and self.selected_file and self.selected_file.suffix == ".bin":
                issues.append("\u26a0  esptool.py not found \u2014 run: pip install esptool")
        else:
            if self.board_name == "Arduino Mega 2560":
                issues.append("\u2718  OTA not supported for Arduino Mega 2560.")
                self._btn_flash.setEnabled(False)
            else:
                self._btn_flash.setEnabled(True)

        kind = "warn" if issues else "ok"
        msg  = "\n".join(issues) if issues else "\u2714  All prerequisites look good."
        self._set_status(self._prereq_label, msg, kind)

    # ── flashing ──────────────────────────────────────────────────────────────

    def _do_flash(self):
        if not self.selected_file:
            return
        cmd = self._build_command()
        if not cmd:
            return

        self._go_to(self.PAGE_FLASH)
        self._flash_title.setText("\u26a1  Flashing\u2026")
        self._output.clear()
        self._append_flash_summary()

        self._process = QProcess(self)
        self._process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self._process.readyRead.connect(self._on_output)
        self._process.finished.connect(self._on_finished)
        self._process.start("bash", ["-c", cmd])
        self._timeout_timer.start(_FLASH_TIMEOUT_MS)

    def _append_flash_summary(self):
        """Show a clean human-readable summary instead of the raw shell command."""
        f = self.selected_file
        method = "OTA" if self.flash_method == "ota" else "Serial"
        target = self.ota_ip if self.flash_method == "ota" else self.serial_port
        board = self.board_fqbn

        self._append_output("\u2500" * 48, color=_CYAN_DIM)
        self._append_output(f"  File      {f.name}", color=_CYAN)
        self._append_output(f"  Type      {f.suffix.lstrip('.')} ({_fmt_size(f)})", color=_WHITE)
        self._append_output(f"  Method    {method}", color=_WHITE)
        self._append_output(f"  Target    {target}", color=_WHITE)
        self._append_output(f"  Board     {board}", color=_WHITE)
        self._append_output("\u2500" * 48, color=_CYAN_DIM)
        self._append_output("")

        if f.suffix == ".ino":
            self._append_output("[1/2]  Compiling sketch\u2026", color=_CYAN_DIM)
        else:
            self._append_output("[1/1]  Uploading binary\u2026", color=_CYAN_DIM)

    def _build_command(self) -> str:
        f    = self.selected_file
        port = self.serial_port
        fqbn = self.board_fqbn
        ip   = self.ota_ip
        pwd  = self.ota_password

        if f.suffix == ".ino":
            sname = f.stem
            setup = (
                f'TMPDIR=$(mktemp -d); '
                f'mkdir -p "$TMPDIR/{sname}"; '
                f'cp "{f}" "$TMPDIR/{sname}/"; '
                f'for x in "{f.parent}"/*.h "{f.parent}"/*.cpp "{f.parent}"/*.hpp; do '
                f'[ -f "$x" ] && cp "$x" "$TMPDIR/{sname}/"; done; '
                f'SPATH="$TMPDIR/{sname}"'
            )
            if self.flash_method == "serial":
                return (
                    f'{setup}; '
                    f'arduino-cli compile --fqbn {fqbn} "$SPATH" && '
                    f'arduino-cli upload --fqbn {fqbn} -p {port} "$SPATH" && '
                    f'echo "[DONE] Firmware flashed successfully!" || '
                    f'echo "[ERROR] Flash failed!"; rm -rf "$TMPDIR"'
                )
            else:
                pf = f"-a {pwd}" if pwd else ""
                return (
                    f'{setup}; '
                    f'arduino-cli compile --fqbn esp32:esp32:esp32 "$SPATH" && '
                    f'ESPOTA=$(find ~/.arduino15 /usr /opt -name espota.py 2>/dev/null | head -n1); '
                    f'python3 "$ESPOTA" -i {ip} -f "$SPATH/build/esp32.esp32.esp32/{sname}.ino.bin" {pf} && '
                    f'echo "[DONE] Firmware flashed via OTA!" || '
                    f'echo "[ERROR] OTA flash failed!"; rm -rf "$TMPDIR"'
                )

        elif f.suffix == ".bin":
            if self.flash_method == "serial":
                return (
                    f'esptool.py --chip esp32 --port {port} --baud 921600 '
                    f'write_flash 0x10000 "{f}" && '
                    f'echo "[DONE] Binary flashed!" || echo "[ERROR] Flash failed!"'
                )
            else:
                pf = f"-a {pwd}" if pwd else ""
                return (
                    f'ESPOTA=$(find ~/.arduino15 /usr /opt -name espota.py 2>/dev/null | head -n1); '
                    f'python3 "$ESPOTA" -i {ip} -f "{f}" {pf} && '
                    f'echo "[DONE] Binary flashed via OTA!" || echo "[ERROR] OTA flash failed!"'
                )
        return ""

    def _on_output(self):
        if self._process:
            raw  = bytes(self._process.readAll())
            text = raw.decode("utf-8", errors="replace")
            for line in text.splitlines():
                stripped = line.strip()
                if not stripped:
                    continue
                ll = stripped.lower()
                # Detect phase transitions and show step markers
                if "compiling sketch" in ll or "compiling" in ll and "sketch" in ll:
                    self._append_output("[1/2]  Compiling sketch\u2026", _CYAN_DIM)
                    continue
                if "uploading" in ll and ("serial" in ll or "port" in ll):
                    self._append_output("[2/2]  Uploading to device\u2026", _CYAN_DIM)
                    continue
                # Color-code output
                if "[error]" in ll or "error:" in ll or "failed" in ll:
                    self._append_output(stripped, _RED)
                elif "[done]" in ll or "success" in ll:
                    self._append_output(stripped, _GREEN)
                elif "warning:" in ll:
                    self._append_output(stripped, _YELLOW)
                elif ll.startswith("sketch uses") or ll.startswith("global variables"):
                    # Compile size summary — show as informational
                    self._append_output(f"  {stripped}", _CYAN_DIM)
                else:
                    self._append_output(stripped)

    def _on_finished(self, exit_code: int, _):
        if self._timeout_timer.isActive():
            self._timeout_timer.stop()
        if exit_code == 0:
            self._flash_title.setText("\u2714  Flash Complete")
            self._append_output("\n[DONE] Process exited successfully.", _GREEN)
        else:
            self._flash_title.setText("\u2718  Flash Failed")
            self._append_output(f"\n[ERROR] Process exited with code {exit_code}.", _RED)
        self._flash_done = True

    def _on_timeout(self):
        if self._process and self._process.state() != QProcess.ProcessState.NotRunning:
            self._process.kill()
        self._flash_title.setText("\u2718  Flash Timed Out")
        self._append_output("\n[ERROR] Timeout after 15 seconds. Check connection and try again.", _RED)
        self._flash_done = True

    def _append_output(self, text: str, color: str = _WHITE):
        cursor = self._output.textCursor()
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(text + "\n", fmt)
        self._output.setTextCursor(cursor)
        self._output.ensureCursorVisible()

    def _reset_runtime_state(self):
        """Reset transient UI/runtime state when window is closed."""
        self._flash_done = False
        if hasattr(self, '_output'):
            self._output.clear()
        if hasattr(self, '_flash_title'):
            self._flash_title.setText("Flashing…")
        if hasattr(self, 'stack'):
            self._go_to(self.PAGE_SELECT)

    def closeEvent(self, event):
        if self._process and self._process.state() != QProcess.ProcessState.NotRunning:
            self._process.kill()
            self._process = None
        if self._timeout_timer.isActive():
            self._timeout_timer.stop()
        self._reset_runtime_state()
        super().closeEvent(event)
