# Gravatela

Grava a tela do Windows junto com o áudio que sai do PC (o que toca nos alto-falantes ou no fone) e salva em `.mp4` (H.264 + AAC).

- Escolha a tela (ou todas juntas) e o dispositivo de saída de áudio.
- O cursor do mouse aparece no vídeo (dá para desligar).
- Usa a placa de vídeo para codificar quando há uma (NVIDIA NVENC, Intel Quick Sync ou AMD AMF). Sem placa, usa a CPU (x264).
- Ao começar a gravar, a janela minimiza. Um ícone na bandeja mostra o tempo de gravação, e clicar nele para a gravação.
- As gravações vão para `Vídeos\Gravatela`, com nome `Gravatela_AAAA-MM-DD_HH-MM-SS.mp4`.

Só Windows 10/11 (64 bits).

## Uso

Baixe o `Gravatela.exe` na página de [Releases](../../releases) e abra. Não precisa instalar nada.

Linha de comando (mesmo executável ou `python app.py`):

```
Gravatela.exe --listar                   telas, saídas de áudio e codificadores
Gravatela.exe --gravar 30                grava 30 s da tela principal com o áudio padrão
Gravatela.exe --gravar 30 --sem-audio --tela 1 --fps 60 --codificador cpu --saida C:\video.mp4
Gravatela.exe --versao
```

O `.exe` não abre console, então a linha de comando dele não imprime nada. Para ver a saída, rode `python app.py`.

## Como funciona

| Parte | Arquivo | O que faz |
|---|---|---|
| Tela | `gravatela/tela.py` | BitBlt do GDI numa DIB section (ctypes) e desenha o cursor com `DrawIconEx` |
| Áudio | `gravatela/audio.py` | Loopback do WASAPI via PyAudioWPatch, PCM 16 bits |
| Codificador | `gravatela/codificador.py` | PyAV: H.264 + AAC, sincronizados pelo relógio |
| Gravador | `gravatela/gravador.py` | Threads de captura de tela, callback de áudio e uma thread de codificação |
| Janela | `gravatela/interface.py` | PySide6, com ícone na bandeja |

**Sincronia.** Os dois fluxos levam o instante de captura (`perf_counter`). O vídeo usa `pts = instante × fps`. Um quadro que chega cedo demais é descartado. O áudio conta amostras.

**Silêncio.** O WASAPI em loopback não entrega pacote nenhum enquanto nada toca no PC. Quando o relógio passa mais de 100 ms à frente das amostras recebidas, o codificador insere silêncio. O fim do arquivo também é completado com silêncio.

**Fila.** Se a codificação não acompanha a captura, a fila segura até ~1 s de quadros. Passando disso, descarta quadros de vídeo. O áudio nunca é descartado.

## Desenvolvimento

```
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe app.py
.venv\Scripts\python.exe tests\rodar_todos.py
build.bat
```

- **Testes.** Os testes gravam a tela de verdade por alguns segundos, mas não tocam som. As preferências vão para um `.ini` temporário (`GRAVATELA_CONFIG`), nunca para o registro do usuário.
- **Build.** O `build.bat` roda a suíte, gera `dist\Gravatela.exe` e executa `Gravatela.exe --autoverificacao`. Essa autoverificação grava 2 s num arquivo temporário e confere a duração do vídeo e do áudio. O log fica em `%TEMP%\gravatela_autoverificacao.log`.
- **Versão.** A versão fica em três lugares: `gravatela/__init__.py`, `versao.txt` e `Gravatela.manifest`. Um teste confere se os três batem.

## Licença

MIT. O executável inclui o FFmpeg (via PyAV), que é LGPL/GPL, e o x264, que é GPL.
