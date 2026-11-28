"""Direct ctypes access to the AzooKey Windows conversion engine."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import site
import sys
import threading
import time


DEFAULT_ENGINE_SETTINGS = {
    "version": "0.1.0",
    "zenzai": {
        "enable": True,
        "profile": "",
        "backend": "cpu",
    },
}

VALID_BACKENDS = ("cpu", "vulkan", "cuda")
_APPDATA_FALLBACK_ORIGIN: tuple[str, str] | None = None
_ENGINE_SETTINGS_LOCK = threading.Lock()


def _write_text_atomic(target: Path, content: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target.with_name(f".{target.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        with tmp_path.open("w", encoding="utf-8") as fh:
            fh.write(content)
            fh.flush()
            try:
                os.fsync(fh.fileno())
            except OSError:
                pass
        os.replace(tmp_path, target)
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass


def preferred_appdata_dir() -> str:
    """Return the pre-fallback APPDATA path when _ensure_engine_settings redirected APPDATA."""
    with _ENGINE_SETTINGS_LOCK:
        current = os.environ.get("APPDATA", "")
        if _APPDATA_FALLBACK_ORIGIN is not None and current == _APPDATA_FALLBACK_ORIGIN[0]:
            return _APPDATA_FALLBACK_ORIGIN[1]
        return current


def _ensure_engine_settings(
    folder: Path,
    *,
    use_zenzai: bool | None = None,
    zenzai_profile: str | None = None,
    zenzai_backend: str | None = None,
) -> Path | None:
    """Ensure %APPDATA%\\Azookey\\settings.json exists and reflects the Zenzai config."""
    global _APPDATA_FALLBACK_ORIGIN
    has_model = (folder / "zenz.gguf").is_file()
    desired_enable = has_model if use_zenzai is None else (bool(use_zenzai) and has_model)
    with _ENGINE_SETTINGS_LOCK:
        current_appdata = os.environ.get("APPDATA", "")
        if _APPDATA_FALLBACK_ORIGIN is not None and current_appdata == _APPDATA_FALLBACK_ORIGIN[0]:
            raw_appdata = _APPDATA_FALLBACK_ORIGIN[1]
        else:
            raw_appdata = current_appdata
        appdata = Path(raw_appdata) if raw_appdata else (Path.home() / "AppData" / "Roaming")
        for base in (appdata, folder / ".appdata"):
            settings_file = base / "Azookey" / "settings.json"
            try:
                existing: dict | None = None
                if settings_file.is_file():
                    try:
                        loaded = json.loads(settings_file.read_text(encoding="utf-8"))
                        if isinstance(loaded, dict):
                            existing = loaded
                    except (ValueError, TypeError):
                        existing = None
                payload = dict(DEFAULT_ENGINE_SETTINGS)
                zenzai_cfg = dict(DEFAULT_ENGINE_SETTINGS["zenzai"])
                if existing is not None:
                    payload.update(existing)
                    if isinstance(existing.get("zenzai"), dict):
                        zenzai_cfg.update(existing["zenzai"])
                zenzai_cfg["enable"] = desired_enable
                if zenzai_profile is not None:
                    zenzai_cfg["profile"] = str(zenzai_profile)
                if zenzai_backend is not None and zenzai_backend in VALID_BACKENDS:
                    zenzai_cfg["backend"] = zenzai_backend
                elif zenzai_cfg.get("backend") not in VALID_BACKENDS:
                    zenzai_cfg["backend"] = "cpu"
                payload["zenzai"] = zenzai_cfg
                _write_text_atomic(
                    settings_file,
                    json.dumps(payload, ensure_ascii=False, indent=2),
                )
                if base != appdata:
                    _APPDATA_FALLBACK_ORIGIN = (str(base), str(appdata))
                    os.environ["APPDATA"] = str(base)
                elif _APPDATA_FALLBACK_ORIGIN is not None:
                    os.environ["APPDATA"] = _APPDATA_FALLBACK_ORIGIN[1]
                    _APPDATA_FALLBACK_ORIGIN = None
                return settings_file
            except OSError:
                continue
        return None


@dataclass(frozen=True)
class Suggestion:
    text: str
    subtext: str = ""
    corresponding_count: int = 0


@dataclass(frozen=True)
class Composition:
    hiragana: str
    suggestions: tuple[Suggestion, ...]

    @property
    def live_text(self) -> str:
        if self.suggestions and self.suggestions[0].text:
            return self.suggestions[0].text
        return self.hiragana


class _NativeSuggestion(ctypes.Structure):
    _fields_ = [
        ("text", ctypes.c_void_p),
        ("subtext", ctypes.c_void_p),
        ("hiragana", ctypes.c_void_p),
        ("corresponding_count", ctypes.c_int),
    ]


_CUDA_DRIVER_DLL = "nvcuda.dll"
_CUDA_RUNTIME_DLLS = ("cudart64_12.dll", "cublas64_12.dll", "cublasLt64_12.dll")
_VULKAN_LOADER_DLL = "vulkan-1.dll"
_VULKAN_PROBE_TTL = 5.0
_VULKAN_PROBE_LOCK = threading.Lock()
_VULKAN_PROBE_CACHE: dict[tuple[str, bool], tuple[float, bool, str]] = {}
_VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO = 1
_VK_SUCCESS = 0
_VK_INCOMPLETE = 5


class _VkInstanceCreateInfo(ctypes.Structure):
    _fields_ = [
        ("sType", ctypes.c_uint32),
        ("pNext", ctypes.c_void_p),
        ("flags", ctypes.c_uint32),
        ("pApplicationInfo", ctypes.c_void_p),
        ("enabledLayerCount", ctypes.c_uint32),
        ("ppEnabledLayerNames", ctypes.c_void_p),
        ("enabledExtensionCount", ctypes.c_uint32),
        ("ppEnabledExtensionNames", ctypes.c_void_p),
    ]


def _probe_vulkan_device(vulkan_dir: Path, *, use_system_loader: bool = False) -> tuple[bool, str]:
    """Verify via Vulkan loader that at least one usable GPU physical device exists."""
    cache_key = (os.path.normcase(str(vulkan_dir)), bool(use_system_loader))
    now = time.monotonic()
    with _VULKAN_PROBE_LOCK:
        cached = _VULKAN_PROBE_CACHE.get(cache_key)
        if cached is not None and now - cached[0] < _VULKAN_PROBE_TTL:
            return cached[1], cached[2]

    dll_dir_handle = None
    instance = ctypes.c_void_p()
    vulkan = None
    result: tuple[bool, str]
    try:
        if use_system_loader:
            vulkan = ctypes.WinDLL(_VULKAN_LOADER_DLL)
        else:
            dll_dir_handle = os.add_dll_directory(str(vulkan_dir))
            vulkan = ctypes.WinDLL(str(vulkan_dir / _VULKAN_LOADER_DLL))
        vulkan.vkCreateInstance.argtypes = [
            ctypes.POINTER(_VkInstanceCreateInfo),
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        vulkan.vkCreateInstance.restype = ctypes.c_int32
        vulkan.vkEnumeratePhysicalDevices.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.c_void_p,
        ]
        vulkan.vkEnumeratePhysicalDevices.restype = ctypes.c_int32
        vulkan.vkDestroyInstance.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        vulkan.vkDestroyInstance.restype = None

        info = _VkInstanceCreateInfo(sType=_VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO)
        rc = int(vulkan.vkCreateInstance(ctypes.byref(info), None, ctypes.byref(instance)))
        if rc != _VK_SUCCESS or not instance.value:
            result = (False, "Vulkan インスタンスを初期化できないため、対応 GPU が利用できません。")
        else:
            device_count = ctypes.c_uint32(0)
            rc_enum = int(vulkan.vkEnumeratePhysicalDevices(instance, ctypes.byref(device_count), None))
            if rc_enum not in (_VK_SUCCESS, _VK_INCOMPLETE) or device_count.value <= 0:
                result = (False, "利用可能な Vulkan GPU デバイス（ドライバ/ICD）が見つかりません。")
            else:
                result = (True, "")
    except (OSError, AttributeError, ValueError, ctypes.ArgumentError):
        result = (False, f"{_VULKAN_LOADER_DLL} を初期化できないため、Vulkan GPU を利用できません。")
    finally:
        if vulkan is not None and instance.value:
            try:
                vulkan.vkDestroyInstance(instance, None)
            except Exception:
                pass
        if vulkan is not None and not use_system_loader:
            _try_free_library(vulkan)
        if dll_dir_handle is not None:
            try:
                dll_dir_handle.close()
            except Exception:
                pass

    with _VULKAN_PROBE_LOCK:
        _VULKAN_PROBE_CACHE[cache_key] = (time.monotonic(), result[0], result[1])
    return result


def _try_free_library(library: object) -> None:
    handle = getattr(library, "_handle", None)
    if not isinstance(handle, int) or not handle:
        return
    try:
        kernel32 = ctypes.WinDLL("kernel32")
        kernel32.FreeLibrary.argtypes = [wintypes.HMODULE]
        kernel32.FreeLibrary.restype = wintypes.BOOL
        kernel32.FreeLibrary(wintypes.HMODULE(handle))
    except Exception:
        pass


@dataclass(frozen=True)
class BackendDiagnostic:
    """Dependency readiness summary for a Zenzai inference backend."""

    backend: str
    ready: bool
    has_nvidia_driver: bool
    missing_files: tuple[str, ...]
    extra_dll_dirs: tuple[Path, ...]
    reason: str


def _version_sort_key(name: str) -> tuple[int, ...]:
    parts = [int(token) for token in re.findall(r"\d+", name)]
    return tuple(parts) if parts else (0,)


def _dedupe_existing_dirs(candidates: list[Path]) -> list[Path]:
    seen: set[str] = set()
    unique: list[Path] = []
    for raw_path in candidates:
        try:
            if not str(raw_path).strip():
                continue
            resolved = raw_path.expanduser().resolve()
            if not resolved.is_dir():
                continue
        except OSError:
            continue
        norm = os.path.normcase(str(resolved))
        if norm in seen:
            continue
        seen.add(norm)
        unique.append(resolved)
    return unique


def _system_dll_dirs() -> list[Path]:
    system_root = Path(os.environ.get("SystemRoot") or r"C:\Windows")
    dirs = [system_root / "System32"]
    for raw_entry in os.environ.get("PATH", "").split(os.pathsep):
        cleaned = raw_entry.strip().strip('"')
        if cleaned:
            dirs.append(Path(cleaned))
    return _dedupe_existing_dirs(dirs)


def _cuda_search_dirs(folder: Path) -> list[Path]:
    candidates: list[Path] = [
        folder / "llama_cuda",
        folder / "llama_cuda" / "bin",
        folder / "cuda",
        folder,
    ]
    for key in sorted(os.environ):
        upper = key.upper()
        if upper == "CUDA_PATH" or upper.startswith("CUDA_PATH_V12"):
            raw_val = os.environ.get(key, "").strip().strip('"')
            if raw_val:
                root = Path(raw_val)
                candidates.extend((root / "bin", root))

    toolkit_roots = _dedupe_existing_dirs(
        [
            Path(os.environ.get("ProgramFiles") or r"C:\Program Files")
            / "NVIDIA GPU Computing Toolkit"
            / "CUDA",
            Path(r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA"),
        ]
    )
    for toolkit_root in toolkit_roots:
        try:
            v12_dirs = [
                entry
                for entry in toolkit_root.iterdir()
                if entry.is_dir() and entry.name.lower().startswith("v12.")
            ]
        except OSError:
            v12_dirs = []
        v12_dirs.sort(key=lambda entry: _version_sort_key(entry.name), reverse=True)
        for v12_dir in v12_dirs:
            candidates.append(v12_dir / "bin")

    site_bases: list[Path] = []
    for prefix in (
        sys.prefix,
        getattr(sys, "base_prefix", ""),
        str(Path(__file__).resolve().parent / ".venv"),
        os.environ.get("CONDA_PREFIX", ""),
    ):
        if prefix:
            prefix_path = Path(prefix)
            site_bases.append(prefix_path / "Lib" / "site-packages")
            candidates.append(prefix_path / "Library" / "bin")
    try:
        user_site = site.getusersitepackages()
        if isinstance(user_site, str) and user_site:
            site_bases.append(Path(user_site))
    except Exception:
        pass
    for site_base in site_bases:
        candidates.extend(
            (
                site_base / "nvidia" / "cuda_runtime" / "bin",
                site_base / "nvidia" / "cublas" / "bin",
                site_base / "torch" / "lib",
            )
        )

    candidates.extend(_system_dll_dirs())
    return _dedupe_existing_dirs(candidates)


def _find_dll_dir(filename: str, dirs: list[Path]) -> Path | None:
    for directory in dirs:
        candidate = directory / filename
        try:
            if candidate.is_file():
                return directory
        except OSError:
            continue
    return None


def diagnose_backend(engine_dir: str | Path, backend: str) -> BackendDiagnostic:
    """Inspect whether local engine files and GPU/CUDA runtime DLLs are available."""
    normalized = backend if backend in VALID_BACKENDS else "cpu"
    raw_dir = str(engine_dir).strip()
    if not raw_dir:
        return BackendDiagnostic(
            backend=normalized,
            ready=False,
            has_nvidia_driver=False,
            missing_files=(),
            extra_dll_dirs=(),
            reason="AzooKey エンジンのフォルダーが未指定です。",
        )

    folder = Path(raw_dir).expanduser()
    try:
        folder = folder.resolve()
    except OSError:
        pass

    backend_dir = folder / f"llama_{normalized}"
    sys_dirs = _system_dll_dirs()
    has_nvidia_driver = _find_dll_dir(_CUDA_DRIVER_DLL, sys_dirs) is not None

    required_engine = ("llama.dll", "ggml.dll", "ggml-base.dll")
    try:
        has_backend_dir = backend_dir.is_dir()
    except OSError:
        has_backend_dir = False
    if not has_backend_dir:
        return BackendDiagnostic(
            backend=normalized,
            ready=False,
            has_nvidia_driver=has_nvidia_driver,
            missing_files=(f"llama_{normalized}",),
            extra_dll_dirs=(),
            reason=f"llama_{normalized} フォルダーが見つかりません。",
        )

    missing_local = [name for name in required_engine if not (backend_dir / name).is_file()]
    if normalized == "cpu":
        if not (backend_dir / "ggml-cpu.dll").is_file():
            missing_local.append("ggml-cpu.dll")
        if missing_local:
            return BackendDiagnostic(
                backend="cpu",
                ready=False,
                has_nvidia_driver=has_nvidia_driver,
                missing_files=tuple(missing_local),
                extra_dll_dirs=(),
                reason=f"llama_cpu 内の必要 DLL（{', '.join(missing_local)}）が見つかりません。",
            )
        return BackendDiagnostic(
            backend="cpu",
            ready=True,
            has_nvidia_driver=has_nvidia_driver,
            missing_files=(),
            extra_dll_dirs=(),
            reason="",
        )

    if normalized == "vulkan":
        if not (backend_dir / "ggml-vulkan.dll").is_file():
            missing_local.append("ggml-vulkan.dll")
        base_dirs = _dedupe_existing_dirs([backend_dir, folder])
        vulkan_dir = _find_dll_dir(_VULKAN_LOADER_DLL, [*base_dirs, *sys_dirs])
        missing = list(missing_local)
        if vulkan_dir is None:
            missing.append(_VULKAN_LOADER_DLL)
        if missing:
            return BackendDiagnostic(
                backend="vulkan",
                ready=False,
                has_nvidia_driver=has_nvidia_driver,
                missing_files=tuple(missing),
                extra_dll_dirs=(),
                reason=f"Vulkan の必要ファイル（{', '.join(missing)}）が見つかりません。",
            )
        system32 = (Path(os.environ.get("SystemRoot") or r"C:\Windows") / "System32")
        try:
            system32_norm = os.path.normcase(str(system32.resolve()))
        except OSError:
            system32_norm = os.path.normcase(str(system32))
        extra_dirs = (
            (vulkan_dir,)
            if vulkan_dir not in base_dirs and os.path.normcase(str(vulkan_dir)) != system32_norm
            else ()
        )
        vulkan_ok, vulkan_reason = _probe_vulkan_device(
            vulkan_dir,
            use_system_loader=(os.path.normcase(str(vulkan_dir)) == system32_norm),
        )
        if not vulkan_ok:
            return BackendDiagnostic(
                backend="vulkan",
                ready=False,
                has_nvidia_driver=has_nvidia_driver,
                missing_files=(),
                extra_dll_dirs=extra_dirs,
                reason=vulkan_reason,
            )
        return BackendDiagnostic(
            backend="vulkan",
            ready=True,
            has_nvidia_driver=has_nvidia_driver,
            missing_files=(),
            extra_dll_dirs=extra_dirs,
            reason="",
        )

    if not (backend_dir / "ggml-cuda.dll").is_file():
        missing_local.append("ggml-cuda.dll")
    if missing_local:
        return BackendDiagnostic(
            backend="cuda",
            ready=False,
            has_nvidia_driver=has_nvidia_driver,
            missing_files=tuple(missing_local),
            extra_dll_dirs=(),
            reason=f"llama_cuda 内の必要 DLL（{', '.join(missing_local)}）が見つかりません。",
        )

    search_dirs = _cuda_search_dirs(folder)
    driver_extra_dir: Path | None = None
    if not has_nvidia_driver:
        driver_extra_dir = _find_dll_dir(_CUDA_DRIVER_DLL, search_dirs)
        has_nvidia_driver = driver_extra_dir is not None

    base_norms = {
        os.path.normcase(str(path))
        for path in _dedupe_existing_dirs([backend_dir, folder])
    }
    extra_dirs: list[Path] = []
    seen_extra: set[str] = set()
    if driver_extra_dir is not None:
        norm_driver = os.path.normcase(str(driver_extra_dir))
        if norm_driver not in base_norms:
            seen_extra.add(norm_driver)
            extra_dirs.append(driver_extra_dir)
    missing_runtime: list[str] = []
    for dll_name in _CUDA_RUNTIME_DLLS:
        found_dir = _find_dll_dir(dll_name, search_dirs)
        if found_dir is None:
            missing_runtime.append(dll_name)
        else:
            norm = os.path.normcase(str(found_dir))
            if norm not in base_norms and norm not in seen_extra:
                seen_extra.add(norm)
                extra_dirs.append(found_dir)

    missing_all = list(missing_runtime)
    if not has_nvidia_driver:
        missing_all.insert(0, _CUDA_DRIVER_DLL)
    if missing_all:
        if has_nvidia_driver:
            reason = (
                "NVIDIA GPU ドライバ (nvcuda.dll) は検出されていますが、"
                f"CUDA 12 ランタイム DLL（{', '.join(missing_runtime)}）が見つかりません。"
                "CUDA Toolkit 12 の導入、.venv への `nvidia-cuda-runtime-cu12` / `nvidia-cublas-cu12` 導入、"
                "または llama_cuda フォルダーへの DLL 配置が必要です。"
            )
        else:
            reason = (
                "NVIDIA CUDA ドライバ (nvcuda.dll) および/または "
                f"CUDA 12 ランタイム DLL（{', '.join(missing_all)}）が見つかりません。"
            )
        return BackendDiagnostic(
            backend="cuda",
            ready=False,
            has_nvidia_driver=has_nvidia_driver,
            missing_files=tuple(missing_all),
            extra_dll_dirs=tuple(extra_dirs),
            reason=reason,
        )

    return BackendDiagnostic(
        backend="cuda",
        ready=True,
        has_nvidia_driver=True,
        missing_files=(),
        extra_dll_dirs=tuple(extra_dirs),
        reason="",
    )


class AzooKeyRuntime:
    """Loads the bundled conversion library without registering a Windows IME."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._call_lock = threading.RLock()
        self._library = None
        self._dll_directory_handles = []
        self._added_path_entries: list[str] = []
        self._folder: Path | None = None
        self._client: AzooKeyClient | None = None
        self.active_backend: str = "cpu"
        self.requested_backend: str = "cpu"
        self.fallback_reason: str = ""

    @property
    def engine_dir(self) -> Path | None:
        return self._folder

    @property
    def client(self) -> "AzooKeyClient":
        if self._client is None:
            raise RuntimeError("AzooKey engine is not initialized")
        return self._client

    def start(
        self,
        engine_dir: str | Path,
        *,
        use_zenzai: bool = True,
        zenzai_profile: str = "",
        zenzai_backend: str = "cpu",
    ) -> "AzooKeyClient":
        if sys.maxsize <= 2**32:
            raise RuntimeError("AzooKey 変換エンジン（x64）を読み込むには 64-bit 版 Python が必要です。")
        folder = Path(engine_dir).expanduser().resolve()
        library_path = folder / "azookey-server.dll"
        if not library_path.is_file():
            raise RuntimeError("選んだフォルダーに azookey-server.dll が見つかりません。")
        if not (folder / "Dictionary").is_dir():
            raise RuntimeError("選んだフォルダーに AzooKey の Dictionary が見つかりません。")

        with self._lock:
            backend = zenzai_backend if zenzai_backend in VALID_BACKENDS else "cpu"
            self.requested_backend = backend
            self.fallback_reason = ""
            has_model = (folder / "zenz.gguf").is_file()
            enable_zenzai = bool(use_zenzai and has_model)

            if self._library is not None:
                if folder != self._folder:
                    raise RuntimeError("変換エンジンの場所を変更するには、アプリを再起動してください。")
                if backend != self.active_backend:
                    diag = diagnose_backend(folder, backend)
                    self.fallback_reason = (
                        diag.reason
                        if (not diag.ready and diag.reason)
                        else "推論バックエンドを変更するには、アプリの再起動が必要です。"
                    )
                _ensure_engine_settings(
                    folder,
                    use_zenzai=enable_zenzai,
                    zenzai_profile=zenzai_profile,
                    zenzai_backend=self.active_backend,
                )
                self._client = AzooKeyClient(self._library, folder=folder, call_lock=self._call_lock)
                self._client.update_config()
                self._client.clear_text()
                return self._client

            preferred_backends = [backend] if backend == "cpu" else [backend, "cpu"]
            last_error: Exception | None = None
            last_reason = ""
            library = None
            chosen_backend = "cpu"
            base_path = os.environ.get("PATH", "")

            for idx, candidate_backend in enumerate(preferred_backends):
                backend_dir = folder / f"llama_{candidate_backend}"
                diag = diagnose_backend(folder, candidate_backend)
                has_fallback = idx + 1 < len(preferred_backends)
                if not diag.ready and has_fallback:
                    last_reason = diag.reason
                    continue
                _ensure_engine_settings(
                    folder,
                    use_zenzai=enable_zenzai,
                    zenzai_profile=zenzai_profile,
                    zenzai_backend=candidate_backend,
                )
                search_dirs = _dedupe_existing_dirs([backend_dir, *diag.extra_dll_dirs, folder])
                added_entries = [str(path) for path in search_dirs]
                added_str = os.pathsep.join(added_entries)
                path_prefix = f"{added_str}{os.pathsep}" if (added_str and base_path) else added_str
                os.environ["PATH"] = f"{path_prefix}{base_path}" if path_prefix else base_path
                handles = []
                try:
                    for path in search_dirs:
                        handles.append(os.add_dll_directory(str(path)))
                    library = ctypes.WinDLL(str(library_path))
                    _configure_native_api(library)
                    library.Initialize(str(folder).encode("utf-8"), has_model)
                    self._dll_directory_handles = handles
                    self._added_path_entries = added_entries
                    chosen_backend = candidate_backend
                    break
                except (OSError, AttributeError) as exc:
                    last_error = exc
                    last_reason = diag.reason if (not diag.ready and diag.reason) else str(exc)
                    if library is not None:
                        _try_free_library(library)
                    library = None
                    os.environ["PATH"] = base_path
                    self._close_dll_handles(handles)

            if library is None:
                detail = last_reason or (str(last_error) if last_error is not None else "unknown error")
                raise RuntimeError(f"AzooKey の変換 DLL を読み込めません: {detail}") from last_error

            self.active_backend = chosen_backend
            if chosen_backend != backend:
                self.fallback_reason = (
                    last_reason
                    or (str(last_error) if last_error is not None else "unavailable")
                )

            self._library = library
            self._folder = folder
            self._client = AzooKeyClient(library, folder=folder, call_lock=self._call_lock)
            self._client.update_config()
            self._client.clear_text()
            return self._client

    @staticmethod
    def _close_dll_handles(handles: list) -> None:
        for handle in handles:
            try:
                handle.close()
            except Exception:
                pass

    def close(self) -> None:
        with self._lock:
            if self._client is not None:
                try:
                    self._client.clear_text()
                except Exception:
                    pass
                self._client = None
            if self._dll_directory_handles:
                self._close_dll_handles(self._dll_directory_handles)
                self._dll_directory_handles = []
            if self._added_path_entries:
                remove_counts: dict[str, int] = {}
                for entry in self._added_path_entries:
                    key = os.path.normcase(entry)
                    remove_counts[key] = remove_counts.get(key, 0) + 1
                current_entries = os.environ.get("PATH", "").split(os.pathsep)
                remaining: list[str] = []
                for entry in current_entries:
                    key = os.path.normcase(entry)
                    if remove_counts.get(key, 0) > 0:
                        remove_counts[key] -= 1
                        continue
                    remaining.append(entry)
                os.environ["PATH"] = os.pathsep.join(remaining)
                self._added_path_entries = []


