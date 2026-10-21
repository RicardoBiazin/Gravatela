"""Ponto de entrada do Gravatela.

    python app.py                          abre a janela
    python app.py --gravar 10              grava 10 s da tela principal com o áudio padrão
    python app.py --gravar 10 --sem-audio --saida teste.mp4 --fps 60 --codificador cpu
    python app.py --listar                 telas, saídas de áudio e codificadores
    python app.py --versao
    python app.py --autoverificacao        grava 2 s num arquivo temporário e confere (usado no build)
"""

import argparse
import os
import sys
import tempfile
import time
import traceback
from datetime import datetime
from pathlib import Path

from gravatela import NOME, VERSAO

LOG_AUTOVERIFICACAO = Path(tempfile.gettempdir()) / "gravatela_autoverificacao.log"


def _escrever(texto: str) -> None:
    # No .exe sem console, sys.stdout é None.
    if sys.stdout is not None:
        print(texto, flush=True)


def listar() -> None:
    from gravatela.audio import listar_saidas
    from gravatela.codificador import HARDWARE, NOMES, codificador_funciona
    from gravatela.tela import listar_monitores
    _escrever("Telas:")
    for i, m in enumerate(listar_monitores()):
        _escrever(f"  {i}: {m.descricao}")
    _escrever("Áudio do PC:")
    for s in listar_saidas():
        _escrever(f"  {s.indice}: {s.descricao} ({s.taxa} Hz, {s.canais} canais)")
    _escrever("Codificadores:")
    for nome in (*HARDWARE, "libx264"):
        _escrever(f"  {NOMES[nome]}: {'disponível' if codificador_funciona(nome) else 'não disponível'}")


def gravar(segundos: float, saida: str | None, tela: int, fps: int, com_audio: bool, codificador: str):
    from gravatela.audio import saida_padrao
    from gravatela.gravador import Gravador
    from gravatela.interface import pasta_padrao
    from gravatela.tela import listar_monitores
    monitores = listar_monitores()
    if not 0 <= tela < len(monitores):
        raise SystemExit(f"tela {tela} não existe (há {len(monitores)})")
    if saida is None:
        Path(pasta_padrao()).mkdir(parents=True, exist_ok=True)
        saida = str(Path(pasta_padrao()) / f"{NOME}_{datetime.now():%Y-%m-%d_%H-%M-%S}.mp4")
    g = Gravador(saida, monitores[tela], fps, saida_padrao() if com_audio else None, codificador)
    g.iniciar()
    try:
        fim = time.perf_counter() + segundos
        while time.perf_counter() < fim and not g.erro:
            time.sleep(0.05)
    finally:
        resumo = g.parar()
    if g.erro:
        raise g.erro
    return resumo


def autoverificacao() -> int:
    import av
    linhas = [f"{NOME} {VERSAO} - autoverificação {datetime.now():%Y-%m-%d %H:%M:%S}"]
    try:
        from gravatela.audio import saida_padrao
        from gravatela.tela import ativar_dpi
        ativar_dpi()
        com_audio = saida_padrao() is not None
        destino = Path(tempfile.mkdtemp(prefix="gravatela_")) / "auto.mp4"
        r = gravar(2, str(destino), 0, 30, com_audio, "auto")
        linhas.append(f"gravou {r.segundos:.2f} s, {r.quadros} quadros, {r.codificador}, áudio={r.com_audio}")
        with av.open(str(destino)) as f:
            tipos = {s.type: s for s in f.streams}
            assert "video" in tipos, "arquivo sem vídeo"
            v = tipos["video"]
            dur_v = float(v.duration * v.time_base)
            assert dur_v > 1.5, f"vídeo curto demais: {dur_v:.2f} s"
            linhas.append(f"vídeo {v.codec_context.name} {v.width}x{v.height} {dur_v:.2f} s")
            if com_audio:
                assert "audio" in tipos, "arquivo sem áudio"
                a = tipos["audio"]
                dur_a = float(a.duration * a.time_base)
                assert abs(dur_a - dur_v) < 0.3, f"áudio {dur_a:.2f} s x vídeo {dur_v:.2f} s"
                linhas.append(f"áudio {a.codec_context.name} {dur_a:.2f} s")
        destino.unlink()
        destino.parent.rmdir()
        # A janela também precisa montar (offscreen, sem aparecer).
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        os.environ["GRAVATELA_CONFIG"] = str(Path(tempfile.mkdtemp(prefix="gravatela_")) / "config.ini")
        from PySide6.QtWidgets import QApplication
        from gravatela.interface import JanelaPrincipal
        app = QApplication.instance() or QApplication([])
        j = JanelaPrincipal()
        assert j.cb_tela.count() >= 1, "nenhuma tela na lista"
        j.close()
        del app
        linhas.append("OK")
        codigo = 0
    except BaseException:
        linhas.append("FALHOU\n" + traceback.format_exc())
        codigo = 1
    LOG_AUTOVERIFICACAO.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    _escrever("\n".join(linhas))
    return codigo


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog=NOME, description="Grava a tela com o áudio do PC.")
    ap.add_argument("--versao", action="store_true")
    ap.add_argument("--listar", action="store_true", help="mostra telas, áudio e codificadores")
    ap.add_argument("--autoverificacao", action="store_true")
    ap.add_argument("--gravar", type=float, metavar="SEGUNDOS", help="grava sem abrir a janela")
    ap.add_argument("--saida", help="arquivo .mp4 (padrão: Vídeos\\Gravatela)")
    ap.add_argument("--tela", type=int, default=0, help="índice da tela (veja --listar)")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--sem-audio", action="store_true")
    ap.add_argument("--codificador", default="auto", help="auto, cpu, h264_nvenc, h264_qsv ou h264_amf")
    args = ap.parse_args(argv)

    if args.versao:
        _escrever(f"{NOME} {VERSAO}")
        return 0
    if args.autoverificacao:
        return autoverificacao()
    if args.listar or args.gravar is not None:
        from gravatela.tela import ativar_dpi
        ativar_dpi()
        if args.listar:
            listar()
            return 0
        r = gravar(args.gravar, args.saida, args.tela, args.fps, not args.sem_audio, args.codificador)
        _escrever(f"Salvo: {r.caminho} ({r.segundos:.1f} s, {r.quadros} quadros, {r.descartados} descartados, "
                  f"{r.codificador}, áudio={'sim' if r.com_audio else 'não'})")
        return 0
    from gravatela.interface import executar
    return executar()


if __name__ == "__main__":
    sys.exit(main())
