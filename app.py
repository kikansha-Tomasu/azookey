from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from azookey_client import (
    VALID_BACKENDS,
    AzooKeyRuntime,
    Composition,
    Suggestion,
    diagnose_backend,
    preferred_appdata_dir,
)
from windows_input import (
    VK_DELETE,
    VK_END,
    VK_HOME,
    VK_LEFT,
    VK_RETURN,
    VK_RIGHT,
    InputEvent,
    KeyboardHook,
    SystemTrayIcon,
    acquire_single_instance_mutex,
    activate_existing_window,
    apply_window_dark_titlebar,
    clamp_to_monitor_work_area,
    cursor_point,
    disable_console_quick_edit,
    dpi_for_point,
    dpi_for_window,
    enable_dpi_awareness,
    focus_window,
    foreground_window,
    has_hardware_caret,
    is_window_elevated,
    make_popup_no_activate,
    monitor_for_window,
    monitor_work_area,
    mouse_button_pressed,
    position_popup_no_activate,
    release_mutex,
    root_window_hwnd,
    send_backspaces,
    send_unicode_text,
    send_virtual_key,
    suppress_native_ime,
    sync_unicode_text,
    system_text_scale_factor,
    system_theme_palette,
    system_theme_signature,
    taskbar_toggle_position,
    text_cursor_position,
    window_contains_point,
)


APP_NAME = "AzooKey Live Bridge"
_AUTO_COMMIT_CHARS = {"、", "。", "！", "？"}
_CURSOR_MOVE_NAME_TO_VK = {
    "left": VK_LEFT,
    "right": VK_RIGHT,
    "home": VK_HOME,
    "end": VK_END,
}
_LEARNING_LIMIT = 2000

_HALFWIDTH_KATAKANA_MAP: dict[str, str] = {
    "ァ": "ｧ", "ア": "ｱ", "ィ": "ｨ", "イ": "ｲ", "ゥ": "ｩ", "ウ": "ｳ", "ェ": "ｪ", "エ": "ｴ", "ォ": "ｫ", "オ": "ｵ",
    "カ": "ｶ", "ガ": "ｶﾞ", "キ": "ｷ", "ギ": "ｷﾞ", "ク": "ｸ", "グ": "ｸﾞ", "ケ": "ｹ", "ゲ": "ｹﾞ", "コ": "ｺ", "ゴ": "ｺﾞ",
    "サ": "ｻ", "ザ": "ｻﾞ", "シ": "ｼ", "ジ": "ｼﾞ", "ス": "ｽ", "ズ": "ｽﾞ", "セ": "ｾ", "ゼ": "ｾﾞ", "ソ": "ｿ", "ゾ": "ｿﾞ",
    "タ": "ﾀ", "ダ": "ﾀﾞ", "チ": "ﾁ", "ヂ": "ﾁﾞ", "ッ": "ｯ", "ツ": "ﾂ", "ヅ": "ﾂﾞ", "テ": "ﾃ", "デ": "ﾃﾞ", "ト": "ﾄ", "ド": "ﾄﾞ",
    "ナ": "ﾅ", "ニ": "ﾆ", "ヌ": "ﾇ", "ネ": "ﾈ", "ノ": "ﾉ",
    "ハ": "ﾊ", "バ": "ﾊﾞ", "パ": "ﾊﾟ", "ヒ": "ﾋ", "ビ": "ﾋﾞ", "ピ": "ﾋﾟ", "フ": "ﾌ", "ブ": "ﾌﾞ", "プ": "ﾌﾟ",
    "ヘ": "ﾍ", "ベ": "ﾍﾞ", "ペ": "ﾍﾟ", "ホ": "ﾎ", "ボ": "ﾎﾞ", "ポ": "ﾎﾟ",
    "マ": "ﾏ", "ミ": "ﾐ", "ム": "ﾑ", "メ": "ﾒ", "モ": "ﾓ",
    "ャ": "ｬ", "ヤ": "ﾔ", "ュ": "ｭ", "ユ": "ﾕ", "ョ": "ｮ", "ヨ": "ﾖ",
    "ラ": "ﾗ", "リル"[0]: "ﾘ", "ル": "ﾙ", "レ": "ﾚ", "ロ": "ﾛ",
    "ヮ": "ﾜ", "ワ": "ﾜ", "ヰ": "ｲ", "ヱ": "ｴ", "ヲ": "ｦ", "ン": "ﾝ", "ヴ": "ｳﾞ",
    "ー": "ｰ", "、": "､", "。": "｡", "「": "｢", "」": "｣", "・": "･",
}


def _to_hiragana(text: str) -> str:
    chars: list[str] = []
    for ch in text:
        code = ord(ch)
        if 0x30A1 <= code <= 0x30F6 or code in (0x30FD, 0x30FE):
            chars.append(chr(code - 0x60))
        else:
            chars.append(ch)
    return "".join(chars)


def _to_fullwidth_katakana(text: str) -> str:
    chars: list[str] = []
    for ch in text:
        code = ord(ch)
        if 0x3041 <= code <= 0x3096 or code in (0x309D, 0x309E):
            chars.append(chr(code + 0x60))
        else:
            chars.append(ch)
    return "".join(chars)


def _to_halfwidth_katakana(text: str) -> str:
    katakana = _to_fullwidth_katakana(text)
    return "".join(_HALFWIDTH_KATAKANA_MAP.get(ch, ch) for ch in katakana)


def _to_fullwidth_ascii(text: str) -> str:
    chars: list[str] = []
    for ch in text:
        code = ord(ch)
        if ch == " ":
            chars.append("\u3000")
        elif 0x21 <= code <= 0x7E:
            chars.append(chr(code + 0xFEE0))
        else:
            chars.append(ch)
    return "".join(chars)

UI_SCALE_ORDER = ("normal", "large", "xlarge")
UI_SCALE_LABELS: tuple[tuple[str, str], ...] = (
    ("normal", "標準"),
    ("large", "大きめ"),
    ("xlarge", "特大"),
)


_OS_THEME_POLL_INTERVAL = 0.5


def _text_scale_multiplier(text_scale: float | None = None) -> float:
    raw = system_text_scale_factor() if text_scale is None else text_scale
    return min(1.5, max(1.0, raw))

UI_SCALES: dict[str, dict[str, int]] = {
    "normal": {
        "popup_header_font": 9,
        "popup_item_font": 11,
        "popup_min_width": 240,
        "popup_max_width": 540,
        "popup_padx": 10,
        "popup_pady": 4,
        "toggle_width": 148,
        "toggle_height": 36,
        "toggle_font": 9,
        "settings_title_font": 16,
        "settings_heading_font": 10,
        "settings_body_font": 10,
        "settings_caption_font": 9,
        "settings_indicator_px": 15,
        "settings_pad": 12,
    },
    "large": {
        "popup_header_font": 10,
        "popup_item_font": 13,
        "popup_min_width": 280,
        "popup_max_width": 620,
        "popup_padx": 12,
        "popup_pady": 5,
        "toggle_width": 172,
        "toggle_height": 42,
        "toggle_font": 11,
        "settings_title_font": 18,
        "settings_heading_font": 12,
        "settings_body_font": 11,
        "settings_caption_font": 10,
        "settings_indicator_px": 18,
        "settings_pad": 14,
    },
    "xlarge": {
        "popup_header_font": 11,
        "popup_item_font": 15,
        "popup_min_width": 320,
        "popup_max_width": 700,
        "popup_padx": 14,
        "popup_pady": 6,
        "toggle_width": 198,
        "toggle_height": 48,
        "toggle_font": 12,
        "settings_title_font": 21,
        "settings_heading_font": 14,
        "settings_body_font": 13,
        "settings_caption_font": 12,
        "settings_indicator_px": 21,
        "settings_pad": 16,
    },
}

# Fixed integer initial position closest to the button's active screen placement.
DEFAULT_TOGGLE_POSITION: tuple[int, int] = (2085, 1465)


