"""User-session keyboard hook and Unicode text injection for Windows."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import os
import queue
import threading
import time
import typing
import winreg


if os.name != "nt":
    raise RuntimeError("AzooKey Live Bridge is a Windows-only application")


WH_KEYBOARD_LL = 13
WH_MOUSE_LL = 14
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
WM_QUIT = 0x0012
WM_LBUTTONDOWN = 0x0201
WM_RBUTTONDOWN = 0x0204
WM_MBUTTONDOWN = 0x0207
WM_XBUTTONDOWN = 0x020B
LLKHF_INJECTED = 0x10
# Mark only this bridge's SendInput events so other injected input remains usable.
APP_INJECTION_TAG = 0x415A4B44
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
INPUT_KEYBOARD = 1

VK_LBUTTON = 0x01
VK_RBUTTON = 0x02
VK_MBUTTON = 0x04
VK_BACK = 0x08
VK_TAB = 0x09
VK_RETURN = 0x0D
VK_ESCAPE = 0x1B
VK_CAPITAL = 0x14
VK_KANA = 0x15
VK_IME_ON = 0x16
VK_KANJI = 0x19
VK_IME_OFF = 0x1A
VK_CONVERT = 0x1C
VK_NONCONVERT = 0x1D
VK_SPACE = 0x20
VK_PRIOR = 0x21
VK_NEXT = 0x22
VK_END = 0x23
VK_HOME = 0x24
VK_LEFT = 0x25
VK_UP = 0x26
VK_RIGHT = 0x27
VK_DOWN = 0x28
VK_DELETE = 0x2E
VK_SCROLL = 0x91
VK_NUMPAD0 = 0x60
VK_NUMPAD1 = 0x61
VK_NUMPAD9 = 0x69
VK_MULTIPLY = 0x6A
VK_ADD = 0x6B
VK_SUBTRACT = 0x6D
VK_DECIMAL = 0x6E
VK_DIVIDE = 0x6F
VK_F6 = 0x75
VK_F7 = 0x76
VK_F8 = 0x77
VK_F9 = 0x78
VK_F10 = 0x79
VK_OEM_1 = 0xBA
VK_OEM_PLUS = 0xBB
VK_OEM_COMMA = 0xBC
VK_OEM_MINUS = 0xBD
VK_OEM_PERIOD = 0xBE
VK_OEM_2 = 0xBF
VK_OEM_3 = 0xC0
VK_OEM_4 = 0xDB
VK_OEM_5 = 0xDC
VK_OEM_6 = 0xDD
VK_OEM_7 = 0xDE
VK_OEM_102 = 0xE2
VK_OEM_ATTN = 0xF0
VK_OEM_FINISH = 0xF1
VK_OEM_COPY = 0xF2
VK_OEM_AUTO = 0xF3
VK_OEM_ENLW = 0xF4
VK_CONTROL = 0x11
VK_MENU = 0x12
VK_SHIFT = 0x10
VK_LWIN = 0x5B
VK_RWIN = 0x5C
VK_NUMLOCK = 0x90
VK_LSHIFT = 0xA0
VK_RSHIFT = 0xA1
VK_LCONTROL = 0xA2
VK_RCONTROL = 0xA3
VK_LMENU = 0xA4
VK_RMENU = 0xA5

_MODIFIER_AND_LOCK_VKS = {
    VK_SHIFT,
    VK_LSHIFT,
    VK_RSHIFT,
    VK_CONTROL,
    VK_LCONTROL,
    VK_RCONTROL,
    VK_MENU,
    VK_LMENU,
    VK_RMENU,
    VK_LWIN,
    VK_RWIN,
    VK_CAPITAL,
    VK_NUMLOCK,
}

_TOGGLE_VKS = {
    VK_SCROLL,
    VK_KANJI,
    VK_OEM_AUTO,
    VK_OEM_ENLW,
}

_TURN_ON_VKS = {
    VK_IME_ON,
    VK_KANA,
    VK_OEM_FINISH,
    VK_OEM_COPY,
}

_TURN_OFF_VKS = {
    VK_IME_OFF,
    VK_OEM_ATTN,
}

_TRANSLITERATE_VKS = {
    VK_F6: "f6",
    VK_F7: "f7",
    VK_F8: "f8",
    VK_F9: "f9",
    VK_F10: "f10",
}

_NUMPAD_LITERAL_VKS = {
    VK_MULTIPLY: "*",
    VK_ADD: "+",
    VK_SUBTRACT: "-",
    VK_DECIMAL: ".",
    VK_DIVIDE: "/",
}

_NUMPAD_VKS = {
    *range(VK_NUMPAD0, VK_NUMPAD9 + 1),
    *_NUMPAD_LITERAL_VKS,
}

_CURSOR_MOVE_VKS = {
    VK_LEFT: "left",
    VK_RIGHT: "right",
    VK_HOME: "home",
    VK_END: "end",
}

_CONTEXT_RESET_VKS = {
    VK_LEFT,
    VK_RIGHT,
    VK_UP,
    VK_DOWN,
    VK_HOME,
    VK_END,
    VK_PRIOR,
    VK_NEXT,
    VK_DELETE,
    VK_TAB,
    VK_ESCAPE,
}

_EXTENDED_VKS = {
    VK_PRIOR,
    VK_NEXT,
    VK_END,
    VK_HOME,
    VK_LEFT,
    VK_UP,
    VK_RIGHT,
    VK_DOWN,
    VK_DELETE,
}

_SYMBOL_AND_DIGIT_VKS = {
    *range(0x30, 0x3A),
    *_NUMPAD_VKS,
    VK_OEM_1,
    VK_OEM_PLUS,
    VK_OEM_COMMA,
    VK_OEM_MINUS,
    VK_OEM_PERIOD,
    VK_OEM_2,
    VK_OEM_3,
    VK_OEM_4,
    VK_OEM_5,
    VK_OEM_6,
    VK_OEM_7,
    VK_OEM_102,
}

JAPANESE_SYMBOL_MAP = {
    "!": "！",
    '"': "\u201d",
    "#": "＃",
    "$": "＄",
    "%": "％",
    "&": "＆",
    "'": "\u2019",
    "(": "（",
    ")": "）",
    "*": "＊",
    "+": "＋",
    ",": "、",
    "-": "ー",
    ".": "。",
    "/": "・",
    ":": "：",
    ";": "；",
    "<": "＜",
    "=": "＝",
    ">": "＞",
    "?": "？",
    "@": "＠",
    "[": "「",
    "\\": "￥",
    "]": "」",
    "^": "＾",
    "_": "＿",
    "`": "｀",
    "{": "｛",
    "|": "｜",
    "}": "｝",
    "~": "～",
}

GWL_EXSTYLE = -20
GA_ROOT = 2
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
HWND_TOPMOST = wintypes.HWND(-1)
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
MONITOR_DEFAULTTONEAREST = 2
WM_IME_CONTROL = 0x0283
IMC_GETOPENSTATUS = 0x0005
IMC_SETOPENSTATUS = 0x0006
SMTO_ABORTIFHUNG = 0x0002
SPI_GETHIGHCONTRAST = 0x0042
HCF_HIGHCONTRASTON = 0x00000001
COLOR_WINDOW = 5
COLOR_WINDOWTEXT = 8
COLOR_HIGHLIGHT = 13
COLOR_HIGHLIGHTTEXT = 14
COLOR_BTNFACE = 15
COLOR_GRAYTEXT = 17
COLOR_BTNTEXT = 18
MDT_EFFECTIVE_DPI = 0
DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)
PROCESS_PER_MONITOR_DPI_AWARE = 2
DWMWA_USE_IMMERSIVE_DARK_MODE_BEFORE_20H1 = 19
DWMWA_USE_IMMERSIVE_DARK_MODE = 20
_VK_MENU_MASK = 0xE8

TOKEN_QUERY = 0x0008
TokenElevation = 20
TokenIntegrityLevel = 25
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
ERROR_ACCESS_DENIED = 5

WM_USER = 0x0400
WM_NULL = 0x0000
WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_CANCELMODE = 0x001F
WM_COMMAND = 0x0111
WM_CONTEXTMENU = 0x007B
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205
WM_TRAY_CALLBACK = WM_USER + 100
WM_TRAY_UPDATE = WM_USER + 101

NIM_ADD = 0x00000000
NIM_MODIFY = 0x00000001
NIM_DELETE = 0x00000002
NIF_MESSAGE = 0x00000001
NIF_ICON = 0x00000002
NIF_TIP = 0x00000004

MF_STRING = 0x00000000
MF_SEPARATOR = 0x00000800
TPM_RIGHTBUTTON = 0x0002
TPM_RETURNCMD = 0x0100
TPM_NONOTIFY = 0x0080

TRANSPARENT = 1
DT_CENTER = 0x00000001
DT_VCENTER = 0x00000004
DT_SINGLELINE = 0x00000020

_TRAY_CLASS_NAME = "AzooKeyLiveBridgeTrayClass"
_TRAY_WINDOW_NAME = "AzooKeyLiveBridgeTray"

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
imm32 = ctypes.WinDLL("imm32", use_last_error=True)
advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
try:
    shcore = ctypes.WinDLL("shcore", use_last_error=True)
except OSError:
    shcore = None
try:
    dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
except OSError:
    dwmapi = None


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


class GUITHREADINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("hwndActive", wintypes.HWND),
        ("hwndFocus", wintypes.HWND),
        ("hwndCapture", wintypes.HWND),
        ("hwndMenuOwner", wintypes.HWND),
        ("hwndMoveSize", wintypes.HWND),
        ("hwndCaret", wintypes.HWND),
        ("rcCaret", RECT),
    ]


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", RECT),
        ("rcWork", RECT),
        ("dwFlags", wintypes.DWORD),
    ]


class HIGHCONTRASTW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("dwFlags", wintypes.DWORD),
        ("lpszDefaultScheme", wintypes.LPWSTR),
    ]


class TOKEN_ELEVATION(ctypes.Structure):
    _fields_ = [("TokenIsElevated", wintypes.DWORD)]


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256),
        ("uVersion", wintypes.UINT),
        ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", GUID),
        ("hBalloonIcon", wintypes.HICON),
    ]


class ICONINFO(ctypes.Structure):
    _fields_ = [
        ("fIcon", wintypes.BOOL),
        ("xHotspot", wintypes.DWORD),
        ("yHotspot", wintypes.DWORD),
        ("hbmMask", wintypes.HBITMAP),
        ("hbmColor", wintypes.HBITMAP),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class LOGFONTW(ctypes.Structure):
    _fields_ = [
        ("lfHeight", wintypes.LONG),
        ("lfWidth", wintypes.LONG),
        ("lfEscapement", wintypes.LONG),
        ("lfOrientation", wintypes.LONG),
        ("lfWeight", wintypes.LONG),
        ("lfItalic", ctypes.c_ubyte),
        ("lfUnderline", ctypes.c_ubyte),
        ("lfStrikeOut", ctypes.c_ubyte),
        ("lfCharSet", ctypes.c_ubyte),
        ("lfOutPrecision", ctypes.c_ubyte),
        ("lfClipPrecision", ctypes.c_ubyte),
        ("lfQuality", ctypes.c_ubyte),
        ("lfPitchAndFamily", ctypes.c_ubyte),
        ("lfFaceName", wintypes.WCHAR * 32),
    ]


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", POINT),
        ("lPrivate", wintypes.DWORD),
    ]


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]


class INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("data",)
    _fields_ = [("type", wintypes.DWORD), ("data", INPUTUNION)]


WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
        ("hIconSm", wintypes.HICON),
    ]


HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
user32.SetWindowsHookExW.restype = wintypes.HHOOK
user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
user32.CallNextHookEx.restype = ctypes.c_ssize_t
user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
user32.UnhookWindowsHookEx.restype = wintypes.BOOL
user32.GetMessageW.argtypes = [ctypes.POINTER(MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.GetMessageW.restype = ctypes.c_int
user32.TranslateMessage.argtypes = [ctypes.POINTER(MSG)]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(MSG)]
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.GetForegroundWindow.restype = wintypes.HWND
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.SetForegroundWindow.restype = wintypes.BOOL
if hasattr(user32, "AllowSetForegroundWindow"):
    user32.AllowSetForegroundWindow.argtypes = [wintypes.DWORD]
    user32.AllowSetForegroundWindow.restype = wintypes.BOOL
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.GetGUIThreadInfo.argtypes = [wintypes.DWORD, ctypes.POINTER(GUITHREADINFO)]
user32.GetGUIThreadInfo.restype = wintypes.BOOL
user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(POINT)]
user32.ClientToScreen.restype = wintypes.BOOL
user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
user32.GetCursorPos.restype = wintypes.BOOL
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
user32.GetWindowRect.restype = wintypes.BOOL
user32.MonitorFromPoint.argtypes = [POINT, wintypes.DWORD]
user32.MonitorFromPoint.restype = wintypes.HMONITOR
user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
user32.MonitorFromWindow.restype = wintypes.HMONITOR
user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MONITORINFO)]
user32.GetMonitorInfoW.restype = wintypes.BOOL
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.SetWindowPos.restype = wintypes.BOOL
if ctypes.sizeof(ctypes.c_void_p) == 8:
    _get_window_long = user32.GetWindowLongPtrW
    _set_window_long = user32.SetWindowLongPtrW
else:
    _get_window_long = user32.GetWindowLongW
    _set_window_long = user32.SetWindowLongW
_get_window_long.argtypes = [wintypes.HWND, ctypes.c_int]
_get_window_long.restype = ctypes.c_ssize_t
_set_window_long.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
_set_window_long.restype = ctypes.c_ssize_t
user32.GetKeyboardLayout.argtypes = [wintypes.DWORD]
user32.GetKeyboardLayout.restype = ctypes.c_void_p
user32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
user32.MapVirtualKeyW.restype = wintypes.UINT
user32.GetKeyboardState.argtypes = [ctypes.POINTER(ctypes.c_ubyte)]
user32.ToUnicodeEx.argtypes = [
    wintypes.UINT,
    wintypes.UINT,
    ctypes.POINTER(ctypes.c_ubyte),
    ctypes.POINTER(wintypes.WCHAR),
    ctypes.c_int,
    wintypes.UINT,
    ctypes.c_void_p,
]
user32.ToUnicodeEx.restype = ctypes.c_int
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.GetKeyState.argtypes = [ctypes.c_int]
user32.GetKeyState.restype = ctypes.c_short
user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = wintypes.UINT
user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.FindWindowW.restype = wintypes.HWND
user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
user32.EnumWindows.restype = wintypes.BOOL
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetClassNameW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.ShowWindow.restype = wintypes.BOOL
user32.SendMessageTimeoutW.argtypes = [
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
    wintypes.UINT,
    wintypes.UINT,
    ctypes.POINTER(ctypes.c_size_t),
]
user32.SendMessageTimeoutW.restype = ctypes.c_ssize_t
user32.SystemParametersInfoW.argtypes = [wintypes.UINT, wintypes.UINT, ctypes.c_void_p, wintypes.UINT]
user32.SystemParametersInfoW.restype = wintypes.BOOL
user32.GetSysColor.argtypes = [ctypes.c_int]
user32.GetSysColor.restype = wintypes.DWORD
user32.RegisterWindowMessageW.argtypes = [wintypes.LPCWSTR]
user32.RegisterWindowMessageW.restype = wintypes.UINT
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostMessageW.restype = wintypes.BOOL
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.DefWindowProcW.restype = ctypes.c_ssize_t
user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
user32.RegisterClassExW.restype = wintypes.ATOM
user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
user32.UnregisterClassW.restype = wintypes.BOOL
user32.CreateWindowExW.argtypes = [
    wintypes.DWORD,
    wintypes.LPCWSTR,
    wintypes.LPCWSTR,
    wintypes.DWORD,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.HWND,
    wintypes.HMENU,
    wintypes.HINSTANCE,
    ctypes.c_void_p,
]
user32.CreateWindowExW.restype = wintypes.HWND
user32.DestroyWindow.argtypes = [wintypes.HWND]
user32.DestroyWindow.restype = wintypes.BOOL
user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetAncestor.restype = wintypes.HWND
user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsWindow.restype = wintypes.BOOL
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.IsIconic.argtypes = [wintypes.HWND]
user32.IsIconic.restype = wintypes.BOOL
user32.CreatePopupMenu.restype = wintypes.HMENU
user32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR]
user32.AppendMenuW.restype = wintypes.BOOL
user32.SetMenuDefaultItem.argtypes = [wintypes.HMENU, wintypes.UINT, wintypes.UINT]
user32.SetMenuDefaultItem.restype = wintypes.BOOL
user32.TrackPopupMenu.argtypes = [
    wintypes.HMENU,
    wintypes.UINT,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.HWND,
    ctypes.c_void_p,
]
user32.TrackPopupMenu.restype = wintypes.BOOL
user32.DestroyMenu.argtypes = [wintypes.HMENU]
user32.DestroyMenu.restype = wintypes.BOOL
user32.DrawTextW.argtypes = [wintypes.HDC, wintypes.LPCWSTR, ctypes.c_int, ctypes.POINTER(RECT), wintypes.UINT]
user32.DrawTextW.restype = ctypes.c_int
user32.FillRect.argtypes = [wintypes.HDC, ctypes.POINTER(RECT), wintypes.HBRUSH]
user32.FillRect.restype = ctypes.c_int
user32.CreateIconIndirect.argtypes = [ctypes.POINTER(ICONINFO)]
user32.CreateIconIndirect.restype = wintypes.HICON
user32.DestroyIcon.argtypes = [wintypes.HICON]
user32.DestroyIcon.restype = wintypes.BOOL
user32.PostQuitMessage.argtypes = [ctypes.c_int]
if hasattr(user32, "SetProcessDpiAwarenessContext"):
    user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
    user32.SetProcessDpiAwarenessContext.restype = wintypes.BOOL
if hasattr(user32, "GetDpiForWindow"):
    user32.GetDpiForWindow.argtypes = [wintypes.HWND]
    user32.GetDpiForWindow.restype = wintypes.UINT
if shcore is not None and hasattr(shcore, "GetDpiForMonitor"):
    shcore.GetDpiForMonitor.argtypes = [
        wintypes.HMONITOR,
        ctypes.c_int,
        ctypes.POINTER(wintypes.UINT),
        ctypes.POINTER(wintypes.UINT),
    ]
    shcore.GetDpiForMonitor.restype = ctypes.c_long
if dwmapi is not None and hasattr(dwmapi, "DwmSetWindowAttribute"):
    dwmapi.DwmSetWindowAttribute.argtypes = [
        wintypes.HWND,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    dwmapi.DwmSetWindowAttribute.restype = ctypes.c_long
imm32.ImmGetDefaultIMEWnd.argtypes = [wintypes.HWND]
imm32.ImmGetDefaultIMEWnd.restype = wintypes.HWND
kernel32.GetCurrentProcess.restype = wintypes.HANDLE
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE
kernel32.GetCurrentThreadId.restype = wintypes.DWORD
kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.CreateMutexW.restype = wintypes.HANDLE
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL
kernel32.GetStdHandle.argtypes = [wintypes.DWORD]
kernel32.GetStdHandle.restype = wintypes.HANDLE
kernel32.GetConsoleMode.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
kernel32.GetConsoleMode.restype = wintypes.BOOL
kernel32.SetConsoleMode.argtypes = [wintypes.HANDLE, wintypes.DWORD]
kernel32.SetConsoleMode.restype = wintypes.BOOL
advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
advapi32.OpenProcessToken.restype = wintypes.BOOL
advapi32.GetTokenInformation.argtypes = [
    wintypes.HANDLE,
    ctypes.c_int,
    ctypes.c_void_p,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
]
advapi32.GetTokenInformation.restype = wintypes.BOOL
advapi32.GetSidSubAuthorityCount.argtypes = [ctypes.c_void_p]
advapi32.GetSidSubAuthorityCount.restype = ctypes.POINTER(ctypes.c_ubyte)
advapi32.GetSidSubAuthority.argtypes = [ctypes.c_void_p, wintypes.DWORD]
advapi32.GetSidSubAuthority.restype = ctypes.POINTER(wintypes.DWORD)
shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
shell32.Shell_NotifyIconW.restype = wintypes.BOOL
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.DeleteDC.argtypes = [wintypes.HDC]
gdi32.DeleteDC.restype = wintypes.BOOL
gdi32.CreateDIBSection.argtypes = [
    wintypes.HDC,
    ctypes.c_void_p,
    wintypes.UINT,
    ctypes.POINTER(ctypes.c_void_p),
    wintypes.HANDLE,
    wintypes.DWORD,
]
gdi32.CreateDIBSection.restype = wintypes.HBITMAP
gdi32.CreateBitmap.argtypes = [ctypes.c_int, ctypes.c_int, wintypes.UINT, wintypes.UINT, ctypes.c_void_p]
gdi32.CreateBitmap.restype = wintypes.HBITMAP
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteObject.restype = wintypes.BOOL
gdi32.CreateSolidBrush.argtypes = [wintypes.DWORD]
gdi32.CreateSolidBrush.restype = wintypes.HBRUSH
gdi32.SetBkMode.argtypes = [wintypes.HDC, ctypes.c_int]
gdi32.SetBkMode.restype = ctypes.c_int
gdi32.SetTextColor.argtypes = [wintypes.HDC, wintypes.DWORD]
gdi32.SetTextColor.restype = wintypes.DWORD
gdi32.CreateFontIndirectW.argtypes = [ctypes.POINTER(LOGFONTW)]
gdi32.CreateFontIndirectW.restype = wintypes.HFONT

ERROR_ALREADY_EXISTS = 183
SW_RESTORE = 9
STD_INPUT_HANDLE = wintypes.DWORD(-10 & 0xFFFFFFFF).value
ENABLE_QUICK_EDIT_MODE = 0x0040
ENABLE_EXTENDED_FLAGS = 0x0080


@dataclass(frozen=True)
class InputEvent:
    kind: str
    hwnd: int
    char: str = ""
    completed: threading.Event | None = None
    raw_char: str = ""
    seq: int = 0


def enable_dpi_awareness() -> None:
    """Enable Per-Monitor V2 DPI awareness so tkinter windows and Win32 coordinates match."""
    try:
        if hasattr(user32, "SetProcessDpiAwarenessContext"):
            if user32.SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2):
                return
    except Exception:
        pass
    try:
        if shcore is not None and hasattr(shcore, "SetProcessDpiAwareness"):
            if shcore.SetProcessDpiAwareness(PROCESS_PER_MONITOR_DPI_AWARE) == 0:
                return
    except Exception:
        pass
    try:
        if hasattr(user32, "SetProcessDPIAware"):
            user32.SetProcessDPIAware()
    except Exception:
        pass


def dpi_for_window(hwnd: int) -> int:
    """Return the effective DPI for a window handle, falling back to 96."""
    if hwnd and hasattr(user32, "GetDpiForWindow"):
        try:
            dpi = int(user32.GetDpiForWindow(wintypes.HWND(hwnd)) or 0)
            if dpi > 0:
                return dpi
        except Exception:
            pass
    return 96


def _dpi_for_monitor(monitor: int) -> int:
    if monitor and shcore is not None and hasattr(shcore, "GetDpiForMonitor"):
        try:
            dpi_x = wintypes.UINT()
            dpi_y = wintypes.UINT()
            if shcore.GetDpiForMonitor(monitor, MDT_EFFECTIVE_DPI, ctypes.byref(dpi_x), ctypes.byref(dpi_y)) == 0:
                if int(dpi_x.value) > 0:
                    return int(dpi_x.value)
        except Exception:
            pass
    return 96


def dpi_for_point(x: int, y: int) -> int:
    """Return the effective DPI for the monitor containing (x, y), falling back to 96."""
    try:
        monitor = int(user32.MonitorFromPoint(POINT(int(x), int(y)), MONITOR_DEFAULTTONEAREST) or 0)
        return _dpi_for_monitor(monitor)
    except Exception:
        return 96


def _sys_color_hex(index: int) -> str:
    color = int(user32.GetSysColor(index))
    r = color & 0xFF
    g = (color >> 8) & 0xFF
    b = (color >> 16) & 0xFF
    return f"#{r:02x}{g:02x}{b:02x}"


def _is_high_contrast() -> bool:
    hc = HIGHCONTRASTW()
    hc.cbSize = ctypes.sizeof(hc)
    try:
        if user32.SystemParametersInfoW(SPI_GETHIGHCONTRAST, hc.cbSize, ctypes.byref(hc), 0):
            return bool(hc.dwFlags & HCF_HIGHCONTRASTON)
    except Exception:
        pass
    return False


def _is_dark_mode() -> bool:
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        ) as key:
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return int(value) == 0
    except OSError:
        return False


def system_text_scale_factor() -> float:
    """Return Windows 'Make text bigger' scale multiplier (1.0 .. 2.25)."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Accessibility") as key:
            value, _ = winreg.QueryValueEx(key, "TextScaleFactor")
            pct = float(int(value))
            if 100.0 <= pct <= 225.0:
                return pct / 100.0
    except (OSError, ValueError, TypeError):
        pass
    return 1.0


