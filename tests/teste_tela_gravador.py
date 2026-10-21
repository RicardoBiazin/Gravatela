"""Captura de tela real e gravações curtas de ponta a ponta (sem tocar som)."""

import shutil
import tempfile
import time
import unittest
from pathlib import Path

import av
import numpy as np

from gravatela.audio import listar_saidas, saida_padrao
from gravatela.gravador import Gravador
from gravatela.tela import CapturaTela, Monitor, area_de_trabalho_virtual, ativar_dpi, listar_monitores

ativar_dpi()


class TesteTela(unittest.TestCase):
    def test_lista_monitores_com_principal_primeiro(self):
        ms = listar_monitores()
        self.assertGreaterEqual(len(ms), 1)
        self.assertTrue(ms[0].principal)
        v = area_de_trabalho_virtual()
        self.assertGreaterEqual(v.largura, ms[0].largura)

    def test_captura_bgra_com_dimensao_par(self):
        with CapturaTela(0, 0, 301, 199) as c:
            q = c.capturar()
            self.assertEqual(q.shape, (198, 300, 4))
            self.assertEqual(q.dtype, np.uint8)
            q2 = c.capturar()
            self.assertIsNot(q, q2)  # cópia, não o buffer interno

    def test_captura_com_cursor_varias_vezes_nao_vaza(self):
        m = listar_monitores()[0]
        with CapturaTela.do_monitor(m, cursor=True) as c:
            for _ in range(50):
                c.capturar()

    def test_area_invalida(self):
        with self.assertRaises(ValueError):
            CapturaTela(0, 0, 1, 1)


class TesteGravador(unittest.TestCase):
    def setUp(self):
        self.pasta = Path(tempfile.mkdtemp(prefix="gravatela_grav_"))

    def tearDown(self):
        shutil.rmtree(self.pasta, ignore_errors=True)

    def gravar(self, segundos, **kw):
        caminho = str(self.pasta / "g.mp4")
        g = Gravador(caminho, kw.pop("monitor", listar_monitores()[0]), **kw)
        g.iniciar()
        time.sleep(segundos)
        r = g.parar()
        self.assertIsNone(g.erro)
        with av.open(caminho) as f:
            dur = {s.type: float(s.duration * s.time_base) for s in f.streams}
        return r, dur

    def test_grava_sem_audio(self):
        r, dur = self.gravar(1.5, fps=15, saida_audio=None, codificador="cpu")
        self.assertNotIn("audio", dur)
        self.assertAlmostEqual(dur["video"], 1.5, delta=0.3)
        self.assertGreater(r.quadros, 15)

    @unittest.skipUnless(saida_padrao(), "sem saída de áudio no PC")
    def test_grava_com_audio_do_pc_sincronizado(self):
        r, dur = self.gravar(2, fps=30, saida_audio=saida_padrao(), codificador="auto")
        self.assertTrue(r.com_audio)
        self.assertAlmostEqual(dur["video"], 2, delta=0.3)
        self.assertAlmostEqual(dur["audio"], dur["video"], delta=0.2)

    def test_regiao_pequena(self):
        r, dur = self.gravar(1, monitor=Monitor("parte", 10, 10, 401, 301), fps=30, codificador="cpu")
        with av.open(r.caminho) as f:
            v = f.streams.video[0]
            self.assertEqual((v.width, v.height), (400, 300))

    def test_saidas_de_audio_listadas_com_padrao_primeiro(self):
        saidas = listar_saidas()
        if saidas:
            self.assertTrue(saidas[0].padrao)
            self.assertTrue(all("[Loopback]" not in s.descricao for s in saidas))


if __name__ == "__main__":
    unittest.main()
