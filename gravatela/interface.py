"""Janela principal (PySide6)."""

import os
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QLibraryInfo, QLocale, QSettings, Qt, QTimer, QTranslator, QUrl
from PySide6.QtGui import QAction, QColor, QDesktopServices, QGuiApplication, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QMenu, QMessageBox, QProgressBar, QPushButton, QSystemTrayIcon, QVBoxLayout, QWidget,
)

from . import NOME, VERSAO, atalhos
from .audio import listar_microfones, listar_saidas
from .codificador import HARDWARE, NOMES, codificador_funciona
from .gravador import Gravador
from .tela import Monitor, area_de_trabalho_virtual, listar_monitores

FPS_OPCOES = (15, 24, 30, 60)
COR_GRAVANDO = "#d93025"
COR_PAUSADO = "#f9ab00"


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
    return QIcon(str(base)) if base.is_file() else _icone_bolinha(COR_GRAVANDO)


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


def descrever_area(m: Monitor) -> str:
    return f"Área escolhida: {m.largura}x{m.altura} em ({m.x}, {m.y})"


def area_para_texto(m: Monitor) -> str:
    return f"{m.x},{m.y},{m.largura},{m.altura}"


def area_de_texto(texto: str) -> Monitor | None:
    try:
        x, y, w, h = (int(v) for v in texto.split(","))
    except (ValueError, AttributeError):
        return None
    return Monitor("Área", x, y, w, h) if w >= 2 and h >= 2 else None


def _barra_nivel(dica: str) -> QProgressBar:
    b = QProgressBar()
    b.setRange(0, 100)
    b.setTextVisible(False)
    b.setMaximumHeight(8)
    b.setToolTip(dica)
    return b


