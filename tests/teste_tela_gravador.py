"""Captura de tela real e gravações curtas de ponta a ponta (sem tocar som)."""

import shutil
import tempfile
import time
import unittest
from pathlib import Path

import av
import numpy as np

from gravatela.audio import listar_microfones, listar_saidas, microfone_padrao, saida_padrao
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

    @unittest.skipUnless(saida_padrao(), "sem saída de áudio no PC")
    def test_pausa_sai_da_linha_do_tempo(self):
        caminho = str(self.pasta / "p.mp4")
        g = Gravador(caminho, listar_monitores()[0], fps=30, saida_audio=saida_padrao(), codificador="cpu")
        g.iniciar()
        time.sleep(1)
        g.pausar()
        self.assertTrue(g.pausado)
        congelado = g.segundos
        time.sleep(1.5)
        self.assertAlmostEqual(g.segundos, congelado, places=3)  # o relógio para na pausa
        g.continuar()
        time.sleep(1)
        r = g.parar()
        self.assertIsNone(g.erro)
        self.assertAlmostEqual(r.segundos, 2.0, delta=0.2)
        with av.open(caminho) as f:
            dur = {s.type: float(s.duration * s.time_base) for s in f.streams}
        self.assertAlmostEqual(dur["video"], 2.0, delta=0.3)
        self.assertAlmostEqual(dur["audio"], dur["video"], delta=0.2)

    def test_parar_durante_a_pausa(self):
        caminho = str(self.pasta / "pp.mp4")
        g = Gravador(caminho, listar_monitores()[0], fps=15, codificador="cpu")
        g.iniciar()
        time.sleep(0.8)
        g.alternar_pausa()
        time.sleep(0.5)
        r = g.parar()
        self.assertAlmostEqual(r.segundos, 0.8, delta=0.15)

    @unittest.skipUnless(microfone_padrao(), "sem microfone no PC")
    def test_grava_com_microfone_e_audio_do_pc(self):
        caminho = str(self.pasta / "m.mp4")
        g = Gravador(caminho, listar_monitores()[0], fps=30, saida_audio=saida_padrao(), codificador="auto",
                     microfone=microfone_padrao())
        g.iniciar()
        time.sleep(1.5)
        self.assertIn("microfone", g.niveis_audio)
        r = g.parar()
        self.assertIsNone(g.erro)
        self.assertTrue(r.com_audio)
        with av.open(caminho) as f:
            dur = {s.type: float(s.duration * s.time_base) for s in f.streams}
        self.assertAlmostEqual(dur["audio"], dur["video"], delta=0.2)

    def test_microfones_nao_incluem_loopback(self):
        for m in listar_microfones():
            self.assertTrue(m.microfone)
            self.assertNotIn("[Loopback]", m.nome)

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
