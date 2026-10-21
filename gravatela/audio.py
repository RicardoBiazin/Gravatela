"""Captura do áudio que sai do PC (loopback do WASAPI, via PyAudioWPatch).

O WASAPI em loopback só entrega pacotes enquanto algum programa toca som. Nos
silêncios o callback para de ser chamado; quem preenche o buraco é o codificador,
pelo relógio (ver Codificador.adicionar_audio).
"""

import time
from dataclasses import dataclass
from typing import Callable

import pyaudiowpatch as pyaudio


@dataclass(frozen=True)
class SaidaAudio:
    indice: int
    nome: str
    taxa: int
    canais: int
    padrao: bool = False

    @property
    def descricao(self) -> str:
        nome = self.nome.replace(" [Loopback]", "")
        return f"{nome} (padrão)" if self.padrao else nome


def _como_saida(info: dict, padrao: bool) -> SaidaAudio:
    return SaidaAudio(int(info["index"]), str(info["name"]), int(info["defaultSampleRate"]),
                      int(info["maxInputChannels"]), padrao)


def listar_saidas() -> list[SaidaAudio]:
    """Dispositivos de saída que dá para gravar; o padrão do Windows vem primeiro."""
    p = pyaudio.PyAudio()
    try:
        try:
            indice_padrao = int(p.get_default_wasapi_loopback()["index"])
        except (OSError, LookupError):
            indice_padrao = -1
        saidas = [_como_saida(info, int(info["index"]) == indice_padrao)
                  for info in p.get_loopback_device_info_generator()]
    finally:
        p.terminate()
    saidas.sort(key=lambda s: not s.padrao)
    return saidas


def saida_padrao() -> SaidaAudio | None:
    saidas = listar_saidas()
    return saidas[0] if saidas else None


class CapturaAudio:
    """Abre o loopback e entrega (instante perf_counter, bytes PCM s16 intercalado) a cada pacote."""

    def __init__(self, saida: SaidaAudio, ao_receber: Callable[[float, bytes], None]):
        self.saida = saida
        self.taxa = saida.taxa
        self.canais = saida.canais
        self._ao_receber = ao_receber
        self._pa = None
        self._fluxo = None

    def _callback(self, dados, _quadros, _info_tempo, _status):
        self._ao_receber(time.perf_counter(), dados)
        return None, pyaudio.paContinue

    def iniciar(self) -> None:
        self._pa = pyaudio.PyAudio()
        try:
            self._fluxo = self._pa.open(format=pyaudio.paInt16, channels=self.canais, rate=self.taxa,
                                        input=True, input_device_index=self.saida.indice,
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
