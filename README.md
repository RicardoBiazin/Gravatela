# Gravatela

Grava a tela do Windows junto com o áudio que sai do PC (o que toca nos alto-falantes ou no fone) e salva em `.mp4` (H.264 + AAC).

- Escolha a tela (ou todas juntas) e o dispositivo de saída de áudio. Para gravar só um pedaço da tela, use **Escolher área…** e arraste o mouse. Esc cancela.
- O microfone pode entrar junto: é misturado ao áudio do PC na mesma faixa. Use fone de ouvido, senão o microfone capta o som das caixas e ele sai duplicado no vídeo.
- Dá para pausar e continuar. O tempo pausado não entra no vídeo.
- Atalhos globais, que funcionam com a janela minimizada: **Ctrl+Shift+F9** grava e para, **Ctrl+Shift+F10** pausa e continua.
- O cursor do mouse aparece no vídeo (dá para desligar).
- Usa a placa de vídeo para codificar quando há uma (NVIDIA NVENC, Intel Quick Sync ou AMD AMF). Sem placa, usa a CPU (x264).
- Ao começar a gravar, a janela minimiza. Um ícone na bandeja mostra o tempo de gravação, e clicar nele para a gravação.
- As gravações vão para `Vídeos\Gravatela`, com nome `Gravatela_AAAA-MM-DD_HH-MM-SS.mp4`.

Só Windows 10/11 (64 bits). Há também uma **versão web**: https://gravatela.biazin.com.br (veja [abaixo](#versão-web)).

## Uso

Baixe o `Gravatela.exe` na página de [Releases](../../releases) e abra. Não precisa instalar nada.

Linha de comando (mesmo executável ou `python app.py`):

```
Gravatela.exe --listar                   telas, saídas de áudio, microfones e codificadores
Gravatela.exe --gravar 30                grava 30 s da tela principal com o áudio padrão
Gravatela.exe --gravar 30 --sem-audio --tela 1 --fps 60 --codificador cpu --saida C:\video.mp4
Gravatela.exe --gravar 30 --microfone --regiao 100,100,1280,720
Gravatela.exe --versao
```

O `.exe` não abre console, então a linha de comando dele não imprime nada. Para ver a saída, rode `python app.py`.

## Como funciona

| Parte | Arquivo | O que faz |
|---|---|---|
| Tela | `gravatela/tela.py` | BitBlt do GDI numa DIB section (ctypes) e desenha o cursor com `DrawIconEx` |
| Áudio | `gravatela/audio.py` | WASAPI via PyAudioWPatch: loopback (áudio do PC) e microfone, PCM 16 bits |
| Codificador | `gravatela/codificador.py` | PyAV: H.264 + AAC, com o mixer das fontes de áudio |
| Gravador | `gravatela/gravador.py` | Threads de captura de tela, callbacks de áudio e uma thread de codificação; pausa |
| Atalhos | `gravatela/atalhos.py` | `RegisterHotKey` + `WM_HOTKEY` no `nativeEvent` da janela |
| Área | `gravatela/selecao.py` | Camada escura sobre cada monitor para arrastar o retângulo |
| Janela | `gravatela/interface.py` | PySide6, com ícone na bandeja |

**Sincronia.** Vídeo e áudio levam o instante de captura (`perf_counter`). O vídeo usa `pts = instante × fps`. Um quadro que chega cedo demais é descartado.

**Mixer.** Cada fonte de áudio é convertida para 48 kHz estéreo e escrita na linha do tempo pela hora em que chegou. As fontes são somadas e limitadas a 16 bits. O mixer espera 0,5 s antes de entregar cada trecho ao AAC, para dar tempo de todas as fontes chegarem.

**Silêncio.** O WASAPI em loopback não entrega pacote nenhum enquanto nada toca no PC. Quando o relógio passa mais de 100 ms à frente do ponto em que a fonte parou, ela recomeça na posição do relógio. O trecho que nenhuma fonte cobriu sai como silêncio.

**Pausa.** O tempo pausado é descontado do relógio da gravação. Na pausa, a tela não é capturada e os pacotes de áudio são descartados.

**Área.** O Qt trabalha em coordenadas lógicas, já divididas pela escala do Windows. A área escolhida vira pixels físicos assim: a origem do monitor (GDI) mais a posição local vezes o `devicePixelRatio`.

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
- **Teste do atalho.** Um dos testes abre por 2 s uma janela de verdade. Ele confere se o atalho fica registrado no Windows, se a mensagem chega à janela e se fechar a janela libera o atalho.
- **Build.** O `build.bat` roda a suíte, gera `dist\Gravatela.exe` e executa `Gravatela.exe --autoverificacao`. Essa autoverificação grava 2 s num arquivo temporário, com 1 s de pausa no meio, e confere a duração do vídeo e do áudio. O log fica em `%TEMP%\gravatela_autoverificacao.log`.
- **Versão.** A versão fica em três lugares: `gravatela/__init__.py`, `versao.txt` e `Gravatela.manifest`. Um teste confere se os três batem.

## Versão web

https://gravatela.biazin.com.br. A pasta é `web/`: Vite + TypeScript, site estático no Netlify.

A gravação acontece inteira no navegador, com `getDisplayMedia` + `MediaRecorder`. Nenhum vídeo passa por servidor. A versão web tem quase tudo do desktop: áudio do PC, microfone mixado (WebAudio), pausa, área da tela, fluidez e cursor.

**Diferenças em relação ao desktop:**
- **Áudio do PC:**
  - No Chrome e no Edge, só vem quando você escolhe **Tela inteira** (ou uma aba) e marca **Compartilhar áudio do sistema**.
  - No Firefox e no Safari, não vem.
- **Atalhos:** Ctrl+Shift+F9 e F10 só funcionam com a aba do Gravatela em foco.
- **Formato:** MP4 (H.264/AAC) no Chrome e no Edge; WebM onde o navegador não grava MP4.
- **Área:** é recortada com `MediaStreamTrackProcessor`. No Firefox, que não tem essa API, o recorte vai por `<canvas>`, e a aba precisa ficar visível durante a gravação.
- **Memória:** a gravação fica na memória até você parar.

```
cd web
npm install
npm test               funções puras (node --test)
npm run typecheck
npm run build
npm run preview        http://localhost:4180 (mesmos cabeçalhos do netlify.toml)
npm run fumaca         Chrome headless com tela e microfone falsos: grava com pausa e uma área e confere os arquivos no ffprobe
netlify deploy --build --prod
```

## Licença

MIT. O executável inclui o FFmpeg (via PyAV), que é LGPL/GPL, e o x264, que é GPL.
