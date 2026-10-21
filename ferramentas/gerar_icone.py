"""Gera recursos/gravatela.ico e web/public/favicon.svg (um monitor com o ponto vermelho de gravar).

    .venv\\Scripts\\python.exe ferramentas\\gerar_icone.py
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPen  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]

# O mesmo desenho de desenhar(), em SVG, para o site.
SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
<rect x="2" y="2" width="60" height="60" rx="14" fill="#202631"/>
<rect x="10" y="13" width="44" height="30" rx="4" fill="none" stroke="#e8eaed" stroke-width="4"/>
<line x1="24" y1="51" x2="40" y2="51" stroke="#e8eaed" stroke-width="4"/>
<circle cx="32" cy="28" r="8" fill="#ea4335"/>
</svg>
"""


def desenhar(tam: int) -> QImage:
    img = QImage(tam, tam, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    e = tam / 64
    p.setBrush(QColor("#202631"))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(QRectF(2 * e, 2 * e, 60 * e, 60 * e), 14 * e, 14 * e)
    # tela
    p.setBrush(Qt.NoBrush)
    p.setPen(QPen(QColor("#e8eaed"), 4 * e))
    p.drawRoundedRect(QRectF(10 * e, 13 * e, 44 * e, 30 * e), 4 * e, 4 * e)
    p.drawLine(int(24 * e), int(51 * e), int(40 * e), int(51 * e))
    # ponto de gravação
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#ea4335"))
    p.drawEllipse(QRectF(24 * e, 20 * e, 16 * e, 16 * e))
    p.end()
    return img


def main() -> int:
    QGuiApplication(sys.argv)
    destino = RAIZ / "recursos" / "gravatela.ico"
    destino.parent.mkdir(exist_ok=True)
    # O plugin ICO do Qt grava só uma imagem: 256 px, que o Windows reduz bem.
    if not desenhar(256).save(str(destino), "ICO"):
        print("ERRO: o Qt não gravou o .ico (plugin imageformats/qico ausente?)")
        return 1
    publico = RAIZ / "web" / "public"
    if publico.parent.is_dir():
        publico.mkdir(exist_ok=True)
        (publico / "favicon.svg").write_text(SVG, encoding="utf-8")
        # O navegador pede /favicon.ico sozinho; sem ele, a página do portão loga um 404.
        (publico / "favicon.ico").write_bytes(destino.read_bytes())
    print(destino)
    return 0


if __name__ == "__main__":
    sys.exit(main())