class JanelaPrincipal(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{NOME} {VERSAO}")
        self.setWindowIcon(icone_app())
        self.cfg = configuracoes()
        self.gravador: Gravador | None = None
        self.ultimo_arquivo: str | None = None
        self.area: Monitor | None = None
        self._hwnd_atalhos: int | None = None

        self.cb_tela = QComboBox()
        self.bt_area = QPushButton("Escolher área…")
        self.bt_area.setToolTip("Arraste na tela para gravar só um pedaço dela")
        self.bt_area.clicked.connect(self.escolher_area)
        self.cb_audio = QComboBox()
        self.cb_microfone = QComboBox()
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

        linha_tela = QHBoxLayout()
        linha_tela.addWidget(self.cb_tela, 1)
        linha_tela.addWidget(self.bt_area)
        linha_pasta = QHBoxLayout()
        linha_pasta.addWidget(self.ed_pasta, 1)
        linha_pasta.addWidget(bt_pasta)
        linha_pasta.addWidget(bt_abrir)

        form = QFormLayout()
        form.addRow("Tela:", linha_tela)
        form.addRow("Áudio do PC:", self.cb_audio)
        form.addRow("Microfone:", self.cb_microfone)
        form.addRow("Fluidez:", self.cb_fps)
        form.addRow("Codificação:", self.cb_codificador)
        form.addRow("Salvar em:", linha_pasta)
        form.addRow("", self.ck_cursor)
        form.addRow("", self.ck_minimizar)

        self.bt_gravar = QPushButton()
        self.bt_gravar.setMinimumHeight(48)
        self.bt_gravar.clicked.connect(self.alternar)
        self.bt_pausar = QPushButton()
        self.bt_pausar.setMinimumHeight(48)
        self.bt_pausar.clicked.connect(self.alternar_pausa)
        self.lb_tempo = QLabel("00:00:00")
        self.lb_tempo.setAlignment(Qt.AlignCenter)
        fonte = self.lb_tempo.font()
        fonte.setPointSize(fonte.pointSize() * 2)
        self.lb_tempo.setFont(fonte)
        self.pb_nivel = _barra_nivel("Nível do áudio do PC que está sendo gravado")
        self.pb_nivel_mic = _barra_nivel("Nível do microfone que está sendo gravado")
        niveis = QFormLayout()
        niveis.addRow("PC", self.pb_nivel)
        niveis.addRow("Mic", self.pb_nivel_mic)

        texto_grav, _, _ = atalhos.ATALHOS[atalhos.GRAVAR_PARAR]
        texto_pausa, _, _ = atalhos.ATALHOS[atalhos.PAUSAR_CONTINUAR]
        self.lb_atalhos = QLabel(f"Atalhos: {texto_grav} grava/para  ·  {texto_pausa} pausa/continua")
        self.lb_atalhos.setAlignment(Qt.AlignCenter)
        self.lb_atalhos.setStyleSheet("color: gray;")

        botoes = QHBoxLayout()
        botoes.addWidget(self.bt_gravar, 2)
        botoes.addWidget(self.bt_pausar, 1)

        corpo = QVBoxLayout()
        corpo.addLayout(form)
        corpo.addWidget(bt_atualizar, 0, Qt.AlignRight)
        corpo.addWidget(self.lb_tempo)
        corpo.addLayout(niveis)
        corpo.addLayout(botoes)
        corpo.addWidget(self.lb_atalhos)
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
        self.acao_pausa = QAction("Pausar", self)
        self.acao_pausa.triggered.connect(self.alternar_pausa)
        menu.addAction(self.acao_bandeja)
        menu.addAction(self.acao_pausa)
        menu.addAction("Mostrar janela", self._mostrar)
        self.bandeja.setContextMenu(menu)
        self.bandeja.activated.connect(self._clique_bandeja)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.bandeja.show()

        self._carregar_dispositivos()
        self._carregar_preferencias()
        self._estado_botao()
        self._registrar_atalhos()
        self.resize(600, self.sizeHint().height())

    # --- atalhos globais --------------------------------------------------------------
    def _registrar_atalhos(self) -> None:
        if QGuiApplication.platformName() != "windows":  # offscreen (testes) não tem janela de verdade
            return
        self._hwnd_atalhos = int(self.winId())
        falhas = atalhos.registrar(self._hwnd_atalhos)
        if falhas:
            self.lb_atalhos.setText(self.lb_atalhos.text() + f"\n(em uso por outro programa: {', '.join(falhas)})")

    def nativeEvent(self, tipo, mensagem):
        if bytes(tipo) == b"windows_generic_MSG":  # tipo chega como QByteArray
            ident = atalhos.id_do_atalho(int(mensagem))
            if ident is not None:
                QTimer.singleShot(0, lambda: self.tratar_atalho(ident))
                return True, 0
        return super().nativeEvent(tipo, mensagem)

    def tratar_atalho(self, ident: int) -> None:
        if ident == atalhos.GRAVAR_PARAR:
            self.alternar()
        elif ident == atalhos.PAUSAR_CONTINUAR:
            self.alternar_pausa()

    # --- dispositivos e preferências --------------------------------------------------
    def _carregar_dispositivos(self) -> None:
        tela_atual = self.cb_tela.currentText()
        audio_atual = self.cb_audio.currentText()
        mic_atual = self.cb_microfone.currentText()
        self.cb_tela.clear()
        monitores = listar_monitores()
        for m in monitores:
            self.cb_tela.addItem(m.descricao, m)
        if len(monitores) > 1:
            v = area_de_trabalho_virtual()
            self.cb_tela.addItem(f"{v.nome}: {v.largura}x{v.altura}", v)
        if self.area is not None:
            self.cb_tela.addItem(descrever_area(self.area), self.area)
        self.cb_audio.clear()
        self.cb_microfone.clear()
        try:
            saidas = listar_saidas()
            mics = listar_microfones()
        except Exception as e:  # sem serviço de áudio, por exemplo
            saidas, mics = [], []
            self.statusBar().showMessage(f"Não deu para listar o áudio: {e}")
        for s in saidas:
            self.cb_audio.addItem(s.descricao, s)
        self.cb_audio.addItem("Sem áudio", None)
        self.cb_microfone.addItem("Sem microfone", None)
        for m in mics:
            self.cb_microfone.addItem(m.descricao, m)
        if self.cb_codificador.count() == 0:
            self.cb_codificador.addItem("Automático (placa de vídeo, se houver)", "auto")
            self.cb_codificador.addItem(NOMES["libx264"], "cpu")
            for nome in HARDWARE:
                if codificador_funciona(nome):
                    self.cb_codificador.addItem(NOMES[nome], nome)
        self._selecionar(self.cb_tela, tela_atual)
        self._selecionar(self.cb_audio, audio_atual)
        self._selecionar(self.cb_microfone, mic_atual)

    def _selecionar(self, combo: QComboBox, texto: str | None) -> None:
        if texto:
            i = combo.findText(texto)
            if i >= 0:
                combo.setCurrentIndex(i)

    def _carregar_preferencias(self) -> None:
        area = area_de_texto(self.cfg.value("area", "", str))
        if area is not None:
            self._definir_area(area, selecionar=False)
        self._selecionar(self.cb_tela, self.cfg.value("tela", "", str))
        self._selecionar(self.cb_audio, self.cfg.value("audio", "", str))
        self._selecionar(self.cb_microfone, self.cfg.value("microfone", "", str))
        i = self.cb_fps.findData(int(self.cfg.value("fps", 30)))
        self.cb_fps.setCurrentIndex(i if i >= 0 else FPS_OPCOES.index(30))
        i = self.cb_codificador.findData(self.cfg.value("codificador", "auto", str))
        self.cb_codificador.setCurrentIndex(max(i, 0))
        self.ck_cursor.setChecked(self.cfg.value("cursor", True, bool))
        self.ck_minimizar.setChecked(self.cfg.value("minimizar", True, bool))
        self.ed_pasta.setText(self.cfg.value("pasta", pasta_padrao(), str))

    def _salvar_preferencias(self) -> None:
        self.cfg.setValue("tela", self.cb_tela.currentText())
        self.cfg.setValue("area", area_para_texto(self.area) if self.area else "")
        self.cfg.setValue("audio", self.cb_audio.currentText())
        self.cfg.setValue("microfone", self.cb_microfone.currentText())
        self.cfg.setValue("fps", self.cb_fps.currentData())
        self.cfg.setValue("codificador", self.cb_codificador.currentData())
        self.cfg.setValue("cursor", self.ck_cursor.isChecked())
        self.cfg.setValue("minimizar", self.ck_minimizar.isChecked())
        self.cfg.setValue("pasta", self.ed_pasta.text())
        self.cfg.sync()

    def _definir_area(self, area: Monitor, selecionar: bool = True) -> None:
        """Troca o item 'Área escolhida' do combo de tela (há no máximo um)."""
        for i in range(self.cb_tela.count()):
            if self.cb_tela.itemText(i).startswith("Área escolhida"):
                self.cb_tela.removeItem(i)
                break
        self.area = area
        self.cb_tela.addItem(descrever_area(area), area)
        if selecionar:
            self.cb_tela.setCurrentIndex(self.cb_tela.count() - 1)

    def escolher_area(self) -> None:
        from .selecao import selecionar_area
        self.hide()  # a janela não pode ficar na frente da área
        try:
            area = selecionar_area()
        finally:
            self._mostrar()
        if area is not None:
            self._definir_area(area)
            self._salvar_preferencias()

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

    @property
    def gravando(self) -> bool:
        return bool(self.gravador and self.gravador.gravando)

    def alternar(self) -> None:
        if self.gravando:
            self.parar()
        else:
            self.iniciar()

    def alternar_pausa(self) -> None:
        if not self.gravando:
            return
        self.gravador.alternar_pausa()
        self._estado_botao()
        self._atualizar()

    def iniciar(self) -> None:
        monitor = self.cb_tela.currentData()
        if monitor is None:
            QMessageBox.warning(self, NOME, "Nenhuma tela encontrada.")
            return
        self._salvar_preferencias()
        try:
            caminho = self.novo_caminho()
            self.gravador = Gravador(caminho, monitor, self.cb_fps.currentData(), self.cb_audio.currentData(),
                                     self.cb_codificador.currentData(), self.ck_cursor.isChecked(),
                                     microfone=self.cb_microfone.currentData())
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
        self.pb_nivel_mic.setValue(0)
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
        tempo = formatar_tempo(g.segundos)
        self.lb_tempo.setText(f"{tempo}  (pausado)" if g.pausado else tempo)
        niveis = g.niveis_audio
        self.pb_nivel.setValue(int(min(niveis.get("pc", 0.0), 1.0) * 100))
        self.pb_nivel_mic.setValue(int(min(niveis.get("microfone", 0.0), 1.0) * 100))
        estado = "pausado" if g.pausado else "gravando"
        self.bandeja.setToolTip(f"{NOME}: {estado} {tempo} (clique para parar)")

    def _estado_botao(self) -> None:
        gravando = self.gravando
        pausado = gravando and self.gravador.pausado
        self.bt_gravar.setText("■  Parar" if gravando else "●  Gravar")
        self.bt_gravar.setStyleSheet(
            "QPushButton{font-size:16px;font-weight:bold;" + (f"color:{COR_GRAVANDO};}}" if gravando else "}"))
        self.bt_pausar.setText("▶  Continuar" if pausado else "❚❚  Pausar")
        self.bt_pausar.setEnabled(gravando)
        self.acao_bandeja.setText("Parar" if gravando else "Gravar")
        self.acao_pausa.setText("Continuar" if pausado else "Pausar")
        self.acao_pausa.setEnabled(gravando)
        cor = COR_PAUSADO if pausado else COR_GRAVANDO
        self.bandeja.setIcon(_icone_bolinha(cor) if gravando else icone_app())
        if not gravando:
            self.bandeja.setToolTip(NOME)
        for w in (self.cb_tela, self.bt_area, self.cb_audio, self.cb_microfone, self.cb_fps, self.cb_codificador,
                  self.ck_cursor, self.ed_pasta):
            w.setEnabled(not gravando)
        if not gravando:
            self.lb_tempo.setText("00:00:00")

    def _clique_bandeja(self, motivo) -> None:
        if motivo != QSystemTrayIcon.Trigger:
            return
        if self.gravando:
            self.parar()
        else:
            self._mostrar()

    def _mostrar(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, evento) -> None:
        if self.gravando:
            r = QMessageBox.question(self, NOME, "Está gravando. Parar e salvar antes de sair?")
            if r != QMessageBox.Yes:
                evento.ignore()
                return
            self.parar()
        self._salvar_preferencias()
        if self._hwnd_atalhos is not None:
            atalhos.liberar(self._hwnd_atalhos)
            self._hwnd_atalhos = None
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
