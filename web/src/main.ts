import "./estilo.css";
import { type Recorte, recortar, selecionarNaPrevia } from "./area.ts";
import { type Retangulo, acaoDoAtalho, formatarTamanho, formatarTempo, nomeArquivo } from "./formato.ts";
import { Gravador, bitsDeVideo } from "./gravador.ts";
import { Mixer } from "./mixer.ts";

declare const __VERSAO__: string;

const $ = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;
const ck = (id: string) => $<HTMLInputElement>(id);

type Fase = "pronto" | "area" | "gravando" | "ocupado";

let fase: Fase = "pronto";
let tela: MediaStream | null = null;
let microfone: MediaStream | null = null;
let mixer: Mixer | null = null;
let recorte: Recorte | null = null;
let gravador: Gravador | null = null;
let area: Retangulo | null = null;
let pararSelecao: (() => void) | null = null;
let urlResultado: string | null = null;
let relogio: ReturnType<typeof setInterval> | undefined;
let inicioGravacao = new Date();

$("versao").textContent = __VERSAO__;

// --- opções lembradas neste navegador ------------------------------------------------
const OPCOES = ["ck-audio-pc", "ck-microfone", "ck-cursor", "ck-area"];
function carregarOpcoes(): void {
  try {
    const salvas = JSON.parse(localStorage.getItem("gt_opcoes") ?? "{}") as Record<string, boolean | string>;
    for (const id of OPCOES) if (typeof salvas[id] === "boolean") ck(id).checked = salvas[id] as boolean;
    if (typeof salvas.fps === "string") $<HTMLSelectElement>("cb-fps").value = salvas.fps;
  } catch { /* sem armazenamento: fica o padrão */ }
}
function salvarOpcoes(): void {
  try {
    const dados: Record<string, boolean | string> = { fps: $<HTMLSelectElement>("cb-fps").value };
    for (const id of OPCOES) dados[id] = ck(id).checked;
    localStorage.setItem("gt_opcoes", JSON.stringify(dados));
  } catch { /* idem */ }
}

// --- avisos de compatibilidade --------------------------------------------------------
function avisar(texto: string): void {
  const a = $("aviso");
  a.textContent = texto;
  a.hidden = !texto;
}
const ehFirefox = /firefox/i.test(navigator.userAgent);
const temCaptura = !!navigator.mediaDevices?.getDisplayMedia;
if (!temCaptura) {
  avisar("Este navegador não permite gravar a tela (a maioria dos celulares não permite). Use o Chrome ou o Edge no computador.");
} else if (ehFirefox) {
  avisar("No Firefox o áudio do PC não é gravado: só a tela e o microfone. Para gravar o áudio do PC, use o Chrome ou o Edge.");
}

function estado(texto: string): void {
  $("estado").textContent = texto;
}

// --- interface ------------------------------------------------------------------------
function mostrarFase(nova: Fase): void {
  fase = nova;
  const gravando = nova === "gravando";
  const pausado = gravando && !!gravador?.pausado;
  $<HTMLButtonElement>("bt-gravar").innerHTML = gravando ? "■&nbsp; Parar" : "●&nbsp; Gravar";
  $<HTMLButtonElement>("bt-gravar").disabled = !temCaptura || nova === "ocupado" || nova === "area";
  $<HTMLButtonElement>("bt-pausar").disabled = !gravando;
  $<HTMLButtonElement>("bt-pausar").innerHTML = pausado ? "▶&nbsp; Continuar" : "❚❚&nbsp; Pausar";
  for (const id of [...OPCOES, "cb-fps"]) $<HTMLInputElement>(id).disabled = nova !== "pronto";
  $("painel-previa").hidden = nova === "pronto" || nova === "ocupado";
  $("dica-area").hidden = nova !== "area";
  $("acoes-area").hidden = nova !== "area";
  $("camada").classList.toggle("inativa", nova !== "area");
  $("titulo-previa").textContent = nova === "area" ? "Escolha a área" : "Gravando";
  $("niveis").hidden = !gravando || !mixer;
  const tempo = $("tempo");
  tempo.classList.toggle("gravando", gravando && !pausado);
  tempo.classList.toggle("pausado", pausado);
  if (!gravando) {
    tempo.textContent = "00:00:00";
    document.title = "Gravatela";
  }
}

