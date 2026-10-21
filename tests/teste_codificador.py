"""Codificador com instantes sintéticos: sincronia, silêncio nos buracos, cortes e descartes."""

import shutil
import tempfile
import unittest
from pathlib import Path

import av
import numpy as np

from gravatela.codificador import CPU, Codificador, codificador_funciona, escolher_codificador

TAXA, CANAIS, FPS = 48000, 2, 30
L, A = 320, 240


def tom(segundos: float, amplitude=8000) -> bytes:
    n = round(segundos * TAXA)
    t = np.arange(n) / TAXA
    onda = (np.sin(2 * np.pi * 440 * t) * amplitude).astype(np.int16)
    return np.repeat(onda[:, None], CANAIS, axis=1).tobytes()


def quadro(cor=128):
    q = np.full((A, L, 4), cor, np.uint8)
    q[..., 3] = 255
    return q


def duracoes(caminho):
    with av.open(caminho) as f:
        r = {}
        for s in f.streams:
            r[s.type] = float(s.duration * s.time_base)
        return r


def amostras_decodificadas(caminho):
    """Áudio decodificado, mono, como float."""
    with av.open(caminho) as f:
        partes = [fr.to_ndarray().mean(axis=0) for fr in f.decode(audio=0)]
    return np.concatenate(partes)


class TesteCodificador(unittest.TestCase):
    def setUp(self):
        self.pasta = Path(tempfile.mkdtemp(prefix="gravatela_cod_"))
        self.caminho = str(self.pasta / "x.mp4")

    def tearDown(self):
        shutil.rmtree(self.pasta, ignore_errors=True)

    def novo(self, audio=True):
        return Codificador(self.caminho, L, A, FPS, (TAXA, CANAIS) if audio else None, "cpu")

    def test_video_e_audio_continuos_ficam_com_a_mesma_duracao(self):
        c = self.novo()
        for i in range(90):  # 3 s
            c.adicionar_video(i / FPS, quadro(i % 255))
        for k in range(1, 151):  # pacotes de 20 ms
            c.adicionar_audio(k * 0.02, tom(0.02))
        c.fechar(3.0)
        d = duracoes(self.caminho)
        self.assertAlmostEqual(d["video"], 3.0, delta=0.1)
        self.assertAlmostEqual(d["audio"], 3.0, delta=0.1)
        self.assertEqual(c.quadros, 90)
        self.assertEqual(c.nome_codificador, CPU)

    def test_buraco_no_loopback_vira_silencio_na_posicao_certa(self):
        c = self.novo()
        for i in range(120):
            c.adicionar_video(i / FPS, quadro())
        # 1 s de som, 2 s sem pacote nenhum (loopback calado), 1 s de som.
        for k in range(1, 51):
            c.adicionar_audio(k * 0.02, tom(0.02))
        for k in range(1, 51):
            c.adicionar_audio(3.0 + k * 0.02, tom(0.02))
        c.fechar(4.0)
        self.assertAlmostEqual(duracoes(self.caminho)["audio"], 4.0, delta=0.1)
        som = np.abs(amostras_decodificadas(self.caminho))
        self.assertGreater(som[int(0.5 * TAXA)-500:int(0.5 * TAXA)+500].max(), 0.1)
        self.assertLess(som[int(1.5 * TAXA):int(2.8 * TAXA)].max(), 0.01)  # silêncio inserido
        self.assertGreater(som[int(3.5 * TAXA)-500:int(3.5 * TAXA)+500].max(), 0.1)  # som volta em 3 s

    def test_sem_audio_algum_completa_com_silencio_ate_o_fim(self):
        c = self.novo()
        for i in range(60):
            c.adicionar_video(i / FPS, quadro())
        c.fechar(2.0)
        d = duracoes(self.caminho)
        self.assertAlmostEqual(d["audio"], 2.0, delta=0.1)

    def test_pacote_que_comecou_antes_da_gravacao_e_cortado(self):
        c = self.novo()
        c.adicionar_audio(0.01, tom(0.05))  # 50 ms que terminaram em 10 ms: sobram 10 ms
        self.assertEqual(c._amostras, round(0.01 * TAXA))
        c.adicionar_audio(-0.5, tom(0.02))  # inteiro antes do início: nada entra
        self.assertEqual(c._amostras, round(0.01 * TAXA))
        c.fechar(0.1)

    def test_oscilacao_pequena_nao_insere_silencio(self):
        c = self.novo()
        for k in range(1, 51):
            atraso = 0.03 if k % 2 else 0.0  # chegada com 30 ms de oscilação
            c.adicionar_audio(k * 0.02 + atraso, tom(0.02))
        self.assertEqual(c._amostras, 50 * round(0.02 * TAXA))
        c.fechar(1.0)

    def test_quadros_rapidos_demais_sao_descartados(self):
        c = self.novo(audio=False)
        aceitos = sum(c.adicionar_video(i / 90, quadro()) for i in range(90))  # 90 qps num vídeo de 30
        c.fechar(1.0)
        self.assertLessEqual(aceitos, 32)
        self.assertGreaterEqual(aceitos, 29)
        self.assertEqual(c.descartados, 90 - aceitos)

    def test_quadro_atrasado_ocupa_o_proximo_pts(self):
        c = self.novo(audio=False)
        self.assertTrue(c.adicionar_video(0.0, quadro()))
        self.assertTrue(c.adicionar_video(0.01, quadro()))  # mesmo pts 0: vai para o 1
        self.assertEqual(c._ultimo_pts, 1)
        c.fechar(0.1)

    def test_dimensao_impar_e_recusada(self):
        with self.assertRaises(ValueError):
            Codificador(self.caminho, 321, 240, FPS)

    def test_canais_nao_suportados(self):
        with self.assertRaises(ValueError):
            Codificador(self.caminho, L, A, FPS, (TAXA, 5), "cpu")

    def test_cinco_ponto_um_vira_estereo(self):
        c = Codificador(self.caminho, L, A, FPS, (TAXA, 6), "cpu")
        c.adicionar_video(0, quadro())
        c.adicionar_audio(0.1, np.zeros((4800, 6), np.int16).tobytes())
        c.fechar(0.5)
        with av.open(self.caminho) as f:
            self.assertEqual(f.streams.audio[0].codec_context.layout.nb_channels, 2)

    def test_escolha_de_codificador(self):
        self.assertEqual(escolher_codificador("cpu", L, A), CPU)
        self.assertTrue(codificador_funciona(CPU))
        self.assertFalse(codificador_funciona("codificador_que_nao_existe"))
        self.assertEqual(escolher_codificador("codificador_que_nao_existe", L, A), CPU)


if __name__ == "__main__":
    unittest.main()