def apply_window_dark_titlebar(hwnd: int, enabled: bool) -> None:
    """Ask DWM to render dark window chrome when supported and not in High Contrast."""
    if not hwnd or dwmapi is None or not hasattr(dwmapi, "DwmSetWindowAttribute"):
        return
    target = root_window_hwnd(hwnd)
    if not target:
        return
    flag = wintypes.BOOL(bool(enabled and not _is_high_contrast()))
    for attr in (DWMWA_USE_IMMERSIVE_DARK_MODE, DWMWA_USE_IMMERSIVE_DARK_MODE_BEFORE_20H1):
        try:
            hr = int(dwmapi.DwmSetWindowAttribute(wintypes.HWND(target), attr, ctypes.byref(flag), ctypes.sizeof(flag)))
            if hr == 0:
                return
        except Exception:
            pass


def system_theme_signature() -> tuple[bool, bool]:
    """Return (high_contrast, dark_mode) to detect Windows theme transitions."""
    return _is_high_contrast(), _is_dark_mode()


def system_theme_palette() -> dict[str, str]:
    """Return color tokens adapting to Windows High Contrast or Light/Dark mode."""
    if _is_high_contrast():
        window_bg = _sys_color_hex(COLOR_WINDOW)
        window_fg = _sys_color_hex(COLOR_WINDOWTEXT)
        highlight_bg = _sys_color_hex(COLOR_HIGHLIGHT)
        highlight_fg = _sys_color_hex(COLOR_HIGHLIGHTTEXT)
        btn_bg = _sys_color_hex(COLOR_BTNFACE)
        btn_fg = _sys_color_hex(COLOR_BTNTEXT)
        disabled_fg = _sys_color_hex(COLOR_GRAYTEXT)
        return {
            "popup_bg": window_bg,
            "popup_border": window_fg,
            "header_bg": btn_bg,
            "header_fg": btn_fg,
            "item_fg": window_fg,
            "selected_bg": highlight_bg,
            "selected_fg": highlight_fg,
            "hover_bg": btn_bg,
            "hover_fg": btn_fg,
            "toggle_on_bg": highlight_bg,
            "toggle_on_fg": highlight_fg,
            "toggle_off_bg": btn_bg,
            "toggle_off_fg": btn_fg,
            "toggle_disabled_bg": btn_bg,
            "toggle_disabled_fg": disabled_fg,
            "toggle_warn_bg": btn_bg,
            "toggle_warn_fg": btn_fg,
            "toggle_active_bg": highlight_bg,
            "settings_bg": window_bg,
            "settings_card_bg": window_bg,
            "settings_card_border": window_fg,
            "settings_fg": window_fg,
            "settings_muted_fg": window_fg,
            "settings_hover_bg": window_bg,
            "settings_input_bg": window_bg,
            "settings_input_fg": window_fg,
            "settings_border": window_fg,
            "settings_focus_ring": highlight_bg,
            "settings_button_bg": btn_bg,
            "settings_button_fg": btn_fg,
            "settings_button_hover_bg": highlight_bg,
            "settings_button_hover_fg": highlight_fg,
            "settings_button_active_bg": highlight_bg,
            "settings_primary_bg": highlight_bg,
            "settings_primary_fg": highlight_fg,
            "settings_primary_hover_bg": btn_bg,
            "settings_primary_hover_fg": btn_fg,
            "settings_primary_active_bg": highlight_bg,
            "settings_danger_bg": btn_bg,
            "settings_danger_fg": btn_fg,
            "settings_danger_hover_bg": highlight_bg,
            "settings_danger_hover_fg": highlight_fg,
            "settings_danger_active_bg": highlight_bg,
            "settings_danger_border": window_fg,
            "settings_accent_bg": btn_bg,
            "settings_accent_fg": btn_fg,
            "settings_accent_hover_bg": highlight_bg,
            "settings_accent_hover_fg": highlight_fg,
            "settings_accent_active_bg": highlight_bg,
            "settings_accent_border": window_fg,
            "settings_warn_bg": btn_bg,
            "settings_warn_fg": btn_fg,
            "settings_warn_hover_bg": highlight_bg,
            "settings_warn_hover_fg": highlight_fg,
            "settings_warn_active_bg": highlight_bg,
            "settings_warn_border": window_fg,
            "settings_disabled_bg": btn_bg,
            "settings_disabled_fg": disabled_fg,
            "settings_selected_bg": highlight_bg,
            "settings_selected_fg": highlight_fg,
            "settings_status_ok_fg": window_fg,
            "settings_status_warn_fg": window_fg,
            "settings_status_err_fg": window_fg,
            "settings_scroll_trough": window_bg,
            "settings_scroll_thumb": btn_bg,
        }
    if _is_dark_mode():
        return {
            "popup_bg": "#202020",
            "popup_border": "#8d96a5",
            "header_bg": "#2b2b2b",
            "header_fg": "#d6d2c8",
            "item_fg": "#f2f2f2",
            "selected_bg": "#284b73",
            "selected_fg": "#ffffff",
            "hover_bg": "#31363f",
            "hover_fg": "#f2f2f2",
            "toggle_on_bg": "#1f4e2d",
            "toggle_on_fg": "#b9f6ca",
            "toggle_off_bg": "#2b2b2b",
            "toggle_off_fg": "#efefef",
            "toggle_disabled_bg": "#242424",
            "toggle_disabled_fg": "#9ca3af",
            "toggle_warn_bg": "#4d3800",
            "toggle_warn_fg": "#ffd666",
            "toggle_active_bg": "#334c66",
            "settings_bg": "#1b1d21",
            "settings_card_bg": "#23262c",
            "settings_card_border": "#8d96a5",
            "settings_fg": "#f3f4f6",
            "settings_muted_fg": "#c8cdd5",
            "settings_hover_bg": "#2c3340",
            "settings_input_bg": "#15171a",
            "settings_input_fg": "#ffffff",
            "settings_border": "#8d96a5",
            "settings_focus_ring": "#7cc4ff",
            "settings_button_bg": "#2e333c",
            "settings_button_fg": "#f3f4f6",
            "settings_button_hover_bg": "#3a414d",
            "settings_button_hover_fg": "#ffffff",
            "settings_button_active_bg": "#454e5d",
            "settings_primary_bg": "#1d5bbf",
            "settings_primary_fg": "#ffffff",
            "settings_primary_hover_bg": "#184ca1",
            "settings_primary_hover_fg": "#ffffff",
            "settings_primary_active_bg": "#133d82",
            "settings_danger_bg": "#3b1418",
            "settings_danger_fg": "#ff5c5c",
            "settings_danger_hover_bg": "#4f1b21",
            "settings_danger_hover_fg": "#ff8080",
            "settings_danger_active_bg": "#632229",
            "settings_danger_border": "#f87171",
            "settings_accent_bg": "#162d4d",
            "settings_accent_fg": "#7cc4ff",
            "settings_accent_hover_bg": "#1e3c66",
            "settings_accent_hover_fg": "#a3d6ff",
            "settings_accent_active_bg": "#264c80",
            "settings_accent_border": "#60a5fa",
            "settings_warn_bg": "#3d2e00",
            "settings_warn_fg": "#ffd666",
            "settings_warn_hover_bg": "#523e00",
            "settings_warn_hover_fg": "#ffe58f",
            "settings_warn_active_bg": "#664e00",
            "settings_warn_border": "#facc15",
            "settings_disabled_bg": "#272a30",
            "settings_disabled_fg": "#9ca3af",
            "settings_selected_bg": "#284b73",
            "settings_selected_fg": "#ffffff",
            "settings_status_ok_fg": "#86efac",
            "settings_status_warn_fg": "#fde047",
            "settings_status_err_fg": "#fca5a5",
            "settings_scroll_trough": "#181a1e",
            "settings_scroll_thumb": "#5c6475",
        }
    return {
        "popup_bg": "#fffdf7",
        "popup_border": "#6d685e",
        "header_bg": "#f3efe4",
        "header_fg": "#4a463d",
        "item_fg": "#1f1f1f",
        "selected_bg": "#cfe4ff",
        "selected_fg": "#0d335d",
        "hover_bg": "#eaf3ff",
        "hover_fg": "#1f1f1f",
        "toggle_on_bg": "#d8f0de",
        "toggle_on_fg": "#14532d",
        "toggle_off_bg": "#e8e8e8",
        "toggle_off_fg": "#333333",
        "toggle_disabled_bg": "#e8e8e8",
        "toggle_disabled_fg": "#666666",
        "toggle_warn_bg": "#fff3cd",
        "toggle_warn_fg": "#664d03",
        "toggle_active_bg": "#d8e8ff",
        "settings_bg": "#f4f5f7",
        "settings_card_bg": "#ffffff",
        "settings_card_border": "#68707d",
        "settings_fg": "#16181d",
        "settings_muted_fg": "#454c57",
        "settings_hover_bg": "#edf3ff",
        "settings_input_bg": "#ffffff",
        "settings_input_fg": "#16181d",
        "settings_border": "#68707d",
        "settings_focus_ring": "#0046ad",
        "settings_button_bg": "#eef0f4",
        "settings_button_fg": "#16181d",
        "settings_button_hover_bg": "#dfe5ee",
        "settings_button_hover_fg": "#16181d",
        "settings_button_active_bg": "#cfd8e6",
        "settings_primary_bg": "#0b57d0",
        "settings_primary_fg": "#ffffff",
        "settings_primary_hover_bg": "#0842a0",
        "settings_primary_hover_fg": "#ffffff",
        "settings_primary_active_bg": "#06327a",
        "settings_danger_bg": "#ffe8e8",
        "settings_danger_fg": "#cc0000",
        "settings_danger_hover_bg": "#ffd6d6",
        "settings_danger_hover_fg": "#a30000",
        "settings_danger_active_bg": "#ffc2c2",
        "settings_danger_border": "#dc2626",
        "settings_accent_bg": "#e8f1ff",
        "settings_accent_fg": "#0842a0",
        "settings_accent_hover_bg": "#d6e6ff",
        "settings_accent_hover_fg": "#06327a",
        "settings_accent_active_bg": "#c2daff",
        "settings_accent_border": "#2563eb",
        "settings_warn_bg": "#fff3cd",
        "settings_warn_fg": "#664d03",
        "settings_warn_hover_bg": "#fde69a",
        "settings_warn_hover_fg": "#543b00",
        "settings_warn_active_bg": "#fcd970",
        "settings_warn_border": "#a16207",
        "settings_disabled_bg": "#e6e8ec",
        "settings_disabled_fg": "#5b626e",
        "settings_selected_bg": "#cfe4ff",
        "settings_selected_fg": "#0d335d",
        "settings_status_ok_fg": "#14532d",
        "settings_status_warn_fg": "#713f12",
        "settings_status_err_fg": "#991b1b",
        "settings_scroll_trough": "#e5e7eb",
        "settings_scroll_thumb": "#7b8494",
    }


