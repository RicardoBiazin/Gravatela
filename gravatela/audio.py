"""Captura de áudio pelo WASAPI (PyAudioWPatch): o que sai do PC (loopback) e o microfone.

O WASAPI em loopback só entrega pacotes enquanto algum programa toca som. Nos
silêncios o callback para de ser chamado; quem preenche o buraco é o mixer do
codificador, pelo relógio (ver codificador.Mixer).
"""

import time
from dataclasses import dataclass
from typing import Callable

import pyaudiowpatch as pyaudio


@dataclass(frozen=True)
class DispositivoAudio:
    indice: int
    nome: str
    taxa: int
    canais: int
    padrao: bool = False
    microfone: bool = False

    @property
    def descricao(self) -> str:
        nome = self.nome.replace(" [Loopback]", "")
        return f"{nome} (padrão)" if self.padrao else nome


# Nome antigo (0.1.x).
SaidaAudio = DispositivoAudio


def _como_dispositivo(info: dict, padrao: bool, microfone: bool) -> DispositivoAudio:
    return DispositivoAudio(int(info["index"]), str(info["name"]), int(info["defaultSampleRate"]),
                            int(info["maxInputChannels"]), padrao, microfone)


def listar_saidas() -> list[DispositivoAudio]:
    """Dispositivos de saída que dá para gravar; o padrão do Windows vem primeiro."""
    p = pyaudio.PyAudio()
    try:
        try:
            indice_padrao = int(p.get_default_wasapi_loopback()["index"])
        except (OSError, LookupError):
            indice_padrao = -1
        saidas = [_como_dispositivo(info, int(info["index"]) == indice_padrao, False)
                  for info in p.get_loopback_device_info_generator()]
    finally:
        p.terminate()
    saidas.sort(key=lambda s: not s.padrao)
    return saidas


def saida_padrao() -> DispositivoAudio | None:
    saidas = listar_saidas()
    return saidas[0] if saidas else None


def listar_microfones() -> list[DispositivoAudio]:
    """Entradas WASAPI de verdade (sem os loopbacks); o microfone padrão vem primeiro."""
    p = pyaudio.PyAudio()
    try:
        try:
            wasapi = p.get_host_api_info_by_type(pyaudio.paWASAPI)
        except OSError:
            return []
        indice_padrao = int(wasapi.get("defaultInputDevice", -1))
        mics = []
        for i in range(p.get_device_count()):
            info = p.get_device_info_by_index(i)
            if (info["hostApi"] == wasapi["index"] and info["maxInputChannels"] > 0
                    and not info.get("isLoopbackDevice", False)):
                mics.append(_como_dispositivo(info, i == indice_padrao, True))
    finally:
        p.terminate()
    mics.sort(key=lambda m: not m.padrao)
    return mics


def microfone_padrao() -> DispositivoAudio | None:
    mics = listar_microfones()
    return mics[0] if mics else None


class CapturaAudio:
    """Abre o dispositivo e entrega (instante perf_counter, bytes PCM s16 intercalado) a cada pacote."""

    def __init__(self, dispositivo: DispositivoAudio, ao_receber: Callable[[float, bytes], None]):
        self.dispositivo = dispositivo
        self.taxa = dispositivo.taxa
        self.canais = dispositivo.canais
        self._ao_receber = ao_receber
        self._pa = None
        self._fluxo = None

    @property
    def saida(self) -> DispositivoAudio:  # nome antigo
        return self.dispositivo

    def _callback(self, dados, _quadros, _info_tempo, _status):
        self._ao_receber(time.perf_counter(), dados)
        return None, pyaudio.paContinue

    def iniciar(self) -> None:
        self._pa = pyaudio.PyAudio()
        try:
            self._fluxo = self._pa.open(format=pyaudio.paInt16, channels=self.canais, rate=self.taxa,
                                        input=True, input_device_index=self.dispositivo.indice,
                                        frames_per_buffer=int(self.taxa * 0.02),
                                        stream_callback=self._callback)
        except Exception:
            self.parar()
            raise

    def parar(self) -> None:
        if self._fluxo is not None:
            try:
                self._fluxo.stop_stream()
                self._fluxo.close()
            finally:
                self._fluxo = None
        if self._pa is not None:
            self._pa.terminate()
            self._pa = None
