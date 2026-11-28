from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import queue
import tempfile
import threading
import unittest
from unittest import mock

import app
import azookey_client
import windows_input


class TextConversionTests(unittest.TestCase):
    def test_kana_and_ascii_conversions(self) -> None:
        self.assertEqual(app._to_hiragana("カタカナ・テスト"), "かたかな・てすと")
        self.assertEqual(app._to_fullwidth_katakana("ひらがなテスト"), "ヒラガナテスト")
        self.assertEqual(app._to_halfwidth_katakana("らりるれろガギグゲゴ"), "ﾗﾘﾙﾚﾛｶﾞｷﾞｸﾞｹﾞｺﾞ")
        self.assertEqual(app._to_fullwidth_ascii("Az 09!"), "Ａｚ\u3000０９！")

    def test_romaji_helpers(self) -> None:
        self.assertEqual(app._trailing_ascii_alpha("かんじk"), "k")
        self.assertEqual(app._trailing_ascii_alpha("かんじ"), "")
        self.assertTrue(app._has_incomplete_romaji("あいk"))
        self.assertFalse(app._has_incomplete_romaji("あいう"))
        self.assertFalse(app._has_non_n_incomplete_romaji("あいn"))
        self.assertTrue(app._has_non_n_incomplete_romaji("あいk"))
        self.assertEqual(app._normalized_kana_prefix("あいn"), "あいん")
        self.assertEqual(app._normalized_kana_prefix("あいk"), "あい")

    def test_sanitize_zenzai_profile_strips_controls_and_truncates(self) -> None:
        self.assertEqual(app._sanitize_zenzai_profile("  dev\n\t\x00user  "), "devuser")
        long_profile = "a" * 300
        self.assertEqual(len(app._sanitize_zenzai_profile(long_profile)), app._ZENZAI_PROFILE_MAX_LEN)


