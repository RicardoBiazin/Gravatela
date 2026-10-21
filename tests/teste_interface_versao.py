"""Janela (offscreen), CLI e consistência da versão nos arquivos de empacotamento."""

import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from PySide6.QtWidgets import QApplication

import app
from gravatela import VERSAO
from gravatela.interface import JanelaPrincipal, formatar_tempo

RAIZ = Path(__file__).resolve().parents[1]


class TesteVersao(unittest.TestCase):
    def test_versao_igual_em_todos_os_lugares(self):
        x, y, z = (int(p) for p in VERSAO.split("."))
        versao_txt = (RAIZ / "versao.txt").read_text(encoding="utf-8")
        self.assertIn(f"filevers=({x}, {y}, {z}, 0)", versao_txt)
        self.assertIn(f"prodvers=({x}, {y}, {z}, 0)", versao_txt)
        self.assertEqual(re.findall(r"'(?:File|Product)Version', '([\d.]+)'", versao_txt), [VERSAO, VERSAO])
        manifest = (RAIZ / "Gravatela.manifest").read_text(encoding="utf-8")
        self.assertIn(f'version="{VERSAO}.0"', manifest)
        import json
        web = json.loads((RAIZ / "web" / "package.json").read_text(encoding="utf-8"))
        self.assertEqual(web["version"], VERSAO)

    def test_cli_versao(self):
        r = subprocess.run([sys.executable, str(RAIZ / "app.py"), "--versao"], capture_output=True, text=True,
                           encoding="utf-8")
        self.assertEqual(r.stdout.strip(), f"Gravatela {VERSAO}")


class TesteInterface(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.pasta = Path(tempfile.mkdtemp(prefix="gravatela_ui_"))
        self.j = JanelaPrincipal()
        self.j.ck_minimizar.setChecked(False)
        self.j.ed_pasta.setText(str(self.pasta))

    def tearDown(self):
        if self.j.gravador:
            self.j.parar()
        self.j.close()
        shutil.rmtree(self.pasta, ignore_errors=True)

    def test_listas_preenchidas(self):
        self.assertGreaterEqual(self.j.cb_tela.count(), 1)
        self.assertEqual(self.j.cb_audio.itemText(self.j.cb_audio.count() - 1), "Sem áudio")
        self.assertEqual(self.j.cb_codificador.itemData(0), "auto")
        self.assertEqual(self.j.cb_fps.currentData(), 30)

    def test_gravar_e_parar_pela_janela(self):
        self.j.cb_audio.setCurrentIndex(self.j.cb_audio.count() - 1)  # sem áudio
        self.j.alternar()
        self.assertTrue(self.j.gravador.gravando)
        self.assertEqual(self.j.bt_gravar.text(), "■  Parar")
        self.assertFalse(self.j.cb_tela.isEnabled())
        fim = time.time() + 1
        while time.time() < fim:
            self.app.processEvents()
            time.sleep(0.05)
        self.j.alternar()
        self.assertIsNone(self.j.gravador)
        self.assertEqual(self.j.bt_gravar.text(), "●  Gravar")
        arquivos = list(self.pasta.glob("Gravatela_*.mp4"))
        self.assertEqual(len(arquivos), 1)
        self.assertGreater(arquivos[0].stat().st_size, 1000)

    def test_preferencias_vao_para_o_ini_dos_testes(self):
        self.assertTrue(os.environ["GRAVATELA_CONFIG"].endswith("config.ini"))
        self.j.cb_fps.setCurrentIndex(self.j.cb_fps.findData(60))
        self.j._salvar_preferencias()
        outra = JanelaPrincipal()
        self.assertEqual(int(outra.cb_fps.currentData()), 60)
        outra.close()

    def test_formatar_tempo(self):
        self.assertEqual(formatar_tempo(3725.9), "01:02:05")


class TesteCli(unittest.TestCase):
    def test_gravar_pela_linha_de_comando(self):
        pasta = Path(tempfile.mkdtemp(prefix="gravatela_cli_"))
        try:
            saida = pasta / "cli.mp4"
            self.assertEqual(app.main(["--gravar", "1", "--sem-audio", "--saida", str(saida), "--fps", "15",
                                       "--codificador", "cpu"]), 0)
            self.assertTrue(saida.is_file())
        finally:
            shutil.rmtree(pasta, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
