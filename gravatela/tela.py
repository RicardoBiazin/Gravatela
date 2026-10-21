"""Captura da tela via GDI (BitBlt), com o cursor do mouse desenhado por cima.

Tudo em ctypes: uma DIB section de 32 bits fica selecionada num DC de memória e o
BitBlt escreve direto nela, então cada quadro custa um BitBlt e uma cópia.
"""

import ctypes
from ctypes import wintypes
from dataclasses import dataclass

import numpy as np

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

SRCCOPY = 0x00CC0020
DIB_RGB_COLORS = 0
BI_RGB = 0
CURSOR_SHOWING = 0x1
DI_NORMAL = 0x3
MONITORINFOF_PRIMARY = 0x1
SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN, SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 76, 77, 78, 79


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG), ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


class CURSORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("hCursor", wintypes.HANDLE), ("ptScreenPos", wintypes.POINT)]


class ICONINFO(ctypes.Structure):
    _fields_ = [("fIcon", wintypes.BOOL), ("xHotspot", wintypes.DWORD), ("yHotspot", wintypes.DWORD),
                ("hbmMask", wintypes.HBITMAP), ("hbmColor", wintypes.HBITMAP)]


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                ("dwFlags", wintypes.DWORD), ("szDevice", wintypes.WCHAR * 32)]


MONITORENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC,
                                     ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)

# Sem argtypes/restype o ctypes trunca os handles de 64 bits para int de 32.
user32.GetDC.restype = wintypes.HDC
user32.GetDC.argtypes = [wintypes.HWND]
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.GetCursorInfo.argtypes = [ctypes.POINTER(CURSORINFO)]
user32.GetIconInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(ICONINFO)]
user32.DrawIconEx.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.HANDLE, ctypes.c_int,
                              ctypes.c_int, wintypes.UINT, wintypes.HBRUSH, wintypes.UINT]
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.EnumDisplayMonitors.argtypes = [wintypes.HDC, ctypes.c_void_p, MONITORENUMPROC, wintypes.LPARAM]
user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MONITORINFOEXW)]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateDIBSection.restype = wintypes.HBITMAP
gdi32.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.POINTER(BITMAPINFO), wintypes.UINT,
                                   ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteDC.argtypes = [wintypes.HDC]
gdi32.BitBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                         wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD]