def _configure_native_api(library) -> None:
    library.Initialize.argtypes = [ctypes.c_char_p, ctypes.c_bool]
    library.Initialize.restype = None
    library.AppendText.argtypes = [ctypes.c_char_p, ctypes.POINTER(ctypes.c_int)]
    library.AppendText.restype = ctypes.c_void_p
    library.RemoveText.argtypes = [ctypes.POINTER(ctypes.c_int)]
    library.RemoveText.restype = ctypes.c_void_p
    library.ClearText.argtypes = []
    library.ClearText.restype = None
    library.GetComposedText.argtypes = [ctypes.POINTER(ctypes.c_int)]
    library.GetComposedText.restype = ctypes.POINTER(ctypes.POINTER(_NativeSuggestion))
    if hasattr(library, "SetContext"):
        library.SetContext.argtypes = [ctypes.c_char_p]
        library.SetContext.restype = None
    if hasattr(library, "LoadConfig"):
        library.LoadConfig.argtypes = []
        library.LoadConfig.restype = None
    if hasattr(library, "UpdateConfig"):
        library.UpdateConfig.argtypes = []
        library.UpdateConfig.restype = None
    if hasattr(library, "MoveCursor"):
        library.MoveCursor.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_int)]
        library.MoveCursor.restype = ctypes.c_void_p
    if hasattr(library, "ShrinkText"):
        library.ShrinkText.argtypes = [ctypes.c_int]
        library.ShrinkText.restype = ctypes.c_void_p


