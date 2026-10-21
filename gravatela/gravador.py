"""Liga captura de tela, captura de áudio e codificador em threads.

    captura de tela  ─┐
                      ├─> fila ─> thread do codificador ─> .mp4
    callback de áudio ┘

Só a thread do codificador mexe no PyAV. Se a fila encher (codificador mais lento
que a captura), quadros de vídeo são descartados; pacotes de áudio nunca.
"""

import queue
import threading
import time
from dataclasses import dataclass

from .audio import CapturaAudio, SaidaAudio
from .codificador import NOMES, Codificador
from .tela import CapturaTela, Monitor

_VIDEO, _AUDIO = 0, 1


@dataclass
class Resumo:
    caminho: str
    segundos: float
    quadros: int
    descartados: int
    codificador: str
    com_audio: bool


class Gravador:
    def __init__(self, caminho: str, monitor: Monitor, fps: int = 30, saida_audio: SaidaAudio | None = None,
                 codificador: str = "auto", cursor: bool = True):
        self.caminho = caminho
        self.monitor = monitor
        self.fps = fps
        self.saida_audio = saida_audio
        self.preferencia = codificador
        self.cursor = cursor
        self.erro: BaseException | None = None
        self._fila: queue.Queue = queue.Queue()
        # Dois contadores, cada um escrito por uma thread só: a diferença é o que está na fila.
        self._quadros_enviados = 0
        self._quadros_consumidos = 0
        self._parar = threading.Event()
        self._t0 = 0.0
        self._t_fim = None
        self._codificador: Codificador | None = None
        self._audio: CapturaAudio | None = None
        self._threads: list[threading.Thread] = []
        self._descartados_fila = 0
        self.gravando = False

    # --- informações para a interface -------------------------------------------------
    @property
    def segundos(self) -> float:
        if not self.gravando and self._t_fim is not None:
            return self._t_fim - self._t0
        return time.perf_counter() - self._t0 if self.gravando else 0.0

    @property
    def nivel_audio(self) -> float:
        return self._codificador.nivel if self._codificador else 0.0

    @property
    def nome_codificador(self) -> str:
        return NOMES.get(self._codificador.nome_codificador, "") if self._codificador else ""

    # --- ciclo de vida ----------------------------------------------------------------
    def iniciar(self) -> None:
        captura = CapturaTela.do_monitor(self.monitor, self.cursor)
        try:
            self._audio = CapturaAudio(self.saida_audio, self._ao_receber_audio) if self.saida_audio else None
            formato_audio = (self._audio.taxa, self._audio.canais) if self._audio else None
            self._codificador = Codificador(self.caminho, captura.largura, captura.altura, self.fps,
                                            formato_audio, self.preferencia)
        except Exception:
            captura.fechar()
            raise
        self._t0 = time.perf_counter()
        self.gravando = True
        cod = threading.Thread(target=self._laco_codificador, name="gravatela-codificador", daemon=True)
        tela = threading.Thread(target=self._laco_tela, args=(captura,), name="gravatela-tela", daemon=True)
        self._threads = [cod, tela]
        cod.start()
        tela.start()
        if self._audio:
            try:
                self._audio.iniciar()
            except Exception as e:
                self.erro = e
                self.parar()
                raise

    def parar(self) -> Resumo:
        if self.gravando:
            self._t_fim = time.perf_counter()
            self.gravando = False
        if self._audio:
            self._audio.parar()
        self._parar.set()
        for t in self._threads:
            t.join()
        self._threads = []
        c = self._codificador
        return Resumo(self.caminho, (self._t_fim or self._t0) - self._t0,
                      c.quadros if c else 0, (c.descartados if c else 0) + self._descartados_fila,
                      self.nome_codificador, bool(c and c.tem_audio))

    # --- threads ----------------------------------------------------------------------
    def _ao_receber_audio(self, instante: float, dados: bytes) -> None:
        if self.gravando:
            self._fila.put((_AUDIO, instante - self._t0, dados))

    def _laco_tela(self, captura: CapturaTela) -> None:
        intervalo = 1.0 / self.fps
        limite_fila = max(self.fps, 10)  # ~1 s de quadros; cada um tem largura*altura*4 bytes
        proximo = self._t0
        try:
            while not self._parar.is_set():
                agora = time.perf_counter()
                if agora < proximo:
                    time.sleep(proximo - agora)
                    continue
                proximo += intervalo
                if proximo < agora:  # atrasou mais de um quadro: realinha em vez de correr atrás
                    proximo = agora + intervalo
                t = time.perf_counter() - self._t0
                quadro = captura.capturar()
                if self._quadros_enviados - self._quadros_consumidos >= limite_fila:
                    self._descartados_fila += 1
                    continue
                self._quadros_enviados += 1
                self._fila.put((_VIDEO, t, quadro))
        except BaseException as e:
            self.erro = e
            self._parar.set()
        finally:
            captura.fechar()

    def _laco_codificador(self) -> None:
        c = self._codificador
        try:
            while True:
                try:
                    tipo, t, dados = self._fila.get(timeout=0.1)
                except queue.Empty:
                    if self._parar.is_set():
                        break
                    continue
                if tipo == _VIDEO:
                    self._quadros_consumidos += 1
                    c.adicionar_video(t, dados)
                else:
                    c.adicionar_audio(t, dados)
        except BaseException as e:
            self.erro = e
            self._parar.set()
        finally:
            fim = (self._t_fim or time.perf_counter()) - self._t0
            try:
                c.fechar(fim)
            except BaseException as e:
                self.erro = self.erro or e
