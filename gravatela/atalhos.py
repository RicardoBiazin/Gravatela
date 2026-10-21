"""Atalhos de teclado globais (RegisterHotKey): funcionam com a janela minimizada ou sem foco.

O Windows manda WM_HOTKEY para a janela registrada; a janela repassa o MSG a
`id_do_atalho` dentro do nativeEvent do Qt.
"""

import ctypes
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x4000
VK_F9, VK_F10 = 0x78, 0x79
WM_HOTKEY = 0x0312

GRAVAR_PARAR = 1
PAUSAR_CONTINUAR = 2

# id: (texto para a interface, modificadores, tecla)
ATALHOS = {
    GRAVAR_PARAR: ("Ctrl+Shift+F9", MOD_CONTROL | MOD_SHIFT, VK_F9),
    PAUSAR_CONTINUAR: ("Ctrl+Shift+F10", MOD_CONTROL | MOD_SHIFT, VK_F10),
}


def registrar(hwnd: int | None) -> list[str]:
    """Registra todos; devolve os textos dos que falharam (outro programa já usa)."""
    falhas = []
    for ident, (texto, mods, tecla) in ATALHOS.items():
        if not user32.RegisterHotKey(hwnd, ident, mods | MOD_NOREPEAT, tecla):
            falhas.append(texto)
    return falhas


def liberar(hwnd: int | None) -> None:
    for ident in ATALHOS:
        user32.UnregisterHotKey(hwnd, ident)


def id_do_atalho(endereco_msg: int) -> int | None:
    """Ponteiro para um MSG do Windows -> id do atalho, se for WM_HOTKEY nosso."""
    if not endereco_msg:
        return None
    msg = wintypes.MSG.from_address(int(endereco_msg))
    if msg.message == WM_HOTKEY and msg.wParam in ATALHOS:
        return int(msg.wParam)
    return None
