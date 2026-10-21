/*
 * Mistura do áudio do PC (faixa do getDisplayMedia) com o microfone num MediaStream só,
 * pelo WebAudio. Nada vai para os alto-falantes (sem eco): as fontes só chegam ao destino
 * de gravação e aos analisadores dos medidores de nível.
 */

import { pico } from "./formato.ts";

export type NomeFonte = "pc" | "microfone";

export class Mixer {
  readonly contexto: AudioContext;
  private destino: MediaStreamAudioDestinationNode;
  private analisadores = new Map<NomeFonte, AnalyserNode>();
  private buffer = new Float32Array(2048);

  constructor() {
    this.contexto = new AudioContext({ sampleRate: 48000 });
    this.destino = this.contexto.createMediaStreamDestination();
  }

  adicionar(nome: NomeFonte, faixa: MediaStreamTrack): void {
    const fonte = this.contexto.createMediaStreamSource(new MediaStream([faixa]));
    const analisador = this.contexto.createAnalyser();
    analisador.fftSize = 2048;
    fonte.connect(this.destino);
    fonte.connect(analisador);
    this.analisadores.set(nome, analisador);
  }

  get faixa(): MediaStreamTrack {
    return this.destino.stream.getAudioTracks()[0];
  }

  get fontes(): NomeFonte[] {
    return [...this.analisadores.keys()];
  }

  nivel(nome: NomeFonte): number {
    const a = this.analisadores.get(nome);
    if (!a) return 0;
    a.getFloatTimeDomainData(this.buffer);
    return pico(this.buffer);
  }

  async retomar(): Promise<void> {
    if (this.contexto.state === "suspended") await this.contexto.resume();
  }

  async fechar(): Promise<void> {
    if (this.contexto.state !== "closed") await this.contexto.close();
  }
}
