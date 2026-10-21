"""Grava vídeo H.264 + áudio AAC num .mp4 com o PyAV, sincronizados pelo relógio.

Todos os instantes chegam em segundos desde o início da gravação (sem contar as
pausas). O vídeo usa time_base 1/fps e o pts de cada quadro é o instante
arredondado: quadro atrasado ocupa o próximo pts livre e quadro que chega cedo
demais é descartado.

O áudio passa por um Mixer: cada fonte (áudio do PC, microfone) é convertida para
48 kHz estéreo e escrita na linha do tempo pela hora em que chegou. O mixer só
entrega ao AAC o que tem mais de ATRASO_MIXER segundos, para dar tempo de todas as
fontes chegarem; o que nenhuma fonte cobriu sai como silêncio.
"""

import functools
from fractions import Fraction

import av
import numpy as np

# Em ordem de preferência no modo automático. h264_mf (Media Foundation) fica de fora:
# aceita abrir em quase toda máquina e entrega qualidade ruim.
HARDWARE = ("h264_nvenc", "h264_qsv", "h264_amf")
CPU = "libx264"

OPCOES = {
    "libx264": {"preset": "veryfast", "crf": "23"},
    "h264_nvenc": {"preset": "p4", "rc": "vbr", "cq": "23", "b": "0"},
    "h264_qsv": {"preset": "veryfast", "global_quality": "23"},
    "h264_amf": {"quality": "balanced", "rc": "cqp", "qp_i": "22", "qp_p": "24"},
}
FORMATO_PIXEL = {"h264_qsv": "nv12"}

NOMES = {
    "libx264": "CPU (x264)",
    "h264_nvenc": "NVIDIA (NVENC)",
    "h264_qsv": "Intel (Quick Sync)",
    "h264_amf": "AMD (AMF)",
}

LAYOUTS = {1: "mono", 2: "stereo", 3: "2.1", 4: "quad", 6: "5.1", 8: "7.1"}
TAXA_SAIDA = 48000

# Diferença entre relógio e posição da fonte acima disso é buraco (silêncio). Abaixo
# é só a oscilação normal de chegada dos pacotes.
TOLERANCIA_AUDIO = 0.1
# Quanto o mixer espera as fontes antes de entregar um trecho ao codificador.
ATRASO_MIXER = 0.5
# Nível de uma fonte que não manda pacote há mais que isso cai para zero.
VALIDADE_NIVEL = 0.3


@functools.lru_cache(maxsize=None)
def codificador_funciona(nome: str, largura: int = 640, altura: int = 480) -> bool:
    """Abre o codificador e codifica um quadro. Placa ausente ou driver velho falham aqui."""
    if nome not in av.codecs_available:
        return False
    try:
        ctx = av.CodecContext.create(nome, "w")
        ctx.width, ctx.height = largura, altura
        ctx.pix_fmt = FORMATO_PIXEL.get(nome, "yuv420p")
        ctx.time_base = Fraction(1, 30)
        ctx.framerate = Fraction(30, 1)
        ctx.options = dict(OPCOES.get(nome, {}))
        ctx.open()
        quadro = av.VideoFrame.from_ndarray(np.zeros((altura, largura, 4), np.uint8), format="bgra")
        quadro.pts = 0
        ctx.encode(quadro)
        ctx.encode(None)
        return True
    except Exception:
        return False


def escolher_codificador(preferencia: str, largura: int, altura: int) -> str:
    """'auto' usa a placa de vídeo se alguma funcionar; 'cpu' ou um nome específico forçam."""
    if preferencia == "cpu":
        return CPU
    candidatos = HARDWARE if preferencia == "auto" else (preferencia,)
    for nome in candidatos:
        if codificador_funciona(nome, largura, altura):
            return nome
    return CPU