def disable_console_quick_edit() -> None:
    """Disable Windows Console QuickEdit so clicking the console cannot freeze the hook."""
    try:
        handle = kernel32.GetStdHandle(STD_INPUT_HANDLE)
        if not handle or handle == wintypes.HANDLE(-1).value:
            return
        mode = wintypes.DWORD()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return
        new_mode = (mode.value & ~ENABLE_QUICK_EDIT_MODE) | ENABLE_EXTENDED_FLAGS
        kernel32.SetConsoleMode(handle, new_mode)
    except Exception:
        pass


def acquire_single_instance_mutex(name: str = "Local\\AzooKeyLiveBridgeSingleton") -> int | None:
    """Return mutex handle if this is the only running instance, else None."""
    handle = kernel32.CreateMutexW(None, False, name)
    if not handle:
        return None
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return None
    return int(handle)


def release_mutex(handle: int | None) -> None:
    if handle:
        kernel32.CloseHandle(wintypes.HANDLE(handle))


_WM_SHOW_SETTINGS = int(user32.RegisterWindowMessageW("AzooKeyLiveBridgeShowSettings") or 0)


def _token_integrity_rid(token_handle: int) -> int | None:
    needed = wintypes.DWORD()
    advapi32.GetTokenInformation(token_handle, TokenIntegrityLevel, None, 0, ctypes.byref(needed))
    if not needed.value:
        return None
    buf = (ctypes.c_ubyte * needed.value)()
    if not advapi32.GetTokenInformation(token_handle, TokenIntegrityLevel, buf, needed.value, ctypes.byref(needed)):
        return None
    psid = ctypes.cast(buf, ctypes.POINTER(ctypes.c_void_p))[0]
    if not psid:
        return None
    count_ptr = advapi32.GetSidSubAuthorityCount(psid)
    if not count_ptr or count_ptr[0] == 0:
        return None
    sub_ptr = advapi32.GetSidSubAuthority(psid, int(count_ptr[0]) - 1)
    return int(sub_ptr[0]) if sub_ptr else None


_SELF_PRIVILEGE: tuple[bool, int] | None = None
_LAST_ELEVATED_CHECK: tuple[int, int, bool, float] | None = None
_ELEVATION_CACHE_TTL = 1.0


def _current_process_privilege() -> tuple[bool, int]:
    global _SELF_PRIVILEGE
    if _SELF_PRIVILEGE is not None:
        return _SELF_PRIVILEGE
    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), TOKEN_QUERY, ctypes.byref(token)):
        return False, 0x2000
    try:
        elev = TOKEN_ELEVATION()
        ret = wintypes.DWORD()
        is_elev = False
        if advapi32.GetTokenInformation(token, TokenElevation, ctypes.byref(elev), ctypes.sizeof(elev), ctypes.byref(ret)):
            is_elev = bool(elev.TokenIsElevated)
        rid = _token_integrity_rid(int(token.value))
        result = (is_elev, (rid if rid is not None else 0x2000))
        _SELF_PRIVILEGE = result
        return result
    finally:
        kernel32.CloseHandle(token)


def is_window_elevated(hwnd: int) -> bool:
    """Return True when hwnd belongs to a higher-privilege process blocked by UIPI."""
    global _LAST_ELEVATED_CHECK
    if not hwnd:
        return False
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    target_pid = int(pid.value or 0)
    if not target_pid or target_pid == os.getpid():
        return False
    now = time.monotonic()
    cached = _LAST_ELEVATED_CHECK
    if cached is not None and cached[0] == hwnd and cached[1] == target_pid and now - cached[3] < _ELEVATION_CACHE_TTL:
        return cached[2]
    self_elevated, self_rid = _current_process_privilege()
    if self_elevated:
        _LAST_ELEVATED_CHECK = (hwnd, target_pid, False, now)
        return False
    proc = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, target_pid)
    if not proc:
        blocked = ctypes.get_last_error() == ERROR_ACCESS_DENIED
        _LAST_ELEVATED_CHECK = (hwnd, target_pid, blocked, now)
        return blocked
    try:
        token = wintypes.HANDLE()
        if not advapi32.OpenProcessToken(proc, TOKEN_QUERY, ctypes.byref(token)):
            blocked = ctypes.get_last_error() == ERROR_ACCESS_DENIED
            _LAST_ELEVATED_CHECK = (hwnd, target_pid, blocked, now)
            return blocked
        try:
            elev = TOKEN_ELEVATION()
            ret = wintypes.DWORD()
            if advapi32.GetTokenInformation(token, TokenElevation, ctypes.byref(elev), ctypes.sizeof(elev), ctypes.byref(ret)):
                if elev.TokenIsElevated:
                    _LAST_ELEVATED_CHECK = (hwnd, target_pid, True, now)
                    return True
            target_rid = _token_integrity_rid(int(token.value))
            blocked = bool(target_rid is not None and target_rid > self_rid)
            _LAST_ELEVATED_CHECK = (hwnd, target_pid, blocked, now)
            return blocked
        finally:
            kernel32.CloseHandle(token)
    finally:
        kernel32.CloseHandle(proc)


