"""Atalhos globais, escolha de área (camada de seleção) e os controles novos da janela."""

import ctypes
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from ctypes import wintypes
from pathlib import Path

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from gravatela import atalhos
from gravatela.interface import JanelaPrincipal, area_de_texto, area_para_texto, descrever_area
from gravatela.selecao import CamadaSelecao, monitor_da_tela, para_fisico
from gravatela.tela import Monitor


class TesteAtalhos(unittest.TestCase):
    def test_id_do_atalho_reconhece_wm_hotkey(self):
        msg = wintypes.MSG()
        msg.message = atalhos.WM_HOTKEY
        msg.wParam = atalhos.PAUSAR_CONTINUAR
        self.assertEqual(atalhos.id_do_atalho(ctypes.addressof(msg)), atalhos.PAUSAR_CONTINUAR)
        msg.wParam = 99  # atalho de outro dono
        self.assertIsNone(atalhos.id_do_atalho(ctypes.addressof(msg)))
        msg.message = 0x0100  # WM_KEYDOWN
        self.assertIsNone(atalhos.id_do_atalho(ctypes.addressof(msg)))
        self.assertIsNone(atalhos.id_do_atalho(0))

    def test_registrar_e_liberar_na_thread(self):
        falhas = atalhos.registrar(None)
        try:
            self.assertEqual(falhas, [])  # ninguém mais usa Ctrl+Shift+F9/F10 aqui
        finally:
            atalhos.liberar(None)
        self.assertEqual(atalhos.registrar(None), [])  # liberou de verdade: registra de novo
        atalhos.liberar(None)


# Roda numa janela de verdade (plataforma "windows"), porque no offscreen não há HWND.
SCRIPT_JANELA_REAL = r"""
import ctypes, subprocess, sys, time
from ctypes import wintypes
from PySide6.QtWidgets import QApplication
app = QApplication([])
from gravatela.interface import JanelaPrincipal
j = JanelaPrincipal()
j.ck_minimizar.setChecked(False)
j.cb_audio.setCurrentIndex(j.cb_audio.count() - 1)
j.ed_pasta.setText(sys.argv[1])
j.show()
app.processEvents()
outro = ("import ctypes;u=ctypes.WinDLL('user32',use_last_error=True);"
         "print(u.RegisterHotKey(None,1,0x4006,0x78), ctypes.get_last_error())")
print("ocupado", subprocess.run([sys.executable, "-c", outro], capture_output=True, text=True).stdout.strip())
ctypes.windll.user32.PostMessageW(wintypes.HWND(j._hwnd_atalhos), 0x0312, 1, 0)
fim = time.time() + 1.5
while time.time() < fim:
    app.processEvents()
    time.sleep(0.02)
print("gravando", j.gravando)
j.parar()
j.close()
app.processEvents()
print("livre", subprocess.run([sys.executable, "-c", outro], capture_output=True, text=True).stdout.strip())
"""


class TesteAtalhoNaJanelaReal(unittest.TestCase):
    def test_janela_registra_recebe_e_libera_o_atalho(self):
        pasta = tempfile.mkdtemp(prefix="gravatela_atalho_")
        try:
            env = {k: v for k, v in os.environ.items() if k != "QT_QPA_PLATFORM"}
            raiz = str(Path(__file__).resolve().parents[1])
            env["PYTHONPATH"] = raiz
            env["GRAVATELA_CONFIG"] = os.path.join(pasta, "config.ini")  # nunca o registro do usuário
            r = subprocess.run([sys.executable, "-c", SCRIPT_JANELA_REAL, pasta], capture_output=True, text=True,
                               env=env, cwd=raiz, timeout=60)
            linhas = r.stdout.splitlines()
            self.assertIn("ocupado 0 1409", linhas, r.stdout + r.stderr)  # 1409: atalho já registrado
            self.assertIn("gravando True", linhas, r.stdout + r.stderr)  # WM_HOTKEY chegou ao nativeEvent
            self.assertIn("livre 1 0", linhas, r.stdout + r.stderr)  # fechar a janela libera
        finally:
            shutil.rmtree(pasta, ignore_errors=True)


class TesteConversaoArea(unittest.TestCase):
    def test_escala_e_origem(self):
        m = para_fisico(QRect(10, 20, 100, 50), (1920, 0), 1.5)
        self.assertEqual((m.x, m.y, m.largura, m.altura), (1935, 30, 150, 75))

    def test_limita_na_borda_do_monitor(self):
        mon = Monitor("DISPLAY1", 0, 0, 1920, 1080)
        m = para_fisico(QRect(1900, 1000, 100, 100), (0, 0), 1.0, mon)
        self.assertEqual((m.x, m.y, m.largura, m.altura), (1900, 1000, 20, 80))

    def test_texto_da_area_ida_e_volta(self):
        m = Monitor("Área", 5, 6, 640, 480)
        self.assertEqual(area_de_texto(area_para_texto(m)), m)
        self.assertIsNone(area_de_texto(""))
        self.assertIsNone(area_de_texto("1,2,3"))
        self.assertIsNone(area_de_texto("0,0,1,1"))
        self.assertEqual(descrever_area(m), "Área escolhida: 640x480 em (5, 6)")