class AzooKeyClient:
    SUPPORTS_CURSOR_OFFSET = True

    def __init__(
        self,
        library,
        *,
        folder: Path | None = None,
        call_lock: threading.RLock | None = None,
    ) -> None:
        self._library = library
        self._folder = folder
        self._call_lock = call_lock if call_lock is not None else threading.RLock()
        self._cursor_pos = 0
        self._hiragana_len = 0

    @property
    def cursor_offset(self) -> int:
        """Current engine cursor relative to the end of the buffer (0 = end, negative = left)."""
        with self._call_lock:
            if self._hiragana_len <= 0:
                return 0
            return max(-self._hiragana_len, min(0, self._cursor_pos - self._hiragana_len))

    def _update_absolute_cursor(self, hiragana: str, cursor_pos: int) -> int:
        self._hiragana_len = len(hiragana)
        self._cursor_pos = max(0, min(self._hiragana_len, int(cursor_pos)))
        return self.cursor_offset

    def append_text_raw_with_cursor(self, text: str) -> tuple[str, int]:
        """Append text to the engine buffer and return (hiragana, cursor_offset)."""
        sanitized = text.replace("\x00", "") if text else ""
        if not sanitized:
            return "", self.cursor_offset
        cursor = ctypes.c_int()
        with self._call_lock:
            hiragana_pointer = self._library.AppendText(sanitized.encode("utf-8"), ctypes.byref(cursor))
            hiragana = _read_utf8(hiragana_pointer)
            return hiragana, self._update_absolute_cursor(hiragana, cursor.value)

    def append_text_raw(self, text: str) -> str:
        """Append text to the engine buffer and return the updated hiragana without running inference."""
        hiragana, _ = self.append_text_raw_with_cursor(text)
        return hiragana

    def remove_text_raw_with_cursor(self) -> tuple[str, int]:
        """Remove one input unit from the engine buffer and return (hiragana, cursor_offset)."""
        cursor = ctypes.c_int()
        with self._call_lock:
            hiragana_pointer = self._library.RemoveText(ctypes.byref(cursor))
            hiragana = _read_utf8(hiragana_pointer)
            return hiragana, self._update_absolute_cursor(hiragana, cursor.value)

    def remove_text_raw(self) -> str:
        """Remove one input unit from the engine buffer and return the updated hiragana without running inference."""
        hiragana, _ = self.remove_text_raw_with_cursor()
        return hiragana

    def compose(self, hiragana: str = "") -> Composition:
        """Run conversion/Zenzai inference on the current buffer and return Composition."""
        with self._call_lock:
            return self._read_composition_from_hiragana(hiragana)

    def append_text(self, text: str) -> Composition:
        if not text:
            return Composition("", ())
        with self._call_lock:
            hiragana = self.append_text_raw(text)
            return self._read_composition_from_hiragana(hiragana)

    def remove_text(self) -> Composition:
        with self._call_lock:
            hiragana = self.remove_text_raw()
            return self._read_composition_from_hiragana(hiragana)

    def shrink_text(self, offset: int) -> Composition:
        if offset <= 0 or not hasattr(self._library, "ShrinkText"):
            return Composition("", ())
        with self._call_lock:
            hiragana_pointer = self._library.ShrinkText(int(offset))
            comp = self._read_composition(hiragana_pointer)
            self._hiragana_len = len(comp.hiragana)
            self._cursor_pos = self._hiragana_len
            return comp

    def move_cursor_raw_with_cursor(self, offset: int) -> tuple[str, int, int]:
        """Move the engine cursor by offset and return (hiragana, cursor_offset, moved_delta)."""
        if not hasattr(self._library, "MoveCursor"):
            return "", 0, 0
        cursor = ctypes.c_int()
        with self._call_lock:
            hiragana_pointer = self._library.MoveCursor(int(offset), ctypes.byref(cursor))
            hiragana = _read_utf8(hiragana_pointer)
            moved = int(cursor.value)
            self._hiragana_len = len(hiragana)
            self._cursor_pos = max(0, min(self._hiragana_len, self._cursor_pos + moved))
            return hiragana, self.cursor_offset, moved

    def move_cursor_raw(self, offset: int) -> str:
        """Move the engine cursor relative to the end (0 = end, negative = left) without running inference."""
        hiragana, _, _ = self.move_cursor_raw_with_cursor(offset)
        return hiragana

    def move_cursor(self, offset: int) -> Composition:
        if not hasattr(self._library, "MoveCursor"):
            return Composition("", ())
        with self._call_lock:
            hiragana = self.move_cursor_raw(offset)
            return self._read_composition_from_hiragana(hiragana)

    def clear_text(self) -> None:
        with self._call_lock:
            self._library.ClearText()
            self._cursor_pos = 0
            self._hiragana_len = 0

    def set_context(self, context: str) -> None:
        if hasattr(self._library, "SetContext"):
            sanitized = context.replace("\x00", "") if context else ""
            with self._call_lock:
                self._library.SetContext(sanitized.encode("utf-8"))

    def update_config(self) -> None:
        with self._call_lock:
            if hasattr(self._library, "LoadConfig"):
                self._library.LoadConfig()
            elif hasattr(self._library, "UpdateConfig"):
                self._library.UpdateConfig()

    def set_zenzai_enabled(self, enabled: bool) -> None:
        with self._call_lock:
            if self._folder is not None:
                _ensure_engine_settings(self._folder, use_zenzai=enabled)
            self.update_config()

    def set_zenzai_config(
        self,
        *,
        enabled: bool | None = None,
        profile: str | None = None,
        backend: str | None = None,
    ) -> None:
        with self._call_lock:
            if self._folder is not None:
                _ensure_engine_settings(
                    self._folder,
                    use_zenzai=enabled,
                    zenzai_profile=profile,
                    zenzai_backend=backend,
                )
            self.update_config()

    def _read_composition(self, hiragana_pointer) -> Composition:
        hiragana = _read_utf8(hiragana_pointer)
        return self._read_composition_from_hiragana(hiragana)

    def _read_composition_from_hiragana(self, hiragana: str) -> Composition:
        count = ctypes.c_int()
        candidates = self._library.GetComposedText(ctypes.byref(count))
        # Short prefixes can legitimately produce more than 128 candidates
        # (for example, "tou" returns around 244 from this engine).
        if count.value < 0 or count.value > 512:
            raise RuntimeError(f"AzooKey が不正な候補数を返しました: {count.value}")
        if not candidates or count.value == 0:
            return Composition(hiragana, ())

        suggestions: list[Suggestion] = []
        for index in range(count.value):
            candidate_pointer = candidates[index]
            if not candidate_pointer:
                continue
            candidate = candidate_pointer.contents
            suggestions.append(
                Suggestion(
                    text=_read_utf8(candidate.text),
                    subtext=_read_utf8(candidate.subtext),
                    corresponding_count=max(0, int(candidate.corresponding_count)),
                )
            )
        return Composition(hiragana, tuple(suggestions))


def _read_utf8(pointer) -> str:
    if not pointer:
        return ""
    return ctypes.string_at(pointer).decode("utf-8", errors="replace")
