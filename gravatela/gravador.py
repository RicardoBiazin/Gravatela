"""Liga captura de tela, captura de áudio e codificador em threads.

    captura de tela        ─┐
    callback áudio do PC   ─┼─> fila ─> thread do codificador ─> .mp4
    callback do microfone  ─┘

Só a thread do codificador mexe no PyAV. Se a fila encher (codificador mais lento
que a captura), quadros de vídeo são descartados; pacotes de áudio nunca.

Pausa: o tempo pausado sai da linha do tempo. Durante a pausa a tela não é
capturada e os pacotes de áudio são jogados fora; ao continuar, o vídeo e o
áudio seguem do ponto em que pararam.
"""

import queue
import threading
import time
from dataclasses import dataclass

from .audio import CapturaAudio, DispositivoAudio
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
    def __init__(self, caminho: str, monitor: Monitor, fps: int = 30,
                 saida_audio: DispositivoAudio | None = None, codificador: str = "auto", cursor: bool = True,
                 microfone: DispositivoAudio | None = None):
        self.caminho = caminho
        self.monitor = monitor
        self.fps = fps
        self.saida_audio = saida_audio
        self.microfone = microfone
        self.preferencia = codificador
        self.cursor = cursor
        self.erro: BaseException | None = None
        self._fila: queue.Queue = queue.Queue()
        # Dois contadores, cada um escrito por uma thread só: a diferença é o que está na fila.
        self._quadros_enviados = 0
        self._quadros_consumidos = 0
        self._parar = threading.Event()
        self._t0 = 0.0
        self._pausado_desde: float | None = None
        self._tempo_pausado = 0.0
        self._fim_linha: float | None = None  # segundos de gravação quando parou
        self._codificador: Codificador | None = None
        self._capturas: list[CapturaAudio] = []
        self._threads: list[threading.Thread] = []
        self._descartados_fila = 0
        self.gravando = False

    # --- informações para a interface -------------------------------------------------
    def _linha(self, instante: float) -> float:
        """Instante perf_counter -> segundos de gravação (sem as pausas)."""
        return instante - self._t0 - self._tempo_pausado

    @property
    def pausado(self) -> bool:
        return self._pausado_desde is not None

    @property
    def segundos(self) -> float:
        if self._fim_linha is not None:
            return self._fim_linha
        if not self.gravando:
            return 0.0
        return self._linha(self._pausado_desde if self.pausado else time.perf_counter())

    @property
    def niveis_audio(self) -> dict[str, float]:
        """Nível (0 a 1) de cada fonte: 'pc' e/ou 'microfone'."""
        if not self._codificador:
            return {}
        return dict(zip(self._nomes_fontes, self._codificador.niveis))

    @property
    def nivel_audio(self) -> float:
        return max(self.niveis_audio.values(), default=0.0)

    @property
    def nome_codificador(self) -> str:
        return NOMES.get(self._codificador.nome_codificador, "") if self._codificador else ""

    # --- ciclo de vida ----------------------------------------------------------------
    def iniciar(self) -> None:
        captura = CapturaTela.do_monitor(self.monitor, self.cursor)
        try:
            self._nomes_fontes = []
            for nome, disp in (("pc", self.saida_audio), ("microfone", self.microfone)):
                if disp is not None:
                    i = len(self._capturas)
                    self._capturas.append(CapturaAudio(disp, lambda t, d, i=i: self._ao_receber_audio(i, t, d)))
                    self._nomes_fontes.append(nome)
            formatos = [(c.taxa, c.canais) for c in self._capturas]
            self._codificador = Codificador(self.caminho, captura.largura, captura.altura, self.fps,
                                            formatos, self.preferencia)
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
        try:
            for c in self._capturas:
                c.iniciar()
        except Exception as e:
            self.erro = e
            self.parar()
            raise

    def pausar(self) -> None:
        if self.gravando and not self.pausado:
            self._pausado_desde = time.perf_counter()

    def continuar(self) -> None:
        if self.pausado:
            self._tempo_pausado += time.perf_counter() - self._pausado_desde
            self._pausado_desde = None

    def alternar_pausa(self) -> None:
        self.continuar() if self.pausado else self.pausar()

    def parar(self) -> Resumo:
        if self.gravando:
            self._fim_linha = self.segundos
            self.gravando = False
        for c in self._capturas:
            c.parar()
        self._parar.set()
        for t in self._threads:
            t.join()
        self._threads = []
        c = self._codificador
        return Resumo(self.caminho, self._fim_linha or 0.0,
                      c.quadros if c else 0, (c.descartados if c else 0) + self._descartados_fila,
                      self.nome_codificador, bool(c and c.tem_audio))

    # --- threads ----------------------------------------------------------------------
    def _ao_receber_audio(self, fonte: int, instante: float, dados: bytes) -> None:
        if self.gravando and not self.pausado:
            self._fila.put((_AUDIO, self._linha(instante), (fonte, dados)))

    def _laco_tela(self, captura: CapturaTela) -> None:
        intervalo = 1.0 / self.fps
        limite_fila = max(self.fps, 10)  # ~1 s de quadros; cada um tem largura*altura*4 bytes
        proximo = self._t0
        try:
            while not self._parar.is_set():
                if self.pausado:
                    time.sleep(0.02)
                    proximo = 0.0  # realinha ao continuar
                    continue
                agora = time.perf_counter()
                if agora < proximo:
                    time.sleep(proximo - agora)
                    continue
                proximo += intervalo
                if proximo < agora:  # atrasou mais de um quadro: realinha em vez de correr atrás
                    proximo = agora + intervalo
                t = self._linha(time.perf_counter())
                quadro = captura.capturar()
                if self.pausado:  # pausou durante a captura
                    continue
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
                    c.adicionar_audio(dados[0], t, dados[1])
        except BaseException as e:
            self.erro = e
            self._parar.set()
        finally:
            fim = self._fim_linha if self._fim_linha is not None else self.segundos
            try:
                c.fechar(fim)
            except BaseException as e:
                self.erro = self.erro or e