def root_window_hwnd(hwnd: int) -> int:
    """Resolve the top-level Win32 wrapper HWND (such as TkTopLevel) for hwnd."""
    if not hwnd:
        return 0
    try:
        root = int(user32.GetAncestor(wintypes.HWND(hwnd), GA_ROOT) or 0)
        return root or hwnd
    except Exception:
        return hwnd


def _is_usable_window(hwnd: int) -> bool:
    return bool(
        hwnd
        and user32.IsWindow(wintypes.HWND(hwnd))
        and user32.IsWindowVisible(wintypes.HWND(hwnd))
        and not user32.IsIconic(wintypes.HWND(hwnd))
    )


def monitor_for_window(hwnd: int) -> int:
    """Return the HMONITOR integer hosting hwnd or cursor fallback."""
    target = root_window_hwnd(hwnd)
    if _is_usable_window(target):
        mon = int(user32.MonitorFromWindow(wintypes.HWND(target), MONITOR_DEFAULTTONEAREST) or 0)
        if mon:
            return mon
    point = POINT()
    if user32.GetCursorPos(ctypes.byref(point)):
        return int(user32.MonitorFromPoint(point, MONITOR_DEFAULTTONEAREST) or 0)
    return 0


def _allow_foreground_for_hwnd(hwnd: int) -> None:
    if not hwnd or not hasattr(user32, "AllowSetForegroundWindow"):
        return
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if pid.value:
        user32.AllowSetForegroundWindow(pid.value)


def _find_tk_window_by_title_prefix(title: str) -> int:
    exact = int(user32.FindWindowW("TkTopLevel", title) or 0)
    if exact:
        return exact
    if not title:
        return 0
    matched: list[int] = []
    class_buf = ctypes.create_unicode_buffer(64)
    title_buf = ctypes.create_unicode_buffer(256)
    prefixes = (f"{title} —", f"{title} -")

    def _enum_cb(hwnd: int, _lparam: int) -> bool:
        if not hwnd:
            return True
        class_len = user32.GetClassNameW(hwnd, class_buf, len(class_buf))
        if class_len <= 0 or class_buf.value != "TkTopLevel":
            return True
        text_len = user32.GetWindowTextW(hwnd, title_buf, len(title_buf))
        if text_len <= 0:
            return True
        text = title_buf.value
        if text == title or text.startswith(prefixes):
            matched.append(int(hwnd))
            return False
        return True

    callback = WNDENUMPROC(_enum_cb)
    user32.EnumWindows(callback, 0)
    return matched[0] if matched else 0


def activate_existing_window(title: str) -> bool:
    tray_hwnd = user32.FindWindowW(_TRAY_CLASS_NAME, _TRAY_WINDOW_NAME)
    if tray_hwnd and _WM_SHOW_SETTINGS:
        _allow_foreground_for_hwnd(tray_hwnd)
        if user32.PostMessageW(tray_hwnd, _WM_SHOW_SETTINGS, 0, 0):
            return True
    hwnd = _find_tk_window_by_title_prefix(title)
    if not hwnd:
        return bool(tray_hwnd)
    _allow_foreground_for_hwnd(hwnd)
    user32.ShowWindow(hwnd, SW_RESTORE)
    user32.SetForegroundWindow(hwnd)
    return True


def foreground_window() -> int:
    return int(user32.GetForegroundWindow() or 0)


def focus_window(hwnd: int) -> None:
    target = root_window_hwnd(hwnd)
    if target:
        user32.SetForegroundWindow(wintypes.HWND(target))


def suppress_native_ime(hwnd: int) -> None:
    """Turn off the target window's native Windows IME open status to prevent double conversion."""
    if not hwnd:
        return
    try:
        target = hwnd
        process_id = wintypes.DWORD()
        thread_id = user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        if thread_id:
            info = GUITHREADINFO()
            info.cbSize = ctypes.sizeof(info)
            if user32.GetGUIThreadInfo(thread_id, ctypes.byref(info)) and info.hwndFocus:
                target = int(info.hwndFocus)
        ime_hwnd = imm32.ImmGetDefaultIMEWnd(wintypes.HWND(target))
        if not ime_hwnd and target != hwnd:
            ime_hwnd = imm32.ImmGetDefaultIMEWnd(wintypes.HWND(hwnd))
        if not ime_hwnd:
            return
        result = ctypes.c_size_t()
        if user32.SendMessageTimeoutW(
            ime_hwnd,
            WM_IME_CONTROL,
            IMC_GETOPENSTATUS,
            0,
            SMTO_ABORTIFHUNG,
            30,
            ctypes.byref(result),
        ):
            if result.value != 0:
                user32.SendMessageTimeoutW(
                    ime_hwnd,
                    WM_IME_CONTROL,
                    IMC_SETOPENSTATUS,
                    0,
                    SMTO_ABORTIFHUNG,
                    30,
                    ctypes.byref(result),
                )
    except Exception:
        pass


def mouse_button_pressed() -> bool:
    return bool(
        (user32.GetAsyncKeyState(VK_LBUTTON) & 0x8000)
        or (user32.GetAsyncKeyState(VK_RBUTTON) & 0x8000)
        or (user32.GetAsyncKeyState(VK_MBUTTON) & 0x8000)
    )


def cursor_point() -> tuple[int, int] | None:
    point = POINT()
    if not user32.GetCursorPos(ctypes.byref(point)):
        return None
    return int(point.x), int(point.y)


def window_contains_point(hwnd: int, x: int, y: int) -> bool:
    target = root_window_hwnd(hwnd)
    if not _is_usable_window(target):
        return False
    rect = RECT()
    if not user32.GetWindowRect(wintypes.HWND(target), ctypes.byref(rect)):
        return False
    return int(rect.left) <= x <= int(rect.right) and int(rect.top) <= y <= int(rect.bottom)


def monitor_work_area(hwnd: int = 0) -> tuple[int, int, int, int]:
    """Return (left, top, right, bottom) of the work area for the window's monitor."""
    target = root_window_hwnd(hwnd) if hwnd else 0
    monitor = (
        user32.MonitorFromWindow(wintypes.HWND(target), MONITOR_DEFAULTTONEAREST)
        if target
        else user32.MonitorFromPoint(POINT(0, 0), MONITOR_DEFAULTTONEAREST)
    )
    if monitor:
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(info)
        if user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            work = info.rcWork
            return int(work.left), int(work.top), int(work.right), int(work.bottom)
    return 0, 0, 1920, 1080


def clamp_to_monitor_work_area(x: int, y: int, width: int, height: int) -> tuple[int, int]:
    point = POINT(x + width // 2, y + height // 2)
    monitor = user32.MonitorFromPoint(point, MONITOR_DEFAULTTONEAREST)
    if not monitor:
        return max(4, x), max(4, y)
    info = MONITORINFO()
    info.cbSize = ctypes.sizeof(info)
    if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        return max(4, x), max(4, y)
    work = info.rcWork
    clamped_x = max(int(work.left) + 4, min(x, int(work.right) - width - 4))
    clamped_y = max(int(work.top) + 4, min(y, int(work.bottom) - height - 4))
    return clamped_x, clamped_y


def has_hardware_caret(hwnd: int) -> bool:
    process_id = wintypes.DWORD()
    thread_id = user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id)) if hwnd else 0
    if not thread_id:
        return False
    info = GUITHREADINFO()
    info.cbSize = ctypes.sizeof(info)
    if not (user32.GetGUIThreadInfo(thread_id, ctypes.byref(info)) and info.hwndCaret):
        return False
    point = POINT(info.rcCaret.left, info.rcCaret.bottom)
    return bool(user32.ClientToScreen(info.hwndCaret, ctypes.byref(point)) and (point.x or point.y))


def text_cursor_position(
    hwnd: int,
    fallback_point: tuple[int, int] | None = None,
) -> tuple[int, int, int, int, int, int] | None:
    """Return caret x/y and its monitor bounds, falling back to anchor/mouse."""
    point = POINT()
    process_id = wintypes.DWORD()
    thread_id = user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id)) if hwnd else 0
    if thread_id:
        info = GUITHREADINFO()
        info.cbSize = ctypes.sizeof(info)
        if user32.GetGUIThreadInfo(thread_id, ctypes.byref(info)) and info.hwndCaret:
            point.x = info.rcCaret.left
            point.y = info.rcCaret.bottom
            if not user32.ClientToScreen(info.hwndCaret, ctypes.byref(point)):
                point.x = point.y = 0
    if not (point.x or point.y):
        if fallback_point is not None and window_contains_point(hwnd, fallback_point[0], fallback_point[1]):
            point.x, point.y = fallback_point[0], fallback_point[1]
        elif not user32.GetCursorPos(ctypes.byref(point)):
            return None

    monitor = user32.MonitorFromPoint(point, MONITOR_DEFAULTTONEAREST)
    if not monitor:
        return int(point.x), int(point.y), 0, 0, 1920, 1080
    info = MONITORINFO()
    info.cbSize = ctypes.sizeof(info)
    if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        return int(point.x), int(point.y), 0, 0, 1920, 1080
    rect = info.rcWork
    return int(point.x), int(point.y), int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)


def position_popup_no_activate(hwnd: int, x: int, y: int, width: int, height: int) -> None:
    target = root_window_hwnd(hwnd)
    if not target:
        return
    style = int(_get_window_long(target, GWL_EXSTYLE))
    _set_window_long(target, GWL_EXSTYLE, style | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)
    if not user32.SetWindowPos(
        target,
        HWND_TOPMOST,
        x,
        y,
        width,
        height,
        SWP_NOACTIVATE | SWP_SHOWWINDOW,
    ):
        raise ctypes.WinError(ctypes.get_last_error())


def make_popup_no_activate(hwnd: int) -> None:
    target = root_window_hwnd(hwnd)
    if not target:
        return
    style = int(_get_window_long(target, GWL_EXSTYLE))
    _set_window_long(target, GWL_EXSTYLE, style | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)