class TesteCamada(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.resultados = []
        self.tela = QGuiApplication.primaryScreen()
        self.camada = CamadaSelecao(self.tela, lambda c, r: self.resultados.append(r))
        self.camada.show()

    def tearDown(self):
        self.camada.close()

    def test_arrastar_devolve_retangulo(self):
        QTest.mousePress(self.camada, Qt.LeftButton, Qt.NoModifier, QPoint(300, 200))
        QTest.mouseMove(self.camada, QPoint(150, 120))
        QTest.mouseRelease(self.camada, Qt.LeftButton, Qt.NoModifier, QPoint(100, 100))
        self.assertEqual(self.resultados, [QRect(100, 100, 200, 100)])

    def test_clique_sem_arrastar_nao_termina(self):
        QTest.mouseClick(self.camada, Qt.LeftButton, Qt.NoModifier, QPoint(50, 50))
        self.assertEqual(self.resultados, [])

    def test_esc_cancela(self):
        QTest.keyClick(self.camada, Qt.Key_Escape)
        self.assertEqual(self.resultados, [None])

    def test_monitor_da_tela_pelo_nome(self):
        nome = self.tela.name().replace("\\\\.\\", "")
        m = Monitor(nome, 0, 0, 100, 100)
        self.assertIs(monitor_da_tela(self.tela, [Monitor("outro", 0, 0, 1, 1), m]), m)
        self.assertIsNone(monitor_da_tela(self.tela, []))


class TesteJanelaRecursos(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.pasta = Path(tempfile.mkdtemp(prefix="gravatela_ui2_"))
        self.j = JanelaPrincipal()
        self.j.ck_minimizar.setChecked(False)
        self.j.ed_pasta.setText(str(self.pasta))
        self.j.cb_audio.setCurrentIndex(self.j.cb_audio.count() - 1)  # sem áudio
        self.j.cb_microfone.setCurrentIndex(0)  # sem microfone

    def tearDown(self):
        if self.j.gravador:
            self.j.parar()
        self.j.close()
        shutil.rmtree(self.pasta, ignore_errors=True)

    def esperar(self, segundos):
        fim = time.time() + segundos
        while time.time() < fim:
            self.app.processEvents()
            time.sleep(0.02)

    def test_combo_de_microfone_comeca_com_sem_microfone(self):
        self.assertEqual(self.j.cb_microfone.itemText(0), "Sem microfone")
        self.assertIsNone(self.j.cb_microfone.itemData(0))

    def test_atalhos_gravam_pausam_e_param(self):
        self.assertFalse(self.j.bt_pausar.isEnabled())
        self.j.tratar_atalho(atalhos.GRAVAR_PARAR)
        self.assertTrue(self.j.gravando)
        self.esperar(0.5)
        self.j.tratar_atalho(atalhos.PAUSAR_CONTINUAR)
        self.assertTrue(self.j.gravador.pausado)
        self.assertEqual(self.j.bt_pausar.text(), "▶  Continuar")
        self.assertIn("(pausado)", self.j.lb_tempo.text())
        self.esperar(0.5)
        self.j.alternar_pausa()
        self.assertFalse(self.j.gravador.pausado)
        self.esperar(0.5)
        self.j.tratar_atalho(atalhos.GRAVAR_PARAR)
        self.assertFalse(self.j.gravando)
        self.assertEqual(len(list(self.pasta.glob("*.mp4"))), 1)

    def test_pausar_sem_gravar_nao_faz_nada(self):
        self.j.alternar_pausa()
        self.assertIsNone(self.j.gravador)

    def test_area_escolhida_entra_no_combo_e_grava(self):
        area = Monitor("Área", 0, 0, 641, 361)
        self.j._definir_area(area)
        self.j._definir_area(area)  # trocar de área não duplica o item
        itens = [self.j.cb_tela.itemText(i) for i in range(self.j.cb_tela.count())]
        self.assertEqual(sum(t.startswith("Área escolhida") for t in itens), 1)
        self.assertEqual(self.j.cb_tela.currentData(), area)
        self.j.alternar()
        self.esperar(0.6)
        self.j.alternar()
        import av
        arquivo = next(self.pasta.glob("*.mp4"))
        with av.open(str(arquivo)) as f:
            self.assertEqual((f.streams.video[0].width, f.streams.video[0].height), (640, 360))

    def test_area_volta_das_preferencias(self):
        self.j._definir_area(Monitor("Área", 1, 2, 300, 200))
        self.j._salvar_preferencias()
        outra = JanelaPrincipal()
        try:
            self.assertEqual(outra.cb_tela.currentText(), "Área escolhida: 300x200 em (1, 2)")
        finally:
            outra.close()
        # Não deixa a área como tela padrão para os outros testes.
        self.j.cfg.setValue("tela", "")
        self.j.cfg.setValue("area", "")
        self.j.cfg.sync()


if __name__ == "__main__":
    unittest.main()