class FonteAudio:
    """Uma entrada do mixer: converte para TAXA_SAIDA estéreo e lembra onde parou na linha do tempo."""

    def __init__(self, taxa: int, canais: int, taxa_saida: int = TAXA_SAIDA):
        self.layout = LAYOUTS.get(canais)
        if self.layout is None:
            raise ValueError(f"{canais} canais de áudio não suportados")
        self.taxa, self.canais, self.taxa_saida = taxa, canais, taxa_saida
        self._direto = taxa == taxa_saida and canais in (1, 2)
        self._conversor = None if self._direto else av.AudioResampler(format="s16", layout="stereo",
                                                                       rate=taxa_saida)
        self.posicao: int | None = None  # próxima amostra (na taxa de saída) a escrever
        self.nivel = 0.0
        self.t_ultimo = -1e9

    def converter(self, dados: bytes) -> np.ndarray:
        """PCM s16 intercalado da fonte -> (amostras, 2) int16 na taxa de saída."""
        pcm = np.frombuffer(dados, dtype=np.int16).reshape(-1, self.canais)
        if self.canais == 1:
            # Duplicado aqui: o swresample baixaria 3 dB ao espalhar mono em estéreo.
            pcm = np.repeat(pcm, 2, axis=1)
        if self._direto or not len(pcm):
            return pcm
        layout = "stereo" if self.canais == 1 else self.layout
        quadro = av.AudioFrame.from_ndarray(np.ascontiguousarray(pcm).reshape(1, -1), format="s16",
                                            layout=layout)
        quadro.sample_rate = self.taxa
        partes = [q.to_ndarray().reshape(-1, 2) for q in self._conversor.resample(quadro)]
        return np.concatenate(partes) if partes else np.zeros((0, 2), np.int16)


class Mixer:
    """Soma as fontes numa linha do tempo única, em amostras de TAXA_SAIDA."""

    def __init__(self, fontes: list[tuple[int, int]], taxa: int = TAXA_SAIDA):
        self.taxa = taxa
        self.fontes = [FonteAudio(t, c, taxa) for t, c in fontes]
        self.entregue = 0  # amostras já devolvidas por retirar()
        self.relogio = 0.0  # maior instante visto (áudio ou vídeo)
        self._acumulado = np.zeros((0, 2), np.int32)  # cobre [entregue, entregue + len)

    def _garantir(self, fim: int) -> None:
        falta = fim - self.entregue - len(self._acumulado)
        if falta > 0:
            self._acumulado = np.concatenate([self._acumulado, np.zeros((falta, 2), np.int32)])

    def adicionar(self, indice: int, t_chegada: float, dados: bytes) -> None:
        """Pacote da fonte `indice` que terminou de chegar no instante t_chegada."""
        self.avancar(t_chegada)
        fonte = self.fontes[indice]
        amostras = fonte.converter(dados)
        if not len(amostras):
            return
        inicio = round(t_chegada * self.taxa) - len(amostras)
        if fonte.posicao is None or inicio - fonte.posicao > TOLERANCIA_AUDIO * self.taxa:
            fonte.posicao = inicio  # primeiro pacote ou volta depois de um silêncio
        pos = fonte.posicao
        fonte.posicao += len(amostras)
        corte = max(0, self.entregue - pos)  # antes do início ou de trecho já entregue
        amostras = amostras[corte:]
        pos += corte
        if not len(amostras):
            return
        fonte.nivel = float(np.abs(amostras).max()) / 32768.0
        fonte.t_ultimo = t_chegada
        self._garantir(pos + len(amostras))
        a = pos - self.entregue
        self._acumulado[a:a + len(amostras)] += amostras

    def avancar(self, t: float) -> None:
        self.relogio = max(self.relogio, t)

    def niveis(self) -> list[float]:
        return [f.nivel if self.relogio - f.t_ultimo < VALIDADE_NIVEL else 0.0 for f in self.fontes]

    def retirar(self, ate: int) -> np.ndarray:
        """Entrega as amostras até `ate` (exclusive), já somadas e limitadas a 16 bits."""
        n = ate - self.entregue
        if n <= 0:
            return np.zeros((0, 2), np.int16)
        self._garantir(ate)
        saida = np.clip(self._acumulado[:n], -32768, 32767).astype(np.int16)
        self._acumulado = self._acumulado[n:]
        self.entregue = ate
        return saida

    def retirar_pronto(self) -> np.ndarray:
        return self.retirar(round((self.relogio - ATRASO_MIXER) * self.taxa))


