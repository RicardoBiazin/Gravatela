"""Grava vídeo H.264 + áudio AAC num .mp4 com o PyAV, sincronizados pelo relógio.

Todos os instantes chegam em segundos desde o início da gravação. O vídeo usa
time_base 1/fps e o pts de cada quadro é o instante arredondado: quadro atrasado
ocupa o próximo pts livre e quadro que chega cedo demais é descartado. O áudio
usa time_base 1/taxa e conta amostras; quando o relógio anda mais que as amostras
recebidas (silêncio no loopback), entra silêncio para não dessincronizar.
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

# Diferença entre relógio e amostras acima disso vira silêncio. Abaixo é só a
# oscilação normal de chegada dos pacotes.
TOLERANCIA_AUDIO = 0.1


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


class Codificador:
    def __init__(self, caminho: str, largura: int, altura: int, fps: int,
                 audio: tuple[int, int] | None = None, codificador: str = "auto"):
        """audio = (taxa, canais) do PCM s16 que vai chegar, ou None para vídeo mudo."""
        if largura % 2 or altura % 2:
            raise ValueError("largura e altura precisam ser pares")
        self.caminho = caminho
        self.fps = fps
        self.nome_codificador = escolher_codificador(codificador, largura, altura)
        self.quadros = 0
        self.descartados = 0
        self._ultimo_pts = -1
        self._amostras = 0
        self.nivel = 0.0

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
            if audio is not None:
                taxa, canais = audio
                self.taxa, self.canais = taxa, canais
                self._layout_entrada = LAYOUTS.get(canais)
                if self._layout_entrada is None:
                    raise ValueError(f"{canais} canais de áudio não suportados")
                a = self._saida.add_stream("aac", rate=taxa)
                a.layout = "mono" if canais == 1 else "stereo"
                a.bit_rate = 160_000
                a.codec_context.time_base = Fraction(1, taxa)
                self._audio = a
        except Exception:
            self._saida.close()
            raise

    @property
    def tem_audio(self) -> bool:
        return self._audio is not None

    @property
    def segundos_audio(self) -> float:
        return self._amostras / self.taxa if self._audio is not None else 0.0

    def adicionar_video(self, t: float, bgra: np.ndarray) -> bool:
        """Quadro capturado no instante t. Devolve False se foi descartado."""
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
        """pcm: (amostras, canais) int16, já na posição certa da linha do tempo."""
        if not len(pcm):
            return
        quadro = av.AudioFrame.from_ndarray(np.ascontiguousarray(pcm).reshape(1, -1), format="s16",
                                            layout=self._layout_entrada)
        quadro.sample_rate = self.taxa
        quadro.pts = self._amostras
        quadro.time_base = Fraction(1, self.taxa)
        for pacote in self._audio.encode(quadro):
            self._saida.mux(pacote)
        self._amostras += len(pcm)

    def _silencio_ate(self, amostra: int) -> None:
        falta = amostra - self._amostras
        while falta > 0:
            n = min(falta, self.taxa)  # em blocos de 1 s para não alocar muito de uma vez
            self._codificar_audio(np.zeros((n, self.canais), np.int16))
            falta -= n

    def adicionar_audio(self, t_chegada: float, dados: bytes) -> None:
        """Pacote PCM s16 intercalado que terminou de chegar no instante t_chegada."""
        if self._audio is None:
            return
        pcm = np.frombuffer(dados, dtype=np.int16).reshape(-1, self.canais)
        inicio = round(t_chegada * self.taxa) - len(pcm)
        if inicio < 0:  # pacote que começou antes da gravação: corta a parte de antes
            pcm = pcm[-inicio:]
            inicio = 0
        if inicio - self._amostras > TOLERANCIA_AUDIO * self.taxa:
            self._silencio_ate(inicio)
        if len(pcm):
            self.nivel = float(np.abs(pcm).max()) / 32768.0
        self._codificar_audio(pcm)

    def fechar(self, t_fim: float) -> None:
        """Completa o áudio com silêncio até t_fim, esvazia os codificadores e fecha o arquivo."""
        try:
            if self._audio is not None:
                self._silencio_ate(round(t_fim * self.taxa))
                for pacote in self._audio.encode(None):
                    self._saida.mux(pacote)
            for pacote in self._video.encode(None):
                self._saida.mux(pacote)
        finally:
            self._saida.close()