class StorageTests(unittest.TestCase):
    def test_atomic_json_and_corrupt_backup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "learning.json"
            app._write_json_atomic(target, {"にほんご": "日本語"})
            self.assertEqual(app._read_json_dict_safe(target), {"にほんご": "日本語"})

            # Corrupt file should be backed up instead of silently discarded.
            target.write_text("{broken json", encoding="utf-8")
            self.assertEqual(app._read_json_dict_safe(target), {})
            backups = list(Path(tmp).glob("learning.json.corrupt.*"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(encoding="utf-8"), "{broken json")

    def test_settings_roundtrip_preserves_toggle_position(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings_file = Path(tmp) / "AzooKeyLiveBridge" / "settings.json"
            with mock.patch.object(app, "_settings_path", return_value=settings_file):
                app._save_settings(
                    {
                        "engine_dir": "",
                        "ui_scale": "large",
                        "toggle_x": "1234",
                        "toggle_y": "567",
                        "english_passthrough": "1",
                        "fullwidth_space": "0",
                        "shift_direct_english": "0",
                        "minimize_to_tray": "1",
                        "start_minimized": "1",
                        "use_zenzai": "0",
                        "zenzai_profile": "coder",
                        "zenzai_backend": "vulkan",
                    }
                )
                loaded = app._load_settings()
                self.assertEqual(loaded["ui_scale"], "large")
                self.assertEqual(loaded["toggle_x"], "1234")
                self.assertEqual(loaded["toggle_y"], "567")
                self.assertEqual(loaded["english_passthrough"], "1")
                self.assertEqual(loaded["fullwidth_space"], "0")
                self.assertEqual(loaded["shift_direct_english"], "0")
                self.assertEqual(loaded["start_minimized"], "1")
                self.assertEqual(loaded["use_zenzai"], "0")
                self.assertEqual(loaded["zenzai_profile"], "coder")
                self.assertEqual(loaded["zenzai_backend"], "vulkan")


class _FakeHook:
    def __init__(self) -> None:
        self.active = threading.Event()
        self.composing = threading.Event()
        self.selecting = threading.Event()
        self.ascii_direct = threading.Event()
        self.has_context = threading.Event()
        self.visible_count = 0

    def mark_has_context(self, enabled: bool) -> None:
        self.has_context.set() if enabled else self.has_context.clear()

    def mark_selecting(self, enabled: bool, *, seq: int = 0) -> None:
        self.selecting.set() if enabled else self.selecting.clear()

    def mark_ascii_direct(self, enabled: bool, *, seq: int = 0) -> None:
        self.ascii_direct.set() if enabled else self.ascii_direct.clear()

    def mark_composing(self, enabled: bool, hwnd: int = 0, *, seq: int = 0) -> None:
        self.composing.set() if enabled else self.composing.clear()

    def set_visible_candidate_count(self, count: int, *, seq: int = 0) -> None:
        self.visible_count = count


class _FakeClient:
    SUPPORTS_CURSOR_OFFSET = True

    def __init__(self) -> None:
        self.cleared = 0
        self.context = ""
        self.moved_offsets: list[int] = []

    def clear_text(self) -> None:
        self.cleared += 1

    def set_context(self, context: str) -> None:
        self.context = context

    def move_cursor_raw_with_cursor(self, offset: int) -> tuple[str, int, int]:
        self.moved_offsets.append(offset)
        return "かんじ", 0, offset


class CompositionWorkerTests(unittest.TestCase):
    def test_transliterate_resets_mid_word_cursor_before_converting(self) -> None:
        client = _FakeClient()
        hook = _FakeHook()
        ui_events: queue.Queue[tuple[str, object]] = queue.Queue()
        events: queue.Queue = queue.Queue()
        worker = app.CompositionWorker(client, hook, ui_events, events)
        worker._target = 100
        worker._hiragana = "かんじ"
        worker._raw_input = "kanji"
        worker._segments = [("か", ["k", "a"]), ("ん", ["n"]), ("じ", ["j", "i"])]
        worker._cursor_offset = -1
        worker._displayed_text = "かんじ"
        worker._displayed_cursor = -1

        with mock.patch.object(worker, "_show") as show_mock:
            worker._handle(windows_input.InputEvent("transliterate", 100, "f7", seq=1))
            self.assertEqual(worker._cursor_offset, 0)
            self.assertTrue(worker._selecting)
            show_mock.assert_called_once_with(100, "カンジ")

    def test_record_learning_persists_lru_reorder_for_existing_entry(self) -> None:
        client = _FakeClient()
        hook = _FakeHook()
        ui_events: queue.Queue[tuple[str, object]] = queue.Queue()
        events: queue.Queue = queue.Queue()
        worker = app.CompositionWorker(
            client,
            hook,
            ui_events,
            events,
            learning_memory={"あい": "愛", "こい": "恋"},
        )
        with mock.patch.object(app, "_save_learning_memory") as save_mock:
            # Re-selecting an older entry should bump it to newest and persist.
            worker._record_learning("あい", "愛")
            self.assertEqual(worker.learning_items(), [("こい", "恋"), ("あい", "愛")])
            self.assertEqual(worker.learning_count(), 2)
            save_mock.assert_called_once()

            # Re-selecting the already-newest entry should not rewrite disk.
            save_mock.reset_mock()
            worker._record_learning("あい", "愛")
            save_mock.assert_not_called()

    def test_commit_selected_and_continue_resets_session_seq(self) -> None:
        client = _FakeClient()
        hook = _FakeHook()
        ui_events: queue.Queue[tuple[str, object]] = queue.Queue()
        events: queue.Queue = queue.Queue()
        worker = app.CompositionWorker(client, hook, ui_events, events)
        worker._target = 200
        worker._hiragana = "てすと"
        worker._candidates = ("テスト",)
        worker._candidate_index = 0
        worker._selecting = True
        worker._session_seq = 42

        with mock.patch.object(worker, "_sync_editor_display"):
            worker._commit_selected_and_continue(200)

        self.assertEqual(worker._session_seq, 0)
        self.assertEqual(worker._hiragana, "")
        self.assertFalse(worker._selecting)
        self.assertEqual(worker.target_hwnd, 200)

    def test_transliterate_f6_in_ascii_direct_preserves_mid_cursor(self) -> None:
        client = _FakeClient()
        hook = _FakeHook()
        ui_events: queue.Queue[tuple[str, object]] = queue.Queue()
        events: queue.Queue = queue.Queue()
        worker = app.CompositionWorker(client, hook, ui_events, events)
        worker._target = 100
        worker._ascii_direct = True
        worker._hiragana = "Abc"
        worker._raw_input = "Abc"
        worker._cursor_offset = -1
        worker._displayed_text = "Abc"
        worker._displayed_cursor = -1

        worker._handle(windows_input.InputEvent("transliterate", 100, "f6", seq=2))
        self.assertEqual(worker._cursor_offset, -1)
        self.assertEqual(client.moved_offsets, [])


class AzooKeyClientTests(unittest.TestCase):
    def test_null_candidates_pointer_returns_empty_composition(self) -> None:
        class _NullLib:
            def GetComposedText(self, count_ptr):
                count_ptr._obj.value = 3
                return None

        client = azookey_client.AzooKeyClient(_NullLib())
        comp = client.compose("あ")
        self.assertEqual(comp.hiragana, "あ")
        self.assertEqual(comp.suggestions, ())

    def test_invalid_candidate_count_raises(self) -> None:
        class _BadCountLib:
            def GetComposedText(self, count_ptr):
                count_ptr._obj.value = 999
                return None

        client = azookey_client.AzooKeyClient(_BadCountLib())
        with self.assertRaises(RuntimeError):
            client.compose("あ")

    def test_append_text_strips_embedded_nul(self) -> None:
        received: list[bytes] = []

        class _CaptureLib:
            def AppendText(self, raw_bytes, cursor_ptr):
                received.append(raw_bytes)
                cursor_ptr._obj.value = 1
                return None

        client = azookey_client.AzooKeyClient(_CaptureLib())
        client.append_text_raw_with_cursor("a\x00b")
        self.assertEqual(received, [b"ab"])

    def test_ensure_engine_settings_atomic_and_preserves_extra_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            appdata = Path(tmp) / "appdata"
            engine_dir = Path(tmp) / "engine"
            engine_dir.mkdir()
            (engine_dir / "zenz.gguf").write_bytes(b"stub")
            existing = appdata / "Azookey" / "settings.json"
            existing.parent.mkdir(parents=True)
            existing.write_text(json.dumps({"custom_key": 123}), encoding="utf-8")

            with mock.patch.dict(os.environ, {"APPDATA": str(appdata)}):
                out = azookey_client._ensure_engine_settings(
                    engine_dir,
                    use_zenzai=True,
                    zenzai_profile="dev",
                    zenzai_backend="vulkan",
                )
            self.assertEqual(out, existing)
            saved = json.loads(existing.read_text(encoding="utf-8"))
            self.assertEqual(saved["custom_key"], 123)
            self.assertEqual(saved["zenzai"]["enable"], True)
            self.assertEqual(saved["zenzai"]["profile"], "dev")
            self.assertEqual(saved["zenzai"]["backend"], "vulkan")

    def test_ensure_engine_settings_backs_up_corrupt_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            appdata = Path(tmp) / "appdata"
            engine_dir = Path(tmp) / "engine"
            engine_dir.mkdir()
            existing = appdata / "Azookey" / "settings.json"
            existing.parent.mkdir(parents=True)
            existing.write_text("{corrupt", encoding="utf-8")

            with mock.patch.dict(os.environ, {"APPDATA": str(appdata)}):
                azookey_client._ensure_engine_settings(engine_dir, use_zenzai=False)
            backups = list(existing.parent.glob("settings.json.corrupt.*"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(encoding="utf-8"), "{corrupt")

    def test_probe_cuda_device_handles_success_zero_devices_and_init_error(self) -> None:
        def _make_fake_cuda(init_rc: int, count_rc: int, dev_count: int):
            def _cu_get_count(out_ptr):
                out_ptr._obj.value = dev_count
                return count_rc

            fake = mock.Mock()
            fake.cuInit = mock.Mock(return_value=init_rc)
            fake.cuDeviceGetCount = mock.Mock(side_effect=_cu_get_count)
            return fake

        with azookey_client._CUDA_PROBE_LOCK:
            azookey_client._CUDA_PROBE_CACHE.clear()
        with mock.patch.object(ctypes, "WinDLL", return_value=_make_fake_cuda(0, 0, 1)):
            ok, reason = azookey_client._probe_cuda_device()
            self.assertTrue(ok, reason)
            self.assertEqual(reason, "")

        with azookey_client._CUDA_PROBE_LOCK:
            azookey_client._CUDA_PROBE_CACHE.clear()
        with mock.patch.object(ctypes, "WinDLL", return_value=_make_fake_cuda(0, 0, 0)):
            ok, reason = azookey_client._probe_cuda_device()
            self.assertFalse(ok)
            self.assertIn("CUDA", reason)

        with azookey_client._CUDA_PROBE_LOCK:
            azookey_client._CUDA_PROBE_CACHE.clear()
        with mock.patch.object(ctypes, "WinDLL", return_value=_make_fake_cuda(100, 0, 1)):
            ok, reason = azookey_client._probe_cuda_device()
            self.assertFalse(ok)
            self.assertIn("cuInit=100", reason)

    def test_diagnose_backend_reports_missing_engine_dir(self) -> None:
        diag = azookey_client.diagnose_backend("", "cpu")
        self.assertFalse(diag.ready)
        self.assertTrue(diag.reason)

    def test_runtime_close_restores_path_even_if_clear_text_fails(self) -> None:
        runtime = azookey_client.AzooKeyRuntime()
        failing_client = mock.Mock()
        failing_client.clear_text.side_effect = RuntimeError("boom")
        runtime._client = failing_client
        runtime._added_path_entries = [r"C:\FakeAzooKeyDir"]
        original_path = os.environ.get("PATH", "")
        with mock.patch.dict(os.environ, {"PATH": f"C:\\FakeAzooKeyDir{os.pathsep}{original_path}"}):
            runtime.close()
            self.assertNotIn("FakeAzooKeyDir", os.environ["PATH"])
            self.assertIsNone(runtime._client)


class WindowsInputTests(unittest.TestCase):
    def test_grapheme_clusters_handle_zwj_flags_and_combining(self) -> None:
        self.assertEqual(windows_input._split_grapheme_clusters("あいう"), ["あ", "い", "う"])
        self.assertEqual(windows_input._split_grapheme_clusters("👨‍👩‍👧‍👦"), ["👨‍👩‍👧‍👦"])
        self.assertEqual(windows_input._split_grapheme_clusters("🇯🇵a"), ["🇯🇵", "a"])
        self.assertEqual(windows_input._split_grapheme_clusters("か\u3099き"), ["か\u3099", "き"])
        # Non-emoji text separated by ZWJ should not swallow the following normal character.
        self.assertEqual(windows_input._split_grapheme_clusters("あ\u200dい"), ["あ", "\u200d", "い"])

    def test_replace_unicode_text_counts_grapheme_clusters_for_backspaces(self) -> None:
        with (
            mock.patch.object(windows_input, "send_backspaces") as bs_mock,
            mock.patch.object(windows_input, "send_unicode_text") as send_mock,
        ):
            windows_input.replace_unicode_text("家族👨‍👩‍👧‍👦", "家族😊")
            bs_mock.assert_called_once_with(1, target_hwnd=0)
            send_mock.assert_called_once_with("😊", target_hwnd=0)

    def test_sync_unicode_text_uses_grapheme_clusters_for_delete_and_cursor(self) -> None:
        with (
            mock.patch.object(windows_input, "_ensure_shift_released"),
            mock.patch.object(windows_input, "send_virtual_keys") as vk_mock,
        ):
            windows_input.sync_unicode_text("あ👨‍👩‍👧‍👦い", -8, "あい", -1)
            vk_mock.assert_called_once_with(windows_input.VK_DELETE, 1, target_hwnd=0)

    def test_send_unicode_text_aborts_when_foreground_window_changes(self) -> None:
        fg_sequence = iter([100, 999])
        with (
            mock.patch.object(windows_input, "foreground_window", side_effect=lambda: next(fg_sequence)),
            mock.patch.object(windows_input, "_send_inputs") as send_mock,
            mock.patch.object(windows_input.time, "sleep"),
        ):
            windows_input.send_unicode_text("ab", target_hwnd=100)
            self.assertEqual(send_mock.call_count, 1)

    def test_ensure_modifiers_released_releases_held_ctrl(self) -> None:
        def _fake_key_state(vk: int) -> int:
            return 0x8000 if vk == windows_input.VK_LCONTROL else 0

        with (
            mock.patch.object(windows_input.user32, "GetAsyncKeyState", side_effect=_fake_key_state),
            mock.patch.object(windows_input, "_send_inputs") as send_mock,
            mock.patch.object(windows_input.time, "sleep"),
        ):
            windows_input._ensure_modifiers_released()
            send_mock.assert_called_once()
            sent_inputs = send_mock.call_args[0][0]
            self.assertEqual(len(sent_inputs), 1)
            self.assertEqual(sent_inputs[0].ki.wVk, windows_input.VK_LCONTROL)
            self.assertTrue(sent_inputs[0].ki.dwFlags & windows_input.KEYEVENTF_KEYUP)

    def test_set_active_false_does_not_drop_in_flight_swallowed_keyup(self) -> None:
        hook = windows_input.KeyboardHook(queue.Queue())
        hook._swallow(windows_input.VK_SCROLL)
        hook.set_active(False)
        with hook._swallowed_lock:
            self.assertIn(windows_input.VK_SCROLL, hook._swallowed)

    def test_truncate_utf16_respects_surrogate_pairs(self) -> None:
        emoji = "😀"  # 2 UTF-16 code units
        text = emoji * 70  # 140 UTF-16 code units
        truncated = windows_input._truncate_utf16(text, 127)
        self.assertLessEqual(len(truncated.encode("utf-16-le")) // 2, 127)
        self.assertEqual(len(truncated), 63)

    def test_valid_caret_rect_rejects_empty_origin_rect(self) -> None:
        self.assertFalse(windows_input._is_valid_caret_rect(windows_input.RECT(0, 0, 0, 0)))
        self.assertTrue(windows_input._is_valid_caret_rect(windows_input.RECT(10, 20, 12, 36)))

    def test_send_inputs_handles_empty_and_uipi_block(self) -> None:
        windows_input._send_inputs([])
        with (
            mock.patch.object(windows_input.user32, "SendInput", return_value=0),
            mock.patch.object(ctypes, "get_last_error", return_value=0),
        ):
            sample = [windows_input.INPUT(type=windows_input.INPUT_KEYBOARD)]
            with self.assertRaises(PermissionError):
                windows_input._send_inputs(sample)

    def test_translate_japanese_symbol_uses_precomputed_raw_ascii(self) -> None:
        with mock.patch.object(
            windows_input.KeyboardHook,
            "_translate_ascii_symbol_or_digit",
            side_effect=AssertionError("should not be called when raw_ascii is passed"),
        ):
            self.assertEqual(
                windows_input.KeyboardHook._translate_japanese_symbol_or_digit(
                    windows_input.VK_OEM_MINUS, 0, 0, raw_ascii="-"
                ),
                "ー",
            )


if __name__ == "__main__":
    unittest.main()
