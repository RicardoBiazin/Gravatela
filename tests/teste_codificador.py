"""Codificador e mixer com instantes sintéticos: sincronia, silêncio nos buracos, mistura, cortes e descartes."""

import shutil
import tempfile
import unittest
from pathlib import Path

import av
import numpy as np

from gravatela.codificador import CPU, TAXA_SAIDA, Codificador, Mixer, codificador_funciona, escolher_codificador

TAXA, CANAIS, FPS = 48000, 2, 30
L, A = 320, 240


def tom(segundos: float, amplitude=8000, taxa=TAXA, canais=CANAIS, freq=440) -> bytes:
    n = round(segundos * taxa)
    t = np.arange(n) / taxa
    onda = (np.sin(2 * np.pi * freq * t) * amplitude).astype(np.int16)
    return np.repeat(onda[:, None], canais, axis=1).tobytes()


def constante(segundos: float, valor: int, taxa=TAXA, canais=CANAIS) -> bytes:
    return np.full((round(segundos * taxa), canais), valor, np.int16).tobytes()


def em_ordem(c, fim, pacotes_audio, fps=FPS):
    """Entrega vídeo e áudio intercalados pela hora, como a fila do Gravador faz."""
    eventos = [(i / fps, 0, None) for i in range(round(fim * fps))]
    eventos += [(t, 1, dados) for t, dados in pacotes_audio]
    for t, tipo, dados in sorted(eventos, key=lambda e: (e[0], e[1])):
        if tipo == 0:
            c.adicionar_video(t, quadro())
        else:
            c.adicionar_audio(0, t, dados)


def quadro(cor=128):
    q = np.full((A, L, 4), cor, np.uint8)
    q[..., 3] = 255
    return q


def duracoes(caminho):
    with av.open(caminho) as f:
        return {s.type: float(s.duration * s.time_base) for s in f.streams}


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
        return Codificador(self.caminho, L, A, FPS, [(TAXA, CANAIS)] if audio else None, "cpu")

    def test_video_e_audio_continuos_ficam_com_a_mesma_duracao(self):
        c = self.novo()
        em_ordem(c, 3.0, [(k * 0.02, tom(0.02)) for k in range(1, 151)])  # pacotes de 20 ms
        c.fechar(3.0)
        d = duracoes(self.caminho)
        self.assertAlmostEqual(d["video"], 3.0, delta=0.1)
        self.assertAlmostEqual(d["audio"], 3.0, delta=0.1)
        self.assertEqual(c.quadros, 90)
        self.assertEqual(c.nome_codificador, CPU)

    def test_buraco_no_loopback_vira_silencio_na_posicao_certa(self):
        c = self.novo()
        # 1 s de som, 2 s sem pacote nenhum (loopback calado), 1 s de som.
        pacotes = [(k * 0.02, tom(0.02)) for k in range(1, 51)]
        pacotes += [(3.0 + k * 0.02, tom(0.02)) for k in range(1, 51)]
        em_ordem(c, 4.0, pacotes)
        c.fechar(4.0)
        self.assertAlmostEqual(duracoes(self.caminho)["audio"], 4.0, delta=0.1)
        som = np.abs(amostras_decodificadas(self.caminho))
        self.assertGreater(som[int(0.5 * TAXA) - 500:int(0.5 * TAXA) + 500].max(), 0.1)
        self.assertLess(som[int(1.5 * TAXA):int(2.8 * TAXA)].max(), 0.01)  # silêncio inserido
        self.assertGreater(som[int(3.5 * TAXA) - 500:int(3.5 * TAXA) + 500].max(), 0.1)  # som volta em 3 s

    def test_sem_audio_algum_completa_com_silencio_ate_o_fim(self):
        c = self.novo()
        for i in range(60):
            c.adicionar_video(i / FPS, quadro())
        c.fechar(2.0)
        self.assertAlmostEqual(duracoes(self.caminho)["audio"], 2.0, delta=0.1)

    def test_video_empurra_o_mixer_sem_acumular_memoria(self):
        c = self.novo()
        for i in range(150):  # 5 s de vídeo e nenhum pacote de áudio
            c.adicionar_video(i / FPS, quadro())
        self.assertGreater(c.segundos_audio, 4.0)  # já entregou quase tudo ao AAC
        self.assertLess(len(c.mixer._acumulado), TAXA)
        c.fechar(5.0)

    def test_dimensao_impar_e_recusada(self):
        with self.assertRaises(ValueError):
            Codificador(self.caminho, 321, 240, FPS)

    def test_canais_nao_suportados(self):
        with self.assertRaises(ValueError):
            Codificador(self.caminho, L, A, FPS, [(TAXA, 5)], "cpu")

    def test_cinco_ponto_um_vira_estereo(self):
        c = Codificador(self.caminho, L, A, FPS, [(TAXA, 6)], "cpu")
        c.adicionar_video(0, quadro())
        c.adicionar_audio(0, 0.1, np.zeros((4800, 6), np.int16).tobytes())
        c.fechar(0.5)
        with av.open(self.caminho) as f:
            self.assertEqual(f.streams.audio[0].codec_context.layout.nb_channels, 2)

    def test_formato_antigo_tupla_unica(self):
        c = Codificador(self.caminho, L, A, FPS, (TAXA, CANAIS), "cpu")
        self.assertTrue(c.tem_audio)
        c.fechar(0.1)

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

    def test_escolha_de_codificador(self):
        self.assertEqual(escolher_codificador("cpu", L, A), CPU)
        self.assertTrue(codificador_funciona(CPU))
        self.assertFalse(codificador_funciona("codificador_que_nao_existe"))
        self.assertEqual(escolher_codificador("codificador_que_nao_existe", L, A), CPU)