function atualizar(): void {
  if (!gravador) return;
  const tempo = formatarTempo(gravador.cronometro.segundos);
  $("tempo").textContent = gravador.pausado ? `${tempo} (pausado)` : tempo;
  document.title = `${gravador.pausado ? "❚❚" : "●"} ${tempo} · Gravatela`;
  if (mixer) {
    for (const nome of ["pc", "microfone"] as const) {
      const medidor = $<HTMLMeterElement>(`nivel-${nome}`);
      medidor.parentElement!.hidden = !mixer.fontes.includes(nome);
      medidor.value = mixer.nivel(nome);
    }
  }
}

function limparResultado(): void {
  if (urlResultado) URL.revokeObjectURL(urlResultado);
  urlResultado = null;
  $<HTMLVideoElement>("resultado").removeAttribute("src");
  $("painel-resultado").hidden = true;
}

/** Para todas as faixas e devolve a página ao estado inicial (menos o resultado). */
function liberar(): void {
  pararSelecao?.();
  pararSelecao = null;
  recorte?.parar();
  recorte = null;
  for (const f of [...(tela?.getTracks() ?? []), ...(microfone?.getTracks() ?? [])]) f.stop();
  tela = microfone = null;
  void mixer?.fechar();
  mixer = null;
  area = null;
  clearInterval(relogio);
  const previa = $<HTMLVideoElement>("previa");
  previa.srcObject = null;
}

// --- gravação -------------------------------------------------------------------------
async function escolherTela(): Promise<void> {
  limparResultado();
  salvarOpcoes();
  mostrarFase("ocupado");
  estado("");
  const fps = Number($<HTMLSelectElement>("cb-fps").value);
  const comAudioPc = ck("ck-audio-pc").checked;
  try {
    tela = await navigator.mediaDevices.getDisplayMedia({
      video: { frameRate: { ideal: fps, max: fps }, cursor: ck("ck-cursor").checked ? "always" : "never" },
      audio: comAudioPc ? { echoCancellation: false, noiseSuppression: false, autoGainControl: false } : false,
      systemAudio: comAudioPc ? "include" : "exclude",
      selfBrowserSurface: "exclude",
      surfaceSwitching: "include",
      monitorTypeSurfaces: "include",
    } as DisplayMediaStreamOptions);
  } catch (e) {
    mostrarFase("pronto");
    const nome = (e as DOMException).name;
    estado(nome === "NotAllowedError" ? "Gravação cancelada." : `Não foi possível capturar a tela: ${(e as Error).message}`);
    return;
  }
  if (ck("ck-microfone").checked) {
    try {
      microfone = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
    } catch (e) {
      estado(`Microfone indisponível (${(e as DOMException).name}); gravando sem ele.`);
    }
  }
  if (comAudioPc && tela.getAudioTracks().length === 0) {
    estado("O navegador não entregou o áudio do PC. Para gravar o som, escolha Tela inteira ou uma aba e marque " +
      "“Compartilhar áudio do sistema”.");
  }
  // O usuário pode parar pelo botão do próprio navegador ("Parar compartilhamento").
  tela.getVideoTracks()[0].addEventListener("ended", () => {
    if (gravador) void parar();
    else if (fase === "area") cancelar();
  });
  const previa = $<HTMLVideoElement>("previa");
  previa.srcObject = tela;
  await previa.play().catch(() => undefined);

  if (ck("ck-area").checked) {
    mostrarFase("area");
    $<HTMLButtonElement>("bt-comecar").disabled = true;
    $("tamanho-area").textContent = "";
    pararSelecao = selecionarNaPrevia(previa, $("camada"), $("caixa"), (a) => {
      area = a;
      $<HTMLButtonElement>("bt-comecar").disabled = !a;
      $("tamanho-area").textContent = a ? `Área: ${a.largura} x ${a.altura} pixels` : "";
    });
    return;
  }
  await gravar(null);
}

