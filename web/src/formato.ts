/* Funções puras (sem DOM): testadas com `node --test`. */

export interface Retangulo {
  x: number;
  y: number;
  largura: number;
  altura: number;
}

export function formatarTempo(segundos: number): string {
  const s = Math.max(0, Math.floor(segundos));
  const dois = (n: number) => String(n).padStart(2, "0");
  return `${dois(Math.floor(s / 3600))}:${dois(Math.floor((s % 3600) / 60))}:${dois(s % 60)}`;
}

export function formatarTamanho(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1).replace(".", ",")} MB`;
  return `${(bytes / 1024 ** 3).toFixed(2).replace(".", ",")} GB`;
}

/** Gravatela_AAAA-MM-DD_HH-MM-SS.ext, igual ao desktop. */
export function nomeArquivo(data: Date, extensao: string): string {
  const d = (n: number) => String(n).padStart(2, "0");
  return `Gravatela_${data.getFullYear()}-${d(data.getMonth() + 1)}-${d(data.getDate())}_` +
    `${d(data.getHours())}-${d(data.getMinutes())}-${d(data.getSeconds())}.${extensao}`;
}

/** Em ordem de preferência: MP4 (H.264/AAC) abre em tudo; WebM fica de reserva (Firefox). */
export const FORMATOS: ReadonlyArray<{ mime: string; extensao: string }> = [
  { mime: "video/mp4;codecs=avc1.640028,mp4a.40.2", extensao: "mp4" },
  { mime: "video/mp4;codecs=avc1,mp4a", extensao: "mp4" },
  { mime: "video/mp4", extensao: "mp4" },
  { mime: "video/webm;codecs=vp9,opus", extensao: "webm" },
  { mime: "video/webm;codecs=vp8,opus", extensao: "webm" },
  { mime: "video/webm", extensao: "webm" },
];

export function escolherFormato(suporta: (mime: string) => boolean): { mime: string; extensao: string } | null {
  return FORMATOS.find((f) => suporta(f.mime)) ?? null;
}

/** Retângulo de dois cantos quaisquer (arrasto em qualquer direção). */
export function retanguloDosCantos(ax: number, ay: number, bx: number, by: number): Retangulo {
  return { x: Math.min(ax, bx), y: Math.min(ay, by), largura: Math.abs(ax - bx), altura: Math.abs(ay - by) };
}

/**
 * Seleção feita sobre a prévia (pixels CSS do elemento <video>, com object-fit: contain)
 * -> retângulo em pixels do vídeo capturado. Corta o que cair nas faixas pretas, limita
 * às bordas e arredonda para números pares (o H.264 em 4:2:0 exige).
 */
export function previaParaVideo(sel: Retangulo, elemento: { largura: number; altura: number },
  video: { largura: number; altura: number }): Retangulo | null {
  if (!elemento.largura || !elemento.altura || !video.largura || !video.altura) return null;
  const escala = Math.min(elemento.largura / video.largura, elemento.altura / video.altura);
  const margemX = (elemento.largura - video.largura * escala) / 2;
  const margemY = (elemento.altura - video.altura * escala) / 2;
  let x1 = (sel.x - margemX) / escala;
  let y1 = (sel.y - margemY) / escala;
  let x2 = (sel.x + sel.largura - margemX) / escala;
  let y2 = (sel.y + sel.altura - margemY) / escala;
  x1 = Math.max(0, Math.min(video.largura, x1));
  x2 = Math.max(0, Math.min(video.largura, x2));
  y1 = Math.max(0, Math.min(video.altura, y1));
  y2 = Math.max(0, Math.min(video.altura, y2));
  const par = (n: number) => Math.floor(n / 2) * 2;
  const x = par(x1);
  const y = par(y1);
  const largura = par(x2 - x);
  const altura = par(y2 - y);
  if (largura < 16 || altura < 16) return null;
  return { x, y, largura, altura };
}

/** Relógio da gravação que desconta as pausas (o MediaRecorder já tira a pausa do arquivo). */
export class Cronometro {
  private inicio = 0;
  private pausadoDesde: number | null = null;
  private tempoPausado = 0;
  private fim: number | null = null;
  private agora: () => number;

  constructor(agora: () => number = () => performance.now()) {
    this.agora = agora;
  }

  iniciar(): void {
    this.inicio = this.agora();
    this.pausadoDesde = null;
    this.tempoPausado = 0;
    this.fim = null;
  }

  pausar(): void {
    if (this.pausadoDesde === null && this.fim === null) this.pausadoDesde = this.agora();
  }

  continuar(): void {
    if (this.pausadoDesde !== null) {
      this.tempoPausado += this.agora() - this.pausadoDesde;
      this.pausadoDesde = null;
    }
  }

  parar(): void {
    if (this.fim === null) this.fim = this.segundos * 1000;
  }

  get pausado(): boolean {
    return this.pausadoDesde !== null;
  }

  get segundos(): number {
    if (this.fim !== null) return this.fim / 1000;
    const ate = this.pausadoDesde ?? this.agora();
    return (ate - this.inicio - this.tempoPausado) / 1000;
  }
}

/** Atalho de teclado da página -> ação. Os mesmos do desktop, mas só valem com a aba em foco. */
export function acaoDoAtalho(e: { key: string; ctrlKey: boolean; shiftKey: boolean; altKey: boolean }):
  "gravar" | "pausar" | null {
  if (!e.ctrlKey || !e.shiftKey || e.altKey) return null;
  if (e.key === "F9") return "gravar";
  if (e.key === "F10") return "pausar";
  return null;
}

/** Pico de um bloco de amostras (0 a 1), para o medidor de nível. */
export function pico(amostras: ArrayLike<number>): number {
  let max = 0;
  for (let i = 0; i < amostras.length; i++) {
    const v = Math.abs(amostras[i]);
    if (v > max) max = v;
  }
  return Math.min(1, max);
}
