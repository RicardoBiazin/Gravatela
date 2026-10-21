/*
 * Gravar só uma área: seleção arrastando sobre a prévia e recorte da faixa de vídeo.
 *
 * No Chrome/Edge o recorte usa MediaStreamTrackProcessor/Generator: cada VideoFrame vira
 * outro com `visibleRect` (sem copiar pixels) e o ritmo é o da própria captura, então
 * continua funcionando com a aba em segundo plano. Sem essa API (Firefox), cai para um
 * <canvas> com setInterval, que o navegador desacelera quando a aba fica escondida.
 */

import { type Retangulo, previaParaVideo, retanguloDosCantos } from "./formato.ts";

export interface Recorte {
  faixa: MediaStreamTrack;
  parar(): void;
  /** true quando usa o canvas (a aba precisa ficar visível). */
  limitado: boolean;
}

declare const MediaStreamTrackProcessor: {
  new (opcoes: { track: MediaStreamTrack }): { readable: ReadableStream<VideoFrame> };
} | undefined;
declare const MediaStreamTrackGenerator: {
  new (opcoes: { kind: "video" }): MediaStreamTrack & { writable: WritableStream<VideoFrame> };
} | undefined;

export function recortar(origem: MediaStreamTrack, area: Retangulo, fps: number): Recorte {
  if (typeof MediaStreamTrackProcessor !== "undefined" && typeof MediaStreamTrackGenerator !== "undefined") {
    const processador = new MediaStreamTrackProcessor({ track: origem });
    const gerador = new MediaStreamTrackGenerator({ kind: "video" });
    const cortador = new TransformStream<VideoFrame, VideoFrame>({
      transform(quadro, saida) {
        try {
          const largura = Math.min(area.largura, quadro.codedWidth - area.x);
          const altura = Math.min(area.altura, quadro.codedHeight - area.y);
          if (largura >= 2 && altura >= 2) {
            saida.enqueue(new VideoFrame(quadro, {
              visibleRect: { x: area.x, y: area.y, width: largura - (largura % 2), height: altura - (altura % 2) },
            }));
          }
        } finally {
          quadro.close();
        }
      },
    });
    const controle = new AbortController();
    processador.readable.pipeThrough(cortador).pipeTo(gerador.writable, { signal: controle.signal })
      .catch(() => undefined);
    return { faixa: gerador, limitado: false, parar: () => { controle.abort(); gerador.stop(); } };
  }

  const video = document.createElement("video");
  video.muted = true;
  video.srcObject = new MediaStream([origem]);
  void video.play();
  const tela = document.createElement("canvas");
  tela.width = area.largura;
  tela.height = area.altura;
  const ctx = tela.getContext("2d")!;
  const relogio = setInterval(() => {
    if (video.readyState >= 2) {
      ctx.drawImage(video, area.x, area.y, area.largura, area.altura, 0, 0, area.largura, area.altura);
    }
  }, 1000 / fps);
  const faixa = tela.captureStream(fps).getVideoTracks()[0];
  return {
    faixa,
    limitado: true,
    parar: () => {
      clearInterval(relogio);
      faixa.stop();
      video.srcObject = null;
    },
  };
}

/**
 * Camada de seleção por cima do <video> da prévia. Devolve a área em pixels do vídeo,
 * ou null se o usuário apertar Esc. O retângulo desenhado fica visível até escolher de novo.
 */
export function selecionarNaPrevia(previa: HTMLVideoElement, camada: HTMLElement, caixa: HTMLElement,
  aoMudar: (area: Retangulo | null) => void): () => void {
  let inicio: { x: number; y: number } | null = null;

  const local = (e: PointerEvent) => {
    const r = camada.getBoundingClientRect();
    return { x: Math.max(0, Math.min(r.width, e.clientX - r.left)), y: Math.max(0, Math.min(r.height, e.clientY - r.top)) };
  };
  const desenhar = (sel: Retangulo | null) => {
    caixa.hidden = !sel;
    if (sel) {
      caixa.style.left = `${sel.x}px`;
      caixa.style.top = `${sel.y}px`;
      caixa.style.width = `${sel.largura}px`;
      caixa.style.height = `${sel.altura}px`;
    }
  };
  const converter = (sel: Retangulo) => {
    const r = camada.getBoundingClientRect();
    return previaParaVideo(sel, { largura: r.width, altura: r.height },
      { largura: previa.videoWidth, altura: previa.videoHeight });
  };

  const aoApertar = (e: PointerEvent) => {
    inicio = local(e);
    camada.setPointerCapture(e.pointerId);
    desenhar(null);
  };
  const aoMover = (e: PointerEvent) => {
    if (!inicio) return;
    const p = local(e);
    const sel = retanguloDosCantos(inicio.x, inicio.y, p.x, p.y);
    desenhar(sel);
    const area = converter(sel);
    caixa.dataset.tamanho = area ? `${area.largura} x ${area.altura}` : "";
  };
  const aoSoltar = (e: PointerEvent) => {
    if (!inicio) return;
    const p = local(e);
    const sel = retanguloDosCantos(inicio.x, inicio.y, p.x, p.y);
    inicio = null;
    const area = converter(sel);
    if (!area) desenhar(null);
    aoMudar(area);
  };
  const aoTeclar = (e: KeyboardEvent) => {
    if (e.key === "Escape") {
      inicio = null;
      desenhar(null);
      aoMudar(null);
    }
  };
  camada.addEventListener("pointerdown", aoApertar);
  camada.addEventListener("pointermove", aoMover);
  camada.addEventListener("pointerup", aoSoltar);
  document.addEventListener("keydown", aoTeclar);
  return () => {
    camada.removeEventListener("pointerdown", aoApertar);
    camada.removeEventListener("pointermove", aoMover);
    camada.removeEventListener("pointerup", aoSoltar);
    document.removeEventListener("keydown", aoTeclar);
    desenhar(null);
  };
}