def _draw_check_indicator_image(
    photo: tk.PhotoImage,
    *,
    size: int,
    right_pad: int,
    fill: str,
    border: str,
    check_fg: str | None,
    border_px: int = 1,
) -> None:
    """Render a rounded checkbox indicator with an optional crisp ✓ checkmark into *photo*."""
    box = max(12, int(size))
    pad = max(0, int(right_pad))
    b = max(1, min(border_px, box // 4))
    radius = max(2.0, box * 0.16)
    inner_r = max(1.0, radius - b)

    photo.configure(width=box + pad, height=box)
    photo.blank()

    def _dist2_seg(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
        vx, vy = bx - ax, by - ay
        wx, wy = px - ax, py - ay
        denom = vx * vx + vy * vy
        t = 0.0 if denom <= 0.0 else max(0.0, min(1.0, (wx * vx + wy * vy) / denom))
        dx, dy = px - (ax + t * vx), py - (ay + t * vy)
        return dx * dx + dy * dy

    def _outside_corner(cx: float, cy: float, r: float) -> bool:
        r2 = r * r
        if cx < r and cy < r:
            return (r - cx) ** 2 + (r - cy) ** 2 > r2
        if cx > box - r and cy < r:
            return (cx - (box - r)) ** 2 + (r - cy) ** 2 > r2
        if cx < r and cy > box - r:
            return (r - cx) ** 2 + (cy - (box - r)) ** 2 > r2
        if cx > box - r and cy > box - r:
            return (cx - (box - r)) ** 2 + (cy - (box - r)) ** 2 > r2
        return False

    p0 = (0.22 * box, 0.52 * box)
    p1 = (0.42 * box, 0.72 * box)
    p2 = (0.78 * box, 0.29 * box)
    half_w2 = max(1.15, box * 0.085) ** 2

    rows: list[tuple[str, ...]] = []
    transparent_corners: list[tuple[int, int]] = []
    for y in range(box):
        row: list[str] = []
        cy = y + 0.5
        for x in range(box):
            cx = x + 0.5
            if _outside_corner(cx, cy, radius):
                row.append(fill)
                transparent_corners.append((x, y))
                continue
            in_border = (
                x < b
                or y < b
                or x >= box - b
                or y >= box - b
                or _outside_corner(cx, cy, inner_r)
            )
            if in_border:
                row.append(border)
            elif check_fg is not None and min(
                _dist2_seg(cx, cy, *p0, *p1),
                _dist2_seg(cx, cy, *p1, *p2),
            ) <= half_w2:
                row.append(check_fg)
            else:
                row.append(fill)
        rows.append(tuple(row))

    photo.put(tuple(rows), to=(0, 0))
    for cx_px, cy_px in transparent_corners:
        photo.transparency_set(cx_px, cy_px, True)


_BRIDGE_APPDATA_CACHE: tuple[str, str, Path] | None = None


def _dir_writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write_probe"
        probe.write_text("", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def _default_engine_dir() -> str:
    folder = Path(__file__).resolve().parent / "azookey-runtime" / "app"
    return str(folder) if (folder / "azookey-server.dll").is_file() else ""


def _settings_path() -> Path:
    global _BRIDGE_APPDATA_CACHE
    raw_base = preferred_appdata_dir()
    primary = Path(raw_base) if raw_base else (Path.home() / "AppData" / "Roaming")
    default_dir = _default_engine_dir()
    cache_key = (str(primary), default_dir)
    if (
        _BRIDGE_APPDATA_CACHE is not None
        and (_BRIDGE_APPDATA_CACHE[0], _BRIDGE_APPDATA_CACHE[1]) == cache_key
    ):
        return _BRIDGE_APPDATA_CACHE[2] / "AzooKeyLiveBridge" / "settings.json"
    chosen = primary
    if default_dir and not _dir_writable(primary / "AzooKeyLiveBridge"):
        fallback = Path(default_dir) / ".appdata"
        if _dir_writable(fallback / "AzooKeyLiveBridge"):
            chosen = fallback
    _BRIDGE_APPDATA_CACHE = (cache_key[0], cache_key[1], chosen)
    return chosen / "AzooKeyLiveBridge" / "settings.json"


def _load_settings() -> dict[str, str]:
    try:
        data = json.loads(_settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    engine_dir = str(data.get("engine_dir", ""))
    if not engine_dir or not (Path(engine_dir) / "azookey-server.dll").is_file():
        engine_dir = _default_engine_dir()
    ui_scale = str(data.get("ui_scale", "normal"))
    if ui_scale not in UI_SCALES:
        ui_scale = "normal"
    toggle_x = str(data.get("toggle_x", ""))
    toggle_y = str(data.get("toggle_y", ""))
    english_passthrough = "1" if str(data.get("english_passthrough", "0")) == "1" else "0"
    fullwidth_space = "0" if str(data.get("fullwidth_space", "1")) == "0" else "1"
    shift_direct_english = "0" if str(data.get("shift_direct_english", "1")) == "0" else "1"
    minimize_to_tray = "0" if str(data.get("minimize_to_tray", "1")) == "0" else "1"
    start_minimized = "1" if str(data.get("start_minimized", "0")) == "1" else "0"
    use_zenzai = "0" if str(data.get("use_zenzai", "1")) == "0" else "1"
    zenzai_profile = str(data.get("zenzai_profile", ""))
    zenzai_backend = str(data.get("zenzai_backend", "cpu")).lower()
    if zenzai_backend not in VALID_BACKENDS:
        zenzai_backend = "cpu"
    return {
        "engine_dir": engine_dir,
        "ui_scale": ui_scale,
        "toggle_x": toggle_x,
        "toggle_y": toggle_y,
        "english_passthrough": english_passthrough,
        "fullwidth_space": fullwidth_space,
        "shift_direct_english": shift_direct_english,
        "minimize_to_tray": minimize_to_tray,
        "start_minimized": start_minimized,
        "use_zenzai": use_zenzai,
        "zenzai_profile": zenzai_profile,
        "zenzai_backend": zenzai_backend,
    }


def _save_settings(settings: dict[str, str]) -> None:
    target = _settings_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        # Settings persistence is optional; an unwritable profile must not
        # prevent the keyboard hook and live conversion from becoming active.
        pass


_LEARNING_IO_LOCK = threading.Lock()


def _learning_path() -> Path:
    return _settings_path().parent / "learning.json"


def _load_learning_memory() -> dict[str, str]:
    with _LEARNING_IO_LOCK:
        try:
            data = json.loads(_learning_path().read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return {}
    if not isinstance(data, dict):
        return {}
    cleaned: dict[str, str] = {}
    for key, value in list(data.items())[-_LEARNING_LIMIT:]:
        if isinstance(key, str) and isinstance(value, str) and key and value:
            cleaned[key] = value
    return cleaned


def _save_learning_memory(memory: dict[str, str]) -> None:
    target = _learning_path()
    with _LEARNING_IO_LOCK:
        try:
            trimmed = dict(list(memory.items())[-_LEARNING_LIMIT:])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(trimmed, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass


def _trailing_ascii_alpha(hiragana: str) -> str:
    idx = len(hiragana)
    while idx > 0 and hiragana[idx - 1].isascii() and hiragana[idx - 1].isalpha():
        idx -= 1
    return hiragana[idx:]


def _has_incomplete_romaji(hiragana: str) -> bool:
    return any(ch.isascii() and ch.isalpha() for ch in hiragana)


def _has_non_n_incomplete_romaji(hiragana: str, cursor_offset: int = 0) -> bool:
    if cursor_offset < 0:
        pos = max(0, len(hiragana) + cursor_offset)
        suffix = _trailing_ascii_alpha(hiragana[:pos])
    else:
        suffix = _trailing_ascii_alpha(hiragana)
    return bool(suffix) and suffix != "n"


def _normalized_kana_prefix(hiragana: str) -> str:
    suffix = _trailing_ascii_alpha(hiragana)
    if suffix == "n":
        return hiragana[:-1] + "ん"
    if suffix:
        return hiragana[: -len(suffix)]
    return hiragana


def _common_prefix_len(first: str, second: str) -> int:
    limit = min(len(first), len(second))
    index = 0
    while index < limit and first[index] == second[index]:
        index += 1
    return index


def _split_segment_list_at(
    segments: list[tuple[str, list[str]]],
    surface_pos: int,
) -> tuple[list[tuple[str, list[str]]], list[tuple[str, list[str]]]]:
    left: list[tuple[str, list[str]]] = []
    right: list[tuple[str, list[str]]] = []
    acc = 0
    for seg_s, seg_raw in segments:
        seg_end = acc + len(seg_s)
        if seg_end <= surface_pos:
            left.append((seg_s, list(seg_raw)))
        elif acc >= surface_pos:
            right.append((seg_s, list(seg_raw)))
        else:
            split_idx = surface_pos - acc
            if len(seg_s) == len(seg_raw):
                left.append((seg_s[:split_idx], list(seg_raw[:split_idx])))
                right.append((seg_s[split_idx:], list(seg_raw[split_idx:])))
            else:
                # Mirror AzooKey collapsing a multi-kana cluster when split mid-cluster.
                parts = [(ch, [ch]) for ch in seg_s]
                left.extend(parts[:split_idx])
                right.extend(parts[split_idx:])
        acc = seg_end
    return left, right


class CompositionWorker:
    def __init__(
        self,
        client,
        hook: KeyboardHook,
        ui_events: queue.Queue[tuple[str, object]],
        events: queue.Queue[InputEvent | tuple[object, ...] | None],
        learning_memory: dict[str, str] | None = None,
    ) -> None:
        self.client = client
        self.hook = hook
        self.ui_events = ui_events
        self.events = events
        self._learning_lock = threading.Lock()
        self._learning_memory: dict[str, str] = dict(learning_memory) if learning_memory else {}
        self._thread = threading.Thread(target=self._run, name="AzooKey conversion worker", daemon=True)
        self._pending_event: InputEvent | tuple[object, ...] | None = None
        self._has_pending_event = False
        self._target = 0
        self._hiragana = ""
        self._raw_input = ""
        self._segments: list[tuple[str, list[str]]] = []
        self._cursor_offset = 0
        self._displayed_text = ""
        self._displayed_cursor = 0
        self._stable_prefix_text = ""
        self._stable_kana_prefix = ""
        self._needs_compose = False
        self._suggestions: tuple[Suggestion, ...] = ()
        self._engine_suggestion_texts: set[str] = set()
        self._candidates: tuple[str, ...] = ()
        self._candidate_index = 0
        self._selecting = False
        self._ascii_direct = False
        self._shift_direct_english = True
        self._context = ""
        self._active_event_seq = 0
        self._session_seq = 0
        self._max_seq = 0

    def set_shift_direct_english(self, enabled: bool) -> None:
        self._shift_direct_english = bool(enabled)

    def start(self) -> None:
        self._thread.start()

    def submit(self, event: InputEvent) -> None:
        self.events.put(event)

    def update_zenzai_config(self, *, enabled: bool, profile: str, backend: str) -> None:
        self.events.put(("update_zenzai_config", bool(enabled), str(profile), str(backend)))

    def close(self) -> None:
        self.events.put(None)
        self._thread.join(timeout=2)

    def _next_event(self) -> InputEvent | tuple[object, ...] | None:
        if self._has_pending_event:
            self._has_pending_event = False
            event = self._pending_event
            self._pending_event = None
            return event
        return self.events.get()

    def _update_context(self, committed: str) -> None:
        if not committed:
            return
        self._context = (self._context + committed)[-60:]
        self.hook.mark_has_context(True)
        try:
            self.client.set_context(self._context)
        except Exception:
            pass

    def _clear_context(self) -> None:
        self._context = ""
        self.hook.mark_has_context(False)
        try:
            self.client.set_context("")
        except Exception:
            pass

    def learning_items(self) -> list[tuple[str, str]]:
        """Return learned (reading, candidate) pairs ordered oldest to newest."""
        with self._learning_lock:
            return list(self._learning_memory.items())

    def remove_learning_entries(self, readings: list[str] | tuple[str, ...] | set[str]) -> int:
        """Remove learned entries for *readings*, persist to disk, and notify UI."""
        targets = {r for r in readings if r}
        if not targets:
            return 0
        removed = 0
        with self._learning_lock:
            for reading in targets:
                if reading in self._learning_memory:
                    self._learning_memory.pop(reading, None)
                    removed += 1
            if removed:
                _save_learning_memory(self._learning_memory)
            count = len(self._learning_memory)
        if removed:
            self.ui_events.put(("learning_count", count))
        return removed

    def _record_learning(self, reading: str, chosen: str) -> None:
        if not reading or not chosen or len(reading) > 24 or _has_incomplete_romaji(reading):
            return
        with self._learning_lock:
            if self._learning_memory.get(reading) == chosen:
                self._learning_memory.pop(reading, None)
                self._learning_memory[reading] = chosen
                return
            self._learning_memory.pop(reading, None)
            self._learning_memory[reading] = chosen
            while len(self._learning_memory) > _LEARNING_LIMIT:
                oldest_key = next(iter(self._learning_memory))
                self._learning_memory.pop(oldest_key, None)
            _save_learning_memory(self._learning_memory)
            count = len(self._learning_memory)
        self.ui_events.put(("learning_count", count))

    def _run(self) -> None:
        while True:
            event = self._next_event()
            if event is None:
                try:
                    self.client.clear_text()
                except Exception:
                    pass
                return
            if isinstance(event, tuple):
                kind = event[0]
                if kind == "toggle":
                    if self.hook.active.is_set() and event[1]:
                        suppress_native_ime(int(event[1]))
                    self.ui_events.put(("toggle", event[1]))
                elif kind == "update_zenzai_config":
                    _, z_enabled, z_profile, z_backend = event
                    try:
                        self.client.set_zenzai_config(
                            enabled=bool(z_enabled),
                            profile=str(z_profile),
                            backend=str(z_backend),
                        )
                    except Exception:
                        pass
                continue
            try:
                self._handle(event)
            except Exception as exc:
                if event.kind in ("letter", "english") and foreground_window() == event.hwnd:
                    try:
                        send_unicode_text(event.char)
                    except Exception:
                        pass
                try:
                    self.client.clear_text()
                except Exception:
                    pass
                self._active_event_seq = 0
                self._reset_state()
                set_mode = getattr(self.hook, "set_mode", None)
                if callable(set_mode):
                    set_mode(active=False, english=False, clear_selecting=True)
                else:
                    self.hook.set_active(False)
                    self.hook.set_english(False)
                self.ui_events.put(("error", f"変換エンジンとの通信が止まりました。入力補助を停止しました。\n{exc}"))
            finally:
                self._active_event_seq = 0
                if event.completed is not None:
                    event.completed.set()

    def _track_event_seq(self, seq: int) -> None:
        self._active_event_seq = seq
        if seq > self._session_seq:
            self._session_seq = seq
        if seq > self._max_seq:
            self._max_seq = seq

    def _sync_raw_from_segments(self) -> None:
        self._raw_input = "".join(ch for _, raw in self._segments for ch in raw)

    def _engine_count(self) -> int:
        return sum(len(raw) for _, raw in self._segments)

    def _clear_if_empty(self) -> bool:
        if self._hiragana or self._raw_input:
            return False
        if self._displayed_text and self._target:
            self._sync_editor_display(self._target, "", 0)
        self._reset_state()
        return True

    def _restore_hook_selection(self) -> None:
        """Re-synchronize hook selection flags when an optimistic selection cannot commit."""
        if self._clear_if_empty():
            return
        self.hook.mark_selecting(self._selecting, seq=self._active_event_seq)
        self._update_visible_candidate_count()

    def _update_visible_candidate_count(self) -> None:
        total = len(self._candidates)
        if total <= 0:
            self.hook.set_visible_candidate_count(0, seq=self._active_event_seq)
            return
        page_size = min(CandidatePopup.MAX_VISIBLE, total)
        page_start = (self._candidate_index // page_size) * page_size
        self.hook.set_visible_candidate_count(
            min(CandidatePopup.MAX_VISIBLE, total - page_start),
            seq=self._active_event_seq,
        )

    def _split_at_cursor(self, old_hiragana: str) -> tuple[list[tuple[str, list[str]]], list[tuple[str, list[str]]]]:
        surface_pos = max(0, min(len(old_hiragana), len(old_hiragana) + self._cursor_offset))
        return _split_segment_list_at(self._segments, surface_pos)

    def _apply_append_to_segments(
        self,
        old_hiragana: str,
        new_hiragana: str,
        engine_char: str,
        actual_raw: str,
        *,
        new_cursor_offset: int | None = None,
    ) -> None:
        left, right = self._split_at_cursor(old_hiragana)
        old_left_h = "".join(s for s, _ in left)
        right_h = "".join(s for s, _ in right)
        expected_right_len = max(0, -new_cursor_offset) if new_cursor_offset is not None else len(right_h)
        if right_h:
            if len(right_h) != expected_right_len or not new_hiragana.endswith(right_h):
                self._segments = [(ch, [ch]) for ch in new_hiragana]
                self._sync_raw_from_segments()
                return
            new_left_h = new_hiragana[: len(new_hiragana) - len(right_h)]
        else:
            if expected_right_len > 0:
                self._segments = [(ch, [ch]) for ch in new_hiragana]
                self._sync_raw_from_segments()
                return
            new_left_h = new_hiragana

        cp = _common_prefix_len(old_left_h, new_left_h)
        kept, popped = _split_segment_list_at(left, cp)
        if (
            not popped
            and engine_char.isascii()
            and engine_char.isalpha()
            and kept
            and _has_incomplete_romaji(kept[-1][0])
        ):
            popped = [kept.pop()]
            cp -= len(popped[0][0])

        pending_raw = [ch for _, raw in popped for ch in raw] + [actual_raw]
        new_rem = new_left_h[cp:]
        if new_rem:
            if (
                len(pending_raw) >= 2
                and len(new_rem) >= 2
                and not (new_rem.isascii() and new_rem.isalpha())
                and new_rem.endswith(engine_char)
            ):
                split_raw = max(1, len(pending_raw) - len(engine_char))
                kept.append((new_rem[: -len(engine_char)], pending_raw[:split_raw]))
                kept.append((engine_char, pending_raw[split_raw:]))
            else:
                kept.append((new_rem, pending_raw))
        self._segments = kept + right
        self._sync_raw_from_segments()

    def _apply_remove_to_segments(
        self,
        old_hiragana: str,
        new_hiragana: str,
        *,
        new_cursor_offset: int | None = None,
    ) -> None:
        if not new_hiragana:
            self._segments.clear()
            self._raw_input = ""
            self._cursor_offset = 0
            return
        if new_hiragana == old_hiragana and new_cursor_offset is None:
            return
        left, right = self._split_at_cursor(old_hiragana)
        old_left_h = "".join(s for s, _ in left)
        right_h = "".join(s for s, _ in right)
        expected_right_len = max(0, -new_cursor_offset) if new_cursor_offset is not None else len(right_h)
        if right_h:
            if len(right_h) != expected_right_len or not new_hiragana.endswith(right_h):
                self._segments = [(ch, [ch]) for ch in new_hiragana]
                self._sync_raw_from_segments()
                return
            new_left_h = new_hiragana[: len(new_hiragana) - len(right_h)]
        else:
            if expected_right_len > 0:
                self._segments = [(ch, [ch]) for ch in new_hiragana]
                self._sync_raw_from_segments()
                return
            new_left_h = new_hiragana

        cp = _common_prefix_len(old_left_h, new_left_h)
        kept, _popped = _split_segment_list_at(left, cp)
        new_rem = new_left_h[cp:]
        if new_rem:
            kept.extend((ch, [ch]) for ch in new_rem)
        self._segments = kept + right
        self._sync_raw_from_segments()

    def _consume_segments_raw(self, count: int, remaining_hiragana: str) -> None:
        if not remaining_hiragana:
            self._segments.clear()
            self._raw_input = ""
            return
        remaining_count = count
        while self._segments and remaining_count > 0:
            seg_s, seg_raw = self._segments[0]
            if len(seg_raw) <= remaining_count:
                remaining_count -= len(seg_raw)
                self._segments.pop(0)
            else:
                if len(seg_s) == len(seg_raw):
                    self._segments[0] = (seg_s[remaining_count:], seg_raw[remaining_count:])
                else:
                    self._segments.pop(0)
                remaining_count = 0
        if "".join(s for s, _ in self._segments) != remaining_hiragana:
            self._segments = [(ch, [ch]) for ch in remaining_hiragana]
        self._sync_raw_from_segments()

    def _client_tracks_cursor(self) -> bool:
        return getattr(self.client, "SUPPORTS_CURSOR_OFFSET", False) is True

    def _append_engine_char_raw(self, engine_char: str, raw_char: str) -> str:
        old_h = self._hiragana
        if self._client_tracks_cursor():
            new_h, new_cursor = self.client.append_text_raw_with_cursor(engine_char)
        else:
            new_h = self.client.append_text_raw(engine_char)
            new_cursor = max(-len(new_h), min(0, self._cursor_offset)) if new_h else 0
        self._hiragana = new_h
        self._apply_append_to_segments(
            old_h,
            new_h,
            engine_char,
            raw_char,
            new_cursor_offset=new_cursor if self._client_tracks_cursor() else None,
        )
        self._cursor_offset = max(-len(new_h), min(0, new_cursor)) if new_h else 0
        self._needs_compose = True
        return self._hiragana

    def _append_letter_raw(self, char: str, raw_char: str = "") -> str:
        actual_raw = raw_char or char
        engine_char = char.lower() if (char.isascii() and char.isalpha()) else char
        return self._append_engine_char_raw(engine_char, actual_raw)

    def _remove_one_step(self) -> str:
        old_h = self._hiragana
        if self._client_tracks_cursor():
            hiragana, new_cursor = self.client.remove_text_raw_with_cursor()
        else:
            hiragana = self.client.remove_text_raw()
            new_cursor = max(-len(hiragana), min(0, self._cursor_offset)) if hiragana else 0
        self._hiragana = hiragana
        self._needs_compose = True
        self._apply_remove_to_segments(
            old_h,
            hiragana,
            new_cursor_offset=new_cursor if self._client_tracks_cursor() else None,
        )
        self._cursor_offset = max(-len(hiragana), min(0, new_cursor)) if hiragana else 0
        return hiragana

    def _move_client_cursor(self, step: int, *, mark_dirty: bool = True) -> tuple[str, int]:
        if step == 0:
            return self._hiragana, 0
        if self._client_tracks_cursor():
            hiragana, new_cursor, moved = self.client.move_cursor_raw_with_cursor(step)
            self._hiragana = hiragana
            self._cursor_offset = max(-len(hiragana), min(0, new_cursor)) if hiragana else 0
            if mark_dirty:
                self._needs_compose = True
            return hiragana, moved
        hiragana = self.client.move_cursor_raw(step)
        self._hiragana = hiragana
        if mark_dirty:
            self._needs_compose = True
        return hiragana, step

    def _move_cursor_to_end_raw(self) -> None:
        if self._cursor_offset >= 0:
            self._cursor_offset = 0
            return
        if self._ascii_direct:
            self._cursor_offset = 0
            return
        if self._client_tracks_cursor():
            for _ in range(max(1, len(self._hiragana) + 1)):
                step = -self._cursor_offset
                if step <= 0:
                    break
                hiragana, moved = self._move_client_cursor(step, mark_dirty=False)
                if not hiragana or self._cursor_offset >= 0 or moved == 0:
                    break
        else:
            self.client.move_cursor_raw(-self._cursor_offset)
        self._cursor_offset = 0

    def _delete_one_step(self) -> tuple[str, bool]:
        if self._cursor_offset >= 0 or not self._hiragana:
            return self._hiragana, False
        if self._client_tracks_cursor():
            hiragana, moved = self._move_client_cursor(1, mark_dirty=True)
            if moved <= 0:
                return hiragana, False
        else:
            self._cursor_offset += 1
            self.client.move_cursor_raw(1)
        return self._remove_one_step(), True

    def _finalize_trailing_n_raw(self) -> None:
        if not self._selecting and self._cursor_offset == 0 and self._hiragana.endswith("n"):
            self._append_engine_char_raw("n", "")

    def _compose_current(self) -> Composition:
        composition = self.client.compose(self._hiragana)
        self._set_candidates(composition)
        self._needs_compose = False
        if self._cursor_offset == 0 and not _has_non_n_incomplete_romaji(self._hiragana):
            self._stable_prefix_text = self._editor_text_for_index(0)
            self._stable_kana_prefix = _normalized_kana_prefix(self._hiragana)
        return composition

    def _ensure_composed(self) -> None:
        if self._ascii_direct:
            return
        if _has_non_n_incomplete_romaji(self._hiragana, self._cursor_offset):
            return
        if self._needs_compose and self._hiragana:
            self._compose_current()

    def _append_letter_to_client(self, char: str, raw_char: str = "") -> Composition:
        self._append_letter_raw(char, raw_char=raw_char)
        return self._compose_current()

    def _finalize_trailing_n(self) -> None:
        if self._ascii_direct:
            return
        self._finalize_trailing_n_raw()
        self._ensure_composed()

    def _set_ascii_direct_candidates(self) -> None:
        raw = self._raw_input
        self._hiragana = raw
        self._engine_suggestion_texts.clear()
        choices: list[str] = []
        for variant in (raw, _to_fullwidth_ascii(raw), raw.lower(), raw.upper()):
            if variant and variant not in choices:
                choices.append(variant)
        self._suggestions = tuple(Suggestion(text=choice, subtext="", corresponding_count=0) for choice in choices)
        self._candidates = tuple(choices)
        self._candidate_index = 0
        self._update_visible_candidate_count()

    def _ascii_insert(self, text: str) -> None:
        pos = max(0, min(len(self._raw_input), len(self._raw_input) + self._cursor_offset))
        self._raw_input = self._raw_input[:pos] + text + self._raw_input[pos:]
        self._hiragana = self._raw_input
        self._stable_prefix_text = self._raw_input

    def _ascii_remove_backspace(self) -> str:
        if not self._raw_input or self._cursor_offset <= -len(self._raw_input):
            return self._raw_input
        pos = max(0, len(self._raw_input) + self._cursor_offset)
        if pos <= 0:
            return self._raw_input
        self._raw_input = self._raw_input[: pos - 1] + self._raw_input[pos:]
        self._hiragana = self._raw_input
        self._stable_prefix_text = self._raw_input
        return self._raw_input

    def _ascii_remove_delete(self) -> str:
        if not self._raw_input or self._cursor_offset >= 0:
            return self._raw_input
        pos = max(0, len(self._raw_input) + self._cursor_offset)
        if pos >= len(self._raw_input):
            return self._raw_input
        self._raw_input = self._raw_input[:pos] + self._raw_input[pos + 1 :]
        self._cursor_offset += 1
        self._hiragana = self._raw_input
        self._stable_prefix_text = self._raw_input
        return self._raw_input

    def _preview_for_incomplete_romaji(self) -> str:
        if self._cursor_offset < 0:
            self._set_incomplete_candidates(self._hiragana)
            return self._hiragana
        suffix = _trailing_ascii_alpha(self._hiragana)
        if not suffix:
            return self._stable_prefix_text or self._hiragana
        suffix_len = len(suffix)
        raw_suffix = (
            self._raw_input[-suffix_len:]
            if len(self._raw_input) >= suffix_len
            else suffix
        )
        kana_prefix = _normalized_kana_prefix(self._hiragana)
        if kana_prefix and kana_prefix == self._stable_kana_prefix and self._stable_prefix_text:
            base = self._stable_prefix_text
        else:
            base = self._hiragana[:-suffix_len]
        preview = base + raw_suffix
        self._set_incomplete_candidates(preview)
        return preview

    def _set_incomplete_candidates(self, preview: str) -> None:
        total_count = self._engine_count()
        suggestions: list[Suggestion] = []
        choices: list[str] = []
        for text in (preview, self._hiragana):
            if text and text not in choices:
                suggestions.append(
                    Suggestion(text=text, subtext="", corresponding_count=total_count)
                )
                choices.append(text)
        if self._raw_input and all(ch.isascii() and ch.isprintable() for ch in self._raw_input):
            for text in (self._raw_input, _to_fullwidth_ascii(self._raw_input)):
                if text and text not in choices:
                    suggestions.append(
                        Suggestion(text=text, subtext="", corresponding_count=total_count)
                    )
                    choices.append(text)
        self._suggestions = tuple(suggestions)
        self._candidates = tuple(choices)
        self._candidate_index = 0
        self._update_visible_candidate_count()

    def _sync_editor_display(self, hwnd: int, new_text: str, new_cursor: int) -> None:
        clamped_cursor = max(-len(new_text), min(0, new_cursor)) if new_text else 0
        if hwnd and foreground_window() == hwnd:
            sync_unicode_text(
                self._displayed_text,
                self._displayed_cursor,
                new_text,
                clamped_cursor,
            )
        self._displayed_text = new_text
        self._displayed_cursor = clamped_cursor

    def _commit_partial_clause(
        self,
        suggestion: Suggestion,
        target: int,
        *,
        force_focus: bool = False,
        defer_render: bool = False,
        explicit: bool = False,
        reset_hook: bool = True,
    ) -> bool:
        committed_prefix = suggestion.text
        prev_hiragana = self._hiragana
        learnable = explicit and committed_prefix in self._engine_suggestion_texts
        self._update_context(committed_prefix)
        remaining = self.client.shrink_text(suggestion.corresponding_count)
        if learnable and prev_hiragana:
            if not remaining.hiragana:
                self._record_learning(prev_hiragana, committed_prefix)
            elif prev_hiragana.endswith(remaining.hiragana):
                clause_reading = prev_hiragana[: len(prev_hiragana) - len(remaining.hiragana)]
                if clause_reading:
                    self._record_learning(clause_reading, committed_prefix)
        if remaining.hiragana or remaining.suggestions:
            self._consume_segments_raw(suggestion.corresponding_count, remaining.hiragana)
            self._cursor_offset = 0
            self._selecting = False
            self._needs_compose = False
            self.hook.mark_selecting(False, seq=self._active_event_seq)
            self.hook.mark_composing(True, target, seq=self._active_event_seq)
            self._set_candidates(remaining)
            next_live = self._editor_text_for_index(0)
            self._stable_prefix_text = next_live
            self._stable_kana_prefix = _normalized_kana_prefix(remaining.hiragana)
            if defer_render:
                if target and foreground_window() == target:
                    if self._displayed_cursor < 0:
                        self._sync_editor_display(target, self._displayed_text, 0)
                    if self._displayed_text.startswith(committed_prefix):
                        self._displayed_text = self._displayed_text[len(committed_prefix) :]
                    else:
                        self._sync_editor_display(target, committed_prefix, 0)
                        self._displayed_text = ""
                else:
                    self._displayed_text = ""
                self._displayed_cursor = 0
            else:
                synced = False
                if target:
                    if force_focus and foreground_window() != target:
                        focus_window(target)
                        time.sleep(0.01)
                    if foreground_window() == target:
                        self._sync_editor_display(target, committed_prefix + next_live, 0)
                        synced = True
                self._displayed_text = next_live if synced else ""
                self._displayed_cursor = 0
                self.ui_events.put(("preview", next_live))
                self.ui_events.put(
                    (
                        "candidate_popup",
                        (target, self._candidates, self._candidate_index, self._selecting, self._active_event_seq),
                    )
                )
            return True

        if target:
            if force_focus and foreground_window() != target:
                focus_window(target)
                time.sleep(0.01)
            self._sync_editor_display(target, committed_prefix, 0)
        self.client.clear_text()
        self._reset_state(reset_hook=reset_hook)
        return False

    def _commit_selected_and_continue(self, hwnd: int, *, reset_hook: bool = True) -> None:
        explicit = self._selecting and self._candidate_index > 0
        self._move_cursor_to_end_raw()
        self._finalize_trailing_n()
        suggestion = self._selected_suggestion()
        if (
            suggestion is not None
            and bool(suggestion.subtext)
            and suggestion.corresponding_count > 0
        ):
            self._commit_partial_clause(
                suggestion,
                hwnd,
                defer_render=True,
                explicit=explicit,
                reset_hook=reset_hook,
            )
            return
        reading = self._hiragana
        selected = self._selected_full_text()
        if explicit and reading and selected in self._engine_suggestion_texts:
            self._record_learning(reading, selected)
        if self._target:
            self._sync_editor_display(hwnd, selected, 0)
        self._update_context(selected)
        self.client.clear_text()
        self._hiragana = ""
        self._raw_input = ""
        self._segments.clear()
        self._cursor_offset = 0
        self._displayed_text = ""
        self._displayed_cursor = 0
        self._stable_prefix_text = ""
        self._stable_kana_prefix = ""
        self._needs_compose = False
        self._suggestions = ()
        self._engine_suggestion_texts.clear()
        self._candidates = ()
        self._candidate_index = 0
        self._selecting = False
        self._ascii_direct = False
        if reset_hook:
            self.hook.mark_ascii_direct(False, seq=self._active_event_seq)
        self.hook.mark_selecting(False, seq=self._active_event_seq)
        self.hook.set_visible_candidate_count(0, seq=self._active_event_seq)

    def _handle(self, event: InputEvent) -> None:
        stale_cutoff = max(self._session_seq, self._max_seq)
        if event.seq > 0 and stale_cutoff > event.seq and event.kind in (
            "detach_commit",
            "select_commit",
            "select_page_index",
            "cycle",
            "cycle_page",
            "resize_clause",
            "transliterate",
            "commit",
            "enter_commit",
            "revert_selection",
            "cancel",
        ):
            return
        self._active_event_seq = event.seq
        if event.kind not in ("english", "clear_context", "clear_learning"):
            if event.seq > self._session_seq:
                self._session_seq = event.seq
            if event.seq > self._max_seq:
                self._max_seq = event.seq
        if event.kind == "english":
            if foreground_window() == event.hwnd:
                send_unicode_text(event.char)
            return
        if event.kind == "clear_context":
            self._clear_context()
            return
        if event.kind == "clear_learning":
            with self._learning_lock:
                self._learning_memory.clear()
                _save_learning_memory(self._learning_memory)
            self.ui_events.put(("learning_count", 0))
            return
        if event.kind == "commit":
            self._commit(allow_partial=False)
            return
        if event.kind == "enter_commit":
            if not self._hiragana and not self._displayed_text:
                if foreground_window() == event.hwnd:
                    send_virtual_key(VK_RETURN)
                self._reset_state()
                return
            self._commit(allow_partial=True)
            return
        if event.kind == "detach_commit":
            # The user clicked elsewhere with the mouse or switched focus; the
            # target app has already moved the caret or focus, and the live
            # candidate is already in-place at the old position. Clear engine
            # state without sending Backspaces at the new caret position.
            self.client.clear_text()
            self._clear_context()
            self._reset_state()
            return
        if event.kind == "select_commit":
            try:
                chosen = int(event.char)
            except ValueError:
                self._restore_hook_selection()
                return
            if chosen == 0 and not self._selecting:
                self._finalize_trailing_n()
            else:
                self._ensure_composed()
            if 0 <= chosen < len(self._candidates):
                self._candidate_index = chosen
                self._selecting = True
                self._commit(force_focus=True, allow_partial=True)
            else:
                self._restore_hook_selection()
            return
        if event.kind == "select_page_index":
            try:
                page_offset = int(event.char)
            except ValueError:
                self._restore_hook_selection()
                return
            if not self._selecting:
                self._finalize_trailing_n()
            else:
                self._ensure_composed()
            if self._candidates:
                page_size = min(CandidatePopup.MAX_VISIBLE, len(self._candidates))
                page_start = (self._candidate_index // page_size) * page_size
                chosen = page_start + page_offset
                if 0 <= chosen < len(self._candidates):
                    self._candidate_index = chosen
                    self._selecting = True
                    self._commit(allow_partial=True)
                    return
            self._restore_hook_selection()
            return
        if event.kind == "transliterate":
            self._finalize_trailing_n()
            if self._clear_if_empty():
                return
            mode = event.char
            if self._ascii_direct and mode in ("f6", "f7", "f8"):
                self.hook.mark_selecting(self._selecting, seq=self._active_event_seq)
                return
            if mode == "f6":
                converted = _to_hiragana(self._hiragana)
            elif mode == "f7":
                converted = _to_fullwidth_katakana(self._hiragana)
            elif mode == "f8":
                converted = _to_halfwidth_katakana(self._hiragana)
            elif mode == "f9":
                converted = _to_fullwidth_ascii(self._raw_input or self._hiragana)
            elif mode == "f10":
                converted = self._raw_input or self._hiragana
            else:
                self.hook.mark_selecting(self._selecting, seq=self._active_event_seq)
                return
            if not converted:
                self.hook.mark_selecting(self._selecting, seq=self._active_event_seq)
                return
            choices = list(self._candidates)
            suggestions = list(self._suggestions)
            if converted not in choices:
                choices.insert(0, converted)
                suggestions.insert(
                    0,
                    Suggestion(text=converted, subtext="", corresponding_count=self._engine_count()),
                )
                self._candidates = tuple(choices)
                self._suggestions = tuple(suggestions)
            self._candidate_index = self._candidates.index(converted)
            self._selecting = True
            self.hook.mark_selecting(True, seq=self._active_event_seq)
            self._update_visible_candidate_count()
            self._show(event.hwnd, converted)
            return
        if event.kind == "revert_selection":
            self._selecting = False
            if self._clear_if_empty():
                return
            self.hook.mark_selecting(False, seq=self._active_event_seq)
            self._sync_unselected_popup(event.hwnd)
            return
        if event.kind == "cancel":
            if self._displayed_text and self._target:
                self._sync_editor_display(self._target, "", 0)
            self.client.clear_text()
            self._clear_context()
            self._reset_state()
            return
        if event.kind == "letter":
            if self._target and self._target != event.hwnd:
                self.client.clear_text()
                self._clear_context()
                self._reset_state(reset_hook=False)
                self.hook.mark_ascii_direct(False, seq=self._active_event_seq)
                if event.seq > self._session_seq:
                    self._session_seq = event.seq
            if not self._hiragana and not self._displayed_text and event.hwnd:
                suppress_native_ime(event.hwnd)
            self._target = event.hwnd
            entering_ascii_direct = (
                self._shift_direct_english
                and (not self._ascii_direct or self._selecting)
                and event.char.isascii()
                and event.char.isupper()
            )
            if self._selecting and (self._hiragana or self._displayed_text):
                self._commit_selected_and_continue(event.hwnd, reset_hook=not entering_ascii_direct)
                self._target = event.hwnd
            if entering_ascii_direct:
                if self._hiragana or self._displayed_text:
                    self._commit(allow_partial=False, reset_hook=False)
                if event.seq > self._session_seq:
                    self._session_seq = event.seq
                self._target = event.hwnd
                self._ascii_direct = True
                self.hook.mark_ascii_direct(True, seq=self._active_event_seq)
                self.hook.mark_composing(True, event.hwnd, seq=self._active_event_seq)
            if self._ascii_direct:
                if event.char in _AUTO_COMMIT_CHARS and not event.raw_char:
                    committed = self._raw_input + event.char
                    self._cursor_offset = 0
                    self._sync_editor_display(event.hwnd, committed, 0)
                    self._update_context(committed)
                    self.client.clear_text()
                    self._reset_state()
                    return
                self._selecting = False
                self.hook.mark_selecting(False, seq=self._active_event_seq)
                self._ascii_insert(event.raw_char or event.char)
                while not self._has_pending_event:
                    try:
                        queued = self.events.get_nowait()
                    except queue.Empty:
                        break
                    if (
                        isinstance(queued, InputEvent)
                        and queued.kind == "letter"
                        and queued.hwnd == event.hwnd
                        and queued.completed is None
                        and not (queued.char in _AUTO_COMMIT_CHARS and not queued.raw_char)
                    ):
                        if queued.seq:
                            self._track_event_seq(queued.seq)
                        self._ascii_insert(queued.raw_char or queued.char)
                    else:
                        self._pending_event = queued
                        self._has_pending_event = True
                        break
                self._set_ascii_direct_candidates()
                self._show(event.hwnd, self._raw_input)
                return
            if event.char in _AUTO_COMMIT_CHARS:
                if self._hiragana or self._displayed_text:
                    self._finalize_trailing_n_raw()
                    self._move_cursor_to_end_raw()
                    self._append_letter_raw(event.char, raw_char=event.raw_char)
                    self._compose_current()
                    committed = self._editor_text_for_index(0)
                    self._sync_editor_display(event.hwnd, committed, 0)
                    self._update_context(committed)
                    self.client.clear_text()
                    self._reset_state()
                else:
                    if foreground_window() == event.hwnd:
                        send_unicode_text(event.char)
                    self._update_context(event.char)
                    self._reset_state()
                return
            self._selecting = False
            self.hook.mark_selecting(False, seq=self._active_event_seq)
            self._append_letter_raw(event.char, raw_char=event.raw_char)
            while not self._has_pending_event:
                try:
                    queued = self.events.get_nowait()
                except queue.Empty:
                    break
                if (
                    isinstance(queued, InputEvent)
                    and queued.kind == "letter"
                    and queued.hwnd == event.hwnd
                    and queued.completed is None
                    and queued.char not in _AUTO_COMMIT_CHARS
                    and not (
                        self._shift_direct_english
                        and queued.char.isascii()
                        and queued.char.isupper()
                    )
                ):
                    if queued.seq:
                        self._track_event_seq(queued.seq)
                    self._append_letter_raw(queued.char, raw_char=queued.raw_char)
                else:
                    self._pending_event = queued
                    self._has_pending_event = True
                    break
            if _has_non_n_incomplete_romaji(self._hiragana, self._cursor_offset):
                preview = self._preview_for_incomplete_romaji()
                self._show(event.hwnd, preview)
            else:
                self._compose_current()
                self._show(event.hwnd, self._editor_text_for_index(0))
            return
        if event.kind == "backspace":
            was_selecting = self._selecting or self._candidate_index != 0
            self._selecting = False
            self.hook.mark_selecting(False, seq=self._active_event_seq)
            if not self._target or self._target != event.hwnd or (not self._hiragana and not self._displayed_text):
                self._reset_uncomposed_edit_key(event.hwnd, backspaces=1)
                return
            if not self._hiragana:
                self._reset_uncomposed_edit_key(event.hwnd)
                return
            if self._cursor_offset <= -len(self._hiragana):
                if was_selecting:
                    self._sync_unselected_popup(event.hwnd)
                return
            if self._ascii_direct:
                raw_text = self._ascii_remove_backspace()
                while raw_text and self._cursor_offset > -len(raw_text) and not self._has_pending_event:
                    try:
                        queued = self.events.get_nowait()
                    except queue.Empty:
                        break
                    if (
                        isinstance(queued, InputEvent)
                        and queued.kind == "backspace"
                        and queued.hwnd == event.hwnd
                        and queued.completed is None
                    ):
                        if queued.seq:
                            self._track_event_seq(queued.seq)
                        raw_text = self._ascii_remove_backspace()
                    else:
                        self._pending_event = queued
                        self._has_pending_event = True
                        break
                if not raw_text:
                    if self._displayed_text:
                        self._sync_editor_display(event.hwnd, "", 0)
                    self._reset_state()
                    return
                self._set_ascii_direct_candidates()
                self._show(event.hwnd, raw_text)
                return
            hiragana = self._remove_one_step()
            while hiragana and self._cursor_offset > -len(hiragana) and not self._has_pending_event:
                try:
                    queued = self.events.get_nowait()
                except queue.Empty:
                    break
                if (
                    isinstance(queued, InputEvent)
                    and queued.kind == "backspace"
                    and queued.hwnd == event.hwnd
                    and queued.completed is None
                ):
                    if queued.seq:
                        self._track_event_seq(queued.seq)
                    hiragana = self._remove_one_step()
                else:
                    self._pending_event = queued
                    self._has_pending_event = True
                    break
            if not hiragana:
                if self._displayed_text:
                    self._sync_editor_display(event.hwnd, "", 0)
                self._reset_state()
                return
            if _has_non_n_incomplete_romaji(hiragana, self._cursor_offset):
                preview = self._preview_for_incomplete_romaji()
                self._show(event.hwnd, preview)
            else:
                composition = self._compose_current()
                self._show(event.hwnd, self._editor_text_for_index(0))
                if not composition.hiragana and not composition.suggestions:
                    self._reset_state()
            return
        if event.kind == "delete":
            was_selecting = self._selecting or self._candidate_index != 0
            self._selecting = False
            self.hook.mark_selecting(False, seq=self._active_event_seq)
            if not self._target or self._target != event.hwnd or (not self._hiragana and not self._displayed_text):
                self._reset_uncomposed_edit_key(event.hwnd, forward_vk=VK_DELETE)
                return
            if not self._hiragana:
                self._reset_uncomposed_edit_key(event.hwnd)
                return
            if self._cursor_offset >= 0:
                if was_selecting:
                    self._sync_unselected_popup(event.hwnd)
                return
            if self._ascii_direct:
                raw_text = self._ascii_remove_delete()
                while raw_text and self._cursor_offset < 0 and not self._has_pending_event:
                    try:
                        queued = self.events.get_nowait()
                    except queue.Empty:
                        break
                    if (
                        isinstance(queued, InputEvent)
                        and queued.kind == "delete"
                        and queued.hwnd == event.hwnd
                        and queued.completed is None
                    ):
                        if queued.seq:
                            self._track_event_seq(queued.seq)
                        raw_text = self._ascii_remove_delete()
                    else:
                        self._pending_event = queued
                        self._has_pending_event = True
                        break
                if not raw_text:
                    if self._displayed_text:
                        self._sync_editor_display(event.hwnd, "", 0)
                    self._reset_state()
                    return
                self._set_ascii_direct_candidates()
                self._show(event.hwnd, raw_text)
                return
            hiragana, did_delete = self._delete_one_step()
            while did_delete and hiragana and self._cursor_offset < 0 and not self._has_pending_event:
                try:
                    queued = self.events.get_nowait()
                except queue.Empty:
                    break
                if (
                    isinstance(queued, InputEvent)
                    and queued.kind == "delete"
                    and queued.hwnd == event.hwnd
                    and queued.completed is None
                ):
                    if queued.seq:
                        self._track_event_seq(queued.seq)
                    hiragana, did_delete = self._delete_one_step()
                else:
                    self._pending_event = queued
                    self._has_pending_event = True
                    break
            if not hiragana:
                if self._displayed_text:
                    self._sync_editor_display(event.hwnd, "", 0)
                self._reset_state()
                return
            if _has_non_n_incomplete_romaji(hiragana, self._cursor_offset):
                preview = self._preview_for_incomplete_romaji()
                self._show(event.hwnd, preview)
            else:
                self._compose_current()
                self._show(event.hwnd, self._editor_text_for_index(0))
            return
        if event.kind == "move_cursor":
            was_selecting = self._selecting or self._candidate_index != 0
            self._selecting = False
            self.hook.mark_selecting(False, seq=self._active_event_seq)
            if not self._target or self._target != event.hwnd or not self._hiragana:
                self._reset_uncomposed_edit_key(
                    event.hwnd,
                    forward_vk=_CURSOR_MOVE_NAME_TO_VK.get(event.char),
                )
                return
            if not self._ascii_direct:
                self._finalize_trailing_n_raw()

            def _next_offset(kind: str, current: int, length: int) -> int:
                if kind == "home":
                    return -length
                if kind == "end":
                    return 0
                delta = -1 if kind == "left" else 1
                return max(-length, min(0, current + delta))

            new_offset = _next_offset(event.char, self._cursor_offset, len(self._hiragana))
            while not self._has_pending_event:
                try:
                    queued = self.events.get_nowait()
                except queue.Empty:
                    break
                if (
                    isinstance(queued, InputEvent)
                    and queued.kind == "move_cursor"
                    and queued.hwnd == event.hwnd
                    and queued.completed is None
                ):
                    if queued.seq:
                        self._track_event_seq(queued.seq)
                    new_offset = _next_offset(queued.char, new_offset, len(self._hiragana))
                else:
                    self._pending_event = queued
                    self._has_pending_event = True
                    break

            step = new_offset - self._cursor_offset
            if step != 0:
                if self._ascii_direct:
                    self._cursor_offset = new_offset
                else:
                    self._cursor_offset = new_offset
                    self._move_client_cursor(step, mark_dirty=True)
            if self._ascii_direct:
                if was_selecting:
                    self._set_ascii_direct_candidates()
                self._show(event.hwnd, self._selected_full_text())
                return
            if _has_non_n_incomplete_romaji(self._hiragana, self._cursor_offset):
                preview = self._preview_for_incomplete_romaji()
                self._show(event.hwnd, preview)
            else:
                if self._needs_compose or was_selecting:
                    self._compose_current()
                self._show(event.hwnd, self._selected_full_text())
            return
        if event.kind == "resize_clause":
            if self._clear_if_empty():
                return
            if self._ascii_direct:
                self.hook.mark_selecting(self._selecting, seq=self._active_event_seq)
                return
            self._finalize_trailing_n()
            if self._suggestions:
                current = self._selected_suggestion()
                current_count = current.corresponding_count if current is not None else self._engine_count()
                distinct_counts = sorted(
                    {item.corresponding_count for item in self._suggestions if item.corresponding_count > 0}
                )
                if distinct_counts:
                    if event.char == "shrink":
                        smaller = [count for count in distinct_counts if count < current_count]
                        target_count = smaller[-1] if smaller else distinct_counts[0]
                    else:
                        larger = [count for count in distinct_counts if count > current_count]
                        target_count = larger[0] if larger else distinct_counts[-1]
                    for idx, item in enumerate(self._suggestions):
                        if item.corresponding_count == target_count:
                            self._candidate_index = idx
                            break
                self._selecting = True
                self.hook.mark_selecting(True, seq=self._active_event_seq)
                self._update_visible_candidate_count()
                self._show(event.hwnd, self._editor_text_for_index(self._candidate_index))
                return
            if self._clear_if_empty():
                return
            self.hook.mark_selecting(self._selecting, seq=self._active_event_seq)
            return
        if event.kind == "cycle_page":
            self._finalize_trailing_n()
            if self._candidates:
                self._selecting = True
                self.hook.mark_selecting(True, seq=self._active_event_seq)
                page_size = min(CandidatePopup.MAX_VISIBLE, len(self._candidates))
                total_pages = (len(self._candidates) + page_size - 1) // page_size
                current_page = self._candidate_index // page_size
                delta_page = -1 if event.char == "previous" else 1
                target_page = (current_page + delta_page) % total_pages
                self._candidate_index = target_page * page_size
                self._update_visible_candidate_count()
                self._show(
                    event.hwnd,
                    self._editor_text_for_index(self._candidate_index),
                )
            else:
                if self._clear_if_empty():
                    return
                self._selecting = False
                self.hook.mark_selecting(False, seq=self._active_event_seq)
            return
        if event.kind == "cycle":
            self._finalize_trailing_n()
            if self._candidates:
                was_selecting = self._selecting
                self._selecting = True
                self.hook.mark_selecting(True, seq=self._active_event_seq)
                direction = -1 if event.char == "previous" else 1
                if not was_selecting and self._cursor_offset < 0:
                    self._candidate_index = 0 if direction > 0 else len(self._candidates) - 1
                else:
                    self._candidate_index = (self._candidate_index + direction) % len(self._candidates)
                self._update_visible_candidate_count()
                self._show(
                    event.hwnd,
                    self._editor_text_for_index(self._candidate_index),
                )
            else:
                if self._clear_if_empty():
                    return
                self._selecting = False
                self.hook.mark_selecting(False, seq=self._active_event_seq)

    def _set_candidates(self, composition: Composition) -> None:
        self._hiragana = composition.hiragana
        total_count = self._engine_count()
        raw_suggestions = [item for item in composition.suggestions if item.text]
        self._engine_suggestion_texts = {item.text for item in raw_suggestions}
        with self._learning_lock:
            preferred = self._learning_memory.get(composition.hiragana)
        if preferred:
            for idx, item in enumerate(raw_suggestions):
                if item.text == preferred and not item.subtext:
                    if idx > 0:
                        raw_suggestions.insert(0, raw_suggestions.pop(idx))
                    break
        suggestions: list[Suggestion] = []
        choices: list[str] = []
        for item in raw_suggestions:
            if item.text not in choices:
                suggestions.append(item)
                choices.append(item.text)
        if composition.hiragana and composition.hiragana not in choices:
            suggestions.append(
                Suggestion(
                    text=composition.hiragana,
                    subtext="",
                    corresponding_count=total_count,
                )
            )
            choices.append(composition.hiragana)
        if composition.hiragana and not _has_incomplete_romaji(composition.hiragana):
            katakana = _to_fullwidth_katakana(composition.hiragana)
            if katakana and katakana not in choices:
                suggestions.append(
                    Suggestion(
                        text=katakana,
                        subtext="",
                        corresponding_count=total_count,
                    )
                )
                choices.append(katakana)
        if self._raw_input and all(ch.isascii() and ch.isprintable() for ch in self._raw_input):
            if self._raw_input not in choices:
                suggestions.append(
                    Suggestion(
                        text=self._raw_input,
                        subtext="",
                        corresponding_count=total_count,
                    )
                )
                choices.append(self._raw_input)
            fullwidth_raw = _to_fullwidth_ascii(self._raw_input)
            if fullwidth_raw and fullwidth_raw not in choices:
                suggestions.append(
                    Suggestion(
                        text=fullwidth_raw,
                        subtext="",
                        corresponding_count=total_count,
                    )
                )
                choices.append(fullwidth_raw)
        self._suggestions = tuple(suggestions)
        self._candidates = tuple(choices)
        self._candidate_index = 0
        self._update_visible_candidate_count()

    def _selected_suggestion(self) -> Suggestion | None:
        if self._suggestions and 0 <= self._candidate_index < len(self._suggestions):
            return self._suggestions[self._candidate_index]
        return None

    def _editor_text_for_index(self, index: int) -> str:
        if self._suggestions and 0 <= index < len(self._suggestions):
            item = self._suggestions[index]
            return item.text + item.subtext
        if self._candidates and 0 <= index < len(self._candidates):
            return self._candidates[index]
        return self._hiragana

    def _show(self, hwnd: int, text: str, *, allow_incomplete: bool = True) -> None:
        if foreground_window() != hwnd:
            self.client.clear_text()
            self._clear_context()
            self._reset_state()
            return
        if allow_incomplete or not _has_incomplete_romaji(self._hiragana):
            if not self._selecting and self._cursor_offset < 0 and self._hiragana:
                editor_text = self._hiragana
                editor_cursor = max(-len(self._hiragana), self._cursor_offset)
            else:
                editor_text = text
                editor_cursor = 0
            self._sync_editor_display(hwnd, editor_text, editor_cursor)
        self.ui_events.put(("preview", text))
        self.ui_events.put(
            ("candidate_popup", (hwnd, self._candidates, self._candidate_index, self._selecting, self._active_event_seq))
        )

    def _commit(
        self,
        *,
        force_focus: bool = False,
        allow_partial: bool = False,
        reset_hook: bool = True,
    ) -> None:
        explicit = self._selecting and self._candidate_index > 0
        self._move_cursor_to_end_raw()
        self._finalize_trailing_n()
        target = self._target
        suggestion = self._selected_suggestion()
        if (
            allow_partial
            and suggestion is not None
            and bool(suggestion.subtext)
            and suggestion.corresponding_count > 0
        ):
            self._commit_partial_clause(
                suggestion,
                target,
                force_focus=force_focus,
                defer_render=False,
                explicit=explicit,
            )
            return

        reading = self._hiragana
        selected = self._selected_full_text()
        if explicit and reading and selected in self._engine_suggestion_texts:
            self._record_learning(reading, selected)
        if target:
            if force_focus and foreground_window() != target:
                focus_window(target)
                time.sleep(0.01)
            self._sync_editor_display(target, selected, 0)
        self._update_context(selected)
        self.client.clear_text()
        self._reset_state(reset_hook=reset_hook)

    def _selected_text(self) -> str:
        if self._candidates and 0 <= self._candidate_index < len(self._candidates):
            return self._candidates[self._candidate_index]
        return self._hiragana

    def _selected_full_text(self) -> str:
        return self._editor_text_for_index(self._candidate_index)

    def _reset_state(self, *, reset_hook: bool = True) -> None:
        self._target = 0
        self._hiragana = ""
        self._raw_input = ""
        self._segments.clear()
        self._cursor_offset = 0
        self._displayed_text = ""
        self._displayed_cursor = 0
        self._stable_prefix_text = ""
        self._stable_kana_prefix = ""
        self._needs_compose = False
        self._suggestions = ()
        self._engine_suggestion_texts.clear()
        self._candidates = ()
        self._candidate_index = 0
        self._selecting = False
        self._ascii_direct = False
        self._session_seq = 0
        if reset_hook:
            clear_if_current = getattr(self.hook, "clear_composing_if_current", None)
            if callable(clear_if_current):
                clear_if_current(self._active_event_seq)
            else:
                self.hook.set_visible_candidate_count(0)
                self.hook.mark_ascii_direct(False)
                self.hook.mark_selecting(False)
                self.hook.mark_composing(False)
        self.ui_events.put(("preview", ""))
        self.ui_events.put(("candidate_popup", None))

    def _sync_unselected_popup(self, hwnd: int) -> None:
        if self._ascii_direct and self._raw_input:
            self._set_ascii_direct_candidates()
            self._show(hwnd, self._selected_full_text())
        elif self._hiragana:
            if _has_non_n_incomplete_romaji(self._hiragana, self._cursor_offset):
                preview = self._preview_for_incomplete_romaji()
                self._show(hwnd, preview)
            else:
                self._compose_current()
                self._show(hwnd, self._selected_full_text())

    def _reset_uncomposed_edit_key(
        self,
        hwnd: int,
        *,
        forward_vk: int | None = None,
        backspaces: int = 0,
    ) -> None:
        mismatch = not self._target or self._target != hwnd
        if not mismatch and self._displayed_text:
            self._sync_editor_display(hwnd, "", 0)
        elif foreground_window() == hwnd:
            if backspaces > 0:
                send_backspaces(backspaces)
            elif forward_vk is not None:
                send_virtual_key(forward_vk)
        if mismatch:
            self.client.clear_text()
            self._clear_context()
        self._reset_state()


def _scale_px(value: int, dpi: int) -> int:
    return max(1, round(value * max(72, dpi) / 96.0))


def _window_hwnds(window: tk.Misc | None) -> set[int]:
    if window is None:
        return set()
    hwnds: set[int] = set()
    try:
        inner = int(window.winfo_id())
    except (tk.TclError, TypeError, ValueError):
        return hwnds
    if inner:
        hwnds.add(inner)
        top = root_window_hwnd(inner)
        if top:
            hwnds.add(top)
    return hwnds


def _top_window_hwnd(window: tk.Misc | None) -> int:
    if window is None:
        return 0
    try:
        inner = int(window.winfo_id())
    except (tk.TclError, TypeError, ValueError):
        return 0
    return root_window_hwnd(inner) if inner else 0


def _geometry_spec(width: int, height: int, x: int, y: int) -> str:
    # Always prefix x and y with '+' so negative multi-monitor coordinates
    # (for example '+-400+-120') are not parsed by Tcl/Tk as right-edge offsets.
    return f"{width}x{height}+{x}+{y}"


class CandidatePopup:
    """A non-activating candidate list positioned by the target text caret."""

    MAX_VISIBLE = 6

    def __init__(self, root: tk.Tk, on_select=None, on_scroll=None, scale: str = "normal") -> None:
        self.target = 0
        self.on_select = on_select
        self.on_scroll = on_scroll
        self.scale = scale if scale in UI_SCALES else "normal"
        self._anchor_hwnd = 0
        self._anchor_position: tuple[int, int, int, int, int, int] | None = None
        self._shown_seq = 0
        self._last_args: tuple[int, tuple[str, ...], int, bool, tuple[int, int] | None, int] | None = None
        self.window = tk.Toplevel(root)
        self.window.withdraw()
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        self.window.focusmodel("passive")
        theme = system_theme_palette()
        self.panel = tk.Frame(
            self.window,
            bg=theme["popup_bg"],
            bd=0,
            highlightthickness=2,
            highlightbackground=theme["popup_border"],
            highlightcolor=theme["popup_border"],
        )
        self.panel.pack(fill="both", expand=True)
        self.window.bind("<MouseWheel>", self._on_mouse_wheel)
        self.panel.bind("<MouseWheel>", self._on_mouse_wheel)
        self.window.update_idletasks()
        make_popup_no_activate(int(self.window.winfo_id()))

    def set_scale(self, scale: str) -> None:
        if scale not in UI_SCALES:
            return
        self.scale = scale
        if self.target and self._last_args is not None:
            hwnd, candidates, selected_index, selecting, fallback_point, shown_seq = self._last_args
            self.show(
                hwnd,
                candidates,
                selected_index,
                selecting=selecting,
                fallback_point=fallback_point,
                shown_seq=shown_seq,
            )

    def contains_point(self, x: int, y: int) -> bool:
        if not self.target:
            return False
        try:
            return window_contains_point(int(self.window.winfo_id()), x, y)
        except tk.TclError:
            return False

    def _resolve_position(
        self,
        hwnd: int,
        fallback_point: tuple[int, int] | None,
    ) -> tuple[int, int, int, int, int, int] | None:
        if has_hardware_caret(hwnd):
            pos = text_cursor_position(hwnd)
            if pos is not None:
                self._anchor_hwnd = hwnd
                self._anchor_position = pos
                return pos
        if self._anchor_hwnd == hwnd and self._anchor_position is not None:
            return self._anchor_position
        pos = text_cursor_position(hwnd, fallback_point=fallback_point)
        if pos is not None:
            self._anchor_hwnd = hwnd
            self._anchor_position = pos
        return pos

    def show(
        self,
        hwnd: int,
        candidates: tuple[str, ...],
        selected_index: int,
        *,
        selecting: bool = False,
        fallback_point: tuple[int, int] | None = None,
        shown_seq: int = 0,
    ) -> None:
        own_hwnds = _window_hwnds(self.window)
        fg = foreground_window()
        if not hwnd or not candidates or (fg != hwnd and fg not in own_hwnds):
            self.hide()
            return
        position = self._resolve_position(hwnd, fallback_point)
        if position is None:
            self.hide()
            return

        effective_seq = (
            max(self._shown_seq, shown_seq)
            if (self.target == hwnd and shown_seq > 0 and self._shown_seq > 0)
            else shown_seq
        )
        self.target = hwnd
        self._shown_seq = effective_seq
        self._last_args = (hwnd, candidates, selected_index, selecting, fallback_point, effective_seq)
        metrics = UI_SCALES[self.scale]
        ts = _text_scale_multiplier()
        theme = system_theme_palette()
        caret_x, caret_y, left, top, right, bottom = position
        dpi = dpi_for_point(caret_x, caret_y)
        work_max_w = max(240, right - left - 16)
        min_width = min(work_max_w, _scale_px(round(metrics["popup_min_width"] * ts), dpi))
        max_width = min(work_max_w, max(min_width, _scale_px(round(metrics["popup_max_width"] * ts), dpi)))
        padx = _scale_px(round(metrics["popup_padx"] * ts), dpi)
        pady = _scale_px(round(metrics["popup_pady"] * ts), dpi)
        content_wrap = max(120, max_width - padx * 2 - 8)
        header_pt = max(9, round(metrics["popup_header_font"] * ts))
        item_pt = max(10, round(metrics["popup_item_font"] * ts))

        self.panel.configure(
            bg=theme["popup_bg"],
            highlightthickness=max(2, _scale_px(2, dpi)),
            highlightbackground=theme["popup_border"],
            highlightcolor=theme["popup_border"],
        )
        total = len(candidates)
        selected_index = max(0, min(selected_index, total - 1))
        page_size = min(self.MAX_VISIBLE, total)
        page_start = (selected_index // page_size) * page_size
        page_end = min(total, page_start + page_size)
        visible_count = page_end - page_start

        for child in self.panel.winfo_children():
            child.destroy()

        hint = (
            f"1-{visible_count}キー / Enter / クリックで確定"
            if selecting
            else "Space・↑↓・ホイールで選択 / クリックで確定"
        )
        header_text = f"変換中 {selected_index + 1}/{total}  ({hint})"
        header = tk.Label(
            self.panel,
            text=header_text,
            anchor="w",
            justify="left",
            wraplength=content_wrap,
            bg=theme["header_bg"],
            fg=theme["header_fg"],
            font=("Yu Gothic UI", header_pt, "bold"),
            padx=padx,
            pady=max(2, pady - 1),
        )
        header.pack(fill="x")
        header.bind("<MouseWheel>", self._on_mouse_wheel)
        divider = tk.Frame(self.panel, height=1, bg=theme["popup_border"])
        divider.pack(fill="x")

        for index in range(page_start, page_end):
            selected = index == selected_index
            slot = index - page_start + 1
            prefix = f"▸ {slot}. " if selected else f"   {slot}. "
            base_bg = theme["selected_bg"] if selected else theme["popup_bg"]
            base_fg = theme["selected_fg"] if selected else theme["item_fg"]
            row = tk.Label(
                self.panel,
                text=f"{prefix}{candidates[index]}",
                anchor="w",
                justify="left",
                wraplength=content_wrap,
                bg=base_bg,
                fg=base_fg,
                font=("Yu Gothic UI", item_pt, "bold" if selected else "normal"),
                padx=padx,
                pady=pady,
                cursor="hand2",
            )
            row.pack(fill="x")
            row.bind("<Button-1>", lambda _event, idx=index: self._on_row_click(idx))
            row.bind("<MouseWheel>", self._on_mouse_wheel)
            if not selected:
                hover_bg = theme["hover_bg"]
                hover_fg = theme["hover_fg"]
                row.bind("<Enter>", lambda _event, widget=row, bg=hover_bg, fg=hover_fg: widget.configure(bg=bg, fg=fg))
                row.bind("<Leave>", lambda _event, widget=row, bg=base_bg, fg=base_fg: widget.configure(bg=bg, fg=fg))

        self.window.update_idletasks()
        width = max(
            min_width,
            min(max_width, self.window.winfo_reqwidth()),
        )
        height = self.window.winfo_reqheight()
        x = caret_x + 2
        y = caret_y + 5
        if y + height > bottom - 4:
            y = caret_y - height - 6
        if x + width > right - 4:
            x = right - width - 4
        x = max(left + 4, x)
        y = max(top + 4, y)
        self.window.geometry(_geometry_spec(width, height, x, y))
        self.window.deiconify()
        self.window.update_idletasks()
        try:
            position_popup_no_activate(_top_window_hwnd(self.window), x, y, width, height)
        except OSError:
            pass

    def _on_row_click(self, index: int) -> None:
        if self.on_select is not None:
            self.on_select(index)

    def _on_mouse_wheel(self, event: tk.Event) -> str:
        delta = int(getattr(event, "delta", 0) or 0)
        if delta != 0 and self.on_scroll is not None:
            self.on_scroll("next" if delta < 0 else "previous")
        return "break"

    def hide(self) -> None:
        self.target = 0
        self._shown_seq = 0
        self._anchor_hwnd = 0
        self._anchor_position = None
        self._last_args = None
        try:
            self.window.withdraw()
        except tk.TclError:
            pass

    def hide_if_focus_moved(self) -> None:
        if not self.target:
            return
        fg = foreground_window()
        own_hwnds = _window_hwnds(self.window)
        if fg != self.target and fg not in own_hwnds:
            self.hide()


class CornerToggle:
    """Always-on-top, non-activating, draggable live-conversion switch."""

    def __init__(
        self,
        root: tk.Tk,
        command,
        *,
        on_position_change=None,
        anchor_resolver=None,
        custom_position: tuple[int, int] | None = None,
        default_position: tuple[int, int] | None = DEFAULT_TOGGLE_POSITION,
        scale: str = "normal",
    ) -> None:
        self.root = root
        self.command = command
        self.on_position_change = on_position_change
        self.anchor_resolver = anchor_resolver
        self.custom_position = custom_position
        self.default_position = default_position
        self.scale = scale if scale in UI_SCALES else "normal"
        self._enabled = False
        self._available = False
        self._blocked = False
        self._current_dpi = 96
        self._drag_start_root = (0, 0)
        self._drag_start_win = (0, 0)
        self._dragged = False
        self._reposition_failed = False

        self.window = tk.Toplevel(root)
        self.window.withdraw()
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        self.window.focusmodel("passive")

        theme = system_theme_palette()
        self.button = tk.Button(
            self.window,
            text="○ ライブ変換 OFF",
            takefocus=False,
            relief="flat",
            bd=0,
            highlightthickness=2,
            highlightbackground=theme["popup_border"],
            highlightcolor=theme["popup_border"],
            font=("Yu Gothic UI", max(9, round(UI_SCALES[self.scale]["toggle_font"] * _text_scale_multiplier())), "bold"),
            bg=theme["toggle_off_bg"],
            activebackground=theme["toggle_active_bg"],
            fg=theme["toggle_off_fg"],
            disabledforeground=theme["toggle_disabled_fg"],
            padx=7,
            pady=3,
            cursor="hand2",
        )
        self.button.pack(fill="both", expand=True)
        self.button.bind("<ButtonPress-1>", self._on_press)
        self.button.bind("<B1-Motion>", self._on_drag)
        self.button.bind("<ButtonRelease-1>", self._on_left_release)
        self.button.bind("<ButtonPress-3>", self._on_press)
        self.button.bind("<B3-Motion>", self._on_drag)
        self.button.bind("<ButtonRelease-3>", self._on_right_release)
        self.button.bind("<Double-Button-3>", self._on_reset_gesture)

        width, height = self._dimensions()
        self.window.geometry(f"{width}x{height}")
        self.window.update_idletasks()
        make_popup_no_activate(int(self.window.winfo_id()))
        self.update(enabled=False, available=False)

    def _dimensions(self, dpi: int | None = None) -> tuple[int, int]:
        active_dpi = self._current_dpi if dpi is None else dpi
        metrics = UI_SCALES[self.scale]
        ts = _text_scale_multiplier()
        return (
            _scale_px(round(metrics["toggle_width"] * ts), active_dpi),
            _scale_px(round(metrics["toggle_height"] * ts), active_dpi),
        )

    def contains_point(self, x: int, y: int) -> bool:
        try:
            return window_contains_point(int(self.window.winfo_id()), x, y)
        except tk.TclError:
            return False

    def set_scale(self, scale: str) -> None:
        if scale not in UI_SCALES:
            return
        self.scale = scale
        self.button.configure(
            font=("Yu Gothic UI", max(9, round(UI_SCALES[self.scale]["toggle_font"] * _text_scale_multiplier())), "bold")
        )
        self.update(enabled=self._enabled, available=self._available, blocked=self._blocked)

    def reset_position(self) -> None:
        self.custom_position = None
        if self.on_position_change is not None:
            self.on_position_change(None)
        self.update(enabled=self._enabled, available=self._available, blocked=self._blocked)

    def _on_press(self, event: tk.Event) -> str:
        self._drag_start_root = (int(event.x_root), int(event.y_root))
        self._drag_start_win = (int(self.window.winfo_x()), int(self.window.winfo_y()))
        self._dragged = False
        return "break"

    def _on_drag(self, event: tk.Event) -> str:
        dx = int(event.x_root) - self._drag_start_root[0]
        dy = int(event.y_root) - self._drag_start_root[1]
        if not self._dragged and abs(dx) <= 4 and abs(dy) <= 4:
            return "break"
        self._dragged = True
        dpi = dpi_for_point(self._drag_start_win[0] + dx, self._drag_start_win[1] + dy)
        self._current_dpi = dpi
        width, height = self._dimensions(dpi)
        new_x, new_y = clamp_to_monitor_work_area(
            self._drag_start_win[0] + dx,
            self._drag_start_win[1] + dy,
            width,
            height,
        )
        self.custom_position = (new_x, new_y)
        self.window.geometry(_geometry_spec(width, height, new_x, new_y))
        try:
            position_popup_no_activate(int(self.window.winfo_id()), new_x, new_y, width, height)
        except OSError:
            pass
        return "break"

    def _on_left_release(self, event: tk.Event) -> str:
        if self._dragged:
            self._dragged = False
            if self.on_position_change is not None and self.custom_position is not None:
                self.on_position_change(self.custom_position)
            return "break"
        base_w, base_h = self._dimensions()
        width = max(base_w, int(self.button.winfo_width() or 0))
        height = max(base_h, int(self.button.winfo_height() or 0))
        if self._available and 0 <= int(event.x) <= width and 0 <= int(event.y) <= height:
            self.command()
        return "break"

    def _on_right_release(self, _event: tk.Event) -> str:
        if self._dragged:
            self._dragged = False
            if self.on_position_change is not None and self.custom_position is not None:
                self.on_position_change(self.custom_position)
        return "break"

    def _on_reset_gesture(self, _event: tk.Event) -> str:
        self.reset_position()
        return "break"

    def update(self, enabled: bool, available: bool, *, blocked: bool = False) -> None:
        self._enabled = enabled
        self._available = available
        self._blocked = blocked
        anchor_hwnd = (
            self.anchor_resolver()
            if self.anchor_resolver is not None
            else _top_window_hwnd(self.root)
        )
        active_pos = self.custom_position if self.custom_position is not None else self.default_position
        if active_pos is not None:
            dpi = dpi_for_point(active_pos[0], active_pos[1])
        else:
            dpi = dpi_for_window(anchor_hwnd)
        self._current_dpi = dpi
        width, height = self._dimensions(dpi)
        ts = _text_scale_multiplier()
        theme = system_theme_palette()
        border_px = max(2, _scale_px(1, dpi))
        toggle_font = ("Yu Gothic UI", max(9, round(UI_SCALES[self.scale]["toggle_font"] * ts)), "bold")
        common_cfg = {
            "font": toggle_font,
            "highlightthickness": border_px,
            "highlightbackground": theme["popup_border"],
            "highlightcolor": theme["popup_border"],
            "activebackground": theme["toggle_active_bg"],
            "disabledforeground": theme["toggle_disabled_fg"],
            "padx": _scale_px(round(8 * ts), dpi),
            "pady": _scale_px(round(4 * ts), dpi),
        }
        if available and blocked and enabled:
            self.button.configure(
                text="⚠ 管理者アプリ(無効)",
                state="normal",
                bg=theme["toggle_warn_bg"],
                fg=theme["toggle_warn_fg"],
                **common_cfg,
            )
        elif available:
            text = f"{'●' if enabled else '○'} ライブ変換 {'ON' if enabled else 'OFF'}"
            self.button.configure(
                text=text,
                state="normal",
                bg=theme["toggle_on_bg"] if enabled else theme["toggle_off_bg"],
                fg=theme["toggle_on_fg"] if enabled else theme["toggle_off_fg"],
                **common_cfg,
            )
        else:
            self.button.configure(
                text="○ ライブ変換 OFF",
                state="disabled",
                bg=theme["toggle_disabled_bg"],
                fg=theme["toggle_disabled_fg"],
                **common_cfg,
            )

        self.window.update_idletasks()
        width = max(width, int(self.button.winfo_reqwidth()) + _scale_px(6, dpi))
        height = max(height, int(self.button.winfo_reqheight()) + _scale_px(4, dpi))
        if active_pos is not None:
            x, y = clamp_to_monitor_work_area(
                int(active_pos[0]),
                int(active_pos[1]),
                width,
                height,
            )
            if self.custom_position is not None:
                self.custom_position = (x, y)
        else:
            x, y = taskbar_toggle_position(anchor_hwnd, width, height)
        self.window.geometry(_geometry_spec(width, height, x, y))
        self.window.deiconify()
        try:
            position_popup_no_activate(int(self.window.winfo_id()), x, y, width, height)
            self._reposition_failed = False
        except OSError:
            self._reposition_failed = True

    def close(self) -> None:
        try:
            self.window.destroy()
        except tk.TclError:
            pass


def _dispose_session(
    runtime: AzooKeyRuntime | None,
    worker: CompositionWorker | None,
    hook: KeyboardHook | None,
    *,
    commit_pending: bool = False,
) -> None:
    if hook is not None:
        try:
            hook.set_active(False)
            hook.stop()
        except Exception:
            pass
    if worker is not None:
        try:
            if commit_pending:
                worker.submit(InputEvent("commit", 0))
            worker.close()
        except Exception:
            pass
    if runtime is not None:
        try:
            runtime.close()
        except Exception:
            pass


class AzooKeyLiveBridge:
    def __init__(self, root: tk.Tk, *, mutex_handle: int | None = None) -> None:
        self.root = root
        self._mutex_handle = mutex_handle
        self._closed = False
        self._lifecycle_lock = threading.Lock()
        self.root.title(f"{APP_NAME} 設定画面")
        self.root.update_idletasks()
        hwnd = int(self.root.winfo_id())
        self._root_dpi = dpi_for_window(hwnd)
        work_left, work_top, work_right, work_bottom = monitor_work_area(hwnd)
        work_w = max(480, work_right - work_left - _scale_px(24, self._root_dpi))
        work_h = max(360, work_bottom - work_top - _scale_px(24, self._root_dpi))
        init_w = min(work_w, _scale_px(720, self._root_dpi))
        init_h = min(work_h, _scale_px(780, self._root_dpi))
        min_w = min(work_w, _scale_px(440, self._root_dpi))
        min_h = min(work_h, _scale_px(360, self._root_dpi))
        self.root.geometry(f"{init_w}x{init_h}")
        self.root.minsize(min_w, min_h)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close_requested)

        self.settings = _load_settings()
        self.runtime: AzooKeyRuntime | None = None
        self.worker: CompositionWorker | None = None
        self.hook: KeyboardHook | None = None
        self.ui_events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.enabled = False
        self.starting = False
        self._loaded_engine_dir = ""
        self._loaded_backend = ""
        self._loaded_requested_backend = ""
        self._path_refresh_after_id: str | None = None
        self._zenzai_refresh_after_id: str | None = None
        self._zenzai_profile_dirty = False
        self._poll_after_id: str | None = None
        self._copy_feedback_after_id: str | None = None
        self._start_zenzai_snapshot: tuple[bool, str] | None = None
        self._was_mouse_down = False
        self._last_click_target: tuple[int, int, int] | None = None
        self._blocked_by_uipi = False
        self._last_toggle_signature: tuple[object, ...] | None = None
        self._last_tray_signature: tuple[object, ...] | None = None
        self._last_settings_theme_sig: tuple[bool, bool, str, float] | None = None
        self._cached_os_theme_sig: tuple[bool, bool] | None = None
        self._cached_os_text_scale: float = 1.0
        self._last_os_theme_check: float = 0.0
        self._pending_disable_passthrough: tuple[threading.Event, int, bool] | None = None

        self._style = ttk.Style(self.root)
        self._wrapped_labels: list[tuple[ttk.Label, int]] = []
        self._entry_widgets: list[ttk.Entry] = []
        self._last_canvas_width = max(360, init_w - _scale_px(28, self._root_dpi))
        self._current_wrap = -1
        self._last_backend_wide: bool | None = None
        self._last_backend_pending: bool | None = None
        self._last_title_wide: bool | None = None
        self._last_learning_wide: bool | None = None
        self._last_action_bar_mode: int | None = None
        self._ui_ready = False
        self._active_section_idx = -1
        self._syncing_scrollregion = False
        self._scale_bar_focused = False
        self._scale_bar_hover = False
        self._hovered_scale_idx: int | None = None
        self._scale_bar_x_stops: tuple[float, float, float] = (20.0, 150.0, 280.0)
        self._current_settings_theme: dict[str, str] | None = None
        self._check_indicator_images: dict[str, tk.PhotoImage] = {}
        self._check_indicator_sig: tuple[object, ...] | None = None
        self._section_targets: list[tuple[ttk.Frame, tk.Widget]] = []
        self._section_meta: dict[ttk.Frame, tuple[ttk.Frame, ttk.Label]] = {}
        self._learning_window: tk.Toplevel | None = None
        self._learning_viewer_widgets: dict[str, tk.Widget] = {}
        self._learning_search_var: tk.StringVar | None = None
        self._learning_summary_var: tk.StringVar | None = None
        self._learning_viewer_feedback_var: tk.StringVar | None = None
        self._learning_sort_col = "order"
        self._learning_sort_desc = True
        self._learning_iid_map: dict[str, tuple[int, str, str]] = {}
        self._learning_feedback_after_id: str | None = None

        saved_scale = self.settings.get("ui_scale", "normal")
        had_saved_toggle_pos = bool(
            self.settings.get("toggle_x", "").strip()
            or self.settings.get("toggle_y", "").strip()
        )

        self._build_ui(saved_scale)
        self.candidate_popup = CandidatePopup(
            root,
            on_select=self._on_candidate_clicked,
            on_scroll=self._on_candidate_scrolled,
            scale=saved_scale,
        )
        self.corner_toggle = CornerToggle(
            root,
            self._toggle,
            on_position_change=self._on_toggle_moved,
            anchor_resolver=self._toggle_anchor_hwnd,
            custom_position=None,
            default_position=DEFAULT_TOGGLE_POSITION,
            scale=saved_scale,
        )
        self.tray_icon = SystemTrayIcon(self.ui_events)
        self.tray_icon.start()
        self._refresh_tray_controls()
        self._refresh_status_and_indicators(force=True)
        if had_saved_toggle_pos:
            self._persist_current_settings()
        self._poll_ui()
        if (
            self.settings.get("start_minimized", "0") == "1"
            and self.settings.get("minimize_to_tray", "1") != "0"
            and self.tray_icon.active
            and self.engine_path.get().strip()
        ):
            self._hide_to_tray()
        if self.engine_path.get().strip():
            self._start()

    def _persist_current_settings(self) -> None:
        _save_settings(
            {
                "engine_dir": self.engine_path.get().strip(),
                "ui_scale": self.ui_scale_var.get(),
                "toggle_x": "",
                "toggle_y": "",
                "english_passthrough": "1" if self.english_passthrough_var.get() else "0",
                "fullwidth_space": "1" if self.fullwidth_space_var.get() else "0",
                "shift_direct_english": "1" if self.shift_direct_english_var.get() else "0",
                "minimize_to_tray": "1" if self.minimize_to_tray_var.get() else "0",
                "start_minimized": "1" if self.start_minimized_var.get() else "0",
                "use_zenzai": "1" if self.use_zenzai_var.get() else "0",
                "zenzai_profile": self.zenzai_profile_var.get().strip(),
                "zenzai_backend": self.zenzai_backend_var.get(),
            }
        )

    def _settings_metrics(self) -> dict[str, int]:
        scale = self.ui_scale_var.get() if hasattr(self, "ui_scale_var") else "normal"
        raw = UI_SCALES.get(scale, UI_SCALES["normal"])
        text_scale = _text_scale_multiplier()
        return {
            "title_font": max(12, round(raw["settings_title_font"] * text_scale)),
            "heading_font": max(9, round(raw["settings_heading_font"] * text_scale)),
            "body_font": max(9, round(raw["settings_body_font"] * text_scale)),
            "caption_font": max(8, round(raw["settings_caption_font"] * text_scale)),
            "indicator_px": _scale_px(round(raw["settings_indicator_px"] * text_scale), self._root_dpi),
            "pad": _scale_px(raw["settings_pad"], self._root_dpi),
        }

    @staticmethod
    def _set_button_label(button: ttk.Button, text: str) -> None:
        button.configure(text=text, underline=-1)

    def _bind_focus_scroll(self, widget: tk.Widget) -> None:
        widget.bind("<FocusIn>", lambda _e, w=widget: self._ensure_widget_visible(w), add="+")

    @staticmethod
    def _select_all_entry(entry: ttk.Entry) -> str:
        try:
            entry.selection_range(0, "end")
            entry.icursor("end")
        except tk.TclError:
            pass
        return "break"

    def _bind_entry_shortcuts(self, entry: ttk.Entry) -> None:
        entry.bind("<Control-a>", lambda _e, w=entry: self._select_all_entry(w))
        entry.bind("<Control-A>", lambda _e, w=entry: self._select_all_entry(w))

    def _bind_label_target(self, label: ttk.Label, target: object) -> None:
        try:
            label.configure(cursor="hand2")
        except tk.TclError:
            pass

        def _focus_target(_event: tk.Event | None = None) -> str:
            if callable(target) and not isinstance(target, tk.Widget):
                target()
                return "break"
            if isinstance(target, tk.Widget):
                try:
                    self._ensure_widget_visible(target)
                    target.focus_set()
                    if isinstance(target, ttk.Entry):
                        target.selection_range(0, "end")
                except tk.TclError:
                    pass
            return "break"

        label.bind("<Button-1>", _focus_target)

    def _focus_selected_backend_radio(self) -> None:
        radios = getattr(self, "_backend_radios", ())
        chosen = self.zenzai_backend_var.get() if hasattr(self, "zenzai_backend_var") else ""
        target = next((rb for rb in radios if rb.cget("value") == chosen), radios[0] if radios else None)
        if target is not None:
            try:
                self._ensure_widget_visible(target)
                target.focus_set()
            except tk.TclError:
                pass

    def _make_button(
        self,
        parent: tk.Misc,
        text: str,
        command,
        *,
        style: str = "Settings.TButton",
        state: str = "normal",
    ) -> ttk.Button:
        button = ttk.Button(parent, text=text, command=command, style=style, state=state)
        button.bind("<Return>", lambda _e, b=button: self._invoke_button_event(b))
        button.bind("<KP_Enter>", lambda _e, b=button: self._invoke_button_event(b))
        self._bind_focus_scroll(button)
        return button

    @staticmethod
    def _invoke_button_event(button: ttk.Button) -> str:
        try:
            if str(button.cget("state")) != "disabled":
                button.invoke()
        except tk.TclError:
            pass
        return "break"

    def _make_checkbutton(
        self,
        parent: tk.Misc,
        text: str,
        variable: tk.BooleanVar,
        command,
    ) -> ttk.Checkbutton:
        check = ttk.Checkbutton(
            parent,
            text=text,
            variable=variable,
            command=command,
            style="Wrap.TCheckbutton",
        )
        check.bind("<Return>", lambda _e, c=check: self._invoke_button_event(c))
        check.bind("<KP_Enter>", lambda _e, c=check: self._invoke_button_event(c))
        self._bind_focus_scroll(check)
        return check

    def _make_wrapped_label(
        self,
        parent: tk.Misc,
        *,
        text: str = "",
        textvariable: tk.StringVar | None = None,
        style: str = "Card.TLabel",
        extra_inset_px: int = 44,
    ) -> ttk.Label:
        kwargs: dict[str, object] = {
            "style": style,
            "justify": "left",
            "anchor": "w",
        }
        if textvariable is not None:
            kwargs["textvariable"] = textvariable
        else:
            kwargs["text"] = text
        label = ttk.Label(parent, **kwargs)
        self._wrapped_labels.append((label, extra_inset_px))
        return label

    def _bind_radio_group(self, radios: list[ttk.Radiobutton]) -> None:
        if not radios:
            return
        for idx, radio in enumerate(radios):
            self._bind_focus_scroll(radio)

            def _move_to(target_idx: int) -> str:
                target = radios[target_idx % len(radios)]
                try:
                    if str(target.cget("state")) != "disabled":
                        target.focus_set()
                        target.invoke()
                except tk.TclError:
                    pass
                return "break"

            radio.bind("<Left>", lambda _e, i=idx - 1: _move_to(i))
            radio.bind("<Up>", lambda _e, i=idx - 1: _move_to(i))
            radio.bind("<Right>", lambda _e, i=idx + 1: _move_to(i))
            radio.bind("<Down>", lambda _e, i=idx + 1: _move_to(i))
            radio.bind("<Home>", lambda _e: _move_to(0))
            radio.bind("<End>", lambda _e: _move_to(len(radios) - 1))

    def _make_section_card(self, parent: tk.Misc, title: str, *, pad_y: tuple[int, int] = (0, 10)) -> ttk.Frame:
        pad = _scale_px(10, self._root_dpi)
        section = ttk.Frame(parent, style="Settings.TFrame")
        section.pack(fill="x", pady=(_scale_px(pad_y[0], self._root_dpi), _scale_px(pad_y[1], self._root_dpi)))
        heading = self._make_wrapped_label(
            section,
            text=title,
            style="CardHeading.TLabel",
            extra_inset_px=36,
        )
        heading.pack(anchor="w", pady=(0, _scale_px(4, self._root_dpi)))
        card = ttk.Frame(section, style="Card.TFrame", padding=(pad, pad))
        card.pack(fill="x")
        self._section_meta[card] = (section, heading)
        return card

    def _build_ui(self, initial_scale: str) -> None:
        self.ui_scale_var = tk.StringVar(value=initial_scale if initial_scale in UI_SCALES else "normal")

        viewport = ttk.Frame(self.root, style="Settings.TFrame")
        viewport.pack(fill="both", expand=True)
        self._viewport_frame = viewport

        self._scroll_canvas = tk.Canvas(
            viewport,
            highlightthickness=0,
            bd=0,
            yscrollincrement=_scale_px(24, self._root_dpi),
        )
        self._scrollbar = ttk.Scrollbar(
            viewport,
            orient="vertical",
            command=self._scroll_canvas.yview,
            style="Vertical.TScrollbar",
        )
        self._scroll_canvas.configure(yscrollcommand=self._scrollbar.set)
        self._scrollbar.pack(side="right", fill="y")
        self._scroll_canvas.pack(side="left", fill="both", expand=True)

        outer_pad = _scale_px(14, self._root_dpi)
        outer = ttk.Frame(self._scroll_canvas, style="Settings.TFrame", padding=outer_pad)
        self._scroll_content = outer
        self._scroll_window_id = self._scroll_canvas.create_window(
            (0, 0),
            window=outer,
            anchor="nw",
            width=self._last_canvas_width,
        )
        outer.bind("<Configure>", self._on_content_configure)
        self._scroll_canvas.bind("<Configure>", self._on_canvas_configure)

        # Header + top mode badge
        header = ttk.Frame(outer, style="Settings.TFrame")
        header.pack(fill="x", pady=(0, _scale_px(8, self._root_dpi)))
        self._header_frame = header
        self._title_frame = ttk.Frame(header, style="Settings.TFrame")
        self._title_frame.pack(fill="x")
        self._header_title_label = self._make_wrapped_label(
            self._title_frame,
            text=f"{APP_NAME} 設定画面",
            style="HeaderTitle.TLabel",
            extra_inset_px=190,
        )
        self.status_badge_var = tk.StringVar(value="● 停止中")
        self._status_badge_label = ttk.Label(
            self._title_frame,
            textvariable=self.status_badge_var,
            style="BadgeNeutral.TLabel",
            padding=(_scale_px(8, self._root_dpi), _scale_px(3, self._root_dpi)),
        )
        self._layout_title_row(wide=True)

        self.status = tk.StringVar(value="停止中")
        self.preview = tk.StringVar(value="")
        self.status_detail_var = tk.StringVar(value="")
        self._status_detail_label = self._make_wrapped_label(
            header,
            textvariable=self.status_detail_var,
            style="DetailMuted.TLabel",
            extra_inset_px=36,
        )
        self._status_detail_visible = False
        self.status.trace_add("write", lambda *_args: self._refresh_status_detail())
        self.preview.trace_add("write", lambda *_args: self._refresh_status_detail())

        # Quick actions above section 1 (diagnostics & exit)
        self._action_bar_frame = ttk.Frame(outer, style="Settings.TFrame")
        self._action_bar_frame.pack(fill="x", pady=(0, _scale_px(10, self._root_dpi)))
        self.copy_diag_button = self._make_button(
            self._action_bar_frame,
            "診断コピー",
            self._copy_diagnostics,
            style="Warn.TButton",
        )
        self.copy_feedback_var = tk.StringVar(value="")
        self._copy_feedback_label = self._make_wrapped_label(
            self._action_bar_frame,
            textvariable=self.copy_feedback_var,
            style="DetailOk.TLabel",
            extra_inset_px=260,
        )
        self.exit_button = self._make_button(
            self._action_bar_frame,
            "アプリを終了",
            self.close,
            style="Danger.TButton",
        )
        self._layout_action_bar(mode=2)

        # Section 1: 接続
        conn_card = self._make_section_card(outer, "1. 接続")
        folder_lbl = self._make_wrapped_label(
            conn_card,
            text="エンジンフォルダー:",
            style="Card.TLabel",
        )
        folder_lbl.pack(anchor="w")

        path_row = ttk.Frame(conn_card, style="CardInner.TFrame")
        path_row.pack(fill="x", pady=(_scale_px(4, self._root_dpi), _scale_px(4, self._root_dpi)))
        self.engine_path = tk.StringVar(value=self.settings.get("engine_dir", ""))
        self.browse_button = self._make_button(
            path_row,
            "参照…",
            self._browse,
        )
        self.browse_button.pack(side="right", padx=(_scale_px(8, self._root_dpi), 0))
        self.path_entry = ttk.Entry(path_row, textvariable=self.engine_path, style="Settings.TEntry")
        self.path_entry.pack(side="left", fill="x", expand=True)
        self.path_entry.bind("<FocusOut>", lambda _event: self._on_engine_path_changed())
        self.path_entry.bind("<Return>", lambda _event: self._on_engine_path_changed())
        self._bind_entry_shortcuts(self.path_entry)
        self._bind_focus_scroll(self.path_entry)
        self._bind_label_target(folder_lbl, self.path_entry)
        self._entry_widgets.append(self.path_entry)
        self.engine_path.trace_add("write", lambda *_args: self._schedule_engine_path_refresh())

        self.engine_path_hint_var = tk.StringVar(value="")
        self._engine_path_hint_label = self._make_wrapped_label(
            conn_card,
            textvariable=self.engine_path_hint_var,
            style="CardMuted.TLabel",
        )
        self._engine_path_hint_label.pack(anchor="w")
        self._refresh_engine_path_hint()

        self.start_button = self._make_button(
            conn_card,
            "エンジンへ接続",
            self._start,
            style="Primary.TButton",
        )
        self._refresh_connect_button()

        # Section 2: Zenzai
        zenzai_card = self._make_section_card(outer, "2. Zenzai（AI 変換）")
        self.use_zenzai_var = tk.BooleanVar(
            value=self.settings.get("use_zenzai", "1") != "0"
        )
        self._use_zenzai_check = self._make_checkbutton(
            zenzai_card,
            "Zenzai を有効にする",
            self.use_zenzai_var,
            self._on_zenzai_changed,
        )
        self._use_zenzai_check.pack(anchor="w", fill="x", pady=(0, _scale_px(6, self._root_dpi)))

        backend_lbl = ttk.Label(
            zenzai_card,
            text="推論バックエンド:",
            style="Card.TLabel",
        )
        backend_lbl.pack(anchor="w")
        self._bind_label_target(backend_lbl, self._focus_selected_backend_radio)
        self._backend_controls_frame = ttk.Frame(zenzai_card, style="CardInner.TFrame")
        self._backend_controls_frame.pack(fill="x", pady=(_scale_px(4, self._root_dpi), _scale_px(4, self._root_dpi)))
        saved_backend = self.settings.get("zenzai_backend", "cpu")
        self.zenzai_backend_var = tk.StringVar(
            value=saved_backend if saved_backend in VALID_BACKENDS else "cpu"
        )
        self._backend_radios: list[ttk.Radiobutton] = []
        for value, label in (("cpu", "CPU"), ("vulkan", "Vulkan (GPU)"), ("cuda", "CUDA (NVIDIA)")):
            rb = ttk.Radiobutton(
                self._backend_controls_frame,
                text=label,
                value=value,
                variable=self.zenzai_backend_var,
                command=self._on_zenzai_backend_changed,
                style="Settings.TRadiobutton",
            )
            self._backend_radios.append(rb)
        self._bind_radio_group(self._backend_radios)

        self.restart_backend_button = self._make_button(
            self._backend_controls_frame,
            "再起動して反映",
            self._restart_app,
            state="disabled",
        )
        self._layout_backend_row(wide=True)

        self.backend_status_var = tk.StringVar(value="")
        self._backend_status_label = self._make_wrapped_label(
            zenzai_card,
            textvariable=self.backend_status_var,
            style="CardMuted.TLabel",
        )
        self._backend_status_label.pack(anchor="w", pady=(_scale_px(2, self._root_dpi), _scale_px(8, self._root_dpi)))
        self._refresh_backend_status()

        profile_lbl = self._make_wrapped_label(
            zenzai_card,
            text="プロフィール（例: 氏名・専門）:",
            style="Card.TLabel",
        )
        profile_lbl.pack(anchor="w")
        self.zenzai_profile_var = tk.StringVar(value=self.settings.get("zenzai_profile", ""))
        self.zenzai_profile_var.trace_add("write", lambda *_args: self._on_zenzai_profile_edited())
        self.profile_entry = ttk.Entry(zenzai_card, textvariable=self.zenzai_profile_var, style="Settings.TEntry")
        self.profile_entry.pack(fill="x", pady=(_scale_px(4, self._root_dpi), _scale_px(2, self._root_dpi)))
        self.profile_entry.bind("<Return>", lambda _event: self._on_zenzai_changed())
        self.profile_entry.bind("<FocusOut>", lambda _event: self._on_zenzai_changed())
        self._bind_entry_shortcuts(self.profile_entry)
        self._bind_focus_scroll(self.profile_entry)
        self._bind_label_target(profile_lbl, self.profile_entry)
        self._entry_widgets.append(self.profile_entry)
        self._refresh_zenzai_controls()

        # Section 3: 表示・入力
        input_card = self._make_section_card(outer, "3. 表示・入力")
        scale_lbl = ttk.Label(
            input_card,
            text="表示サイズ:",
            style="Card.TLabel",
        )
        scale_lbl.pack(anchor="w")
        self._scale_lbl = scale_lbl

        self._scale_controls_frame = ttk.Frame(input_card, style="CardInner.TFrame")
        self._scale_controls_frame.pack(anchor="w", pady=(_scale_px(6, self._root_dpi), _scale_px(2, self._root_dpi)))
        self._scale_bar = tk.Canvas(
            self._scale_controls_frame,
            width=self._desired_scale_bar_width(),
            height=_scale_px(34, self._root_dpi),
            highlightthickness=0,
            bd=0,
            takefocus=1,
            cursor="hand2",
        )
        self._scale_bar.pack(anchor="w")
        self._scale_bar.bind("<Configure>", lambda _e: self._draw_scale_bar())
        self._scale_bar.bind("<Button-1>", lambda e: self._on_scale_bar_pointer(e, focus=True))
        self._scale_bar.bind("<B1-Motion>", lambda e: self._on_scale_bar_pointer(e))
        self._scale_bar.bind("<Enter>", lambda _e: self._set_scale_bar_hover(True))
        self._scale_bar.bind("<Leave>", lambda _e: self._set_scale_bar_hover(False))
        self._scale_bar.bind("<FocusIn>", lambda _e: self._set_scale_bar_focused(True), add="+")
        self._scale_bar.bind("<FocusOut>", lambda _e: self._set_scale_bar_focused(False), add="+")
        self._scale_bar.bind("<Left>", lambda _e: self._step_ui_scale(-1))
        self._scale_bar.bind("<Down>", lambda _e: self._step_ui_scale(-1))
        self._scale_bar.bind("<Right>", lambda _e: self._step_ui_scale(1))
        self._scale_bar.bind("<Up>", lambda _e: self._step_ui_scale(1))
        self._scale_bar.bind("<Home>", lambda _e: self._set_scale_index(0))
        self._scale_bar.bind("<End>", lambda _e: self._set_scale_index(len(UI_SCALE_ORDER) - 1))
        for step_idx in range(len(UI_SCALE_ORDER)):
            self._scale_bar.bind(f"<Key-{step_idx + 1}>", lambda _e, i=step_idx: self._set_scale_index(i))
        self._bind_focus_scroll(self._scale_bar)
        self._bind_label_target(self._scale_lbl, self._scale_bar)

        self._scale_labels_frame = ttk.Frame(self._scale_controls_frame, style="CardInner.TFrame")
        self._scale_labels_frame.pack(fill="x", pady=(_scale_px(2, self._root_dpi), _scale_px(6, self._root_dpi)))
        for col in range(len(UI_SCALE_LABELS)):
            self._scale_labels_frame.columnconfigure(col, weight=1, uniform="scale_stops")
        self._scale_step_labels: list[ttk.Label] = []
        stop_sticky = ("w", "", "e")
        for idx, (_value, label) in enumerate(UI_SCALE_LABELS):
            lbl = ttk.Label(
                self._scale_labels_frame,
                text=label,
                style="CardMuted.TLabel",
                cursor="hand2",
            )
            lbl.grid(row=0, column=idx, sticky=stop_sticky[idx])
            lbl.bind("<Button-1>", lambda _e, i=idx: self._on_scale_label_click(i))
            lbl.bind("<Enter>", lambda _e, i=idx: self._set_scale_label_hover(i))
            lbl.bind("<Leave>", lambda _e, i=idx: self._set_scale_label_hover(None, left=i))
            self._scale_step_labels.append(lbl)

        self.fullwidth_space_var = tk.BooleanVar(
            value=self.settings.get("fullwidth_space", "1") != "0"
        )
        self._make_checkbutton(
            input_card,
            "全角スペースを入力（Shift+Space で半角）",
            self.fullwidth_space_var,
            self._on_fullwidth_space_changed,
        ).pack(anchor="w", fill="x", pady=(_scale_px(2, self._root_dpi), 0))

        self.shift_direct_english_var = tk.BooleanVar(
            value=self.settings.get("shift_direct_english", "1") != "0"
        )
        self._make_checkbutton(
            input_card,
            "Shift+英字で一時的に半角英字を入力",
            self.shift_direct_english_var,
            self._on_shift_direct_english_changed,
        ).pack(anchor="w", fill="x", pady=(_scale_px(4, self._root_dpi), 0))

        self.english_passthrough_var = tk.BooleanVar(
            value=self.settings.get("english_passthrough", "0") == "1"
        )
        self._make_checkbutton(
            input_card,
            "英語モード時はキー入力をそのまま渡す",
            self.english_passthrough_var,
            self._on_passthrough_changed,
        ).pack(anchor="w", fill="x", pady=(_scale_px(4, self._root_dpi), 0))

        # Section 4: 常駐・学習
        tray_card = self._make_section_card(outer, "4. 常駐・学習", pad_y=(0, 4))
        self.minimize_to_tray_var = tk.BooleanVar(
            value=self.settings.get("minimize_to_tray", "1") != "0"
        )
        self._minimize_to_tray_check = self._make_checkbutton(
            tray_card,
            "閉じる（×）で通知領域（タスクバー右下）に常駐",
            self.minimize_to_tray_var,
            self._on_tray_setting_changed,
        )
        self._minimize_to_tray_check.pack(anchor="w", fill="x")

        self.start_minimized_var = tk.BooleanVar(
            value=self.settings.get("start_minimized", "0") == "1"
        )
        self._start_minimized_check = self._make_checkbutton(
            tray_card,
            "起動時は設定画面を隠して常駐",
            self.start_minimized_var,
            self._on_tray_setting_changed,
        )
        self._start_minimized_check.pack(anchor="w", fill="x", pady=(_scale_px(4, self._root_dpi), 0))

        self.tray_hint_var = tk.StringVar(value="")
        self._tray_hint_label = self._make_wrapped_label(
            tray_card,
            textvariable=self.tray_hint_var,
            style="CardMuted.TLabel",
        )

        self._learning_row = ttk.Frame(tray_card, style="CardInner.TFrame")
        self._learning_row.pack(fill="x", pady=(_scale_px(8, self._root_dpi), 0))
        self.learning_count_var = tk.StringVar(
            value=f"学習履歴: {len(_load_learning_memory())} 件"
        )
        self._learning_count_label = ttk.Label(
            self._learning_row,
            textvariable=self.learning_count_var,
            style="Card.TLabel",
        )
        self.view_learning_button = self._make_button(
            self._learning_row,
            "閲覧…",
            self._open_learning_viewer,
        )
        self._bind_label_target(self._learning_count_label, self.view_learning_button)
        self._layout_learning_row(wide=True)
        self._refresh_tray_controls()

        self._section_targets = [
            (conn_card, self.path_entry),
            (zenzai_card, self._use_zenzai_check),
            (input_card, self._scale_bar),
            (tray_card, self._minimize_to_tray_check),
        ]
        self._ui_ready = True
        self._bind_keyboard_shortcuts()
        self._apply_settings_theme(force_wrap=True)

    def _layout_title_row(self, *, wide: bool) -> None:
        if wide == self._last_title_wide:
            return
        self._last_title_wide = wide
        self._current_wrap = -1
        self._header_title_label.grid_forget()
        self._status_badge_label.grid_forget()
        self._title_frame.columnconfigure(0, weight=1)
        self._title_frame.columnconfigure(1, weight=0)
        if wide:
            self._header_title_label.grid(row=0, column=0, sticky="w")
            self._status_badge_label.grid(row=0, column=1, sticky="e", padx=(_scale_px(8, self._root_dpi), 0))
        else:
            self._header_title_label.grid(row=0, column=0, sticky="w")
            self._status_badge_label.grid(row=1, column=0, sticky="w", pady=(_scale_px(4, self._root_dpi), 0))

    def _layout_learning_row(self, *, wide: bool) -> None:
        if wide == self._last_learning_wide:
            return
        self._last_learning_wide = wide
        self._learning_count_label.grid_forget()
        self.view_learning_button.grid_forget()
        if wide:
            gap_x = _scale_px(10, self._root_dpi)
            self._learning_count_label.grid(row=0, column=0, sticky="w")
            self.view_learning_button.grid(row=0, column=1, sticky="w", padx=(gap_x, 0))
        else:
            gap_y = _scale_px(6, self._root_dpi)
            self._learning_count_label.grid(row=0, column=0, sticky="w")
            self.view_learning_button.grid(row=1, column=0, sticky="w", pady=(gap_y, 0))

    def _layout_action_bar(self, *, mode: int) -> None:
        has_feedback = bool(self.copy_feedback_var.get()) if hasattr(self, "copy_feedback_var") else False
        prev_has_fb = getattr(self, "_last_action_bar_has_feedback", None)
        if mode == self._last_action_bar_mode and has_feedback == prev_has_fb:
            return
        self._last_action_bar_mode = mode
        self._last_action_bar_has_feedback = has_feedback
        self._current_wrap = -1
        for child in (self.copy_diag_button, self._copy_feedback_label, self.exit_button):
            child.grid_forget()
        for col in range(3):
            self._action_bar_frame.columnconfigure(col, weight=0, uniform="")
        gap = _scale_px(8, self._root_dpi)
        gap_y = _scale_px(6, self._root_dpi)
        if mode >= 2:
            self._action_bar_frame.columnconfigure(1, weight=1)
            self.copy_diag_button.grid(row=0, column=0, sticky="w")
            self._copy_feedback_label.grid(row=0, column=1, sticky="w", padx=(gap, gap))
            self.exit_button.grid(row=0, column=2, sticky="e")
        elif mode == 1:
            self._action_bar_frame.columnconfigure(0, weight=1)
            self._action_bar_frame.columnconfigure(1, weight=1)
            self.copy_diag_button.grid(row=0, column=0, sticky="w")
            self.exit_button.grid(row=0, column=1, sticky="e")
            if has_feedback:
                self._copy_feedback_label.grid(row=1, column=0, columnspan=2, sticky="w", pady=(gap_y, 0))
        else:
            self._action_bar_frame.columnconfigure(0, weight=1)
            self.copy_diag_button.grid(row=0, column=0, sticky="w")
            next_row = 1
            if has_feedback:
                self._copy_feedback_label.grid(row=next_row, column=0, sticky="w", pady=(gap_y, 0))
                next_row += 1
            self.exit_button.grid(row=next_row, column=0, sticky="w", pady=(gap_y, 0))

    def _layout_backend_row(self, *, wide: bool) -> None:
        pending = bool(self._pending_engine_restart_reason()) if hasattr(self, "zenzai_backend_var") else False
        if wide == self._last_backend_wide and pending == self._last_backend_pending:
            return
        was_pending = self._last_backend_pending
        self._last_backend_wide = wide
        self._last_backend_pending = pending
        for child in (*self._backend_radios, self.restart_backend_button):
            child.grid_forget()
        gap = _scale_px(8, self._root_dpi)
        for col in range(4):
            self._backend_controls_frame.columnconfigure(col, weight=0)
        if wide:
            for idx, rb in enumerate(self._backend_radios):
                rb.grid(row=0, column=idx, sticky="w", padx=(0, gap))
            if pending:
                self.restart_backend_button.grid(row=0, column=3, sticky="w", padx=(gap, 0))
        else:
            for idx, rb in enumerate(self._backend_radios):
                rb.grid(row=idx, column=0, sticky="w", pady=(0, _scale_px(3, self._root_dpi)))
            if pending:
                self.restart_backend_button.grid(
                    row=len(self._backend_radios),
                    column=0,
                    sticky="w",
                    pady=(_scale_px(4, self._root_dpi), 0),
                )
        if (was_pending is not None and pending != was_pending) and not self._closed and getattr(self, "_ui_ready", False):
            self._sync_scrollregion()

    def _current_scale_index(self) -> int:
        current = self.ui_scale_var.get()
        return UI_SCALE_ORDER.index(current) if current in UI_SCALE_ORDER else 0

    def _set_scale_index(self, index: int) -> str:
        clamped = max(0, min(len(UI_SCALE_ORDER) - 1, index))
        next_scale = UI_SCALE_ORDER[clamped]
        if next_scale != self.ui_scale_var.get():
            self.ui_scale_var.set(next_scale)
            self._on_scale_changed()
        else:
            self._draw_scale_bar()
        return "break"

    def _scale_index_from_x(self, x: int) -> int:
        x0, x1, x2 = self._scale_bar_x_stops
        if x < (x0 + x1) / 2.0:
            return 0
        if x < (x1 + x2) / 2.0:
            return 1
        return 2

    def _on_scale_bar_pointer(self, event: tk.Event, *, focus: bool = False) -> str:
        if focus:
            try:
                self._scale_bar.focus_set()
            except tk.TclError:
                pass
        idx = self._scale_index_from_x(int(getattr(event, "x", 0) or 0))
        return self._set_scale_index(idx)

    def _on_scale_label_click(self, index: int) -> None:
        try:
            self._scale_bar.focus_set()
        except tk.TclError:
            pass
        self._set_scale_index(index)

    def _set_scale_bar_hover(self, hover: bool) -> None:
        if self._scale_bar_hover != hover:
            self._scale_bar_hover = hover
            self._draw_scale_bar()

    def _set_scale_bar_focused(self, focused: bool) -> None:
        if self._scale_bar_focused != focused:
            self._scale_bar_focused = focused
            self._draw_scale_bar()

    def _desired_scale_bar_width(self) -> int:
        metrics = self._settings_metrics()
        avail = max(180, self._last_canvas_width - _scale_px(56, self._root_dpi))
        ideal = max(_scale_px(210, self._root_dpi), _scale_px(round(metrics["body_font"] * 21), self._root_dpi))
        return min(avail, ideal)

    def _set_scale_label_hover(self, index: int | None, *, left: int | None = None) -> None:
        if left is not None and self._hovered_scale_idx != left:
            return
        if self._hovered_scale_idx != index:
            self._hovered_scale_idx = index
            self._draw_scale_bar()

    def _draw_scale_bar(self) -> None:
        if not hasattr(self, "_scale_bar"):
            return
        idx = self._current_scale_index()
        for lbl_idx, lbl in enumerate(getattr(self, "_scale_step_labels", ())):
            try:
                if lbl_idx == idx:
                    lbl_style = "ScaleActive.TLabel"
                elif lbl_idx == self._hovered_scale_idx:
                    lbl_style = "ScaleHover.TLabel"
                else:
                    lbl_style = "CardMuted.TLabel"
                lbl.configure(style=lbl_style)
            except tk.TclError:
                pass

        theme = self._current_settings_theme or system_theme_palette()
        high_contrast, _dark_mode = system_theme_signature()
        metrics = self._settings_metrics()
        try:
            w = self._desired_scale_bar_width()
            h = max(int(float(self._scale_bar.cget("height") or 32)), 28)
            thumb_r = min(
                (h - 8) // 2,
                max(_scale_px(8, self._root_dpi), round(metrics["indicator_px"] * 0.50)),
            )
            thumb_r = max(6, thumb_r)
            track_h = max(_scale_px(6, self._root_dpi), round(thumb_r * 0.58))
            pad_x = max(thumb_r + _scale_px(10, self._root_dpi), _scale_px(18, self._root_dpi))
            x0 = float(pad_x)
            x2 = float(max(x0 + 48.0, w - pad_x))
            x1 = (x0 + x2) / 2.0
            self._scale_bar_x_stops = (x0, x1, x2)
            cy = h / 2.0

            c = self._scale_bar
            c.configure(bg=theme["settings_card_bg"])
            c.delete("all")

            if self._scale_bar_focused:
                c.create_rectangle(
                    2,
                    2,
                    w - 2,
                    h - 2,
                    outline=theme["settings_focus_ring"],
                    width=2,
                )

            y0 = cy - track_h / 2.0
            y1 = cy + track_h / 2.0
            c.create_rectangle(
                x0,
                y0,
                x2,
                y1,
                fill=theme["settings_scroll_trough"],
                outline=theme["settings_border"],
                width=1,
            )

            active_x = self._scale_bar_x_stops[idx]
            if idx > 0:
                c.create_rectangle(
                    x0,
                    y0,
                    active_x,
                    y1,
                    fill=theme["settings_primary_bg"],
                    outline=theme["settings_focus_ring"] if high_contrast else theme["settings_primary_bg"],
                    width=1,
                )

            dot_r = max(_scale_px(3, self._root_dpi), round(track_h * 0.55))
            for stop_i, sx in enumerate(self._scale_bar_x_stops):
                if stop_i == idx:
                    continue
                if stop_i < idx:
                    c.create_oval(
                        sx - dot_r,
                        cy - dot_r,
                        sx + dot_r,
                        cy + dot_r,
                        fill=theme["settings_primary_fg"],
                        outline=theme["settings_primary_bg"],
                        width=1,
                    )
                else:
                    c.create_oval(
                        sx - dot_r,
                        cy - dot_r,
                        sx + dot_r,
                        cy + dot_r,
                        fill=theme["settings_card_bg"],
                        outline=theme["settings_border"],
                        width=2,
                    )

            knob_fill = theme["settings_primary_hover_bg"] if self._scale_bar_hover else theme["settings_primary_bg"]
            knob_outline = (
                theme["settings_focus_ring"]
                if (self._scale_bar_hover or self._scale_bar_focused)
                else (theme["settings_fg"] if high_contrast else theme["settings_card_bg"])
            )
            outline_w = 3 if (self._scale_bar_hover or self._scale_bar_focused) else 2
            c.create_oval(
                active_x - thumb_r,
                cy - thumb_r,
                active_x + thumb_r,
                cy + thumb_r,
                fill=knob_fill,
                outline=knob_outline,
                width=outline_w,
            )
            inner_r = max(2, thumb_r // 3)
            c.create_oval(
                active_x - inner_r,
                cy - inner_r,
                active_x + inner_r,
                cy + inner_r,
                fill=theme["settings_primary_fg"],
                outline="",
            )
        except tk.TclError:
            pass

    def _reflow_responsive_grids(self, canvas_width: int) -> None:
        if canvas_width < 200 or not getattr(self, "_ui_ready", False):
            return
        body_pt = self._settings_metrics()["body_font"]
        extra_factor = max(1.0, body_pt / 10.0)
        self._layout_title_row(wide=canvas_width >= _scale_px(round(470 * extra_factor), self._root_dpi))
        self._layout_backend_row(wide=canvas_width >= _scale_px(round(500 * extra_factor), self._root_dpi))
        self._layout_learning_row(wide=canvas_width >= _scale_px(round(490 * extra_factor), self._root_dpi))
        if canvas_width >= _scale_px(round(490 * extra_factor), self._root_dpi):
            action_bar_mode = 2
        elif canvas_width >= _scale_px(round(340 * extra_factor), self._root_dpi):
            action_bar_mode = 1
        else:
            action_bar_mode = 0
        self._layout_action_bar(mode=action_bar_mode)
        if hasattr(self, "_scale_bar"):
            try:
                bar_w = self._desired_scale_bar_width()
                if int(float(self._scale_bar.cget("width") or 0)) != bar_w:
                    self._scale_bar.configure(width=bar_w)
                    self._draw_scale_bar()
            except tk.TclError:
                pass

    def _update_wraplengths(self, force: bool = False) -> None:
        width = max(320, self._last_canvas_width)
        if not force and abs(width - self._current_wrap) < 2:
            return
        self._current_wrap = width
        card_wrap = max(200, width - _scale_px(56, self._root_dpi))
        self._style.configure("Wrap.TCheckbutton", wraplength=card_wrap)
        for label, inset in self._wrapped_labels:
            effective_inset = inset
            if label is getattr(self, "_header_title_label", None):
                effective_inset = 190 if self._last_title_wide else 28
            elif label is getattr(self, "_copy_feedback_label", None):
                effective_inset = 260 if (self._last_action_bar_mode or 0) >= 2 else 36
            try:
                label.configure(wraplength=max(160, width - _scale_px(effective_inset, self._root_dpi)))
            except tk.TclError:
                pass

    def _sync_scrollregion(self) -> None:
        if self._closed or not hasattr(self, "_scroll_canvas"):
            return
        if self._syncing_scrollregion:
            return
        self._syncing_scrollregion = True
        try:
            self._scroll_canvas.update_idletasks()
            req_w = max(1, int(self._scroll_content.winfo_reqwidth()))
            req_h = max(1, int(self._scroll_content.winfo_reqheight()))
            bbox = self._scroll_canvas.bbox("all")
            if bbox:
                req_w = max(req_w, int(bbox[2] - bbox[0]))
            self._scroll_canvas.configure(scrollregion=(0, 0, req_w, req_h))
            view_h = int(self._scroll_canvas.winfo_height() or 0)
            if view_h > 1:
                cur_top = float(self._scroll_canvas.canvasy(0))
                max_top = max(0.0, float(req_h - view_h))
                if req_h <= view_h:
                    if abs(cur_top) > 0.5:
                        self._scroll_canvas.yview_moveto(0.0)
                        self._scroll_canvas.update_idletasks()
                elif cur_top > max_top + 0.5 or cur_top < -0.5:
                    clamped = max(0.0, min(cur_top, max_top))
                    self._scroll_canvas.yview_moveto(clamped / float(req_h))
                    self._scroll_canvas.update_idletasks()
        except tk.TclError:
            pass
        finally:
            self._syncing_scrollregion = False

    def _on_content_configure(self, _event: tk.Event) -> None:
        self._sync_scrollregion()

    def _on_canvas_configure(self, event: tk.Event) -> None:
        width = int(getattr(event, "width", 0) or 0)
        if width < 200:
            return
        self._last_canvas_width = width
        try:
            self._scroll_canvas.itemconfigure(self._scroll_window_id, width=width)
        except tk.TclError:
            pass
        self._reflow_responsive_grids(width)
        self._update_wraplengths()
        self._sync_scrollregion()

    def _on_mousewheel(self, event: tk.Event) -> None:
        if not hasattr(self, "_scroll_canvas"):
            return
        try:
            first, last = self._scroll_canvas.yview()
        except tk.TclError:
            return
        if first <= 0.0 and last >= 1.0:
            return
        delta = int(getattr(event, "delta", 0) or 0)
        if delta == 0:
            return
        steps = -round(delta / 120) if abs(delta) >= 120 else (-1 if delta > 0 else 1)
        if steps:
            self._scroll_canvas.yview_scroll(steps, "units")

    def _ensure_widget_visible(self, widget: tk.Widget) -> None:
        if self._closed or not hasattr(self, "_scroll_canvas"):
            return
        try:
            if self.root.state() == "withdrawn":
                return
            self._scroll_canvas.update_idletasks()
            bbox = self._scroll_canvas.bbox("all")
            if not bbox:
                return
            content_h = max(1, bbox[3] - bbox[1])
            view_h = max(1, self._scroll_canvas.winfo_height())
            if content_h <= view_h:
                return
            first, last = self._scroll_canvas.yview()
            vis_top = first * content_h
            vis_bottom = last * content_h
            w_top = widget.winfo_rooty() - self._scroll_content.winfo_rooty()
            w_bottom = w_top + max(1, widget.winfo_height())
            margin = _scale_px(18, self._root_dpi)
            if w_top - margin < vis_top:
                target = max(0.0, (w_top - margin) / content_h)
                self._scroll_canvas.yview_moveto(target)
            elif w_bottom + margin > vis_bottom:
                target = min(1.0, (w_bottom + margin - view_h) / content_h)
                self._scroll_canvas.yview_moveto(target)
        except tk.TclError:
            pass

    def _bind_keyboard_shortcuts(self) -> None:
        self.root.bind("<MouseWheel>", self._on_mousewheel)
        self.root.bind("<FocusIn>", self._on_root_focus_in, add="+")
        self.root.bind("<F5>", lambda _e: self._on_refresh_shortcut())
        self.root.bind("<F1>", lambda _e: self._on_help_shortcut())
        for seq in ("<Control-plus>", "<Control-equal>", "<Control-KP_Add>"):
            self.root.bind(seq, lambda _e: self._step_ui_scale(1))
        for seq in ("<Control-minus>", "<Control-KP_Subtract>"):
            self.root.bind(seq, lambda _e: self._step_ui_scale(-1))
        for seq in ("<Control-Key-0>", "<Control-KP_0>"):
            self.root.bind(seq, lambda _e: self._step_ui_scale(0))
        self.root.bind("<Prior>", lambda _e: self._scroll_page(-1))
        self.root.bind("<Next>", lambda _e: self._scroll_page(1))
        self.root.bind("<Control-Home>", lambda _e: self._scroll_to_top())
        self.root.bind("<Control-End>", lambda _e: self._scroll_to_bottom())
        self.root.bind("<F6>", lambda _e: self._cycle_section(1))
        self.root.bind("<Shift-F6>", lambda _e: self._cycle_section(-1))
        for sec_idx in range(len(self._section_targets)):
            self.root.bind(f"<Control-Key-{sec_idx + 1}>", lambda _e, i=sec_idx: self._jump_to_section(i))

    def _section_index_for_widget(self, widget: tk.Misc | None) -> int:
        if not self._section_targets or widget is None:
            return -1
        cards = [card for card, _w in self._section_targets]
        cur: tk.Misc | None = widget
        try:
            while cur is not None:
                if cur in cards:
                    return cards.index(cur)
                parent_name = cur.winfo_parent()
                cur = self.root.nametowidget(parent_name) if parent_name else None
        except (tk.TclError, KeyError, ValueError):
            return -1
        return -1

    def _set_active_section(self, index: int) -> None:
        if index == self._active_section_idx:
            return
        self._active_section_idx = index
        for idx, (card, _target) in enumerate(self._section_targets):
            active = idx == index
            try:
                card.configure(style="ActiveCard.TFrame" if active else "Card.TFrame")
            except tk.TclError:
                pass
            meta = self._section_meta.get(card)
            if meta is not None:
                try:
                    meta[1].configure(style="ActiveCardHeading.TLabel" if active else "CardHeading.TLabel")
                except tk.TclError:
                    pass

    def _on_root_focus_in(self, event: tk.Event) -> None:
        widget = getattr(event, "widget", None)
        idx = self._section_index_for_widget(widget if isinstance(widget, tk.Misc) else None)
        self._set_active_section(idx)

    def _scroll_to_top(self) -> str:
        try:
            self._scroll_canvas.yview_moveto(0.0)
        except tk.TclError:
            pass
        if self._section_targets:
            self._set_active_section(0)
            target = self._section_targets[0][1]
            try:
                target.focus_set()
                if isinstance(target, ttk.Entry):
                    target.selection_range(0, "end")
            except tk.TclError:
                pass
        return "break"

    def _scroll_to_bottom(self) -> str:
        try:
            self._scroll_canvas.yview_moveto(1.0)
        except tk.TclError:
            pass
        if self._section_targets:
            last_idx = len(self._section_targets) - 1
            self._set_active_section(last_idx)
            try:
                target = getattr(self, "view_learning_button", self._section_targets[last_idx][1])
                target.focus_set()
                self._ensure_widget_visible(self._section_targets[last_idx][0])
            except tk.TclError:
                pass
        return "break"

    def _jump_to_section(self, index: int) -> str:
        if not self._section_targets:
            return "break"
        idx = index % len(self._section_targets)
        card, target = self._section_targets[idx]
        self._set_active_section(idx)
        meta = self._section_meta.get(card)
        visible_widget = meta[0] if meta is not None else card
        try:
            self._ensure_widget_visible(visible_widget)
            target.focus_set()
            if isinstance(target, ttk.Entry):
                target.selection_range(0, "end")
        except tk.TclError:
            pass
        return "break"

    def _cycle_section(self, delta: int) -> str:
        if not self._section_targets:
            return "break"
        current_idx = self._section_index_for_widget(self.root.focus_get())
        if current_idx < 0:
            next_idx = 0 if delta >= 0 else len(self._section_targets) - 1
        else:
            next_idx = (current_idx + delta) % len(self._section_targets)
        return self._jump_to_section(next_idx)

    def _scroll_page(self, direction: int) -> str:
        try:
            first, last = self._scroll_canvas.yview()
            if not (first <= 0.0 and last >= 1.0):
                self._scroll_canvas.yview_scroll(direction, "pages")
        except tk.TclError:
            pass
        return "break"

    def _step_ui_scale(self, delta: int) -> str:
        current = self.ui_scale_var.get()
        idx = UI_SCALE_ORDER.index(current) if current in UI_SCALE_ORDER else 0
        next_idx = 0 if delta == 0 else max(0, min(len(UI_SCALE_ORDER) - 1, idx + delta))
        next_scale = UI_SCALE_ORDER[next_idx]
        if next_scale != current:
            self.ui_scale_var.set(next_scale)
            self._on_scale_changed()
        return "break"

    def _on_refresh_shortcut(self) -> str:
        self._on_engine_path_changed()
        self._refresh_status_and_indicators(force=True)
        self._show_copy_feedback("✓ エンジンとバックエンドの状態を再確認しました")
        return "break"

    def _on_help_shortcut(self) -> str:
        try:
            self._scroll_canvas.yview_moveto(0.0)
        except tk.TclError:
            pass
        self._set_active_section(-1)
        try:
            self.copy_diag_button.focus_set()
            if hasattr(self, "_action_bar_frame"):
                self._ensure_widget_visible(self._action_bar_frame)
        except tk.TclError:
            pass
        return "break"

    @staticmethod
    def _configure_button_style(
        style: ttk.Style,
        name: str,
        *,
        bg: str,
        fg: str,
        hover_bg: str,
        hover_fg: str,
        active_bg: str,
        border: str,
        dark_border: str | None = None,
        focus_ring: str,
        focus_thickness: int = 2,
        disabled_bg: str,
        disabled_fg: str,
        disabled_border: str,
        font: tuple[object, ...],
        padding: tuple[int, int],
    ) -> None:
        style.configure(
            name,
            background=bg,
            foreground=fg,
            bordercolor=border,
            lightcolor=bg,
            darkcolor=dark_border or border,
            focuscolor=focus_ring,
            focusthickness=focus_thickness,
            padding=padding,
            font=font,
            relief="solid",
            borderwidth=1,
            width=0,
        )
        style.map(
            name,
            background=[
                ("disabled", disabled_bg),
                ("pressed", active_bg),
                ("active", hover_bg),
            ],
            foreground=[
                ("disabled", disabled_fg),
                ("pressed", hover_fg),
                ("active", hover_fg),
            ],
            bordercolor=[
                ("focus", focus_ring),
                ("disabled", disabled_border),
            ],
        )

    def _ensure_checkbutton_indicator(
        self,
        *,
        theme: dict[str, str],
        ind_px: int,
        high_contrast: bool,
    ) -> None:
        """Build or refresh a rounded ✓ checkbox indicator synced with theme and scale."""
        right_pad = max(6, _scale_px(8, self._root_dpi))
        base_b = max(2 if high_contrast else 1, round(ind_px / (11 if high_contrast else 14)))
        focus_b = max(2, base_b + 1)
        checked_border = theme["settings_border"] if high_contrast else theme["settings_primary_bg"]
        hover_fill = theme["settings_primary_bg"] if high_contrast else theme["settings_primary_hover_bg"]
        states: dict[str, tuple[str, str, str | None, int]] = {
            "off": (theme["settings_input_bg"], theme["settings_border"], None, base_b),
            "off_focus": (theme["settings_input_bg"], theme["settings_focus_ring"], None, focus_b),
            "on": (theme["settings_primary_bg"], checked_border, theme["settings_primary_fg"], base_b),
            "on_focus": (hover_fill, theme["settings_focus_ring"], theme["settings_primary_fg"], focus_b),
            "dis_off": (theme["settings_disabled_bg"], theme["settings_border"], None, base_b),
            "dis_on": (theme["settings_disabled_bg"], theme["settings_border"], theme["settings_disabled_fg"], base_b),
        }
        sig = (ind_px, right_pad, tuple(states.items()))
        if self._check_indicator_sig != sig:
            for key, (fill, border, check_fg, border_px) in states.items():
                photo = self._check_indicator_images.get(key)
                if photo is None:
                    photo = tk.PhotoImage(master=self.root)
                    self._check_indicator_images[key] = photo
                _draw_check_indicator_image(
                    photo,
                    size=ind_px,
                    right_pad=right_pad,
                    fill=fill,
                    border=border,
                    check_fg=check_fg,
                    border_px=border_px,
                )
            self._check_indicator_sig = sig

        s = self._style
        if "WrapCheck.indicator" not in s.element_names():
            imgs = self._check_indicator_images
            s.element_create(
                "WrapCheck.indicator",
                "image",
                imgs["off"],
                ("disabled", "selected", imgs["dis_on"]),
                ("disabled", imgs["dis_off"]),
                ("selected", "focus", imgs["on_focus"]),
                ("selected", "active", imgs["on_focus"]),
                ("selected", imgs["on"]),
                ("focus", imgs["off_focus"]),
                ("active", imgs["off_focus"]),
                sticky="",
            )
        s.layout(
            "Wrap.TCheckbutton",
            [
                (
                    "Checkbutton.padding",
                    {
                        "sticky": "nswe",
                        "children": [
                            ("WrapCheck.indicator", {"side": "left", "sticky": ""}),
                            (
                                "Checkbutton.focus",
                                {
                                    "side": "left",
                                    "sticky": "w",
                                    "children": [("Checkbutton.label", {"sticky": "nswe"})],
                                },
                            ),
                        ],
                    },
                )
            ],
        )

    def _apply_settings_theme(self, *, force_wrap: bool = False) -> None:
        theme = system_theme_palette()
        self._current_settings_theme = theme
        high_contrast, dark_mode = system_theme_signature()
        text_scale = system_text_scale_factor()
        scale_name = self.ui_scale_var.get()
        self._last_settings_theme_sig = (high_contrast, dark_mode, scale_name, text_scale)

        metrics = self._settings_metrics()
        title_font = ("Yu Gothic UI", metrics["title_font"], "bold")
        heading_font = ("Yu Gothic UI", metrics["heading_font"], "bold")
        body_font = ("Yu Gothic UI", metrics["body_font"])
        body_bold_font = ("Yu Gothic UI", metrics["body_font"], "bold")
        caption_font = ("Yu Gothic UI", metrics["caption_font"])
        caption_bold_font = ("Yu Gothic UI", metrics["caption_font"], "bold")
        caption_hover_font = ("Yu Gothic UI", metrics["caption_font"], "bold underline")
        ind_px = metrics["indicator_px"]
        focus_px = max(2, _scale_px(3 if high_contrast else 2, self._root_dpi))
        card_border_px = max(2, _scale_px(2, self._root_dpi))
        pad_sm = _scale_px(4, self._root_dpi)
        pad_row = max(_scale_px(6, self._root_dpi), round(metrics["body_font"] * 0.45))
        pad_btn = (_scale_px(10, self._root_dpi), _scale_px(6, self._root_dpi))

        try:
            if self._style.theme_use() != "clam":
                self._style.theme_use("clam")
        except tk.TclError:
            pass

        apply_window_dark_titlebar(_top_window_hwnd(self.root), dark_mode and not high_contrast)
        self.root.configure(bg=theme["settings_bg"])
        if hasattr(self, "_scroll_canvas"):
            self._scroll_canvas.configure(bg=theme["settings_bg"])

        s = self._style
        s.configure("Settings.TFrame", background=theme["settings_bg"])
        active_card_label_fg = theme["settings_fg"] if high_contrast else theme["settings_focus_ring"]
        for style_name, border_color in (
            ("Card.TFrame", theme["settings_card_border"]),
            ("ActiveCard.TFrame", theme["settings_focus_ring"]),
        ):
            s.configure(
                style_name,
                background=theme["settings_card_bg"],
                bordercolor=border_color,
                lightcolor=border_color,
                darkcolor=border_color,
                relief="solid",
                borderwidth=card_border_px,
            )
        for style_name, fg_color in (
            ("CardHeading.TLabel", theme["settings_fg"]),
            ("ActiveCardHeading.TLabel", active_card_label_fg),
        ):
            s.configure(
                style_name,
                background=theme["settings_bg"],
                foreground=fg_color,
                font=heading_font,
                padding=(pad_sm, 0),
            )
        s.configure("CardInner.TFrame", background=theme["settings_card_bg"])
        s.configure("DetailInfo.TLabel", background=theme["settings_bg"], foreground=theme["settings_fg"], font=body_font)
        s.configure("DetailMuted.TLabel", background=theme["settings_bg"], foreground=theme["settings_muted_fg"], font=caption_font)
        s.configure("DetailOk.TLabel", background=theme["settings_bg"], foreground=theme["settings_status_ok_fg"], font=caption_font)
        s.configure("DetailWarn.TLabel", background=theme["settings_bg"], foreground=theme["settings_status_warn_fg"], font=caption_font)
        s.configure("DetailErr.TLabel", background=theme["settings_bg"], foreground=theme["settings_status_err_fg"], font=caption_font)
        s.configure("HeaderTitle.TLabel", background=theme["settings_bg"], foreground=theme["settings_fg"], font=title_font)

        s.configure("BadgeNeutral.TLabel", background=theme["toggle_off_bg"], foreground=theme["toggle_off_fg"], font=caption_font)
        s.configure("BadgeOk.TLabel", background=theme["toggle_on_bg"], foreground=theme["toggle_on_fg"], font=caption_font)
        s.configure("BadgeWarn.TLabel", background=theme["toggle_warn_bg"], foreground=theme["toggle_warn_fg"], font=caption_font)
        s.configure("BadgeErr.TLabel", background=theme["toggle_disabled_bg"], foreground=theme["settings_status_err_fg"], font=caption_font)

        s.configure("Card.TLabel", background=theme["settings_card_bg"], foreground=theme["settings_fg"], font=body_font)
        s.configure("CardMuted.TLabel", background=theme["settings_card_bg"], foreground=theme["settings_muted_fg"], font=caption_font)
        active_step_fg = theme["settings_fg"] if high_contrast else theme["settings_focus_ring"]
        s.configure(
            "ScaleActive.TLabel",
            background=theme["settings_card_bg"],
            foreground=active_step_fg,
            font=caption_bold_font,
        )
        s.configure(
            "ScaleHover.TLabel",
            background=theme["settings_card_bg"],
            foreground=active_step_fg,
            font=caption_hover_font,
        )
        s.configure("Ok.Card.TLabel", background=theme["settings_card_bg"], foreground=theme["settings_status_ok_fg"], font=caption_font)
        s.configure("Warn.Card.TLabel", background=theme["settings_card_bg"], foreground=theme["settings_status_warn_fg"], font=caption_font)
        s.configure("Err.Card.TLabel", background=theme["settings_card_bg"], foreground=theme["settings_status_err_fg"], font=caption_font)
        s.configure("Viewer.TLabel", background=theme["settings_bg"], foreground=theme["settings_fg"], font=body_font)
        s.configure("ViewerMuted.TLabel", background=theme["settings_bg"], foreground=theme["settings_muted_fg"], font=caption_font)
        s.configure("ViewerOk.TLabel", background=theme["settings_bg"], foreground=theme["settings_status_ok_fg"], font=caption_font)

        self._ensure_checkbutton_indicator(
            theme=theme,
            ind_px=ind_px,
            high_contrast=high_contrast,
        )
        for toggle_style in ("Wrap.TCheckbutton", "Settings.TRadiobutton"):
            s.configure(
                toggle_style,
                background=theme["settings_card_bg"],
                foreground=theme["settings_fg"],
                font=body_font,
                padding=(pad_sm, pad_row),
                focusthickness=focus_px,
                focuscolor=theme["settings_focus_ring"],
            )
            s.map(
                toggle_style,
                background=[
                    ("disabled", theme["settings_card_bg"]),
                    ("focus", theme["settings_hover_bg"]),
                    ("active", theme["settings_hover_bg"]),
                ],
                foreground=[("disabled", theme["settings_disabled_fg"])],
            )

        s.configure(
            "Settings.TRadiobutton",
            indicatorsize=ind_px,
            indicatormargin="2 2 6 2",
            indicatorbackground=theme["settings_input_bg"],
            indicatorforeground=theme["settings_fg"],
            upperbordercolor=theme["settings_border"],
            lowerbordercolor=theme["settings_border"],
        )
        s.map(
            "Settings.TRadiobutton",
            upperbordercolor=[
                ("disabled", theme["settings_border"]),
                ("focus", theme["settings_focus_ring"]),
                ("active", theme["settings_focus_ring"]),
            ],
            lowerbordercolor=[
                ("disabled", theme["settings_border"]),
                ("focus", theme["settings_focus_ring"]),
                ("active", theme["settings_focus_ring"]),
            ],
            indicatorbackground=[
                ("disabled", theme["settings_disabled_bg"]),
                ("selected", theme["settings_primary_bg"]),
                ("!selected", theme["settings_input_bg"]),
            ],
            indicatorforeground=[
                ("disabled", theme["settings_disabled_fg"]),
                ("selected", theme["settings_primary_fg"]),
            ],
        )

        common_btn_kw = dict(
            focus_ring=theme["settings_focus_ring"],
            focus_thickness=focus_px,
            disabled_bg=theme["settings_disabled_bg"],
            disabled_fg=theme["settings_disabled_fg"],
            disabled_border=theme["settings_border"],
            padding=pad_btn,
        )
        self._configure_button_style(
            s,
            "Settings.TButton",
            bg=theme["settings_button_bg"],
            fg=theme["settings_button_fg"],
            hover_bg=theme["settings_button_hover_bg"],
            hover_fg=theme["settings_button_hover_fg"],
            active_bg=theme["settings_button_active_bg"],
            border=theme["settings_border"],
            font=body_font,
            **common_btn_kw,
        )
        self._configure_button_style(
            s,
            "Primary.TButton",
            bg=theme["settings_primary_bg"],
            fg=theme["settings_primary_fg"],
            hover_bg=theme["settings_primary_hover_bg"],
            hover_fg=theme["settings_primary_hover_fg"],
            active_bg=theme["settings_primary_active_bg"],
            border=theme["settings_primary_bg"],
            font=heading_font,
            **common_btn_kw,
        )
        for style_name, prefix in (
            ("Danger.TButton", "settings_danger"),
            ("Accent.TButton", "settings_accent"),
            ("Warn.TButton", "settings_warn"),
        ):
            self._configure_button_style(
                s,
                style_name,
                bg=theme[f"{prefix}_bg"],
                fg=theme[f"{prefix}_fg"],
                hover_bg=theme[f"{prefix}_hover_bg"],
                hover_fg=theme[f"{prefix}_hover_fg"],
                active_bg=theme[f"{prefix}_active_bg"],
                border=theme[f"{prefix}_border"],
                font=body_bold_font,
                **common_btn_kw,
            )

        s.configure(
            "Settings.TEntry",
            fieldbackground=theme["settings_input_bg"],
            foreground=theme["settings_input_fg"],
            insertcolor=theme["settings_input_fg"],
            insertwidth=2,
            selectbackground=theme["settings_selected_bg"],
            selectforeground=theme["settings_selected_fg"],
            bordercolor=theme["settings_border"],
            lightcolor=theme["settings_border"],
            padding=(_scale_px(7, self._root_dpi), _scale_px(5, self._root_dpi)),
            font=body_font,
        )
        s.map(
            "Settings.TEntry",
            fieldbackground=[("disabled", theme["settings_disabled_bg"])],
            foreground=[("disabled", theme["settings_disabled_fg"])],
            bordercolor=[
                ("disabled", theme["settings_border"]),
                ("focus", theme["settings_focus_ring"]),
                ("active", theme["settings_fg"]),
            ],
            lightcolor=[
                ("focus", theme["settings_focus_ring"]),
                ("active", theme["settings_fg"]),
            ],
        )

        s.configure(
            "Vertical.TScrollbar",
            background=theme["settings_scroll_thumb"],
            troughcolor=theme["settings_scroll_trough"],
            bordercolor=theme["settings_border"],
            arrowcolor=theme["settings_fg"],
            arrowsize=_scale_px(14, self._root_dpi),
        )
        tree_row_h = max(_scale_px(26, self._root_dpi), round(metrics["body_font"] * 2.15))
        s.configure(
            "Settings.Treeview",
            background=theme["settings_input_bg"],
            fieldbackground=theme["settings_input_bg"],
            foreground=theme["settings_input_fg"],
            bordercolor=theme["settings_border"],
            lightcolor=theme["settings_border"],
            rowheight=tree_row_h,
            font=body_font,
        )
        s.map(
            "Settings.Treeview",
            background=[("selected", theme["settings_selected_bg"])],
            foreground=[("selected", theme["settings_selected_fg"])],
            bordercolor=[("focus", theme["settings_focus_ring"])],
            lightcolor=[("focus", theme["settings_focus_ring"])],
        )
        s.configure(
            "Settings.Treeview.Heading",
            background=theme["settings_button_bg"],
            foreground=theme["settings_button_fg"],
            bordercolor=theme["settings_border"],
            relief="flat",
            padding=(_scale_px(8, self._root_dpi), _scale_px(5, self._root_dpi)),
            font=caption_bold_font,
        )
        s.map(
            "Settings.Treeview.Heading",
            background=[
                ("pressed", theme["settings_button_active_bg"]),
                ("active", theme["settings_button_hover_bg"]),
            ],
            foreground=[
                ("pressed", theme["settings_button_hover_fg"]),
                ("active", theme["settings_button_hover_fg"]),
            ],
        )

        for entry in self._entry_widgets:
            try:
                entry.configure(font=body_font)
            except tk.TclError:
                pass
        if hasattr(self, "_scale_bar"):
            try:
                bar_w = self._desired_scale_bar_width()
                bar_h = max(_scale_px(32, self._root_dpi), ind_px + _scale_px(14, self._root_dpi))
                self._scale_bar.configure(width=bar_w, height=bar_h, bg=theme["settings_card_bg"])
            except tk.TclError:
                pass
            self._draw_scale_bar()

        self._reflow_responsive_grids(self._last_canvas_width)
        self._update_wraplengths(force=True)
        self._sync_scrollregion()
        self._apply_learning_viewer_theme()

    def _refresh_engine_path_hint(self) -> None:
        if not hasattr(self, "engine_path_hint_var"):
            return
        folder = self.engine_path.get().strip()
        if not folder:
            self.engine_path_hint_var.set("ℹ azookey-server.dll のフォルダーを指定")
            if hasattr(self, "_engine_path_hint_label"):
                self._engine_path_hint_label.configure(style="Warn.Card.TLabel")
            return
        path = Path(folder).expanduser()
        if not path.is_dir():
            self.engine_path_hint_var.set("⚠ フォルダーが見つかりません")
            if hasattr(self, "_engine_path_hint_label"):
                self._engine_path_hint_label.configure(style="Err.Card.TLabel")
            return
        missing: list[str] = []
        if not (path / "azookey-server.dll").is_file():
            missing.append("azookey-server.dll")
        if not (path / "Dictionary").is_dir():
            missing.append("Dictionary")
        if missing:
            self.engine_path_hint_var.set(f"⚠ 不足: {', '.join(missing)}")
            if hasattr(self, "_engine_path_hint_label"):
                self._engine_path_hint_label.configure(style="Err.Card.TLabel")
            return
        self.engine_path_hint_var.set("✓ 検出済み")
        if hasattr(self, "_engine_path_hint_label"):
            self._engine_path_hint_label.configure(style="Ok.Card.TLabel")

    def _refresh_tray_controls(self) -> None:
        tray_active = bool(hasattr(self, "tray_icon") and self.tray_icon.active)
        if hasattr(self, "_minimize_to_tray_check"):
            self._minimize_to_tray_check.configure(state="normal" if tray_active else "disabled")
        if hasattr(self, "_start_minimized_check"):
            can_start_min = tray_active and bool(self.minimize_to_tray_var.get())
            self._start_minimized_check.configure(state="normal" if can_start_min else "disabled")
        if hasattr(self, "tray_hint_var"):
            if not tray_active:
                hint = "ℹ 通知領域アイコン非対応のため常駐は無効"
            elif not self.minimize_to_tray_var.get():
                hint = "ℹ 常駐設定 OFF のため × 押下で終了"
            else:
                hint = ""
            self.tray_hint_var.set(hint)
            if hasattr(self, "_tray_hint_label"):
                was_packed = False
                is_packed = False
                try:
                    was_packed = self._tray_hint_label.winfo_manager() == "pack"
                    if hint:
                        if not was_packed:
                            self._tray_hint_label.pack(
                                anchor="w",
                                pady=(_scale_px(3, self._root_dpi), 0),
                                before=self._learning_row,
                            )
                        is_packed = True
                    elif was_packed:
                        self._tray_hint_label.pack_forget()
                except tk.TclError:
                    pass
                if (was_packed != is_packed) and not self._closed and getattr(self, "_ui_ready", False):
                    self._sync_scrollregion()

    def _refresh_connect_button(self) -> None:
        if not hasattr(self, "start_button"):
            return
        should_show = (self.hook is None) and (not self.starting)
        was_packed = False
        try:
            was_packed = self.start_button.winfo_manager() == "pack"
            if should_show:
                if not was_packed:
                    self.start_button.pack(anchor="w", pady=(_scale_px(8, self._root_dpi), 0))
                self.start_button.configure(state="normal")
            elif was_packed:
                self.start_button.pack_forget()
        except tk.TclError:
            pass
        if (should_show != was_packed) and not self._closed and getattr(self, "_ui_ready", False):
            self._sync_scrollregion()

    _REDUNDANT_STATUS_TEXTS = frozenset(
        {
            "",
            "停止中",
            "エンジンに接続中…",
            "日本語変換 ON",
            "英語入力 OFF",
        }
    )

    def _refresh_status_detail(self) -> None:
        if not hasattr(self, "status_detail_var") or not hasattr(self, "_status_detail_label"):
            return
        status_text = self.status.get().strip() if hasattr(self, "status") else ""
        preview_text = self.preview.get().strip() if hasattr(self, "preview") else ""
        parts: list[str] = []
        if status_text and status_text not in self._REDUNDANT_STATUS_TEXTS:
            parts.append(status_text)
        if preview_text:
            parts.append(preview_text)
        detail = "\n".join(parts)
        was_visible = getattr(self, "_status_detail_visible", False)
        self.status_detail_var.set(detail)
        if detail:
            if any(token in detail for token in ("できませんでした", "停止しました")):
                style = "DetailErr.TLabel"
            elif "⚠" in detail:
                style = "DetailWarn.TLabel"
            elif preview_text and not any(token in detail for token in ("削除", "リセット")):
                style = "DetailInfo.TLabel"
            else:
                style = "DetailMuted.TLabel"
            try:
                self._status_detail_label.configure(style=style)
                if self._status_detail_label.winfo_manager() != "pack":
                    self._status_detail_label.pack(
                        anchor="w",
                        fill="x",
                        pady=(_scale_px(4, self._root_dpi), 0),
                    )
                self._status_detail_visible = True
            except tk.TclError:
                pass
            if not self._closed and getattr(self, "_ui_ready", False):
                self._sync_scrollregion()
        else:
            if was_visible:
                try:
                    self._status_detail_label.pack_forget()
                except tk.TclError:
                    pass
                self._status_detail_visible = False
                if not self._closed and getattr(self, "_ui_ready", False):
                    self._sync_scrollregion()

    def _refresh_status_badge(self) -> None:
        if not hasattr(self, "status_badge_var") or not hasattr(self, "_status_badge_label"):
            return
        if self.starting:
            text, style = "● エンジン接続中…", "BadgeWarn.TLabel"
        elif self.hook is None:
            text, style = "● 停止中", "BadgeNeutral.TLabel"
        elif self._blocked_by_uipi and self.enabled:
            text, style = "⚠ 管理者アプリ前面（無効）", "BadgeWarn.TLabel"
        elif self.enabled:
            text, style = "● 日本語変換 ON", "BadgeOk.TLabel"
        else:
            text, style = "● 英語入力 OFF", "BadgeNeutral.TLabel"
        self.status_badge_var.set(text)
        try:
            self._status_badge_label.configure(style=style)
        except tk.TclError:
            pass
        settings_title = f"{APP_NAME} 設定画面"
        title_state = text.lstrip("● ").strip()
        try:
            self.root.title(f"{settings_title} — {title_state}" if title_state else settings_title)
        except tk.TclError:
            pass

    def _cancel_copy_feedback(self) -> None:
        after_id = getattr(self, "_copy_feedback_after_id", None)
        if after_id is not None:
            self._copy_feedback_after_id = None
            try:
                self.root.after_cancel(after_id)
            except tk.TclError:
                pass

    def _clear_copy_feedback(self) -> None:
        if self._closed or not hasattr(self, "copy_feedback_var"):
            return
        self._copy_feedback_after_id = None
        self.copy_feedback_var.set("")
        if self._last_action_bar_mode is not None:
            self._layout_action_bar(mode=self._last_action_bar_mode)
            self._sync_scrollregion()

    def _show_copy_feedback(self, message: str) -> None:
        if not hasattr(self, "copy_feedback_var"):
            return
        self._cancel_copy_feedback()
        self.copy_feedback_var.set(message)
        if self._last_action_bar_mode is not None:
            self._layout_action_bar(mode=self._last_action_bar_mode)
            if not self._closed and getattr(self, "_ui_ready", False):
                self._sync_scrollregion()
        try:
            self._copy_feedback_after_id = self.root.after(
                3500,
                self._clear_copy_feedback,
            )
        except tk.TclError:
            pass

    def _copy_diagnostics(self) -> None:
        folder = self.engine_path.get().strip()
        selected_backend = self.zenzai_backend_var.get()
        diag = diagnose_backend(folder, selected_backend) if folder else None
        high_contrast, dark_mode = system_theme_signature()
        lines = [
            f"{APP_NAME} 診断情報",
            f"状態: {self.status.get()}",
            f"エンジンフォルダー: {folder or '(未設定)'}",
            f"選択バックエンド: {self._format_backend_label(selected_backend)}",
            f"現在の動作バックエンド: {self._format_backend_label(self.runtime.active_backend) if self.runtime else '(停止中)'}",
            f"バックエンド状態: {self.backend_status_var.get()}",
            f"バックエンド診断: {'OK' if (diag and diag.ready) else (diag.reason if diag else 'N/A')}",
            f"Zenzai: {'ON' if self.use_zenzai_var.get() else 'OFF'} / 表示サイズ: {self.ui_scale_var.get()}",
            f"OS設定: HighContrast={high_contrast}, DarkMode={dark_mode}, TextScale={system_text_scale_factor():.2f}, DPI={self._root_dpi}",
        ]
        if self.runtime and self.runtime.fallback_reason:
            lines.append(f"フォールバック理由: {self.runtime.fallback_reason}")
        if self.preview.get():
            lines.append(self.preview.get())
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append("\n".join(lines))
            self.root.update()
            self._show_copy_feedback("✓ 状態と診断情報をクリップボードにコピーしました")
        except tk.TclError:
            self._show_copy_feedback("⚠ クリップボードへのコピーに失敗しました")

    def _on_scale_changed(self) -> None:
        scale = self.ui_scale_var.get()
        self.candidate_popup.set_scale(scale)
        self.corner_toggle.set_scale(scale)
        self._apply_settings_theme(force_wrap=True)
        self._persist_current_settings()

    @staticmethod
    def _normalized_dir(raw: str) -> str:
        cleaned = raw.strip()
        if not cleaned:
            return ""
        try:
            return os.path.normcase(str(Path(cleaned).expanduser().resolve()))
        except OSError:
            return os.path.normcase(cleaned)

    @staticmethod
    def _is_valid_engine_folder(raw: str) -> bool:
        cleaned = raw.strip()
        if not cleaned:
            return False
        try:
            folder = Path(cleaned).expanduser()
            return (folder / "azookey-server.dll").is_file() and (folder / "Dictionary").is_dir()
        except OSError:
            return False

    def _cancel_after_attr(self, attr_name: str) -> None:
        """Cancel and clear a scheduled ``root.after`` callback attribute if set."""
        after_id = getattr(self, attr_name, None)
        if after_id is not None:
            setattr(self, attr_name, None)
            try:
                self.root.after_cancel(after_id)
            except tk.TclError:
                pass

    def _cancel_path_refresh(self) -> None:
        self._cancel_after_attr("_path_refresh_after_id")

    def _cancel_zenzai_refresh(self) -> None:
        self._cancel_after_attr("_zenzai_refresh_after_id")

    def _schedule_engine_path_refresh(self) -> None:
        if self._closed:
            return
        self._cancel_path_refresh()
        try:
            self._path_refresh_after_id = self.root.after(120, self._on_engine_path_changed)
        except tk.TclError:
            pass

    def _on_engine_path_changed(self) -> None:
        self._cancel_path_refresh()
        self._refresh_engine_path_hint()
        self._refresh_backend_status()
        self._update_backend_restart_button()

    def _on_zenzai_profile_edited(self) -> None:
        """Mark the Zenzai profile dirty and debounce applying and saving it."""
        if self._closed:
            return
        self._zenzai_profile_dirty = True
        self._cancel_zenzai_refresh()
        try:
            self._zenzai_refresh_after_id = self.root.after(350, self._on_zenzai_changed)
        except tk.TclError:
            pass

    def _flush_pending_zenzai_change(self, *, persist_only: bool = False) -> None:
        """Apply or persist any uncommitted Zenzai profile edit right away."""
        pending = self._zenzai_profile_dirty or getattr(self, "_zenzai_refresh_after_id", None) is not None
        self._cancel_zenzai_refresh()
        if not pending:
            return
        self._zenzai_profile_dirty = False
        if persist_only:
            self._persist_current_settings()
        else:
            self._on_zenzai_changed()

    def _refresh_zenzai_controls(self) -> None:
        enabled = bool(self.use_zenzai_var.get()) if hasattr(self, "use_zenzai_var") else True
        state = "normal" if enabled else "disabled"
        for rb in getattr(self, "_backend_radios", ()):
            try:
                rb.configure(state=state)
            except tk.TclError:
                pass
        if hasattr(self, "profile_entry"):
            try:
                self.profile_entry.configure(state=state)
            except tk.TclError:
                pass

    def _on_zenzai_changed(self) -> None:
        self._cancel_zenzai_refresh()
        self._zenzai_profile_dirty = False
        enabled = bool(self.use_zenzai_var.get())
        profile = self.zenzai_profile_var.get().strip()
        if self.runtime is not None and self.worker is not None:
            self.worker.update_zenzai_config(
                enabled=enabled,
                profile=profile,
                backend=self.runtime.active_backend,
            )
        elif self.runtime and self.runtime.client:
            try:
                self.runtime.client.set_zenzai_config(
                    enabled=enabled,
                    profile=profile,
                    backend=self.runtime.active_backend,
                )
            except Exception:
                pass
        self._refresh_zenzai_controls()
        self._update_backend_restart_button()
        self._refresh_backend_status()
        self._persist_current_settings()

    @staticmethod
    def _format_backend_label(backend: str) -> str:
        return {
            "cpu": "CPU",
            "vulkan": "Vulkan (GPU)",
            "cuda": "CUDA (NVIDIA)",
        }.get(backend, backend.upper())

    def _set_backend_status(self, text: str, severity: str = "muted") -> None:
        self.backend_status_var.set(text)
        if hasattr(self, "_backend_status_label"):
            style_map = {
                "ok": "Ok.Card.TLabel",
                "warn": "Warn.Card.TLabel",
                "err": "Err.Card.TLabel",
                "muted": "CardMuted.TLabel",
            }
            try:
                self._backend_status_label.configure(style=style_map.get(severity, "CardMuted.TLabel"))
            except tk.TclError:
                pass

    def _refresh_backend_status(self) -> None:
        if not hasattr(self, "backend_status_var"):
            return
        folder = self.engine_path.get().strip()
        selected = self.zenzai_backend_var.get()
        selected_label = self._format_backend_label(selected)
        diag = diagnose_backend(folder, selected) if folder else None
        vulkan_ready = bool(
            folder
            and selected == "cuda"
            and diag is not None
            and not diag.ready
            and diagnose_backend(folder, "vulkan").ready
        )
        vulkan_note = " / Vulkan (GPU) は利用可" if vulkan_ready else ""
        folder_changed = bool(
            folder
            and self._loaded_engine_dir
            and self._normalized_dir(folder) != self._loaded_engine_dir
        )

        if self.runtime is not None:
            active_label = self._format_backend_label(self.runtime.active_backend)
            if folder_changed:
                if not self._is_valid_engine_folder(folder):
                    self._set_backend_status(
                        f"⚠ 動作中: {active_label}（フォルダー不正）",
                        "err",
                    )
                elif diag is not None and not diag.ready:
                    self._set_backend_status(
                        f"⚠ 動作中: {active_label}（{selected_label} 不可: {diag.reason}{vulkan_note}）",
                        "warn",
                    )
                else:
                    self._set_backend_status(
                        f"ℹ 動作中: {active_label}（再起動で新フォルダー）",
                        "muted",
                    )
                return
            if hasattr(self, "use_zenzai_var") and not self.use_zenzai_var.get():
                self._set_backend_status("ℹ Zenzai OFF のため無効中", "muted")
                return
            if (
                self.runtime.requested_backend != self.runtime.active_backend
                and selected == self.runtime.requested_backend
            ):
                req_label = self._format_backend_label(self.runtime.requested_backend)
                reason = self.runtime.fallback_reason
                self._set_backend_status(
                    f"⚠ 動作中: {active_label}（{req_label} 不可: {reason}{vulkan_note}）",
                    "warn",
                )
            elif selected != self.runtime.active_backend:
                if diag is not None and not diag.ready:
                    self._set_backend_status(
                        f"⚠ 動作中: {active_label}（{selected_label} 不可: {diag.reason}{vulkan_note}）",
                        "warn",
                    )
                else:
                    self._set_backend_status(
                        f"ℹ 動作中: {active_label}（再起動で {selected_label}）",
                        "muted",
                    )
            else:
                self._set_backend_status(f"✓ 動作中: {active_label}", "ok")
            return

        if hasattr(self, "use_zenzai_var") and not self.use_zenzai_var.get():
            self._set_backend_status("ℹ Zenzai OFF のため無効中", "muted")
            return

        if diag is not None and not diag.ready:
            self._set_backend_status(f"⚠ {selected_label} 不可: {diag.reason}{vulkan_note}", "warn")
        elif diag is not None and diag.ready:
            self._set_backend_status(f"✓ {selected_label} 利用可能", "ok")
        else:
            self._set_backend_status(f"ℹ {selected_label}（フォルダー指定で診断）", "muted")

    def _pending_engine_restart_reason(self) -> str:
        folder = self.engine_path.get().strip()
        selected = self.zenzai_backend_var.get()
        diag = diagnose_backend(folder, selected) if folder else None
        backend_ready = bool(diag is not None and diag.ready)
        folder_changed = bool(
            folder
            and self._loaded_engine_dir
            and self._normalized_dir(folder) != self._loaded_engine_dir
        )
        if self.runtime is not None:
            active_backend = self.runtime.active_backend
            requested_backend = self.runtime.requested_backend
        elif self._loaded_engine_dir:
            active_backend = self._loaded_backend
            requested_backend = self._loaded_requested_backend
        else:
            return ""
        if folder_changed and self._is_valid_engine_folder(folder):
            return "folder"
        if hasattr(self, "use_zenzai_var") and not self.use_zenzai_var.get():
            return ""
        already_failed_backend = bool(
            requested_backend
            and requested_backend != active_backend
            and selected == requested_backend
        )
        if active_backend and selected != active_backend and not already_failed_backend and backend_ready:
            return "backend"
        return ""

    def _update_backend_restart_button(self) -> None:
        if not hasattr(self, "restart_backend_button"):
            return
        pending = bool(self._pending_engine_restart_reason())
        self.restart_backend_button.configure(
            state="normal" if pending else "disabled",
            style="Accent.TButton" if pending else "Settings.TButton",
        )
        if hasattr(self, "_backend_controls_frame"):
            wide = self._last_backend_wide if self._last_backend_wide is not None else True
            self._layout_backend_row(wide=wide)

    def _on_zenzai_backend_changed(self) -> None:
        self._persist_current_settings()
        self._update_backend_restart_button()
        self._refresh_backend_status()

    def _restart_app(self) -> None:
        self._cancel_zenzai_refresh()
        self._zenzai_profile_dirty = False
        self._persist_current_settings()
        env = os.environ.copy()
        orig_appdata = preferred_appdata_dir()
        if orig_appdata:
            env["APPDATA"] = orig_appdata
        self.close()
        subprocess.Popen([sys.executable, str(Path(__file__).resolve())], env=env, close_fds=True)

    def _on_fullwidth_space_changed(self) -> None:
        if self.hook:
            self.hook.set_fullwidth_space(bool(self.fullwidth_space_var.get()))
        self._persist_current_settings()

    def _on_shift_direct_english_changed(self) -> None:
        enabled = bool(self.shift_direct_english_var.get())
        if self.hook:
            self.hook.set_shift_direct_english(enabled)
        if self.worker:
            self.worker.set_shift_direct_english(enabled)
        self._persist_current_settings()

    def _on_passthrough_changed(self) -> None:
        enabled = bool(self.english_passthrough_var.get())
        pending = self._pending_disable_passthrough
        if pending is not None:
            done, seq, _ = pending
            if not done.is_set():
                self._pending_disable_passthrough = (done, seq, enabled)
            else:
                self._pending_disable_passthrough = None
                self._complete_disable_passthrough_pref(seq, enabled)
        if self.hook:
            self.hook.set_english_passthrough(enabled)
        self._persist_current_settings()

    def _on_tray_setting_changed(self) -> None:
        self._refresh_tray_controls()
        self._persist_current_settings()

    def _current_learning_items(self) -> list[tuple[str, str]]:
        if self.worker is not None:
            getter = getattr(self.worker, "learning_items", None)
            if callable(getter):
                return list(getter())
            raw = getattr(self.worker, "_learning_memory", {})
            return [(str(k), str(v)) for k, v in dict(raw).items() if k and v]
        return list(_load_learning_memory().items())

    def _remove_learning_entries(self, readings: list[str]) -> int:
        targets = [r for r in readings if r]
        if not targets:
            return 0
        removed = 0
        if self.worker is not None:
            remover = getattr(self.worker, "remove_learning_entries", None)
            if callable(remover):
                removed = int(remover(targets))
            else:
                mem = getattr(self.worker, "_learning_memory", None)
                if isinstance(mem, dict):
                    for reading in targets:
                        if reading in mem:
                            mem.pop(reading, None)
                            removed += 1
                    if removed:
                        _save_learning_memory(mem)
        else:
            mem = _load_learning_memory()
            for reading in targets:
                if reading in mem:
                    mem.pop(reading, None)
                    removed += 1
            if removed:
                _save_learning_memory(mem)
        if removed:
            self.learning_count_var.set(f"学習履歴: {len(self._current_learning_items())} 件")
            self._refresh_learning_viewer()
        return removed

    def _set_learning_feedback_visible(self, visible: bool) -> None:
        lbl = self._learning_viewer_widgets.get("feedback_lbl")
        if not isinstance(lbl, ttk.Label):
            return
        try:
            if visible:
                if lbl.winfo_manager() != "grid":
                    lbl.grid(row=3, column=0, sticky="w", pady=(_scale_px(6, self._root_dpi), 0))
            elif lbl.winfo_manager() == "grid":
                lbl.grid_forget()
        except tk.TclError:
            pass

    def _clear_learning_viewer_feedback(self) -> None:
        self._learning_feedback_after_id = None
        var = self._learning_viewer_feedback_var
        if var is not None and not self._closed and self._learning_window is not None:
            var.set("")
            self._set_learning_feedback_visible(False)

    def _cancel_learning_feedback(self) -> None:
        after_id = getattr(self, "_learning_feedback_after_id", None)
        if after_id is not None:
            self._learning_feedback_after_id = None
            try:
                self.root.after_cancel(after_id)
            except tk.TclError:
                pass

    def _show_learning_viewer_feedback(self, message: str) -> None:
        var = self._learning_viewer_feedback_var
        if var is None:
            return
        self._cancel_learning_feedback()
        var.set(message)
        self._set_learning_feedback_visible(bool(message))
        try:
            self._learning_feedback_after_id = self.root.after(
                3500,
                self._clear_learning_viewer_feedback,
            )
        except tk.TclError:
            pass

    def _close_learning_viewer(self) -> None:
        self._cancel_learning_feedback()
        win = self._learning_window
        self._learning_window = None
        self._learning_viewer_widgets.clear()
        self._learning_iid_map.clear()
        self._learning_search_var = None
        self._learning_summary_var = None
        self._learning_viewer_feedback_var = None
        if win is not None:
            try:
                if win.winfo_exists():
                    win.destroy()
            except tk.TclError:
                pass
        if not self._closed and hasattr(self, "view_learning_button"):
            try:
                if self.view_learning_button.winfo_exists():
                    self.view_learning_button.focus_set()
            except tk.TclError:
                pass

    def _apply_learning_viewer_theme(self) -> None:
        win = self._learning_window
        if win is None:
            return
        try:
            if not win.winfo_exists():
                return
        except tk.TclError:
            return
        theme = self._current_settings_theme or system_theme_palette()
        high_contrast, dark_mode = system_theme_signature()
        metrics = self._settings_metrics()
        body_font = ("Yu Gothic UI", metrics["body_font"])
        apply_window_dark_titlebar(_top_window_hwnd(win), dark_mode and not high_contrast)
        win.configure(bg=theme["settings_bg"])

        search_entry = self._learning_viewer_widgets.get("search_entry")
        if isinstance(search_entry, ttk.Entry):
            try:
                search_entry.configure(font=body_font)
            except tk.TclError:
                pass

        tree = self._learning_viewer_widgets.get("tree")
        if isinstance(tree, ttk.Treeview):
            extra = max(1.0, metrics["body_font"] / 10.0)
            try:
                tree.column("order", width=_scale_px(round(58 * extra), self._root_dpi), minwidth=_scale_px(44, self._root_dpi))
                odd_bg = theme["settings_input_bg"] if high_contrast else theme["settings_card_bg"]
                tree.tag_configure("odd", background=odd_bg, foreground=theme["settings_input_fg"])
                tree.tag_configure("even", background=theme["settings_input_bg"], foreground=theme["settings_input_fg"])
            except tk.TclError:
                pass
        try:
            win_w = win.winfo_width()
            self._layout_learning_viewer_footer(win_w if win_w > 1 else _scale_px(560, self._root_dpi))
        except tk.TclError:
            pass

    def _layout_learning_viewer_footer(self, width: int) -> None:
        if width < 180 or not self._learning_viewer_widgets:
            return
        wrap = max(200, width - _scale_px(28, self._root_dpi))
        for key in ("summary_lbl", "feedback_lbl"):
            lbl = self._learning_viewer_widgets.get(key)
            if isinstance(lbl, ttk.Label):
                try:
                    lbl.configure(wraplength=wrap)
                except tk.TclError:
                    pass
        btn_row = self._learning_viewer_widgets.get("btn_row")
        copy_btn = self._learning_viewer_widgets.get("copy_btn")
        delete_btn = self._learning_viewer_widgets.get("delete_btn")
        refresh_btn = self._learning_viewer_widgets.get("refresh_btn")
        reset_btn = self._learning_viewer_widgets.get("reset_btn")
        if not all(isinstance(w, tk.Widget) for w in (btn_row, copy_btn, delete_btn, refresh_btn, reset_btn)):
            return
        extra = max(1.0, self._settings_metrics()["body_font"] / 10.0)
        wide = width >= _scale_px(round(460 * extra), self._root_dpi)
        gap = _scale_px(6, self._root_dpi)
        for btn in (copy_btn, delete_btn, refresh_btn, reset_btn):
            btn.grid_forget()  # type: ignore[union-attr]
        for col in range(5):
            btn_row.columnconfigure(col, weight=0)  # type: ignore[union-attr]
        if wide:
            btn_row.columnconfigure(3, weight=1)  # type: ignore[union-attr]
            copy_btn.grid(row=0, column=0, sticky="w", padx=(0, gap))  # type: ignore[union-attr]
            delete_btn.grid(row=0, column=1, sticky="w", padx=(0, gap))  # type: ignore[union-attr]
            refresh_btn.grid(row=0, column=2, sticky="w")  # type: ignore[union-attr]
            reset_btn.grid(row=0, column=4, sticky="e")  # type: ignore[union-attr]
        else:
            btn_row.columnconfigure(2, weight=1)  # type: ignore[union-attr]
            copy_btn.grid(row=0, column=0, sticky="w", padx=(0, gap))  # type: ignore[union-attr]
            delete_btn.grid(row=0, column=1, sticky="w", padx=(0, gap))  # type: ignore[union-attr]
            refresh_btn.grid(row=0, column=2, sticky="w")  # type: ignore[union-attr]
            reset_btn.grid(row=1, column=0, sticky="w", pady=(gap, 0))  # type: ignore[union-attr]

    def _selected_learning_entries(self) -> list[tuple[int, str, str]]:
        tree = self._learning_viewer_widgets.get("tree")
        if not isinstance(tree, ttk.Treeview):
            return []
        entries: list[tuple[int, str, str]] = []
        for iid in tree.selection():
            row = self._learning_iid_map.get(iid)
            if row is not None:
                entries.append(row)
        return entries

    def _update_learning_viewer_actions(self) -> None:
        has_sel = bool(self._selected_learning_entries())
        sel_state = "normal" if has_sel else "disabled"
        for key in ("copy_btn", "delete_btn"):
            btn = self._learning_viewer_widgets.get(key)
            if isinstance(btn, ttk.Button):
                try:
                    btn.configure(state=sel_state)
                except tk.TclError:
                    pass
        clear_btn = self._learning_viewer_widgets.get("clear_btn")
        if isinstance(clear_btn, ttk.Button) and self._learning_search_var is not None:
            try:
                clear_btn.configure(state="normal" if self._learning_search_var.get() else "disabled")
            except tk.TclError:
                pass

    def _sort_learning_viewer(self, col: str) -> None:
        if self._learning_sort_col == col:
            self._learning_sort_desc = not self._learning_sort_desc
        else:
            self._learning_sort_col = col
            self._learning_sort_desc = col == "order"
        self._refresh_learning_viewer()

    def _refresh_learning_viewer(
        self,
        *,
        focus_first: bool = False,
        items_override: list[tuple[str, str]] | None = None,
    ) -> None:
        win = self._learning_window
        tree = self._learning_viewer_widgets.get("tree")
        if win is None or not isinstance(tree, ttk.Treeview):
            return
        try:
            if not win.winfo_exists():
                return
        except tk.TclError:
            return

        prev_selected = {row[1] for row in self._selected_learning_entries()}
        prev_children = list(tree.get_children())
        prev_focus_iid = tree.focus() or next(iter(tree.selection()), "")
        prev_focus_idx = prev_children.index(prev_focus_iid) if prev_focus_iid in prev_children else 0
        raw_items = list(items_override) if items_override is not None else self._current_learning_items()
        total = len(raw_items)
        # raw_items is oldest -> newest; assign recency rank 1 to most recent entry.
        ranked = [
            (total - idx, reading, candidate)
            for idx, (reading, candidate) in enumerate(raw_items)
        ]

        query = self._learning_search_var.get().strip().casefold() if self._learning_search_var is not None else ""
        if query:
            filtered = [
                row
                for row in ranked
                if query in row[1].casefold() or query in row[2].casefold()
            ]
        else:
            filtered = ranked

        col = self._learning_sort_col
        desc = self._learning_sort_desc
        if col == "order":
            # rank 1 = newest; descending means newest-first (ascending rank)
            filtered.sort(key=lambda r: r[0], reverse=not desc)
        elif col == "reading":
            filtered.sort(key=lambda r: (r[1].casefold(), r[1], r[0]), reverse=desc)
        else:
            filtered.sort(key=lambda r: (r[2].casefold(), r[2], r[0]), reverse=desc)

        col_titles = {"order": "#", "reading": "読み", "candidate": "変換候補"}
        arrow = " ▼" if desc else " ▲"
        for cid, label in col_titles.items():
            tree.heading(cid, text=f"{label}{arrow if cid == col else ''}")

        tree.delete(*tree.get_children())
        self._learning_iid_map.clear()
        restore_iids: list[str] = []
        for row_idx, (rank, reading, candidate) in enumerate(filtered):
            tag = "even" if row_idx % 2 == 0 else "odd"
            iid = tree.insert("", "end", values=(rank, reading, candidate), tags=(tag,))
            self._learning_iid_map[iid] = (rank, reading, candidate)
            if reading in prev_selected:
                restore_iids.append(iid)

        children = tree.get_children()
        if restore_iids:
            tree.selection_set(restore_iids)
            tree.focus(restore_iids[0])
        elif children:
            fallback_idx = (
                0
                if (focus_first or not prev_selected)
                else min(prev_focus_idx, len(children) - 1)
            )
            fallback_iid = children[fallback_idx]
            tree.selection_set(fallback_iid)
            tree.focus(fallback_iid)
            tree.see(fallback_iid)

        if self._learning_summary_var is not None:
            if total == 0:
                self._learning_summary_var.set("学習履歴はまだありません（候補一覧から選択・確定すると記録されます）")
            elif query:
                self._learning_summary_var.set(
                    f"表示: {len(filtered)} / 全 {total} 件（絞り込み中）"
                    if filtered
                    else f"一致なし（全 {total} 件中）"
                )
            elif col == "order" and desc:
                self._learning_summary_var.set(f"全 {total} 件（新しい順・最大 {_LEARNING_LIMIT} 件）")
            else:
                self._learning_summary_var.set(f"全 {total} 件（{col_titles.get(col, '')}{'降順' if desc else '昇順'}）")
        self._update_learning_viewer_actions()

    def _copy_selected_learning_entries(self) -> str:
        selected = self._selected_learning_entries()
        if not selected:
            return "break"
        lines = [f"{reading}\t{candidate}" for _rank, reading, candidate in selected]
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append("\n".join(lines))
            self.root.update()
            if len(selected) == 1:
                _r, reading, candidate = selected[0]
                self._show_learning_viewer_feedback(f"✓ 「{reading} → {candidate}」をコピーしました")
            else:
                self._show_learning_viewer_feedback(f"✓ {len(selected)} 件をクリップボードにコピーしました")
        except tk.TclError:
            self._show_learning_viewer_feedback("⚠ クリップボードへのコピーに失敗しました")
        return "break"

    def _delete_selected_learning_entries(self) -> str:
        selected = self._selected_learning_entries()
        win = self._learning_window
        if not selected or win is None:
            return "break"
        if len(selected) == 1:
            _rank, reading, candidate = selected[0]
            prompt = f"学習履歴「{reading} → {candidate}」を削除しますか？"
        else:
            prompt = f"選択中の学習履歴 {len(selected)} 件を削除しますか？"
        if not messagebox.askyesno("学習履歴を削除", prompt, parent=win):
            return "break"
        removed = self._remove_learning_entries([reading for _rank, reading, _cand in selected])
        if removed:
            self._show_learning_viewer_feedback(f"✓ {removed} 件の学習履歴を削除しました")
            self.status.set(f"学習履歴を {removed} 件削除しました。")
        return "break"

    def _open_learning_viewer(self) -> None:
        """Open (or focus) the accessible window to browse, filter, and manage learning history."""
        existing = self._learning_window
        if existing is not None:
            try:
                if existing.winfo_exists():
                    existing.deiconify()
                    existing.lift()
                    self._refresh_learning_viewer()
                    search_entry = self._learning_viewer_widgets.get("search_entry")
                    if isinstance(search_entry, tk.Widget):
                        search_entry.focus_set()
                    return
            except tk.TclError:
                pass
            self._learning_window = None

        win = tk.Toplevel(self.root)
        self._learning_window = win
        self._learning_viewer_widgets.clear()
        self._learning_iid_map.clear()

        text_scale = _text_scale_multiplier()
        left, top, right, bottom = monitor_work_area(_top_window_hwnd(self.root))
        work_w = max(480, right - left)
        work_h = max(360, bottom - top)
        init_w = min(work_w - 40, _scale_px(round(580 * text_scale), self._root_dpi))
        init_h = min(work_h - 40, _scale_px(round(500 * text_scale), self._root_dpi))
        x = left + max(16, (work_w - init_w) // 2)
        y = top + max(16, (work_h - init_h) // 2)
        win.title(f"学習履歴 — {APP_NAME}")
        win.geometry(f"{init_w}x{init_h}+{x}+{y}")
        win.minsize(
            min(init_w, _scale_px(380, self._root_dpi)),
            min(init_h, _scale_px(300, self._root_dpi)),
        )
        win.protocol("WM_DELETE_WINDOW", self._close_learning_viewer)

        pad = _scale_px(12, self._root_dpi)
        outer = ttk.Frame(win, style="Settings.TFrame", padding=pad)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(2, weight=1)

        # Row 0: Search bar
        search_row = ttk.Frame(outer, style="Settings.TFrame")
        search_row.grid(row=0, column=0, sticky="ew", pady=(0, _scale_px(6, self._root_dpi)))
        search_row.columnconfigure(1, weight=1)

        search_lbl = ttk.Label(
            search_row,
            text="検索:",
            style="Viewer.TLabel",
        )
        search_lbl.grid(row=0, column=0, sticky="w", padx=(0, _scale_px(8, self._root_dpi)))
        self._learning_search_var = tk.StringVar(master=win, value="")
        search_entry = ttk.Entry(search_row, textvariable=self._learning_search_var, style="Settings.TEntry")
        search_entry.grid(row=0, column=1, sticky="ew")
        self._bind_entry_shortcuts(search_entry)
        self._bind_label_target(search_lbl, search_entry)

        clear_btn = ttk.Button(
            search_row,
            text="クリア",
            style="Settings.TButton",
            command=lambda: (
                self._learning_search_var.set("") if self._learning_search_var is not None else None,
                search_entry.focus_set(),
            ),
        )
        clear_btn.grid(row=0, column=2, padx=(_scale_px(6, self._root_dpi), 0))
        self._learning_search_var.trace_add("write", lambda *_: self._refresh_learning_viewer())

        # Row 1: Count & sort summary
        self._learning_summary_var = tk.StringVar(master=win, value="")
        summary_lbl = ttk.Label(outer, textvariable=self._learning_summary_var, style="ViewerMuted.TLabel")
        summary_lbl.grid(row=1, column=0, sticky="w", pady=(0, _scale_px(6, self._root_dpi)))

        # Row 2: Sortable multi-select history table
        table_frame = ttk.Frame(outer, style="Settings.TFrame")
        table_frame.grid(row=2, column=0, sticky="nsew")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)

        tree = ttk.Treeview(
            table_frame,
            columns=("order", "reading", "candidate"),
            show="headings",
            style="Settings.Treeview",
            selectmode="extended",
        )
        tree.column("order", anchor="e", stretch=False, width=_scale_px(58, self._root_dpi))
        tree.column("reading", anchor="w", stretch=True, width=_scale_px(180, self._root_dpi), minwidth=_scale_px(90, self._root_dpi))
        tree.column("candidate", anchor="w", stretch=True, width=_scale_px(240, self._root_dpi), minwidth=_scale_px(110, self._root_dpi))
        for cid, heading_lbl in (("order", "#"), ("reading", "読み"), ("candidate", "変換候補")):
            tree.heading(cid, text=heading_lbl, command=lambda c=cid: self._sort_learning_viewer(c))

        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview, style="Vertical.TScrollbar")
        tree.configure(yscrollcommand=vsb.set)
        tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")

        # Row 3: Action feedback (shown only while feedback is active)
        self._learning_viewer_feedback_var = tk.StringVar(master=win, value="")
        feedback_lbl = ttk.Label(outer, textvariable=self._learning_viewer_feedback_var, style="ViewerOk.TLabel")

        # Row 4: Footer buttons
        btn_row = ttk.Frame(outer, style="Settings.TFrame")
        btn_row.grid(row=4, column=0, sticky="ew", pady=(_scale_px(8, self._root_dpi), 0))

        def _viewer_btn(text: str, command, *, style: str = "Settings.TButton") -> ttk.Button:
            return ttk.Button(
                btn_row,
                text=text,
                style=style,
                command=command,
            )

        copy_btn = _viewer_btn(
            "コピー",
            self._copy_selected_learning_entries,
            style="Warn.TButton",
        )
        delete_btn = _viewer_btn(
            "削除…",
            self._delete_selected_learning_entries,
            style="Danger.TButton",
        )
        refresh_btn = _viewer_btn(
            "再読込",
            lambda: (self._refresh_learning_viewer(), self._show_learning_viewer_feedback("✓ 学習履歴を再読込しました")),
        )
        reset_btn = _viewer_btn(
            "全リセット…",
            lambda: self._reset_learning_history(parent=win),
            style="Danger.TButton",
        )

        self._learning_viewer_widgets.update(
            {
                "search_entry": search_entry,
                "clear_btn": clear_btn,
                "summary_lbl": summary_lbl,
                "tree": tree,
                "feedback_lbl": feedback_lbl,
                "btn_row": btn_row,
                "copy_btn": copy_btn,
                "delete_btn": delete_btn,
                "refresh_btn": refresh_btn,
                "reset_btn": reset_btn,
            }
        )
        win.bind("<Configure>", lambda e: self._layout_learning_viewer_footer(e.width) if e.widget is win else None)

        # Keyboard shortcuts for fast accessible browsing
        tree.bind("<<TreeviewSelect>>", lambda _e: self._update_learning_viewer_actions())
        tree.bind(
            "<Control-a>",
            lambda _e: (tree.selection_set(tree.get_children()), self._update_learning_viewer_actions(), "break")[-1],
        )
        tree.bind(
            "<Control-A>",
            lambda _e: (tree.selection_set(tree.get_children()), self._update_learning_viewer_actions(), "break")[-1],
        )
        tree.bind("<Control-c>", lambda _e: self._copy_selected_learning_entries())
        tree.bind("<Control-C>", lambda _e: self._copy_selected_learning_entries())
        tree.bind("<Delete>", lambda _e: self._delete_selected_learning_entries())
        tree.bind(
            "<Double-Button-1>",
            lambda e: self._copy_selected_learning_entries()
            if tree.identify_region(e.x, e.y) == "cell"
            else None,
        )
        tree.bind("<Return>", lambda _e: self._copy_selected_learning_entries())

        win.bind("<Escape>", lambda _e: (self._close_learning_viewer(), "break")[-1])
        win.bind(
            "<F5>",
            lambda _e: (self._refresh_learning_viewer(), self._show_learning_viewer_feedback("✓ 学習履歴を再読込しました"), "break")[-1],
        )
        for seq in ("<Control-f>", "<Control-F>"):
            win.bind(seq, lambda _e: (search_entry.focus_set(), search_entry.selection_range(0, "end"), "break")[-1])

        self._apply_learning_viewer_theme()
        self._refresh_learning_viewer(focus_first=True)
        search_entry.focus_set()

    def _reset_learning_history(self, *, parent: tk.Misc | None = None) -> None:
        if not messagebox.askyesno(
            "学習履歴をリセット",
            "保存されている変換の学習履歴をすべて削除しますか？",
            parent=parent or self.root,
        ):
            return
        if self.worker:
            self.worker.submit(InputEvent("clear_learning", 0))
            self.learning_count_var.set("学習履歴: 0 件")
        else:
            _save_learning_memory({})
            self.learning_count_var.set("学習履歴: 0 件")
        self._refresh_learning_viewer(items_override=[])
        self._show_learning_viewer_feedback("✓ 学習履歴をすべてリセットしました")
        self.status.set("学習履歴をリセットしました。")

    def _own_hwnds(self) -> set[int]:
        own = _window_hwnds(self.root)
        own.update(_window_hwnds(getattr(self, "_learning_window", None)))
        for child_name in ("candidate_popup", "corner_toggle"):
            child = getattr(self, child_name, None)
            if child is not None:
                own.update(_window_hwnds(getattr(child, "window", None)))
        return own

    def _toggle_anchor_hwnd(self) -> int:
        fg = foreground_window()
        own = self._own_hwnds()
        if fg and fg not in own:
            return fg
        if self.worker and self.worker._target and self.worker._target not in own:
            return self.worker._target
        return _top_window_hwnd(self.root)

    def _on_toggle_moved(self, _pos: tuple[int, int] | None) -> None:
        self._persist_current_settings()

    def _reset_toggle_position(self) -> None:
        self.corner_toggle.reset_position()

    def _hide_to_tray(self) -> None:
        self._flush_pending_zenzai_change()
        self.root.withdraw()

    def _show_settings_window(self) -> None:
        self.root.deiconify()
        try:
            self.root.state("normal")
        except tk.TclError:
            pass
        self.root.lift()
        focus_window(_top_window_hwnd(self.root))
        self._refresh_status_and_indicators(force=True)

    def _on_close_requested(self) -> None:
        if self.minimize_to_tray_var.get() and self.tray_icon.active:
            self._hide_to_tray()
            return
        self.close()

    def _hook_input_seq(self) -> int:
        seq_fn = getattr(self.hook, "current_input_seq", None)
        if callable(seq_fn):
            raw = seq_fn()
            if isinstance(raw, int):
                return raw
        return 0

    def _on_candidate_clicked(self, index: int) -> None:
        if not self.worker or not self.candidate_popup.target:
            return
        shown_seq = getattr(self.candidate_popup, "_shown_seq", 0)
        seq = self._hook_input_seq()
        if self.hook:
            begin_click = getattr(self.hook, "try_begin_candidate_click", None)
            if callable(begin_click):
                result = begin_click(shown_seq)
                if result is None:
                    return
                if isinstance(result, int) and not isinstance(result, bool):
                    seq = result
                else:
                    self.hook.mark_selecting(False)
            else:
                self.hook.mark_selecting(False)
        self.worker.submit(
            InputEvent("select_commit", self.candidate_popup.target, str(index), seq=seq)
        )

    def _on_candidate_scrolled(self, direction: str) -> None:
        target = self.candidate_popup.target
        if not self.worker or not target:
            return
        shown_seq = getattr(self.candidate_popup, "_shown_seq", 0)
        seq = self._hook_input_seq()
        if self.hook:
            begin_scroll = getattr(self.hook, "try_begin_candidate_scroll", None)
            if callable(begin_scroll):
                result = begin_scroll(shown_seq)
                if result is None:
                    return
                if isinstance(result, int) and not isinstance(result, bool):
                    seq = result
                    if shown_seq > 0 and self.candidate_popup.target == target:
                        self.candidate_popup._shown_seq = seq
        self.worker.submit(
            InputEvent("cycle", target, direction, seq=seq)
        )

    def _browse(self) -> None:
        chosen = filedialog.askdirectory(title="AzooKey エンジンのフォルダーを選択")
        if chosen:
            self.engine_path.set(chosen)
            self._on_engine_path_changed()

    def _start(self) -> None:
        if self.starting:
            return
        self._on_engine_path_changed()
        folder = self.engine_path.get().strip()
        if not folder:
            messagebox.showinfo("エンジンの場所", "azookey-server.dll があるフォルダーを選んでください。")
            return
        if self.runtime is None and self._pending_engine_restart_reason():
            self._restart_app()
            return
        self.starting = True
        self._refresh_connect_button()
        self.status.set("エンジンに接続中…")
        self._refresh_status_badge()
        passthrough = bool(self.english_passthrough_var.get())
        fullwidth_space = bool(self.fullwidth_space_var.get())
        shift_direct_english = bool(self.shift_direct_english_var.get())
        self._flush_pending_zenzai_change(persist_only=True)
        use_zenzai = bool(self.use_zenzai_var.get())
        zenzai_profile = self.zenzai_profile_var.get().strip()
        zenzai_backend = self.zenzai_backend_var.get()
        self._start_zenzai_snapshot = (use_zenzai, zenzai_profile)
        threading.Thread(
            target=self._start_background,
            args=(
                folder,
                passthrough,
                fullwidth_space,
                shift_direct_english,
                use_zenzai,
                zenzai_profile,
                zenzai_backend,
            ),
            daemon=True,
        ).start()

    def _cleanup_session(self, *, commit_pending: bool = False) -> None:
        self._pending_disable_passthrough = None
        hook = self.hook
        worker = self.worker
        runtime = self.runtime
        self.hook = None
        self.worker = None
        self.runtime = None
        _dispose_session(runtime, worker, hook, commit_pending=commit_pending)

    def _start_background(
        self,
        folder: str,
        passthrough: bool,
        fullwidth_space: bool,
        shift_direct_english: bool,
        use_zenzai: bool,
        zenzai_profile: str,
        zenzai_backend: str,
    ) -> None:
        runtime = AzooKeyRuntime()
        hook: KeyboardHook | None = None
        worker: CompositionWorker | None = None
        try:
            client = runtime.start(
                folder,
                use_zenzai=use_zenzai,
                zenzai_profile=zenzai_profile,
                zenzai_backend=zenzai_backend,
            )
            with self._lifecycle_lock:
                if self._closed:
                    _dispose_session(runtime, worker, hook)
                    return
            events: queue.Queue[InputEvent | tuple[object, ...] | None] = queue.Queue()
            hook = KeyboardHook(events)
            hook.set_english_passthrough(passthrough)
            hook.set_fullwidth_space(fullwidth_space)
            hook.set_shift_direct_english(shift_direct_english)
            worker = CompositionWorker(
                client,
                hook,
                self.ui_events,
                events,
                learning_memory=_load_learning_memory(),
            )
            worker.set_shift_direct_english(shift_direct_english)
            worker.start()
            hook.start()
            hook.set_english(False)
            hook.set_active(True)
            with self._lifecycle_lock:
                if not self._closed:
                    self.ui_events.put(("ready", (runtime, worker, hook)))
                    return
            _dispose_session(runtime, worker, hook)
        except Exception as exc:
            _dispose_session(runtime, worker, hook)
            with self._lifecycle_lock:
                if not self._closed:
                    self.ui_events.put(("start_error", str(exc)))

    def _toggle(self) -> None:
        if not self.hook:
            return
        self._set_enabled(not self.enabled)

    def _apply_enabled_ui(self, enabled: bool) -> None:
        self.enabled = enabled
        if self.worker:
            self.worker.set_shift_direct_english(bool(self.shift_direct_english_var.get()))
        self._refresh_connect_button()
        self.status.set(self._default_status_message())
        self._refresh_status_and_indicators(force=True)

    def _complete_disable_passthrough_pref(self, seq: int | None, enabled: bool) -> None:
        if not self.hook:
            return
        complete_fn = getattr(self.hook, "complete_disable_passthrough", None)
        if callable(complete_fn) and seq is not None:
            complete_fn(seq, enabled=enabled)
            return
        english_ev = getattr(self.hook, "english", None)
        if english_ev is None or english_ev.is_set():
            self.hook.set_english_passthrough(enabled)

    def _flush_deferred_passthrough(self) -> None:
        if not self.hook:
            self._pending_disable_passthrough = None
            return
        flush_fn = getattr(self.hook, "flush_pending_passthrough_restore", None)
        if callable(flush_fn):
            flush_fn()
        pending = self._pending_disable_passthrough
        if pending is None:
            return
        done, seq, pref = pending
        english_ev = getattr(self.hook, "english", None)
        if english_ev is not None and not english_ev.is_set():
            self._pending_disable_passthrough = None
            return
        if done.is_set():
            self._pending_disable_passthrough = None
            self._complete_disable_passthrough_pref(seq, pref)

    def _set_enabled(self, enabled: bool) -> None:
        self._pending_disable_passthrough = None
        if self.hook:
            if enabled:
                set_mode = getattr(self.hook, "set_mode", None)
                if callable(set_mode):
                    set_mode(active=True, english=False)
                else:
                    self.hook.set_active(True)
                    self.hook.set_english(False)
                self.hook.set_english_passthrough(bool(self.english_passthrough_var.get()))
                self.hook.set_fullwidth_space(bool(self.fullwidth_space_var.get()))
                self.hook.set_shift_direct_english(bool(self.shift_direct_english_var.get()))
                suppress_native_ime(foreground_window())
            else:
                seq: int | None = None
                had_atomic_disable = False
                worker_thread = getattr(self.worker, "_thread", None) if self.worker else None
                live_worker = isinstance(worker_thread, threading.Thread) and worker_thread.is_alive()
                done: threading.Event | None = threading.Event() if (self.worker and live_worker) else None
                if self.worker:
                    begin_disable = getattr(self.hook, "try_begin_disable_commit", None)
                    if callable(begin_disable):
                        try:
                            res = begin_disable(
                                deactivate=True,
                                suppress_passthrough=live_worker,
                                completed=done,
                            )
                        except TypeError:
                            try:
                                res = begin_disable(deactivate=True, suppress_passthrough=live_worker)
                            except TypeError:
                                res = begin_disable()
                        if res is None or (isinstance(res, int) and not isinstance(res, bool)):
                            had_atomic_disable = True
                            seq = res
                if self.worker:
                    if had_atomic_disable:
                        if seq is not None:
                            self.worker.submit(InputEvent("commit", foreground_window(), completed=done, seq=seq))
                        else:
                            done = None
                    else:
                        done = None
                        self.worker.submit(InputEvent("commit", foreground_window(), seq=self._hook_input_seq()))
                passthrough_pref = bool(self.english_passthrough_var.get())
                self.hook.set_fullwidth_space(bool(self.fullwidth_space_var.get()))
                self.hook.set_shift_direct_english(bool(self.shift_direct_english_var.get()))
                if not had_atomic_disable:
                    set_mode = getattr(self.hook, "set_mode", None)
                    if callable(set_mode):
                        set_mode(active=False, english=True)
                    else:
                        self.hook.set_active(False)
                        self.hook.set_english(True)
                    self.hook.set_english_passthrough(passthrough_pref)
                elif done is not None:
                    finished = done.wait(timeout=0.22)
                    if finished:
                        self._complete_disable_passthrough_pref(seq, passthrough_pref)
                    elif seq is not None:
                        self._pending_disable_passthrough = (done, seq, passthrough_pref)
                else:
                    english_ev = getattr(self.hook, "english", None)
                    if english_ev is None or english_ev.is_set():
                        self.hook.set_english_passthrough(passthrough_pref)
        self._apply_enabled_ui(enabled)

    def _default_status_message(self) -> str:
        if self.starting:
            return "エンジンに接続中…"
        if self.hook is None:
            return "停止中"
        if self.enabled:
            return "日本語変換 ON"
        return "英語入力 OFF"

    def _refresh_status_and_indicators(self, *, force: bool = False) -> None:
        available = self.hook is not None
        fg = foreground_window()
        own = self._own_hwnds()
        blocked = bool(available and self.enabled and fg and fg not in own and is_window_elevated(fg))
        if blocked and not self._blocked_by_uipi:
            self.status.set("⚠ 管理者アプリ前面（通常権限からは入力不可）")
        elif not blocked and self._blocked_by_uipi:
            self.status.set(self._default_status_message())
        self._blocked_by_uipi = blocked

        anchor_hwnd = self._toggle_anchor_hwnd()
        monitor_id = None if self.corner_toggle.custom_position is not None else monitor_for_window(anchor_hwnd)
        now = time.monotonic()
        if force or self._cached_os_theme_sig is None or (now - self._last_os_theme_check) >= _OS_THEME_POLL_INTERVAL:
            self._cached_os_theme_sig = system_theme_signature()
            self._cached_os_text_scale = system_text_scale_factor()
            self._last_os_theme_check = now
        theme_sig = self._cached_os_theme_sig
        text_scale = self._cached_os_text_scale
        settings_theme_sig = (
            theme_sig[0],
            theme_sig[1],
            self.ui_scale_var.get(),
            text_scale,
        )
        if settings_theme_sig != self._last_settings_theme_sig:
            self._apply_settings_theme(force_wrap=True)
            self.candidate_popup.set_scale(self.ui_scale_var.get())
        self._refresh_status_badge()
        toggle_sig: tuple[object, ...] = (
            self.enabled,
            available,
            blocked,
            monitor_id,
            self.corner_toggle.custom_position,
            theme_sig,
            _text_scale_multiplier(text_scale),
        )
        if force or getattr(self.corner_toggle, "_reposition_failed", False) or toggle_sig != self._last_toggle_signature:
            self.corner_toggle.update(enabled=self.enabled, available=available, blocked=blocked)
            if not getattr(self.corner_toggle, "_reposition_failed", False):
                self._last_toggle_signature = toggle_sig

        if self.tray_icon.active:
            if not available:
                tray_state, tooltip = "disabled", f"{APP_NAME} (停止中)"
            elif blocked:
                tray_state, tooltip = "blocked", f"{APP_NAME} (管理者アプリ前面のため無効)"
            elif self.enabled:
                tray_state, tooltip = "on", f"{APP_NAME} (ライブ変換 ON)"
            else:
                tray_state, tooltip = "off", f"{APP_NAME} (英語モード OFF)"
            tray_sig: tuple[object, ...] = (tray_state, self.enabled, tooltip)
            if force or tray_sig != self._last_tray_signature:
                self.tray_icon.update_state(tray_state, self.enabled, tooltip)
                self._last_tray_signature = tray_sig

    def _detach_hook_composing(self, fg: int, *, if_fg_differs: int = 0) -> bool:
        if not self.worker or not self.hook:
            return False
        detach = getattr(self.hook, "try_detach_composing", None)
        if callable(detach):
            res = detach(if_fg_differs=if_fg_differs) if if_fg_differs else detach()
            if isinstance(res, int) and not isinstance(res, bool):
                self.worker.submit(InputEvent("detach_commit", fg, seq=res))
                return True
            if res is None:
                return False
        if not self.hook.composing.is_set():
            return False
        if if_fg_differs:
            raw_hook_target = getattr(self.hook, "_composing_hwnd", 0)
            hook_target = raw_hook_target if isinstance(raw_hook_target, int) and raw_hook_target else 0
            target = hook_target or self.worker._target
            if not target or if_fg_differs == target:
                return False
        seq = self._hook_input_seq()
        self.hook.mark_composing(False)
        self.worker.submit(InputEvent("detach_commit", fg, seq=seq))
        return True

    def _check_mouse_activity(self) -> None:
        is_down = mouse_button_pressed()
        if is_down and not self._was_mouse_down:
            pt = cursor_point()
            if pt is not None:
                mx, my = pt
                if not self.candidate_popup.contains_point(mx, my) and not self.corner_toggle.contains_point(mx, my):
                    fg = foreground_window()
                    if fg:
                        self._last_click_target = (fg, mx, my + 18)
                    if self.worker and self.hook:
                        if not self._detach_hook_composing(fg):
                            clear_ctx = getattr(self.hook, "try_clear_context", None)
                            if callable(clear_ctx):
                                cleared = clear_ctx()
                                if cleared is True:
                                    self.worker.submit(InputEvent("clear_context", fg))
                                elif cleared is not False and self.hook.has_context.is_set():
                                    self.hook.mark_has_context(False)
                                    self.worker.submit(InputEvent("clear_context", fg))
                            elif self.hook.has_context.is_set():
                                self.hook.mark_has_context(False)
                                self.worker.submit(InputEvent("clear_context", fg))
        self._was_mouse_down = is_down

    def _fallback_point_for_hwnd(self, hwnd: int) -> tuple[int, int] | None:
        if self._last_click_target is not None and self._last_click_target[0] == hwnd:
            return self._last_click_target[1], self._last_click_target[2]
        return None

    def _poll_ui(self) -> None:
        self._cancel_poll_timer()
        if self._closed:
            return
        try:
            self._flush_deferred_passthrough()
            try:
                self._check_mouse_activity()
                if self.worker and self.hook and self.hook.composing.is_set():
                    fg = foreground_window()
                    popup_hwnds = _window_hwnds(self.candidate_popup.window)
                    if fg and fg not in popup_hwnds:
                        raw_hook_target = getattr(self.hook, "_composing_hwnd", 0)
                        hook_target = raw_hook_target if isinstance(raw_hook_target, int) and raw_hook_target else 0
                        if hook_target:
                            self._detach_hook_composing(fg, if_fg_differs=fg)
                        elif self.worker._target and fg != self.worker._target:
                            self._detach_hook_composing(fg)
            except (OSError, tk.TclError):
                pass
            popup_hide_first = False
            popup_update_pending = False
            popup_update = None
            while True:
                try:
                    kind, value = self.ui_events.get_nowait()
                except queue.Empty:
                    break
                if kind == "ready":
                    runtime, worker, hook = value  # type: ignore[misc]
                    if self._closed:
                        _dispose_session(runtime, worker, hook)
                        continue
                    self._cleanup_session()
                    self.runtime, self.worker, self.hook = runtime, worker, hook
                    set_ignored_mouse = getattr(self.hook, "set_ignored_mouse_hwnds", None)
                    if callable(set_ignored_mouse):
                        try:
                            set_ignored_mouse(
                                (int(self.candidate_popup.window.winfo_id()), int(self.corner_toggle.window.winfo_id()))
                            )
                        except tk.TclError:
                            pass
                    self._loaded_engine_dir = self._normalized_dir(
                        str(self.runtime.engine_dir or self.engine_path.get())
                    )
                    self._loaded_backend = self.runtime.active_backend
                    self._loaded_requested_backend = self.runtime.requested_backend
                    self.starting = False
                    self._refresh_connect_button()
                    self.learning_count_var.set(f"学習履歴: {len(self.worker._learning_memory)} 件")
                    self._refresh_learning_viewer()
                    self._persist_current_settings()
                    self._set_enabled(True)
                    snapshot = self._start_zenzai_snapshot
                    self._start_zenzai_snapshot = None
                    if snapshot is not None:
                        current_zenzai = (
                            bool(self.use_zenzai_var.get()),
                            self.zenzai_profile_var.get().strip(),
                        )
                        if current_zenzai != snapshot:
                            self.worker.update_zenzai_config(
                                enabled=current_zenzai[0],
                                profile=current_zenzai[1],
                                backend=self.runtime.active_backend,
                            )
                    self._update_backend_restart_button()
                    self._refresh_backend_status()
                elif kind == "start_error":
                    self._start_zenzai_snapshot = None
                    self.starting = False
                    self._refresh_connect_button()
                    self.status.set("エンジンに接続できませんでした。")
                    self._update_backend_restart_button()
                    self._refresh_backend_status()
                    self._show_settings_window()
                    self._refresh_status_and_indicators(force=True)
                    messagebox.showerror("起動できません", str(value))
                elif kind == "toggle":
                    if self.hook:
                        active_now = self.hook.active.is_set()
                        if active_now:
                            self._pending_disable_passthrough = None
                            self.hook.set_english_passthrough(bool(self.english_passthrough_var.get()))
                        self._apply_enabled_ui(active_now)
                elif kind == "tray_show":
                    self._show_settings_window()
                elif kind == "tray_toggle":
                    self._toggle()
                elif kind == "tray_reset_toggle":
                    self._reset_toggle_position()
                elif kind == "tray_exit":
                    self.close()
                    return
                elif kind == "learning_count":
                    try:
                        count = int(value)  # type: ignore[arg-type]
                    except (TypeError, ValueError):
                        count = 0
                    self.learning_count_var.set(f"学習履歴: {count} 件")
                    self._refresh_learning_viewer()
                elif kind == "preview":
                    self.preview.set(f"変換候補: {value}" if value else "")
                elif kind == "candidate_popup":
                    if value is None:
                        popup_hide_first = True
                        popup_update_pending = False
                        popup_update = None
                    else:
                        popup_update_pending = True
                        popup_update = value
                elif kind == "error":
                    self.enabled = False
                    self._cleanup_session()
                    self.candidate_popup.hide()
                    self.preview.set("")
                    self._refresh_connect_button()
                    self.status.set("入力補助を停止しました。")
                    self._update_backend_restart_button()
                    self._refresh_backend_status()
                    self._show_settings_window()
                    self._refresh_status_and_indicators(force=True)
                    messagebox.showerror("入力補助を停止しました", str(value))
            if popup_hide_first:
                self.candidate_popup.hide()
            if popup_update_pending and popup_update is not None:
                if len(popup_update) >= 5:
                    hwnd, candidates, selected_index, selecting, shown_seq = popup_update[:5]
                elif len(popup_update) >= 4:
                    hwnd, candidates, selected_index, selecting = popup_update[:4]
                    shown_seq = 0
                else:
                    hwnd, candidates, selected_index = popup_update
                    selecting = False
                    shown_seq = 0
                try:
                    self.candidate_popup.show(
                        hwnd,
                        candidates,
                        selected_index,
                        selecting=bool(selecting),
                        fallback_point=self._fallback_point_for_hwnd(hwnd),
                        shown_seq=int(shown_seq or 0),
                    )
                except (OSError, tk.TclError):
                    pass
            try:
                self.candidate_popup.hide_if_focus_moved()
            except (OSError, tk.TclError):
                pass
            try:
                self._refresh_status_and_indicators()
            except (OSError, tk.TclError):
                pass
        finally:
            if not self._closed:
                try:
                    self._poll_after_id = self.root.after(25, self._poll_ui)
                except tk.TclError:
                    self._poll_after_id = None

    def _cancel_poll_timer(self) -> None:
        after_id = getattr(self, "_poll_after_id", None)
        if after_id is not None:
            self._poll_after_id = None
            try:
                self.root.after_cancel(after_id)
            except tk.TclError:
                pass

    def close(self) -> None:
        with self._lifecycle_lock:
            if self._closed:
                return
            self._closed = True
        self._cancel_poll_timer()
        self._cancel_path_refresh()
        self._flush_pending_zenzai_change(persist_only=True)
        self._cancel_copy_feedback()
        self._close_learning_viewer()
        self._cleanup_session(commit_pending=True)
        while True:
            try:
                kind, value = self.ui_events.get_nowait()
            except queue.Empty:
                break
            if kind == "ready":
                runtime, worker, hook = value  # type: ignore[misc]
                _dispose_session(runtime, worker, hook)
        if hasattr(self, "tray_icon"):
            self.tray_icon.stop()
        self.candidate_popup.hide()
        self.corner_toggle.close()
        release_mutex(self._mutex_handle)
        self._mutex_handle = None
        try:
            self.root.destroy()
        except tk.TclError:
            pass


def main() -> None:
    enable_dpi_awareness()
    disable_console_quick_edit()
    mutex_handle = acquire_single_instance_mutex()
    if mutex_handle is None:
        activate_existing_window(f"{APP_NAME} 設定画面")
        return
    root = tk.Tk()
    app = AzooKeyLiveBridge(root, mutex_handle=mutex_handle)
    root.mainloop()


if __name__ == "__main__":
    main()
