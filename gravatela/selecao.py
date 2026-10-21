"""Escolha de uma área da tela arrastando o mouse.

Uma camada escura e sem borda cobre cada monitor. Arrastar desenha o retângulo,
soltar confirma e Esc (ou botão direito) cancela. As coordenadas do Qt são
lógicas (divididas pela escala do Windows); a conversão para pixels físicos usa a
origem física do monitor (GDI) mais a posição local vezes o devicePixelRatio.
"""

from PySide6.QtCore import QEventLoop, QPoint, QRect, Qt
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen, QScreen
from PySide6.QtWidgets import QWidget

from .tela import Monitor, listar_monitores

TAMANHO_MINIMO = 16  # px físicos; arrasto menor que isso é tratado como clique


def para_fisico(local: QRect, origem: tuple[int, int], escala: float, limite: Monitor | None = None) -> Monitor:
    """Retângulo em coordenadas lógicas locais da tela -> Monitor em pixels físicos da área de trabalho."""
    x = origem[0] + round(local.x() * escala)
    y = origem[1] + round(local.y() * escala)
    largura = round(local.width() * escala)
    altura = round(local.height() * escala)
    if limite is not None:  # não deixa passar da borda do monitor
        x2 = min(x + largura, limite.x + limite.largura)
        y2 = min(y + altura, limite.y + limite.altura)
        x, y = max(x, limite.x), max(y, limite.y)
        largura, altura = x2 - x, y2 - y
    return Monitor("Área", x, y, largura, altura)


def monitor_da_tela(tela: QScreen, monitores: list[Monitor]) -> Monitor | None:
    """O Monitor (GDI) que corresponde ao QScreen. No Windows o name() do Qt é '\\\\.\\DISPLAY1'."""
    nome = tela.name().replace("\\\\.\\", "")
    for m in monitores:
        if m.nome == nome:
            return m
    return None


class CamadaSelecao(QWidget):
    def __init__(self, tela: QScreen, ao_terminar):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setCursor(Qt.CrossCursor)
        self.setMouseTracking(True)
        self.tela = tela
        self.setGeometry(tela.geometry())
        self._ao_terminar = ao_terminar
        self._inicio: QPoint | None = None
        self._fim: QPoint | None = None

    def retangulo(self) -> QRect | None:
        if self._inicio is None or self._fim is None:
            return None
        a, b = self._inicio, self._fim  # QRect(p1, p2).normalized() erra 1 px quando p2 < p1
        return QRect(min(a.x(), b.x()), min(a.y(), b.y()), abs(a.x() - b.x()), abs(a.y() - b.y()))

    def paintEvent(self, _evento):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0, 110))
        r = self.retangulo()
        if r is None:
            p.setPen(QColor("white"))
            p.drawText(self.rect(), Qt.AlignCenter, "Arraste para escolher a área  ·  Esc cancela")
            return
        p.setCompositionMode(QPainter.CompositionMode_Clear)
        p.fillRect(r, Qt.transparent)
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        p.setPen(QPen(QColor("#ea4335"), 2))
        p.drawRect(r.adjusted(-1, -1, 0, 0))
        escala = self.tela.devicePixelRatio()
        texto = f"{round(r.width() * escala)} x {round(r.height() * escala)}"
        p.setPen(QColor("white"))
        p.drawText(r.left(), max(r.top() - 6, 14), texto)

    def mousePressEvent(self, e):
        if e.button() == Qt.RightButton:
            self._ao_terminar(self, None)
            return
        self._inicio = self._fim = e.position().toPoint()
        self.update()

    def mouseMoveEvent(self, e):
        if self._inicio is not None:
            self._fim = e.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton or self._inicio is None:
            return
        self._fim = e.position().toPoint()
        r = self.retangulo()
        escala = self.tela.devicePixelRatio()
        if r.width() * escala < TAMANHO_MINIMO or r.height() * escala < TAMANHO_MINIMO:
            self._inicio = self._fim = None
            self.update()
            return
        self._ao_terminar(self, r)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self._ao_terminar(self, None)


def selecionar_area() -> Monitor | None:
    """Mostra as camadas e espera o usuário arrastar. None se cancelar."""
    monitores = listar_monitores()
    laco = QEventLoop()
    resultado: list[Monitor | None] = []

    def terminar(camada: CamadaSelecao, r: QRect | None):
        if resultado:
            return
        if r is None:
            resultado.append(None)
        else:
            m = monitor_da_tela(camada.tela, monitores)
            escala = camada.tela.devicePixelRatio()
            if m is not None:
                resultado.append(para_fisico(r, (m.x, m.y), escala, m))
            else:
                g = camada.tela.geometry()
                resultado.append(para_fisico(r, (round(g.x() * escala), round(g.y() * escala)), escala))
        laco.quit()

    camadas = [CamadaSelecao(t, terminar) for t in QGuiApplication.screens()]
    for c in camadas:
        c.show()
    camadas[0].activateWindow()
    camadas[0].setFocus()
    laco.exec()
    for c in camadas:
        c.close()
    return resultado[0] if resultado else None