def ativar_dpi() -> None:
    """Coordenadas em pixels físicos. O Qt já faz isso sozinho; serve para o modo sem janela."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        user32.SetProcessDPIAware()


@dataclass(frozen=True)
class Monitor:
    nome: str
    x: int
    y: int
    largura: int
    altura: int
    principal: bool = False

    @property
    def descricao(self) -> str:
        extra = " (principal)" if self.principal else ""
        return f"{self.nome}: {self.largura}x{self.altura}{extra}"


def listar_monitores() -> list[Monitor]:
    """Monitores na ordem do Windows, o principal primeiro."""
    achados: list[Monitor] = []

    def ao_achar(hmon, _hdc, _rect, _dados):
        info = MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(MONITORINFOEXW)
        if user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
            r = info.rcMonitor
            nome = info.szDevice.replace("\\\\.\\", "") or f"Tela {len(achados) + 1}"
            achados.append(Monitor(nome, r.left, r.top, r.right - r.left, r.bottom - r.top,
                                   bool(info.dwFlags & MONITORINFOF_PRIMARY)))
        return True

    user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(ao_achar), 0)
    achados.sort(key=lambda m: not m.principal)
    return achados


def area_de_trabalho_virtual() -> Monitor:
    """O retângulo que cobre todas as telas juntas."""
    return Monitor("Todas as telas",
                   user32.GetSystemMetrics(SM_XVIRTUALSCREEN), user32.GetSystemMetrics(SM_YVIRTUALSCREEN),
                   user32.GetSystemMetrics(SM_CXVIRTUALSCREEN), user32.GetSystemMetrics(SM_CYVIRTUALSCREEN))


class CapturaTela:
    """Captura um retângulo da área de trabalho em BGRA (altura, largura, 4).

    Largura e altura são arredondadas para baixo até um número par: o H.264 em
    yuv420p não aceita dimensão ímpar.
    """

    def __init__(self, x: int, y: int, largura: int, altura: int, cursor: bool = True):
        self.x, self.y = x, y
        self.largura, self.altura = largura - largura % 2, altura - altura % 2
        if self.largura < 2 or self.altura < 2:
            raise ValueError(f"área de captura inválida: {largura}x{altura}")
        self.cursor = cursor
        self._hotspots: dict[int, tuple[int, int]] = {}
        self._dc_tela = user32.GetDC(None)
        self._dc_mem = gdi32.CreateCompatibleDC(self._dc_tela)
        bmi = BITMAPINFO()
        h = bmi.bmiHeader
        h.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        h.biWidth, h.biHeight = self.largura, -self.altura  # negativo: linhas de cima para baixo
        h.biPlanes, h.biBitCount, h.biCompression = 1, 32, BI_RGB
        bits = ctypes.c_void_p()
        self._bitmap = gdi32.CreateDIBSection(self._dc_mem, ctypes.byref(bmi), DIB_RGB_COLORS,
                                              ctypes.byref(bits), None, 0)
        if not self._bitmap or not bits.value:
            self.fechar()
            raise OSError(ctypes.get_last_error(), "CreateDIBSection falhou")
        self._anterior = gdi32.SelectObject(self._dc_mem, self._bitmap)
        tamanho = self.largura * self.altura * 4
        memoria = (ctypes.c_ubyte * tamanho).from_address(bits.value)
        self._quadro = np.ndarray((self.altura, self.largura, 4), dtype=np.uint8, buffer=memoria)

    @classmethod
    def do_monitor(cls, monitor: Monitor, cursor: bool = True) -> "CapturaTela":
        return cls(monitor.x, monitor.y, monitor.largura, monitor.altura, cursor)

    def capturar(self) -> np.ndarray:
        """Um quadro novo (cópia; o buffer interno é reaproveitado)."""
        gdi32.BitBlt(self._dc_mem, 0, 0, self.largura, self.altura, self._dc_tela, self.x, self.y, SRCCOPY)
        if self.cursor:
            self._desenhar_cursor()
        gdi32.GdiFlush()
        return self._quadro.copy()

    def _desenhar_cursor(self) -> None:
        info = CURSORINFO()
        info.cbSize = ctypes.sizeof(CURSORINFO)
        if not user32.GetCursorInfo(ctypes.byref(info)) or not (info.flags & CURSOR_SHOWING) or not info.hCursor:
            return
        hotspot = self._hotspots.get(info.hCursor)
        if hotspot is None:
            icone = ICONINFO()
            if not user32.GetIconInfo(info.hCursor, ctypes.byref(icone)):
                return
            # GetIconInfo cria bitmaps que são nossos: apagar, senão vaza GDI a cada quadro.
            for bmp in (icone.hbmMask, icone.hbmColor):
                if bmp:
                    gdi32.DeleteObject(bmp)
            hotspot = self._hotspots[info.hCursor] = (icone.xHotspot, icone.yHotspot)
        px = info.ptScreenPos.x - self.x - hotspot[0]
        py = info.ptScreenPos.y - self.y - hotspot[1]
        user32.DrawIconEx(self._dc_mem, px, py, info.hCursor, 0, 0, 0, None, DI_NORMAL)

    def fechar(self) -> None:
        if getattr(self, "_dc_mem", None):
            if getattr(self, "_anterior", None):
                gdi32.SelectObject(self._dc_mem, self._anterior)
            if getattr(self, "_bitmap", None):
                gdi32.DeleteObject(self._bitmap)
            gdi32.DeleteDC(self._dc_mem)
            self._dc_mem = None
        if getattr(self, "_dc_tela", None):
            user32.ReleaseDC(None, self._dc_tela)
            self._dc_tela = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.fechar()
