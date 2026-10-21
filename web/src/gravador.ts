/* MediaRecorder com pausa, pedaços de 1 s e o arquivo final num Blob. */

import { Cronometro, escolherFormato } from "./formato.ts";

export class Gravador {
  readonly mime: string;
  readonly extensao: string;
  readonly cronometro = new Cronometro();
  private gravador: MediaRecorder;
  private pedacos: Blob[] = [];
  private terminou: Promise<Blob>;
  bytes = 0;

  constructor(fluxo: MediaStream, bitsVideo: number) {
    const formato = escolherFormato((m) => MediaRecorder.isTypeSupported(m));
    if (!formato) throw new Error("Este navegador não grava vídeo (MediaRecorder sem MP4 nem WebM).");
    this.mime = formato.mime;
    this.extensao = formato.extensao;
    this.gravador = new MediaRecorder(fluxo, {
      mimeType: formato.mime,
      videoBitsPerSecond: bitsVideo,
      audioBitsPerSecond: 160_000,
    });
    this.gravador.addEventListener("dataavailable", (e) => {
      if (e.data.size) {
        this.pedacos.push(e.data);
        this.bytes += e.data.size;
      }
    });
    this.terminou = new Promise((ok, falha) => {
      this.gravador.addEventListener("stop", () => ok(new Blob(this.pedacos, { type: this.mime.split(";")[0] })));
      this.gravador.addEventListener("error", (e) => falha((e as ErrorEvent).error ?? new Error("erro na gravação")));
    });
  }

  iniciar(): void {
    this.gravador.start(1000);
    this.cronometro.iniciar();
  }

  get pausado(): boolean {
    return this.gravador.state === "paused";
  }

  get ativo(): boolean {
    return this.gravador.state !== "inactive";
  }

  pausar(): void {
    if (this.gravador.state === "recording") {
      this.gravador.pause();
      this.cronometro.pausar();
    }
  }

  continuar(): void {
    if (this.gravador.state === "paused") {
      this.gravador.resume();
      this.cronometro.continuar();
    }
  }

  async parar(): Promise<Blob> {
    if (this.gravador.state !== "inactive") {
      this.cronometro.parar();
      this.gravador.stop();
    }
    return this.terminou;
  }
}

/** Bits por segundo de vídeo pela área e fluidez (~0,1 bit por pixel por quadro, entre 2 e 25 Mbit/s). */
export function bitsDeVideo(largura: number, altura: number, fps: number): number {
  return Math.round(Math.max(2e6, Math.min(25e6, largura * altura * fps * 0.1)));
}
