"""Janela principal (PySide6)."""

import os
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QLibraryInfo, QLocale, QSettings, Qt, QTimer, QTranslator, QUrl
from PySide6.QtGui import QAction, QColor, QDesktopServices, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QMenu, QMessageBox, QProgressBar, QPushButton, QSystemTrayIcon, QVBoxLayout, QWidget,
)

from . import NOME, VERSAO
from .audio import listar_saidas
from .codificador import HARDWARE, NOMES, codificador_funciona
from .gravador import Gravador
from .tela import area_de_trabalho_virtual, listar_monitores

FPS_OPCOES = (15, 24, 30, 60)


def configuracoes() -> QSettings:
    """GRAVATELA_CONFIG aponta para um .ini (testes); sem ela, o registro do usuário."""
    caminho = os.environ.get("GRAVATELA_CONFIG")
    if caminho:
        return QSettings(caminho, QSettings.IniFormat)
    return QSettings("RicardoBiazin", NOME)


def pasta_padrao() -> str:
    return str(Path.home() / "Videos" / NOME)


def icone_app() -> QIcon:
    caminho = Path(__file__).resolve().parent.parent / "recursos" / "gravatela.ico"
    if caminho.is_file():
        return QIcon(str(caminho))
    base = Path(getattr(sys, "_MEIPASS", "")) / "recursos" / "gravatela.ico"
    return QIcon(str(base)) if base.is_file() else _icone_bolinha("#d93025")


def _icone_bolinha(cor: str) -> QIcon:
    pix = QPixmap(64, 64)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(cor))
    p.setPen(Qt.NoPen)
    p.drawEllipse(8, 8, 48, 48)
    p.end()
    return QIcon(pix)


def formatar_tempo(segundos: float) -> str:
    s = int(segundos)
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