class TesteMixer(unittest.TestCase):
    def test_pacote_que_comecou_antes_da_gravacao_e_cortado(self):
        m = Mixer([(TAXA, CANAIS)])
        m.adicionar(0, 0.01, constante(0.05, 100))  # 50 ms que terminaram em 10 ms: sobram 10 ms
        saida = m.retirar(round(0.02 * TAXA))
        self.assertEqual(int((saida[:, 0] == 100).sum()), round(0.01 * TAXA))
        m2 = Mixer([(TAXA, CANAIS)])
        m2.adicionar(0, -0.5, constante(0.02, 100))  # inteiro antes do início: nada entra
        self.assertFalse(m2.retirar(TAXA).any())

    def test_oscilacao_pequena_nao_insere_silencio(self):
        m = Mixer([(TAXA, CANAIS)])
        for k in range(1, 51):
            atraso = 0.03 if k % 2 else 0.0  # chegada com 30 ms de oscilação
            m.adicionar(0, k * 0.02 + atraso, constante(0.02, 100))
        saida = m.retirar(TAXA)
        # O 1º pacote chegou 30 ms atrasado e fixou o começo em 30 ms; dali em diante, sem buraco.
        self.assertFalse(saida[:round(0.03 * TAXA)].any())
        self.assertTrue((saida[round(0.03 * TAXA):, 0] == 100).all())

    def test_duas_fontes_sao_somadas(self):
        m = Mixer([(TAXA, CANAIS), (TAXA, CANAIS)])
        for k in range(1, 51):
            m.adicionar(0, k * 0.02, constante(0.02, 1000))
            m.adicionar(1, k * 0.02 + 0.005, constante(0.02, 300))  # outra fonte, pacotes desencontrados
        saida = m.retirar(round(0.9 * TAXA))
        meio = saida[round(0.1 * TAXA):]
        self.assertTrue((meio == 1300).all())

    def test_soma_satura_em_16_bits(self):
        m = Mixer([(TAXA, CANAIS), (TAXA, CANAIS)])
        m.adicionar(0, 0.1, constante(0.1, 30000))
        m.adicionar(1, 0.1, constante(0.1, 30000))
        self.assertEqual(int(m.retirar(round(0.1 * TAXA)).max()), 32767)

    def test_microfone_mono_44100_e_convertido(self):
        m = Mixer([(TAXA, CANAIS), (44100, 1)])
        for k in range(1, 51):
            m.adicionar(1, k * 0.02, tom(0.02, taxa=44100, canais=1))
        saida = m.retirar(round(0.9 * TAXA))
        self.assertEqual(saida.shape[1], 2)
        trecho = saida[round(0.2 * TAXA):round(0.8 * TAXA)]
        self.assertGreater(int(np.abs(trecho).max()), 6000)  # o tom passou pela conversão
        self.assertTrue((trecho[:, 0] == trecho[:, 1]).all())  # mono vira os dois canais

    def test_pacote_atrasado_alem_do_ja_entregue_e_descartado_sem_erro(self):
        m = Mixer([(TAXA, CANAIS)])
        m.adicionar(0, 1.0, constante(0.02, 100))
        m.retirar(TAXA)  # entregou até 1 s
        m.adicionar(0, 0.9, constante(0.02, 100))  # pacote chegou tarde: some
        self.assertEqual(m.entregue, TAXA)

    def test_niveis_por_fonte_caem_quando_a_fonte_cala(self):
        m = Mixer([(TAXA, CANAIS), (TAXA, CANAIS)])
        m.adicionar(0, 0.1, constante(0.02, 16384))
        self.assertAlmostEqual(m.niveis()[0], 0.5, places=2)
        self.assertEqual(m.niveis()[1], 0.0)
        m.avancar(1.0)
        self.assertEqual(m.niveis()[0], 0.0)

    def test_taxa_de_saida(self):
        self.assertEqual(TAXA_SAIDA, 48000)


if __name__ == "__main__":
    unittest.main()