class Codificador:
    def __init__(self, caminho: str, largura: int, altura: int, fps: int,
                 audio: list[tuple[int, int]] | tuple[int, int] | None = None, codificador: str = "auto"):
        """audio = lista de (taxa, canais), uma por fonte de PCM s16; None ou [] para vídeo mudo."""
        if largura % 2 or altura % 2:
            raise ValueError("largura e altura precisam ser pares")
        if isinstance(audio, tuple):
            audio = [audio]
        self.caminho = caminho
        self.fps = fps
        self.nome_codificador = escolher_codificador(codificador, largura, altura)
        self.quadros = 0
        self.descartados = 0
        self._ultimo_pts = -1
        self._amostras = 0
        self.mixer = Mixer(audio) if audio else None
        self.taxa = TAXA_SAIDA

        self._saida = av.open(caminho, "w")
        try:
            v = self._saida.add_stream(self.nome_codificador, rate=fps,
                                       options=dict(OPCOES.get(self.nome_codificador, {})))
            v.width, v.height = largura, altura
            v.pix_fmt = FORMATO_PIXEL.get(self.nome_codificador, "yuv420p")
            v.codec_context.time_base = Fraction(1, fps)
            v.codec_context.gop_size = fps * 2
            self._video = v

            self._audio = None
            if self.mixer:
                a = self._saida.add_stream("aac", rate=TAXA_SAIDA)
                a.layout = "stereo"
                a.bit_rate = 160_000
                a.codec_context.time_base = Fraction(1, TAXA_SAIDA)
                self._audio = a
        except Exception:
            self._saida.close()
            raise

    @property
    def tem_audio(self) -> bool:
        return self._audio is not None

    @property
    def segundos_audio(self) -> float:
        return self._amostras / TAXA_SAIDA if self._audio is not None else 0.0

    @property
    def niveis(self) -> list[float]:
        return self.mixer.niveis() if self.mixer else []

    @property
    def nivel(self) -> float:
        return max(self.niveis, default=0.0)

    def adicionar_video(self, t: float, bgra: np.ndarray) -> bool:
        """Quadro capturado no instante t. Devolve False se foi descartado."""
        if self.mixer:
            # Sem pacote de áudio nenhum (PC calado, sem microfone), é o vídeo que empurra o mixer.
            self.mixer.avancar(t)
            self._codificar_audio(self.mixer.retirar_pronto())
        pts = max(round(t * self.fps), self._ultimo_pts + 1)
        if t < 0 or pts > round(t * self.fps) + 1:
            # Chegou mais de um quadro adiantado: a fila atrasou e já tem quadro mais novo atrás.
            self.descartados += 1
            return False
        quadro = av.VideoFrame.from_ndarray(bgra, format="bgra")
        quadro.pts = pts
        quadro.time_base = Fraction(1, self.fps)
        for pacote in self._video.encode(quadro):
            self._saida.mux(pacote)
        self._ultimo_pts = pts
        self.quadros += 1
        return True

    def _codificar_audio(self, pcm: np.ndarray) -> None:
        """pcm: (amostras, 2) int16, continuação exata do que já foi codificado."""
        for i in range(0, len(pcm), TAXA_SAIDA):  # em blocos de 1 s
            bloco = np.ascontiguousarray(pcm[i:i + TAXA_SAIDA])
            quadro = av.AudioFrame.from_ndarray(bloco.reshape(1, -1), format="s16", layout="stereo")
            quadro.sample_rate = TAXA_SAIDA
            quadro.pts = self._amostras
            quadro.time_base = Fraction(1, TAXA_SAIDA)
            for pacote in self._audio.encode(quadro):
                self._saida.mux(pacote)
            self._amostras += len(bloco)

    def adicionar_audio(self, fonte: int, t_chegada: float, dados: bytes) -> None:
        """Pacote PCM s16 intercalado da fonte `fonte` que terminou de chegar no instante t_chegada."""
        if self.mixer is None:
            return
        self.mixer.adicionar(fonte, t_chegada, dados)
        self._codificar_audio(self.mixer.retirar_pronto())

    def fechar(self, t_fim: float) -> None:
        """Entrega o resto do mixer (silêncio até t_fim), esvazia os codificadores e fecha o arquivo."""
        try:
            if self._audio is not None:
                self._codificar_audio(self.mixer.retirar(round(t_fim * TAXA_SAIDA)))
                for pacote in self._audio.encode(None):
                    self._saida.mux(pacote)
            for pacote in self._video.encode(None):
                self._saida.mux(pacote)
        finally:
            self._saida.close()