class JanelaPrincipal(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{NOME} {VERSAO}")
        self.setWindowIcon(icone_app())
        self.cfg = configuracoes()
        self.gravador: Gravador | None = None
        self.ultimo_arquivo: str | None = None

        self.cb_tela = QComboBox()
        self.cb_audio = QComboBox()
        self.cb_fps = QComboBox()
        for f in FPS_OPCOES:
            self.cb_fps.addItem(f"{f} quadros/s", f)
        self.cb_codificador = QComboBox()
        self.ck_cursor = QCheckBox("Mostrar o cursor do mouse")
        self.ck_minimizar = QCheckBox("Minimizar a janela ao começar a gravar")
        self.ed_pasta = QLineEdit()
        bt_pasta = QPushButton("Escolher…")
        bt_pasta.clicked.connect(self._escolher_pasta)
        bt_abrir = QPushButton("Abrir pasta")
        bt_abrir.clicked.connect(self._abrir_pasta)
        bt_atualizar = QPushButton("Atualizar listas")
        bt_atualizar.clicked.connect(self._carregar_dispositivos)

        linha_pasta = QHBoxLayout()
        linha_pasta.addWidget(self.ed_pasta, 1)
        linha_pasta.addWidget(bt_pasta)
        linha_pasta.addWidget(bt_abrir)

        form = QFormLayout()
        form.addRow("Tela:", self.cb_tela)
        form.addRow("Áudio do PC:", self.cb_audio)
        form.addRow("Fluidez:", self.cb_fps)
        form.addRow("Codificação:", self.cb_codificador)
        form.addRow("Salvar em:", linha_pasta)
        form.addRow("", self.ck_cursor)
        form.addRow("", self.ck_minimizar)

        self.bt_gravar = QPushButton()
        self.bt_gravar.setMinimumHeight(48)
        self.bt_gravar.clicked.connect(self.alternar)
        self.lb_tempo = QLabel("00:00:00")
        self.lb_tempo.setAlignment(Qt.AlignCenter)
        fonte = self.lb_tempo.font()
        fonte.setPointSize(fonte.pointSize() * 2)
        self.lb_tempo.setFont(fonte)
        self.pb_nivel = QProgressBar()
        self.pb_nivel.setRange(0, 100)
        self.pb_nivel.setTextVisible(False)
        self.pb_nivel.setMaximumHeight(8)
        self.pb_nivel.setToolTip("Nível do áudio que está sendo gravado")

        corpo = QVBoxLayout()
        corpo.addLayout(form)
        corpo.addWidget(bt_atualizar, 0, Qt.AlignRight)
        corpo.addWidget(self.lb_tempo)
        corpo.addWidget(self.pb_nivel)
        corpo.addWidget(self.bt_gravar)
        central = QWidget()
        central.setLayout(corpo)
        self.setCentralWidget(central)
        self.statusBar().showMessage(f"{NOME} {VERSAO}")

        self.relogio = QTimer(self)
        self.relogio.setInterval(200)
        self.relogio.timeout.connect(self._atualizar)

        self.bandeja = QSystemTrayIcon(icone_app(), self)
        self.bandeja.setToolTip(NOME)
        menu = QMenu(self)
        self.acao_bandeja = QAction("Gravar", self)
        self.acao_bandeja.triggered.connect(self.alternar)
        menu.addAction(self.acao_bandeja)
        menu.addAction("Mostrar janela", self._mostrar)
        self.bandeja.setContextMenu(menu)
        self.bandeja.activated.connect(self._clique_bandeja)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.bandeja.show()

        self._carregar_dispositivos()
        self._carregar_preferencias()
        self._estado_botao()
        self.resize(560, self.sizeHint().height())

    # --- dispositivos e preferências --------------------------------------------------
    def _carregar_dispositivos(self) -> None:
        tela_atual = self.cb_tela.currentText()
        audio_atual = self.cb_audio.currentText()
        self.cb_tela.clear()
        monitores = listar_monitores()
        for m in monitores:
            self.cb_tela.addItem(m.descricao, m)
        if len(monitores) > 1:
            v = area_de_trabalho_virtual()
            self.cb_tela.addItem(f"{v.nome}: {v.largura}x{v.altura}", v)
        self.cb_audio.clear()
        try:
            saidas = listar_saidas()
        except Exception as e:  # sem serviço de áudio, por exemplo
            saidas = []
            self.statusBar().showMessage(f"Não deu para listar o áudio: {e}")
        for s in saidas:
            self.cb_audio.addItem(s.descricao, s)
        self.cb_audio.addItem("Sem áudio", None)
        if self.cb_codificador.count() == 0:
            self.cb_codificador.addItem("Automático (placa de vídeo, se houver)", "auto")
            self.cb_codificador.addItem(NOMES["libx264"], "cpu")
            for nome in HARDWARE:
                if codificador_funciona(nome):
                    self.cb_codificador.addItem(NOMES[nome], nome)
        self._selecionar(self.cb_tela, tela_atual)
        self._selecionar(self.cb_audio, audio_atual)

    def _selecionar(self, combo: QComboBox, texto: str | None) -> None:
        if texto:
            i = combo.findText(texto)
            if i >= 0:
                combo.setCurrentIndex(i)

    def _carregar_preferencias(self) -> None:
        self._selecionar(self.cb_tela, self.cfg.value("tela", "", str))
        self._selecionar(self.cb_audio, self.cfg.value("audio", "", str))
        i = self.cb_fps.findData(int(self.cfg.value("fps", 30)))
        self.cb_fps.setCurrentIndex(i if i >= 0 else FPS_OPCOES.index(30))
        i = self.cb_codificador.findData(self.cfg.value("codificador", "auto", str))
        self.cb_codificador.setCurrentIndex(max(i, 0))
        self.ck_cursor.setChecked(self.cfg.value("cursor", True, bool))
        self.ck_minimizar.setChecked(self.cfg.value("minimizar", True, bool))
        self.ed_pasta.setText(self.cfg.value("pasta", pasta_padrao(), str))

    def _salvar_preferencias(self) -> None:
        self.cfg.setValue("tela", self.cb_tela.currentText())
        self.cfg.setValue("audio", self.cb_audio.currentText())
        self.cfg.setValue("fps", self.cb_fps.currentData())
        self.cfg.setValue("codificador", self.cb_codificador.currentData())
        self.cfg.setValue("cursor", self.ck_cursor.isChecked())
        self.cfg.setValue("minimizar", self.ck_minimizar.isChecked())
        self.cfg.setValue("pasta", self.ed_pasta.text())
        self.cfg.sync()

    def _escolher_pasta(self) -> None:
        pasta = QFileDialog.getExistingDirectory(self, "Salvar gravações em", self.ed_pasta.text())
        if pasta:
            self.ed_pasta.setText(pasta)

    def _abrir_pasta(self) -> None:
        pasta = Path(self.ed_pasta.text() or pasta_padrao())
        pasta.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(pasta)))

    # --- gravação ---------------------------------------------------------------------
    def novo_caminho(self) -> str:
        pasta = Path(self.ed_pasta.text() or pasta_padrao())
        pasta.mkdir(parents=True, exist_ok=True)
        return str(pasta / f"{NOME}_{datetime.now():%Y-%m-%d_%H-%M-%S}.mp4")

    def alternar(self) -> None:
        if self.gravador and self.gravador.gravando:
            self.parar()
        else:
            self.iniciar()

    def iniciar(self) -> None:
        monitor = self.cb_tela.currentData()
        if monitor is None:
            QMessageBox.warning(self, NOME, "Nenhuma tela encontrada.")
            return
        self._salvar_preferencias()
        try:
            caminho = self.novo_caminho()
            self.gravador = Gravador(caminho, monitor, self.cb_fps.currentData(), self.cb_audio.currentData(),
                                     self.cb_codificador.currentData(), self.ck_cursor.isChecked())
            self.gravador.iniciar()
        except Exception as e:
            self.gravador = None
            QMessageBox.critical(self, NOME, f"Não foi possível começar a gravar:\n\n{e}")
            return
        self.relogio.start()
        self._estado_botao()
        self.statusBar().showMessage(f"Gravando com {self.gravador.nome_codificador} em {caminho}")
        if self.ck_minimizar.isChecked():
            self.showMinimized()

    def parar(self) -> None:
        if not self.gravador:
            return
        self.relogio.stop()
        resumo = self.gravador.parar()
        erro = self.gravador.erro
        self.gravador = None
        self.pb_nivel.setValue(0)
        self._estado_botao()
        if erro:
            QMessageBox.critical(self, NOME, f"A gravação parou com erro:\n\n{erro}")
        self.ultimo_arquivo = resumo.caminho
        extra = f", {resumo.descartados} quadros descartados" if resumo.descartados else ""
        self.statusBar().showMessage(f"Salvo: {resumo.caminho} ({formatar_tempo(resumo.segundos)}{extra})")
        self._mostrar()
        if self.bandeja.isVisible():
            self.bandeja.showMessage(NOME, f"Gravação salva em\n{resumo.caminho}", QSystemTrayIcon.Information, 4000)

    def _atualizar(self) -> None:
        g = self.gravador
        if not g:
            return
        if g.erro:
            self.parar()
            return
        self.lb_tempo.setText(formatar_tempo(g.segundos))
        self.pb_nivel.setValue(int(min(g.nivel_audio, 1.0) * 100))
        self.bandeja.setToolTip(f"{NOME}: gravando {formatar_tempo(g.segundos)} (clique para parar)")

    def _estado_botao(self) -> None:
        gravando = bool(self.gravador and self.gravador.gravando)
        self.bt_gravar.setText("■  Parar" if gravando else "●  Gravar")
        self.bt_gravar.setStyleSheet(
            "QPushButton{font-size:16px;font-weight:bold;" + ("color:#d93025;}" if gravando else "}"))
        self.acao_bandeja.setText("Parar" if gravando else "Gravar")
        self.bandeja.setIcon(_icone_bolinha("#d93025") if gravando else icone_app())
        self.bandeja.setToolTip(f"{NOME}: gravando (clique para parar)" if gravando else NOME)
        for w in (self.cb_tela, self.cb_audio, self.cb_fps, self.cb_codificador, self.ck_cursor, self.ed_pasta):
            w.setEnabled(not gravando)
        if not gravando:
            self.lb_tempo.setText("00:00:00")

    def _clique_bandeja(self, motivo) -> None:
        if motivo != QSystemTrayIcon.Trigger:
            return
        if self.gravador and self.gravador.gravando:
            self.parar()
        else:
            self._mostrar()

    def _mostrar(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, evento) -> None:
        if self.gravador and self.gravador.gravando:
            r = QMessageBox.question(self, NOME, "Está gravando. Parar e salvar antes de sair?")
            if r != QMessageBox.Yes:
                evento.ignore()
                return
            self.parar()
        self._salvar_preferencias()
        self.bandeja.hide()
        evento.accept()


def executar() -> int:
    app = QApplication.instance() or QApplication([])
    app.setApplicationName(NOME)
    app.setWindowIcon(icone_app())
    for nome in ("qtbase_pt_BR", "qt_pt_BR"):  # botões Sim/Não/Cancelar em português
        tradutor = QTranslator(app)
        if tradutor.load(QLocale("pt_BR"), nome.rsplit("_pt_BR")[0], "_", QLibraryInfo.path(QLibraryInfo.TranslationsPath)):
            app.installTranslator(tradutor)
    janela = JanelaPrincipal()
    janela.show()
    return app.exec()