async function gravar(regiao: Retangulo | null): Promise<void> {
  if (!tela) return;
  mostrarFase("ocupado");
  const fps = Number($<HTMLSelectElement>("cb-fps").value);
  const origem = tela.getVideoTracks()[0];
  let faixaVideo = origem;
  if (regiao) {
    // Larga a camada de seleção (fica só o retângulo desenhado) e recorta a faixa.
    pararSelecao?.();
    pararSelecao = null;
    recorte = recortar(origem, regiao, fps);
    faixaVideo = recorte.faixa;
    if (recorte.limitado) estado("Neste navegador, mantenha esta aba visível enquanto grava uma área.");
  }
  const faixas: MediaStreamTrack[] = [faixaVideo];
  const audioPc = tela.getAudioTracks()[0];
  const audioMic = microfone?.getAudioTracks()[0];
  if (audioPc || audioMic) {
    mixer = new Mixer();
    if (audioPc) mixer.adicionar("pc", audioPc);
    if (audioMic) mixer.adicionar("microfone", audioMic);
    await mixer.retomar();
    faixas.push(mixer.faixa);
  }
  const cfg = origem.getSettings();
  const largura = regiao?.largura ?? cfg.width ?? 1920;
  const altura = regiao?.altura ?? cfg.height ?? 1080;
  try {
    gravador = new Gravador(new MediaStream(faixas), bitsDeVideo(largura, altura, fps));
    gravador.iniciar();
  } catch (e) {
    gravador = null;
    liberar();
    mostrarFase("pronto");
    estado(`Não foi possível começar a gravar: ${(e as Error).message}`);
    return;
  }
  inicioGravacao = new Date();
  relogio = setInterval(atualizar, 200);
  mostrarFase("gravando");
  atualizar();
}

async function parar(): Promise<void> {
  if (!gravador) return;
  const g = gravador;
  gravador = null;
  mostrarFase("ocupado");
  let arquivo: Blob;
  try {
    arquivo = await g.parar();
  } catch (e) {
    liberar();
    mostrarFase("pronto");
    estado(`A gravação parou com erro: ${(e as Error).message}`);
    return;
  }
  liberar();
  const nome = nomeArquivo(inicioGravacao, g.extensao);
  urlResultado = URL.createObjectURL(arquivo);
  $<HTMLVideoElement>("resultado").src = urlResultado;
  const link = $<HTMLAnchorElement>("lk-baixar");
  link.href = urlResultado;
  link.download = nome;
  $("info-resultado").textContent =
    `${nome} · ${formatarTempo(g.cronometro.segundos)} · ${formatarTamanho(arquivo.size)}`;
  $("painel-resultado").hidden = false;
  mostrarFase("pronto");
  estado("Gravação salva na pasta de downloads.");
  link.click();
}

function cancelar(): void {
  liberar();
  mostrarFase("pronto");
  estado("");
}

function alternarGravacao(): void {
  if (fase === "gravando") void parar();
  else if (fase === "area") {
    if (area) void gravar(area);
  } else if (fase === "pronto" && temCaptura) void escolherTela();
}

function alternarPausa(): void {
  if (fase !== "gravando" || !gravador) return;
  if (gravador.pausado) gravador.continuar();
  else gravador.pausar();
  mostrarFase("gravando");
  atualizar();
}

$("bt-gravar").addEventListener("click", alternarGravacao);
$("bt-pausar").addEventListener("click", alternarPausa);
$("bt-comecar").addEventListener("click", () => area && void gravar(area));
$("bt-cancelar").addEventListener("click", cancelar);
for (const id of [...OPCOES, "cb-fps"]) $(id).addEventListener("change", salvarOpcoes);
document.addEventListener("keydown", (e) => {
  const acao = acaoDoAtalho(e);
  if (!acao) return;
  e.preventDefault();
  if (acao === "gravar") alternarGravacao();
  else alternarPausa();
});
window.addEventListener("beforeunload", (e) => {
  if (gravador) e.preventDefault();  // pergunta antes de fechar a aba no meio da gravação
});

carregarOpcoes();
mostrarFase("pronto");