def taskbar_toggle_position(anchor_hwnd: int, width: int, height: int) -> tuple[int, int]:
    """Place the quick toggle just above the taskbar near the notification/IME area."""
    rect = RECT()
    target = root_window_hwnd(anchor_hwnd)
    if _is_usable_window(target) and user32.GetWindowRect(wintypes.HWND(target), ctypes.byref(rect)):
        point = POINT((rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2)
    else:
        point = POINT()
        if not user32.GetCursorPos(ctypes.byref(point)):
            point = POINT(0, 0)

    monitor = user32.MonitorFromPoint(point, MONITOR_DEFAULTTONEAREST)
    if not monitor:
        return 1920 - width - 360, 1080 - height - 56

    info = MONITORINFO()
    info.cbSize = ctypes.sizeof(info)
    if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        return 1920 - width - 360, 1080 - height - 56

    screen = info.rcMonitor
    work = info.rcWork
    scale = max(72, _dpi_for_monitor(int(monitor))) / 96.0
    margin = max(4, round(8 * scale))
    tray_reserve = max(120, round(292 * scale))
    if work.bottom < screen.bottom:
        y = work.bottom - height - margin
        x = screen.right - width - tray_reserve
    else:
        # Auto-hidden or non-bottom taskbar: keep the control above the
        # bottom-right edge of the usable desktop instead of covering the IME.
        x = work.right - width - margin
        y = work.bottom - height - margin

    edge_pad = max(4, round(4 * scale))
    x = max(work.left + edge_pad, min(x, work.right - width - edge_pad))
    y = max(work.top + edge_pad, min(y, work.bottom - height - edge_pad))
    return int(x), int(y)


def send_virtual_key(vk: int) -> None:
    send_virtual_keys(vk, 1)


def send_virtual_keys(vk: int, count: int) -> None:
    if count <= 0:
        return
    scan_code = int(user32.MapVirtualKeyW(vk, 0) or 0)
    ext_flag = KEYEVENTF_EXTENDEDKEY if vk in _EXTENDED_VKS else 0
    for index in range(count):
        _send_inputs(
            [
                INPUT(
                    type=INPUT_KEYBOARD,
                    ki=KEYBDINPUT(vk, scan_code, ext_flag, 0, APP_INJECTION_TAG),
                ),
                INPUT(
                    type=INPUT_KEYBOARD,
                    ki=KEYBDINPUT(vk, scan_code, ext_flag | KEYEVENTF_KEYUP, 0, APP_INJECTION_TAG),
                ),
            ]
        )
        if index + 1 < count:
            time.sleep(0.004)


def _ensure_shift_released() -> None:
    """Avoid turning synthetic Left/Right/Delete navigation into Shift-selection."""
    deadline = time.monotonic() + 0.04
    while user32.GetAsyncKeyState(VK_SHIFT) & 0x8000:
        if time.monotonic() >= deadline:
            inputs: list[INPUT] = []
            for shift_vk in (VK_LSHIFT, VK_RSHIFT):
                if user32.GetAsyncKeyState(shift_vk) & 0x8000:
                    scan = int(user32.MapVirtualKeyW(shift_vk, 0) or 0)
                    inputs.append(
                        INPUT(
                            type=INPUT_KEYBOARD,
                            ki=KEYBDINPUT(shift_vk, scan, KEYEVENTF_KEYUP, 0, APP_INJECTION_TAG),
                        )
                    )
            if inputs:
                _send_inputs(inputs)
                time.sleep(0.004)
            return
        time.sleep(0.005)


def send_backspaces(count: int) -> None:
    if count <= 0:
        return
    scan_code = int(user32.MapVirtualKeyW(VK_BACK, 0) or 0x0E)
    for index in range(count):
        _send_inputs(
            [
                INPUT(
                    type=INPUT_KEYBOARD,
                    ki=KEYBDINPUT(VK_BACK, scan_code, 0, 0, APP_INJECTION_TAG),
                ),
                INPUT(
                    type=INPUT_KEYBOARD,
                    ki=KEYBDINPUT(VK_BACK, scan_code, KEYEVENTF_KEYUP, 0, APP_INJECTION_TAG),
                ),
            ]
        )
        if index + 1 < count:
            time.sleep(0.004)


def replace_unicode_text(old_text: str, new_text: str) -> None:
    if old_text == new_text:
        return
    common = 0
    limit = min(len(old_text), len(new_text))
    while common < limit and old_text[common] == new_text[common]:
        common += 1
    backspaces = len(old_text) - common
    suffix = new_text[common:]
    if backspaces > 0:
        send_backspaces(backspaces)
        if suffix:
            time.sleep(0.008)
    if suffix:
        send_unicode_text(suffix)


def sync_unicode_text(
    old_text: str,
    old_cursor: int,
    new_text: str,
    new_cursor: int,
) -> None:
    """Update editor text from (old_text, old_cursor) to (new_text, new_cursor)."""
    old_len = len(old_text)
    new_len = len(new_text)
    clamped_old = max(-old_len, min(0, old_cursor)) if old_len else 0
    clamped_new = max(-new_len, min(0, new_cursor)) if new_len else 0
    old_pos = old_len + clamped_old
    new_pos = new_len + clamped_new

    if old_text == new_text:
        delta = new_pos - old_pos
        if delta != 0:
            _ensure_shift_released()
            if delta < 0:
                send_virtual_keys(VK_LEFT, -delta)
            else:
                send_virtual_keys(VK_RIGHT, delta)
        return

    old_left = old_text[:old_pos]
    old_right = old_text[old_pos:]
    new_left = new_text[:new_pos]
    new_right = new_text[new_pos:]

    if old_right == new_right:
        replace_unicode_text(old_left, new_left)
        return

    if (
        old_left == new_left
        and len(old_right) > len(new_right)
        and old_right.endswith(new_right)
    ):
        _ensure_shift_released()
        send_virtual_keys(VK_DELETE, len(old_right) - len(new_right))
        return

    if clamped_old < 0:
        _ensure_shift_released()
        send_virtual_keys(VK_RIGHT, -clamped_old)
        time.sleep(0.006)
    replace_unicode_text(old_text, new_text)
    if clamped_new < 0:
        time.sleep(0.006)
        _ensure_shift_released()
        send_virtual_keys(VK_LEFT, -clamped_new)


def send_unicode_text(text: str) -> None:
    # Rich-text and async UI editors can lose or reorder characters when many
    # Unicode packets are queued in a single SendInput call. Send one character
    # at a time so each character is consumed in order.
    for index, character in enumerate(text):
        encoded = character.encode("utf-16-le")
        inputs: list[INPUT] = []
        for offset in range(0, len(encoded), 2):
            code_unit = int.from_bytes(encoded[offset:offset + 2], "little")
            inputs.append(
                INPUT(
                    type=INPUT_KEYBOARD,
                    ki=KEYBDINPUT(0, code_unit, KEYEVENTF_UNICODE, 0, APP_INJECTION_TAG),
                )
            )
            inputs.append(
                INPUT(
                    type=INPUT_KEYBOARD,
                    ki=KEYBDINPUT(0, code_unit, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0, APP_INJECTION_TAG),
                )
            )
        if inputs:
            _send_inputs(inputs)
        if index + 1 < len(text):
            time.sleep(0.003)


def _send_inputs(inputs: list[INPUT]) -> None:
    array_type = INPUT * len(inputs)
    sent = user32.SendInput(len(inputs), array_type(*inputs), ctypes.sizeof(INPUT))
    if sent != len(inputs):
        raise ctypes.WinError(ctypes.get_last_error())


_HOOK_WAIT_TIMEOUT = 0.22


class KeyboardHook:
    """Installs only after the user starts the app and stays in this session."""

    def __init__(self, events: queue.Queue[InputEvent | tuple[str, int]]) -> None:
        self.events = events
        self.active = threading.Event()
        self.english = threading.Event()
        self.english_passthrough = threading.Event()
        self.fullwidth_space = threading.Event()
        self.fullwidth_space.set()
        self.shift_direct_english = threading.Event()
        self.shift_direct_english.set()
        self.ascii_direct = threading.Event()
        self.has_context = threading.Event()
        self.composing = threading.Event()
        self.selecting = threading.Event()
        self._ready = threading.Event()
        self._stopped = threading.Event()
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._hook = None
        self._mouse_hook = None
        self._callback = HOOKPROC(self._handle)
        self._mouse_callback = HOOKPROC(self._handle_mouse)
        self._swallowed: set[int] = set()
        self._swallowed_lock = threading.Lock()
        self._state_lock = threading.RLock()
        self._ignored_mouse_hwnds: tuple[int, ...] = ()
        self._input_seq = 0
        self._passthrough_gen = 0
        self._english_passthrough_pref = False
        self._suppress_commit_tokens: dict[int, int] = {}
        self._passthrough_barrier: threading.Event | None = None
        self._pending_passthrough_restore: tuple[threading.Event, int] | None = None
        self._startup_error: Exception | None = None
        self._last_toggle_time = 0.0
        self._composing_hwnd = 0
        self._visible_candidate_count = 0

    def current_input_seq(self) -> int:
        with self._state_lock:
            return self._input_seq

    def _bump_input_seq(self) -> int:
        with self._state_lock:
            self._input_seq += 1
            return self._input_seq

    def _clear_composing_locked(self) -> None:
        self.composing.clear()
        self.selecting.clear()
        self.ascii_direct.clear()
        self._composing_hwnd = 0
        self._visible_candidate_count = 0

    def clear_composing_if_current(self, seq: int = 0) -> bool:
        """Clear composing flags unless newer hook input events have already been queued."""
        with self._state_lock:
            if seq > 0 and self._input_seq != seq:
                return False
            self._clear_composing_locked()
            return True

    def try_detach_composing(self, *, if_fg_differs: int = 0) -> int | None:
        """Atomically clear composing state if still active (and optionally focus moved)."""
        with self._state_lock:
            if not self.composing.is_set():
                return None
            if if_fg_differs and (not self._composing_hwnd or if_fg_differs == self._composing_hwnd):
                return None
            self._input_seq += 1
            seq = self._input_seq
            self._clear_composing_locked()
            return seq

    def set_ignored_mouse_hwnds(self, hwnds: typing.Iterable[int]) -> None:
        """Register overlay HWNDs whose clicks should not detach uncommitted composition."""
        valid = tuple(int(hwnd) for hwnd in hwnds if hwnd)
        with self._state_lock:
            self._ignored_mouse_hwnds = valid

    def _is_ignored_mouse_point(self, x: int, y: int) -> bool:
        with self._state_lock:
            hwnds = self._ignored_mouse_hwnds
        return any(window_contains_point(hwnd, x, y) for hwnd in hwnds)

    def _handle_mouse(self, code: int, message: int, pointer: int) -> int:
        if code >= 0 and message in (WM_LBUTTONDOWN, WM_RBUTTONDOWN, WM_MBUTTONDOWN, WM_XBUTTONDOWN):
            try:
                if self.composing.is_set() or self.has_context.is_set():
                    event = ctypes.cast(pointer, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
                    mx, my = int(event.pt.x), int(event.pt.y)
                    if not self._is_ignored_mouse_point(mx, my):
                        fg = foreground_window()
                        with self._state_lock:
                            detach_seq = self.try_detach_composing()
                            if detach_seq is not None:
                                self.has_context.clear()
                                self.events.put(InputEvent("detach_commit", fg, seq=detach_seq))
                            elif self.try_clear_context():
                                self.events.put(InputEvent("clear_context", fg))
            except Exception:
                pass
        return user32.CallNextHookEx(self._mouse_hook, code, message, pointer)

    def _active_passthrough_barrier_locked(self) -> threading.Event | None:
        if self._passthrough_barrier is not None:
            if self._passthrough_barrier.is_set():
                self._passthrough_barrier = None
            else:
                return self._passthrough_barrier
        if self._pending_passthrough_restore is not None:
            commit_done, _gen = self._pending_passthrough_restore
            if not commit_done.is_set():
                return commit_done
        return None

    def _has_active_passthrough_barrier_locked(self) -> bool:
        return bool(self._suppress_commit_tokens) or self._active_passthrough_barrier_locked() is not None

    def try_begin_disable_commit(
        self,
        *,
        deactivate: bool = False,
        suppress_passthrough: bool = False,
        completed: threading.Event | None = None,
    ) -> int | None:
        """Atomically capture a commit seq, clear composing, and optionally disable Japanese mode."""
        with self._state_lock:
            if deactivate:
                self.active.clear()
                self.english.set()
                if self.composing.is_set():
                    self._pending_passthrough_restore = None
            if not self.composing.is_set():
                return None
            self._input_seq += 1
            seq = self._input_seq
            if deactivate and suppress_passthrough:
                self._passthrough_gen += 1
                self.english_passthrough.clear()
                self._suppress_commit_tokens[seq] = self._passthrough_gen
                if completed is not None:
                    self._passthrough_barrier = completed
                if len(self._suppress_commit_tokens) > 8:
                    oldest = next(iter(self._suppress_commit_tokens))
                    if oldest != seq:
                        self._suppress_commit_tokens.pop(oldest, None)
            self._clear_composing_locked()
            return seq

    def complete_disable_passthrough(self, seq: int, *, enabled: bool) -> bool:
        """Apply deferred passthrough setting once a matching disable commit completes."""
        with self._state_lock:
            expected_gen = self._suppress_commit_tokens.pop(seq, None)
            if expected_gen is None:
                return False
            if not self.english.is_set() or self._passthrough_gen != expected_gen:
                return False
            self._english_passthrough_pref = bool(enabled)
            self._passthrough_gen += 1
            if self._english_passthrough_pref and not self._has_active_passthrough_barrier_locked():
                self._pending_passthrough_restore = None
                self.english_passthrough.set()
            else:
                self.english_passthrough.clear()
            return True

    def flush_pending_passthrough_restore(self) -> bool:
        """Restore english_passthrough deferred after a slow mode-switch commit finishes."""
        with self._state_lock:
            pending = self._pending_passthrough_restore
            if pending is None:
                return False
            commit_done, expected_gen = pending
            if not self.english.is_set() or self._passthrough_gen != expected_gen:
                self._pending_passthrough_restore = None
                return False
            if not commit_done.is_set():
                return False
            if self._suppress_commit_tokens:
                return False
            self._pending_passthrough_restore = None
            if self._passthrough_barrier is commit_done:
                self._passthrough_barrier = None
            self._passthrough_gen += 1
            if self._english_passthrough_pref and not self._has_active_passthrough_barrier_locked():
                self.english_passthrough.set()
                return True
            self.english_passthrough.clear()
            return False

    def try_clear_context(self) -> bool:
        with self._state_lock:
            if not self.has_context.is_set():
                return False
            self.has_context.clear()
            return True

    def try_begin_candidate_click(self, shown_seq: int = 0) -> int | None:
        """Validate popup freshness and consume selection state atomically on row click."""
        with self._state_lock:
            if not self.composing.is_set():
                return None
            if shown_seq > 0 and self._input_seq != shown_seq:
                return None
            self._input_seq += 1
            seq = self._input_seq
            self.selecting.clear()
            self._visible_candidate_count = 0
            return seq

    def try_begin_candidate_scroll(self, shown_seq: int = 0) -> int | None:
        """Validate popup freshness and enter selection state atomically on wheel scroll."""
        with self._state_lock:
            if not self.composing.is_set():
                return None
            if shown_seq > 0 and self._input_seq != shown_seq:
                return None
            self._input_seq += 1
            seq = self._input_seq
            self.selecting.set()
            return seq

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._message_loop, name="AzooKey keyboard hook", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=5):
            raise RuntimeError("Windows のキーボードフックを開始できませんでした。")
        if self._startup_error is not None:
            raise RuntimeError(f"Windows のキーボードフックを開始できません: {self._startup_error}")

    def set_active(self, enabled: bool) -> None:
        with self._state_lock:
            if enabled:
                self.active.set()
            else:
                self.active.clear()
                self._clear_composing_locked()

    def set_english(self, enabled: bool) -> None:
        with self._state_lock:
            if enabled:
                self.english.set()
            else:
                self.english.clear()

    def set_mode(
        self,
        *,
        active: bool,
        english: bool,
        clear_selecting: bool = False,
    ) -> None:
        with self._state_lock:
            if active:
                self.active.set()
            else:
                self.active.clear()
                self._clear_composing_locked()
            if english:
                self.english.set()
            else:
                self.english.clear()
            if active or not english:
                self._passthrough_gen += 1
                self._pending_passthrough_restore = None
                self._suppress_commit_tokens.clear()
                if not active and not english:
                    self._passthrough_barrier = None
            if clear_selecting:
                self.selecting.clear()

    def set_english_passthrough(self, enabled: bool) -> None:
        with self._state_lock:
            self._english_passthrough_pref = bool(enabled)
            if not self._english_passthrough_pref:
                self._pending_passthrough_restore = None
                self.english_passthrough.clear()
                return
            if self._has_active_passthrough_barrier_locked():
                self.english_passthrough.clear()
                barrier = self._active_passthrough_barrier_locked()
                if barrier is not None and self.english.is_set():
                    self._pending_passthrough_restore = (barrier, self._passthrough_gen)
                return
            self._pending_passthrough_restore = None
            self.english_passthrough.set()

    def set_fullwidth_space(self, enabled: bool) -> None:
        if enabled:
            self.fullwidth_space.set()
        else:
            self.fullwidth_space.clear()

    def set_shift_direct_english(self, enabled: bool) -> None:
        if enabled:
            self.shift_direct_english.set()
        else:
            self.shift_direct_english.clear()

    def mark_ascii_direct(self, enabled: bool, *, seq: int = 0) -> None:
        with self._state_lock:
            if seq > 0 and self._input_seq != seq:
                return
            if enabled:
                self.ascii_direct.set()
            else:
                self.ascii_direct.clear()

    def mark_has_context(self, enabled: bool) -> None:
        with self._state_lock:
            if enabled:
                self.has_context.set()
            else:
                self.has_context.clear()

    def set_visible_candidate_count(self, count: int, *, seq: int = 0) -> None:
        with self._state_lock:
            if seq > 0 and self._input_seq != seq:
                return
            self._visible_candidate_count = max(0, min(6, int(count)))

    def mark_composing(self, enabled: bool, hwnd: int = 0, *, seq: int = 0) -> None:
        with self._state_lock:
            if seq > 0 and self._input_seq != seq:
                return
            if enabled:
                self.composing.set()
                if hwnd:
                    self._composing_hwnd = hwnd
            else:
                self._clear_composing_locked()

    def mark_selecting(self, enabled: bool, *, seq: int = 0) -> None:
        with self._state_lock:
            if seq > 0 and self._input_seq != seq:
                return
            if enabled:
                self.selecting.set()
            else:
                self.selecting.clear()

    def stop(self) -> None:
        if self._thread is None:
            return
        with self._state_lock:
            self.active.clear()
            self.english.clear()
            self._passthrough_gen += 1
            self._passthrough_barrier = None
            self._pending_passthrough_restore = None
            self._suppress_commit_tokens.clear()
            self._clear_composing_locked()
        if self._thread_id:
            user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        self._thread.join(timeout=2)
        self._thread = None

    def _message_loop(self) -> None:
        self._thread_id = int(kernel32.GetCurrentThreadId())
        module_handle = kernel32.GetModuleHandleW(None)
        handle = user32.SetWindowsHookExW(
            WH_KEYBOARD_LL,
            self._callback,
            module_handle,
            0,
        )
        if not handle:
            self._startup_error = ctypes.WinError(ctypes.get_last_error())
            self._ready.set()
            return
        self._hook = handle
        mouse_handle = user32.SetWindowsHookExW(
            WH_MOUSE_LL,
            self._mouse_callback,
            module_handle,
            0,
        )
        self._mouse_hook = mouse_handle
        self._ready.set()
        message = MSG()
        try:
            while True:
                result = user32.GetMessageW(ctypes.byref(message), None, 0, 0)
                if result <= 0:
                    break
                user32.TranslateMessage(ctypes.byref(message))
                user32.DispatchMessageW(ctypes.byref(message))
        finally:
            if mouse_handle:
                user32.UnhookWindowsHookEx(mouse_handle)
            self._mouse_hook = None
            user32.UnhookWindowsHookEx(handle)
            self._hook = None
            self._stopped.set()

    def _trigger_mode_switch(self, hwnd: int, target_japanese: bool | None = None) -> bool:
        commit_done: threading.Event | None = None
        pending_barrier: threading.Event | None = None
        restore_passthrough_gen: int | None = None
        with self._state_lock:
            now = time.monotonic()
            if target_japanese is None and now - self._last_toggle_time < 0.15:
                return self.active.is_set() or self.english.is_set()
            if not self.active.is_set() and not self.english.is_set():
                return False
            self._last_toggle_time = now
            current_japanese = self.active.is_set()
            new_japanese = (not current_japanese) if target_japanese is None else target_japanese
            emit_toggle = new_japanese != current_japanese
            had_composing = self.composing.is_set()
            if had_composing:
                self._input_seq += 1
                seq = self._input_seq
                self._clear_composing_locked()
                commit_done = threading.Event()
                self.events.put(InputEvent("commit", hwnd, completed=commit_done, seq=seq))
            if emit_toggle:
                if new_japanese:
                    self.active.set()
                    self.english.clear()
                    self._passthrough_gen += 1
                    self._pending_passthrough_restore = None
                    self._suppress_commit_tokens.clear()
                else:
                    wants_passthrough = self._english_passthrough_pref or self.english_passthrough.is_set()
                    if wants_passthrough and not self._english_passthrough_pref:
                        self._english_passthrough_pref = True
                    self.active.clear()
                    self._clear_composing_locked()
                    self.english.set()
                    self._pending_passthrough_restore = None
                    self._passthrough_gen += 1
                    if had_composing:
                        self._passthrough_barrier = commit_done
                    pending_barrier = (
                        commit_done if had_composing else self._active_passthrough_barrier_locked()
                    )
                    if pending_barrier is not None:
                        self.english_passthrough.clear()
                        if wants_passthrough:
                            restore_passthrough_gen = self._passthrough_gen
                    elif wants_passthrough and not self._has_active_passthrough_barrier_locked():
                        self.english_passthrough.set()
                    else:
                        self.english_passthrough.clear()
                self.selecting.clear()
                self.events.put(("toggle", hwnd))
        if commit_done is not None:
            finished = commit_done.wait(timeout=_HOOK_WAIT_TIMEOUT)
            if restore_passthrough_gen is not None:
                with self._state_lock:
                    if self.english.is_set() and self._passthrough_gen == restore_passthrough_gen:
                        if finished:
                            if self._passthrough_barrier is commit_done:
                                self._passthrough_barrier = None
                            if (
                                self._english_passthrough_pref
                                and not self._has_active_passthrough_barrier_locked()
                            ):
                                self.english_passthrough.set()
                        else:
                            self._pending_passthrough_restore = (commit_done, restore_passthrough_gen)
        elif pending_barrier is not None and restore_passthrough_gen is not None:
            with self._state_lock:
                if (
                    self.english.is_set()
                    and self._passthrough_gen == restore_passthrough_gen
                    and self._english_passthrough_pref
                ):
                    if pending_barrier.is_set():
                        if self._passthrough_barrier is pending_barrier:
                            self._passthrough_barrier = None
                        if not self._has_active_passthrough_barrier_locked():
                            self.english_passthrough.set()
                    else:
                        self._pending_passthrough_restore = (pending_barrier, restore_passthrough_gen)
        return True

    def _handle(self, code: int, message: int, pointer: int) -> int:
        if code < 0:
            return user32.CallNextHookEx(self._hook, code, message, pointer)
        try:
            if message not in (WM_KEYDOWN, WM_SYSKEYDOWN, WM_KEYUP, WM_SYSKEYUP):
                return user32.CallNextHookEx(self._hook, code, message, pointer)
            event = ctypes.cast(pointer, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            vk = int(event.vkCode)
            is_key_up = message in (WM_KEYUP, WM_SYSKEYUP)
            if event.flags & LLKHF_INJECTED and event.dwExtraInfo == APP_INJECTION_TAG:
                return user32.CallNextHookEx(self._hook, code, message, pointer)
            if is_key_up:
                with self._swallowed_lock:
                    swallowed = vk in self._swallowed
                    self._swallowed.discard(vk)
                if swallowed:
                    return 1
                return user32.CallNextHookEx(self._hook, code, message, pointer)

            hwnd = foreground_window()
            process_id = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
            own_process = process_id.value == os.getpid()

            if not own_process:
                with self._state_lock:
                    detach_seq = self.try_detach_composing(if_fg_differs=hwnd)
                    if detach_seq is not None:
                        self.events.put(InputEvent("detach_commit", hwnd, seq=detach_seq))

            bridge_enabled = self.active.is_set() or self.english.is_set()
            no_sys_modifiers = not self._modifier_pressed(VK_CONTROL, VK_MENU, VK_LWIN, VK_RWIN)
            alt_only = (
                self._modifier_pressed(VK_MENU)
                and not self._modifier_pressed(VK_CONTROL, VK_LWIN, VK_RWIN, VK_SHIFT)
            )

            if bridge_enabled and vk in (VK_KANJI, VK_OEM_3) and alt_only:
                if self._trigger_mode_switch(hwnd, None):
                    self._mask_alt_menu_activation()
                    self._swallow(vk)
                    return 1

            if bridge_enabled and vk in _TOGGLE_VKS and no_sys_modifiers:
                if self._trigger_mode_switch(hwnd, None):
                    self._swallow(vk)
                    return 1

            if bridge_enabled and vk in _TURN_ON_VKS and no_sys_modifiers:
                if self._trigger_mode_switch(hwnd, True):
                    self._swallow(vk)
                    return 1

            if (
                bridge_enabled
                and vk in _TURN_OFF_VKS
                and no_sys_modifiers
                and not self._modifier_pressed(VK_SHIFT)
            ):
                if self._trigger_mode_switch(hwnd, False):
                    self._swallow(vk)
                    return 1

            if (
                bridge_enabled
                and vk == VK_SPACE
                and self._modifier_pressed(VK_CONTROL)
                and not self._modifier_pressed(VK_MENU, VK_LWIN, VK_RWIN, VK_SHIFT)
            ):
                if self._trigger_mode_switch(hwnd, None):
                    self._swallow(vk)
                    return 1

            if bridge_enabled and vk == VK_NONCONVERT and no_sys_modifiers:
                if self._trigger_mode_switch(hwnd, None):
                    self._swallow(vk)
                    return 1

            if bridge_enabled and vk == VK_CONVERT and no_sys_modifiers:
                convert_action = "pass"
                direction = "previous" if self._modifier_pressed(VK_SHIFT) else "next"
                with self._state_lock:
                    if self.english.is_set():
                        convert_action = "to_japanese"
                    elif not own_process and self.active.is_set():
                        convert_action = "swallow"
                        if self.composing.is_set():
                            self._input_seq += 1
                            seq = self._input_seq
                            self.selecting.set()
                            self.events.put(InputEvent("cycle", hwnd, direction, seq=seq))
                if convert_action == "to_japanese":
                    if self._trigger_mode_switch(hwnd, True):
                        self._swallow(vk)
                        return 1
                if convert_action == "swallow":
                    self._swallow(vk)
                    return 1

            if own_process:
                return user32.CallNextHookEx(self._hook, code, message, pointer)

            if vk in _MODIFIER_AND_LOCK_VKS:
                return user32.CallNextHookEx(self._hook, code, message, pointer)

            if self._modifier_pressed(VK_CONTROL, VK_MENU, VK_LWIN, VK_RWIN):
                clear_needed = False
                if self.composing.is_set():
                    clear_needed = self._commit_before_passthrough(hwnd) == "not_composing"
                elif self.active.is_set():
                    clear_needed = True
                if (
                    clear_needed
                    and not (
                        vk == 0x43
                        and self._modifier_pressed(VK_CONTROL)
                        and not self._modifier_pressed(VK_MENU, VK_LWIN, VK_RWIN)
                    )
                    and self.try_clear_context()
                ):
                    self.events.put(InputEvent("clear_context", hwnd))
                return user32.CallNextHookEx(self._hook, code, message, pointer)

            english_result = self._try_dispatch_english_key(
                code,
                message,
                pointer,
                hwnd,
                vk,
                int(event.scanCode),
            )
            if english_result is not None:
                return english_result

            if 0x41 <= vk <= 0x5A:
                char = self._translate_letter(vk, int(event.scanCode), hwnd, respect_caps=False)
                if char:
                    if not self.active.is_set():
                        return user32.CallNextHookEx(self._hook, code, message, pointer)
                    dispatch_mode = "letter"
                    with self._state_lock:
                        if not self.active.is_set():
                            dispatch_mode = "english" if self.english.is_set() else "pass"
                        else:
                            self._input_seq += 1
                            seq = self._input_seq
                            was_selecting = self.selecting.is_set()
                            self.selecting.clear()
                            if self.shift_direct_english.is_set() and char.isupper():
                                self.ascii_direct.set()
                            elif was_selecting:
                                self.ascii_direct.clear()
                            self.mark_composing(True, hwnd)
                            self.events.put(InputEvent("letter", hwnd, char, raw_char=char, seq=seq))
                    if dispatch_mode != "letter":
                        return self._fallback_inactive_key(
                            code,
                            message,
                            pointer,
                            hwnd,
                            vk,
                            int(event.scanCode),
                            allow_english=(dispatch_mode == "english"),
                        )
                    self._swallow(vk)
                    return 1

            if not self.active.is_set():
                return user32.CallNextHookEx(self._hook, code, message, pointer)

            if not self._modifier_pressed(VK_SHIFT):
                slot_index = -1
                if 0x31 <= vk <= 0x36:
                    slot_index = vk - 0x31
                elif VK_NUMPAD1 <= vk <= VK_NUMPAD1 + 5:
                    slot_index = vk - VK_NUMPAD1
                if (
                    slot_index >= 0
                    and self.composing.is_set()
                    and self.selecting.is_set()
                    and self._try_select_page_commit(hwnd, vk, slot_index)
                ):
                    return 1

            if vk in _SYMBOL_AND_DIGIT_VKS:
                raw_ascii = self._translate_ascii_symbol_or_digit(vk, int(event.scanCode), hwnd)
                char = self._translate_japanese_symbol_or_digit(vk, int(event.scanCode), hwnd)
                if char:
                    dispatch_mode = "letter"
                    auto_commit_done: threading.Event | None = None
                    with self._state_lock:
                        if not self.active.is_set():
                            dispatch_mode = "english" if self.english.is_set() else "pass"
                        else:
                            self._input_seq += 1
                            seq = self._input_seq
                            was_selecting = self.selecting.is_set()
                            self.selecting.clear()
                            keep_ascii = self.ascii_direct.is_set() and not was_selecting and bool(raw_ascii)
                            if not keep_ascii and was_selecting:
                                self.ascii_direct.clear()
                            if char in ("、", "。", "！", "？") and not keep_ascii:
                                self.mark_composing(False)
                                auto_commit_done = threading.Event()
                            else:
                                self.mark_composing(True, hwnd)
                            self.events.put(
                                InputEvent(
                                    "letter",
                                    hwnd,
                                    char,
                                    raw_char=raw_ascii or char,
                                    completed=auto_commit_done,
                                    seq=seq,
                                )
                            )
                    if dispatch_mode != "letter":
                        return self._fallback_inactive_key(
                            code,
                            message,
                            pointer,
                            hwnd,
                            vk,
                            int(event.scanCode),
                            allow_english=(dispatch_mode == "english"),
                        )
                    self._swallow(vk)
                    if auto_commit_done is not None:
                        auto_commit_done.wait(timeout=_HOOK_WAIT_TIMEOUT)
                    return 1

            if self.composing.is_set():
                status = self._dispatch_composing_key(hwnd, vk)
                if status == "swallow":
                    self._swallow(vk)
                    return 1
                if status == "swallowed":
                    return 1
                if status == "committed":
                    return user32.CallNextHookEx(self._hook, code, message, pointer)
                if status == "fallback_english":
                    return self._fallback_inactive_key(
                        code,
                        message,
                        pointer,
                        hwnd,
                        vk,
                        int(event.scanCode),
                        allow_english=True,
                    )
                if status == "fallback_inactive":
                    return user32.CallNextHookEx(self._hook, code, message, pointer)
            if vk == VK_SPACE:
                space_mode = "pass"
                space_done: threading.Event | None = None
                with self._state_lock:
                    if not self.active.is_set():
                        space_mode = "english" if self.english.is_set() else "pass"
                    else:
                        space_char = (
                            "\u3000"
                            if (self.fullwidth_space.is_set() and not self._modifier_pressed(VK_SHIFT))
                            else " "
                        )
                        space_done = threading.Event()
                        self.events.put(InputEvent("english", hwnd, space_char, space_done))
                        space_mode = "active"
                if space_mode == "english":
                    return self._fallback_inactive_key(
                        code,
                        message,
                        pointer,
                        hwnd,
                        vk,
                        int(event.scanCode),
                        allow_english=True,
                    )
                if space_mode == "active" and space_done is not None:
                    self._swallow(vk)
                    space_done.wait(timeout=_HOOK_WAIT_TIMEOUT)
                    return 1
                return user32.CallNextHookEx(self._hook, code, message, pointer)
            if vk in _CONTEXT_RESET_VKS and self.active.is_set() and self.try_clear_context():
                self.events.put(InputEvent("clear_context", hwnd))
            return user32.CallNextHookEx(self._hook, code, message, pointer)
        except Exception:
            return user32.CallNextHookEx(self._hook, code, message, pointer)

    def _enqueue_composing_action(
        self,
        hwnd: int,
        action: str,
        value: str = "",
        *,
        selecting: bool | None = None,
        swallow_ascii_direct: bool = False,
        wait_completed: bool = False,
        vk: int = 0,
    ) -> str:
        completed = threading.Event() if wait_completed else None
        with self._state_lock:
            if not self.active.is_set():
                return "fallback_english" if self.english.is_set() else "fallback_inactive"
            if not self.composing.is_set():
                return "not_composing"
            if swallow_ascii_direct and self.ascii_direct.is_set():
                return "swallow"
            self._input_seq += 1
            seq = self._input_seq
            if action == "escape":
                if self.selecting.is_set():
                    self.selecting.clear()
                    self.events.put(InputEvent("revert_selection", hwnd, seq=seq))
                    return "swallow"
                cancel_done = threading.Event()
                self.mark_composing(False)
                self.events.put(InputEvent("cancel", hwnd, completed=cancel_done, seq=seq))
                completed = cancel_done
            else:
                if selecting is True:
                    self.selecting.set()
                elif selecting is False:
                    self.selecting.clear()
                if action == "enter_commit":
                    self._visible_candidate_count = 0
                self.events.put(InputEvent(action, hwnd, value, completed=completed, seq=seq))
        if completed is not None:
            if vk:
                self._swallow(vk)
            # Stay strictly under Windows' LowLevelHooksTimeout (~300ms); worker sets
            # final composing state (False on full commit, True on remaining clause).
            completed.wait(timeout=_HOOK_WAIT_TIMEOUT)
            return "swallowed"
        return "swallow"

    def _dispatch_composing_key(self, hwnd: int, vk: int) -> str:
        shift_pressed = self._modifier_pressed(VK_SHIFT)
        if vk in _TRANSLITERATE_VKS and not shift_pressed:
            return self._enqueue_composing_action(
                hwnd,
                "transliterate",
                _TRANSLITERATE_VKS[vk],
                selecting=True,
                swallow_ascii_direct=(vk in (VK_F6, VK_F7, VK_F8)),
            )
        if vk == VK_BACK:
            return self._enqueue_composing_action(hwnd, "backspace", selecting=False)
        if vk == VK_DELETE and not shift_pressed:
            return self._enqueue_composing_action(hwnd, "delete", selecting=False)
        if vk in (VK_LEFT, VK_RIGHT) and shift_pressed:
            return self._enqueue_composing_action(
                hwnd,
                "resize_clause",
                "shrink" if vk == VK_LEFT else "expand",
                selecting=True,
                swallow_ascii_direct=True,
            )
        if vk in _CURSOR_MOVE_VKS and not shift_pressed:
            return self._enqueue_composing_action(
                hwnd,
                "move_cursor",
                _CURSOR_MOVE_VKS[vk],
                selecting=False,
            )
        if vk in (VK_PRIOR, VK_NEXT) and not shift_pressed:
            return self._enqueue_composing_action(
                hwnd,
                "cycle_page",
                "previous" if vk == VK_PRIOR else "next",
                selecting=True,
            )
        if vk == VK_SPACE or (vk in (VK_UP, VK_DOWN) and not shift_pressed):
            shift_back = vk == VK_SPACE and shift_pressed
            direction = "previous" if (vk == VK_UP or shift_back) else "next"
            return self._enqueue_composing_action(hwnd, "cycle", direction, selecting=True)
        if vk == VK_RETURN:
            return self._enqueue_composing_action(
                hwnd,
                "enter_commit",
                selecting=False,
                wait_completed=True,
                vk=vk,
            )
        if vk == VK_ESCAPE:
            return self._enqueue_composing_action(hwnd, "escape", vk=vk)
        return self._commit_before_passthrough(hwnd)

    def _try_select_page_commit(self, hwnd: int, vk: int, slot_index: int) -> bool:
        completed = threading.Event()
        with self._state_lock:
            if (
                not self.active.is_set()
                or not self.composing.is_set()
                or not self.selecting.is_set()
                or slot_index < 0
                or slot_index >= self._visible_candidate_count
            ):
                return False
            self._input_seq += 1
            seq = self._input_seq
            self.selecting.clear()
            self._visible_candidate_count = 0
            self.events.put(InputEvent("select_page_index", hwnd, str(slot_index), completed=completed, seq=seq))
        self._swallow(vk)
        completed.wait(timeout=_HOOK_WAIT_TIMEOUT)
        return True

    def _commit_before_passthrough(self, hwnd: int) -> str:
        completed = threading.Event()
        with self._state_lock:
            if not self.active.is_set():
                return "fallback_english" if self.english.is_set() else "fallback_inactive"
            if not self.composing.is_set():
                return "not_composing"
            self._input_seq += 1
            seq = self._input_seq
            self.mark_composing(False)
            self.events.put(InputEvent("commit", hwnd, completed=completed, seq=seq))
        # Ensure committed text reaches the active control before the delimiter
        # or shortcut passes through. Without this barrier, Office text boxes can
        # receive the delimiter first and then reorder the injected text.
        completed.wait(timeout=_HOOK_WAIT_TIMEOUT)
        return "committed"

    def _swallow(self, vk: int) -> None:
        with self._swallowed_lock:
            self._swallowed.add(vk)

    def _mask_alt_menu_activation(self) -> None:
        try:
            _send_inputs(
                [
                    INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(_VK_MENU_MASK, 0, 0, 0, APP_INJECTION_TAG)),
                    INPUT(
                        type=INPUT_KEYBOARD,
                        ki=KEYBDINPUT(_VK_MENU_MASK, 0, KEYEVENTF_KEYUP, 0, APP_INJECTION_TAG),
                    ),
                ]
            )
        except Exception:
            pass

    def _try_dispatch_english_key(
        self,
        code: int,
        message: int,
        pointer: int,
        hwnd: int,
        vk: int,
        scan_code: int,
    ) -> int | None:
        """Atomically inspect english/passthrough flags, translate outside lock, and re-verify before sending."""
        with self._state_lock:
            if not self.english.is_set():
                return None
            if self.english_passthrough.is_set():
                return user32.CallNextHookEx(self._hook, code, message, pointer)
        char = self._translate_english_character(vk, scan_code, hwnd)
        completed: threading.Event | None = None
        with self._state_lock:
            if not self.english.is_set():
                if self.active.is_set():
                    return None
                return user32.CallNextHookEx(self._hook, code, message, pointer)
            if self.english_passthrough.is_set() or not char:
                return user32.CallNextHookEx(self._hook, code, message, pointer)
            completed = threading.Event()
            self.events.put(InputEvent("english", hwnd, char, completed))
        self._swallow(vk)
        completed.wait(timeout=_HOOK_WAIT_TIMEOUT)
        return 1

    def _fallback_inactive_key(
        self,
        code: int,
        message: int,
        pointer: int,
        hwnd: int,
        vk: int,
        scan_code: int,
        *,
        allow_english: bool,
    ) -> int:
        if allow_english:
            result = self._try_dispatch_english_key(code, message, pointer, hwnd, vk, scan_code)
            if result is not None:
                return result
        return user32.CallNextHookEx(self._hook, code, message, pointer)

    def _send_english_character(self, hwnd: int, vk: int, char: str) -> None:
        completed = threading.Event()
        self.events.put(InputEvent("english", hwnd, char, completed))
        self._swallow(vk)
        # English characters are sent asynchronously by the worker; wait briefly
        # so later spaces, punctuation, and keys cannot overtake them, while
        # preserving english mode if the worker takes longer than 220ms.
        completed.wait(timeout=_HOOK_WAIT_TIMEOUT)

    @staticmethod
    def _modifier_pressed(*keys: int) -> bool:
        return any(user32.GetAsyncKeyState(key) & 0x8000 for key in keys)

    @staticmethod
    def _keyboard_state() -> ctypes.Array:
        # Use a clean key state array so a toggled VK_KANA state in the thread
        # never causes ToUnicodeEx to emit half-width kana instead of ASCII.
        state = (ctypes.c_ubyte * 256)()
        shift_down = bool(user32.GetAsyncKeyState(VK_SHIFT) & 0x8000)
        for key in (VK_SHIFT, VK_LSHIFT, VK_RSHIFT):
            state[key] = 0x80 if shift_down else 0
        caps_lock = bool(user32.GetKeyState(VK_CAPITAL) & 1)
        state[VK_CAPITAL] = int(caps_lock)
        num_lock = bool(user32.GetKeyState(VK_NUMLOCK) & 1)
        state[VK_NUMLOCK] = int(num_lock)
        return state

    @staticmethod
    def _translate_letter(vk: int, scan_code: int, hwnd: int, *, respect_caps: bool = True) -> str:
        state = KeyboardHook._keyboard_state()
        process_id = wintypes.DWORD()
        thread_id = user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        layout = user32.GetKeyboardLayout(thread_id)
        output = (wintypes.WCHAR * 8)()
        count = user32.ToUnicodeEx(vk, scan_code, state, output, len(output), 0, layout)
        shifted = bool(user32.GetAsyncKeyState(VK_SHIFT) & 0x8000)
        caps_lock = bool(user32.GetKeyState(VK_CAPITAL) & 1) if respect_caps else False
        uppercase = shifted ^ caps_lock
        if count == 1:
            char = output[0]
            if char.isascii() and char.isalpha():
                return char.upper() if uppercase else char.lower()
        # Some Japanese layouts return kana here even though the physical
        # letter key still needs to feed romaji into the converter.
        if 0x41 <= vk <= 0x5A:
            char = chr(vk)
            return char if uppercase else char.lower()
        return ""

    @staticmethod
    def _translate_ascii_symbol_or_digit(vk: int, scan_code: int, hwnd: int) -> str:
        if vk in _NUMPAD_LITERAL_VKS:
            return _NUMPAD_LITERAL_VKS[vk]
        if vk in _SYMBOL_AND_DIGIT_VKS:
            state = KeyboardHook._keyboard_state()
            process_id = wintypes.DWORD()
            thread_id = user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
            layout = user32.GetKeyboardLayout(thread_id)
            output = (wintypes.WCHAR * 8)()
            count = user32.ToUnicodeEx(vk, scan_code, state, output, len(output), 0, layout)
            if count == 1:
                char = output[0]
                if char.isascii() and char.isprintable():
                    return char
        return ""

    @staticmethod
    def _translate_japanese_symbol_or_digit(vk: int, scan_code: int, hwnd: int) -> str:
        if vk in _NUMPAD_VKS:
            return KeyboardHook._translate_ascii_symbol_or_digit(vk, scan_code, hwnd)
        char = KeyboardHook._translate_ascii_symbol_or_digit(vk, scan_code, hwnd)
        if not char:
            return ""
        if char in JAPANESE_SYMBOL_MAP:
            return JAPANESE_SYMBOL_MAP[char]
        if char.isdigit():
            return char
        return ""

    @staticmethod
    def _translate_english_character(vk: int, scan_code: int, hwnd: int) -> str:
        if vk == VK_SPACE:
            return " "
        if 0x41 <= vk <= 0x5A:
            return KeyboardHook._translate_letter(vk, scan_code, hwnd)
        return KeyboardHook._translate_ascii_symbol_or_digit(vk, scan_code, hwnd)


def _create_tray_badge_icon(glyph: str, rgb: tuple[int, int, int]) -> int:
    """Create a 32x32 Win32 HICON badge using pure GDI (no external .ico asset)."""
    size = 32
    dc = gdi32.CreateCompatibleDC(None)
    mask_dc = gdi32.CreateCompatibleDC(None)
    bmi = BITMAPINFOHEADER()
    bmi.biSize = ctypes.sizeof(bmi)
    bmi.biWidth = size
    bmi.biHeight = -size
    bmi.biPlanes = 1
    bmi.biBitCount = 24
    bits = ctypes.c_void_p()
    hbmp = gdi32.CreateDIBSection(dc, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
    hmask = gdi32.CreateBitmap(size, size, 1, 1, None)
    if not dc or not mask_dc or not hbmp or not hmask:
        for obj in (hbmp, hmask):
            if obj:
                gdi32.DeleteObject(obj)
        for hdc in (dc, mask_dc):
            if hdc:
                gdi32.DeleteDC(hdc)
        return 0

    old_bmp = gdi32.SelectObject(dc, hbmp)
    old_mask = gdi32.SelectObject(mask_dc, hmask)
    rect = RECT(0, 0, size, size)

    colorref = rgb[0] | (rgb[1] << 8) | (rgb[2] << 16)
    bg_brush = gdi32.CreateSolidBrush(colorref)
    user32.FillRect(dc, ctypes.byref(rect), bg_brush)
    gdi32.DeleteObject(bg_brush)

    lf = LOGFONTW()
    lf.lfHeight = -22
    lf.lfWeight = 700
    lf.lfCharSet = 1
    lf.lfFaceName = "Yu Gothic UI"
    font = gdi32.CreateFontIndirectW(ctypes.byref(lf))
    old_font = gdi32.SelectObject(dc, font)
    gdi32.SetBkMode(dc, TRANSPARENT)
    gdi32.SetTextColor(dc, 0x00FFFFFF)
    user32.DrawTextW(dc, glyph, -1, ctypes.byref(rect), DT_CENTER | DT_VCENTER | DT_SINGLELINE)
    gdi32.SelectObject(dc, old_font)
    gdi32.DeleteObject(font)

    opaque_brush = gdi32.CreateSolidBrush(0x00000000)
    user32.FillRect(mask_dc, ctypes.byref(rect), opaque_brush)
    gdi32.DeleteObject(opaque_brush)

    gdi32.SelectObject(dc, old_bmp)
    gdi32.SelectObject(mask_dc, old_mask)
    gdi32.DeleteDC(dc)
    gdi32.DeleteDC(mask_dc)

    info = ICONINFO(fIcon=True, xHotspot=0, yHotspot=0, hbmMask=hmask, hbmColor=hbmp)
    hicon = int(user32.CreateIconIndirect(ctypes.byref(info)) or 0)
    gdi32.DeleteObject(hbmp)
    gdi32.DeleteObject(hmask)
    return hicon


class SystemTrayIcon:
    """Windows notification-area icon and context menu on a dedicated Win32 message thread."""

    _ID_OPEN = 1001
    _ID_TOGGLE = 1002
    _ID_RESET_POS = 1003
    _ID_EXIT = 1004

    def __init__(self, ui_events: queue.Queue[tuple[str, object]]) -> None:
        self.ui_events = ui_events
        self.active = False
        self._closing = False
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self._thread: threading.Thread | None = None
        self._hwnd = 0
        self._state = "disabled"
        self._enabled = False
        self._tooltip = "AzooKey Live Bridge"
        self._icons: dict[str, int] = {}
        self._wm_taskbar_created = int(user32.RegisterWindowMessageW("TaskbarCreated") or 0)
        self._wnd_proc_ref = WNDPROC(self._wnd_proc)

    def start(self) -> bool:
        if self._thread is not None:
            return self.active
        self._thread = threading.Thread(target=self._run, name="AzooKey tray icon", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=2.0)
        return self.active

    def update_state(self, state: str, enabled: bool, tooltip: str) -> None:
        with self._lock:
            self._state = state
            self._enabled = enabled
            self._tooltip = (tooltip or "AzooKey Live Bridge")[:127]
            hwnd = self._hwnd
        if hwnd and user32.IsWindow(hwnd):
            user32.PostMessageW(hwnd, WM_TRAY_UPDATE, 0, 0)

    def stop(self) -> None:
        thread = self._thread
        if thread is None:
            return
        with self._lock:
            self._closing = True
            hwnd = self._hwnd
        if hwnd and user32.IsWindow(hwnd):
            user32.PostMessageW(hwnd, WM_CANCELMODE, 0, 0)
            user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
        thread.join(timeout=2.0)
        self._thread = None
        self.active = False

    def _build_icons(self) -> None:
        specs = {
            "on": ("あ", (25, 111, 61)),
            "off": ("A", (74, 85, 104)),
            "blocked": ("!", (180, 83, 9)),
            "disabled": ("・", (107, 114, 128)),
        }
        for key, (glyph, rgb) in specs.items():
            hicon = _create_tray_badge_icon(glyph, rgb)
            if hicon:
                self._icons[key] = hicon

    def _destroy_icons(self) -> None:
        for hicon in self._icons.values():
            if hicon:
                user32.DestroyIcon(hicon)
        self._icons.clear()

    def _notify_data(self, hwnd: int) -> NOTIFYICONDATAW:
        with self._lock:
            state = self._state
            tip = self._tooltip
        hicon = self._icons.get(state) or self._icons.get("disabled") or 0
        return NOTIFYICONDATAW(
            cbSize=ctypes.sizeof(NOTIFYICONDATAW),
            hWnd=hwnd,
            uID=1,
            uFlags=NIF_MESSAGE | NIF_ICON | NIF_TIP,
            uCallbackMessage=WM_TRAY_CALLBACK,
            hIcon=hicon,
            szTip=tip[:127],
        )

    def _add_or_modify_icon(self, hwnd: int, *, add: bool) -> bool:
        nid = self._notify_data(hwnd)
        if not nid.hIcon:
            return False
        cmd = NIM_ADD if add else NIM_MODIFY
        ok = bool(shell32.Shell_NotifyIconW(cmd, ctypes.byref(nid)))
        if not ok and not add:
            ok = bool(shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid)))
        return ok

    def _show_context_menu(self, hwnd: int) -> None:
        menu = user32.CreatePopupMenu()
        if not menu:
            return
        try:
            with self._lock:
                enabled = self._enabled
                state = self._state
            user32.AppendMenuW(menu, MF_STRING, self._ID_OPEN, "設定を開く")
            toggle_label = (
                "ライブ変換を OFF にする（英語入力へ）"
                if enabled
                else "ライブ変換を ON にする（日本語入力へ）"
            )
            if state != "disabled":
                user32.AppendMenuW(menu, MF_STRING, self._ID_TOGGLE, toggle_label)
            user32.AppendMenuW(menu, MF_STRING, self._ID_RESET_POS, "ライブ変換ボタン位置を戻す")
            user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
            user32.AppendMenuW(menu, MF_STRING, self._ID_EXIT, "終了")
            user32.SetMenuDefaultItem(menu, self._ID_OPEN, False)

            pt = POINT()
            user32.GetCursorPos(ctypes.byref(pt))
            user32.SetForegroundWindow(hwnd)
            cmd = int(
                user32.TrackPopupMenu(
                    menu,
                    TPM_RIGHTBUTTON | TPM_RETURNCMD | TPM_NONOTIFY,
                    pt.x,
                    pt.y,
                    0,
                    hwnd,
                    None,
                )
            )
            if user32.IsWindow(hwnd):
                user32.PostMessageW(hwnd, WM_NULL, 0, 0)
            with self._lock:
                closing = self._closing
            if closing:
                return
            if cmd == self._ID_OPEN:
                self.ui_events.put(("tray_show", None))
            elif cmd == self._ID_TOGGLE:
                self.ui_events.put(("tray_toggle", None))
            elif cmd == self._ID_RESET_POS:
                self.ui_events.put(("tray_reset_toggle", None))
            elif cmd == self._ID_EXIT:
                self.ui_events.put(("tray_exit", None))
        finally:
            user32.DestroyMenu(menu)

    def _wnd_proc(self, hwnd: int, msg: int, wparam: int, lparam: int) -> int:
        if msg == WM_TRAY_CALLBACK:
            event_msg = lparam & 0xFFFF
            if event_msg in (WM_LBUTTONUP, WM_LBUTTONDBLCLK):
                with self._lock:
                    closing = self._closing
                if not closing:
                    self.ui_events.put(("tray_show", None))
                return 0
            if event_msg in (WM_RBUTTONUP, WM_CONTEXTMENU):
                with self._lock:
                    closing = self._closing
                if not closing:
                    self._show_context_menu(hwnd)
                return 0
        elif msg == WM_TRAY_UPDATE:
            if self._add_or_modify_icon(hwnd, add=False):
                self.active = True
            return 0
        elif _WM_SHOW_SETTINGS and msg == _WM_SHOW_SETTINGS:
            self.ui_events.put(("tray_show", None))
            return 0
        elif self._wm_taskbar_created and msg == self._wm_taskbar_created:
            self.active = self._add_or_modify_icon(hwnd, add=True)
            return 0
        elif msg == WM_CLOSE:
            nid = NOTIFYICONDATAW(cbSize=ctypes.sizeof(NOTIFYICONDATAW), hWnd=hwnd, uID=1)
            shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))
            user32.DestroyWindow(hwnd)
            return 0
        elif msg == WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        return int(user32.DefWindowProcW(hwnd, msg, wparam, lparam))

    def _run(self) -> None:
        hinst = kernel32.GetModuleHandleW(None)
        wc = WNDCLASSEXW(
            cbSize=ctypes.sizeof(WNDCLASSEXW),
            lpfnWndProc=self._wnd_proc_ref,
            hInstance=hinst,
            lpszClassName=_TRAY_CLASS_NAME,
        )
        atom = user32.RegisterClassExW(ctypes.byref(wc))
        if not atom:
            self._ready.set()
            return
        hwnd = 0
        try:
            self._build_icons()
            hwnd = int(
                user32.CreateWindowExW(
                    0,
                    _TRAY_CLASS_NAME,
                    _TRAY_WINDOW_NAME,
                    0,
                    0,
                    0,
                    0,
                    0,
                    None,
                    None,
                    hinst,
                    None,
                )
                or 0
            )
            with self._lock:
                self._hwnd = hwnd
            if hwnd:
                self.active = self._add_or_modify_icon(hwnd, add=True)
            self._ready.set()
            if not hwnd:
                return
            msg = MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            if hwnd and user32.IsWindow(hwnd):
                nid = NOTIFYICONDATAW(cbSize=ctypes.sizeof(NOTIFYICONDATAW), hWnd=hwnd, uID=1)
                shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))
                user32.DestroyWindow(hwnd)
            with self._lock:
                self._hwnd = 0
            self.active = False
            self._destroy_icons()
            user32.UnregisterClassW(_TRAY_CLASS_NAME, hinst)
