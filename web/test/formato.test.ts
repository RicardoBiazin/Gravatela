import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import {
  Cronometro, FORMATOS, acaoDoAtalho, escolherFormato, formatarTamanho, formatarTempo, nomeArquivo, pico,
  previaParaVideo, retanguloDosCantos,
} from "../src/formato.ts";
import { bitsDeVideo } from "../src/gravador.ts";

test("formatarTempo", () => {
  assert.equal(formatarTempo(0), "00:00:00");
  assert.equal(formatarTempo(3725.9), "01:02:05");
  assert.equal(formatarTempo(-3), "00:00:00");
});

test("formatarTamanho", () => {
  assert.equal(formatarTamanho(500), "1 KB");
  assert.equal(formatarTamanho(5.5 * 1024 * 1024), "5,5 MB");
  assert.equal(formatarTamanho(2 * 1024 ** 3), "2,00 GB");
});

test("nomeArquivo igual ao do desktop", () => {
  assert.equal(nomeArquivo(new Date(2026, 9, 21, 9, 5, 3), "mp4"), "Gravatela_2026-10-21_09-05-03.mp4");
});

test("escolherFormato prefere MP4 e cai para WebM", () => {
  assert.equal(escolherFormato(() => true)?.extensao, "mp4");
  assert.equal(escolherFormato((m) => m.startsWith("video/webm"))?.mime, "video/webm;codecs=vp9,opus");
  assert.equal(escolherFormato(() => false), null);
  assert.ok(FORMATOS.every((f) => f.mime.startsWith(`video/${f.extensao}`)));
});

test("retanguloDosCantos em qualquer direção", () => {
  assert.deepEqual(retanguloDosCantos(300, 200, 100, 50), { x: 100, y: 50, largura: 200, altura: 150 });
});

test("previaParaVideo com faixas pretas nas laterais (vídeo mais estreito que a prévia)", () => {
  // Vídeo 1000x500 numa prévia 1200x500: escala 1, faixas de 100 px de cada lado.
  const r = previaParaVideo({ x: 50, y: 10, largura: 400, altura: 201 }, { largura: 1200, altura: 500 },
    { largura: 1000, altura: 500 });
  assert.deepEqual(r, { x: 0, y: 10, largura: 350, altura: 200 }); // corta a faixa preta, arredonda para par
});

test("previaParaVideo com escala (prévia menor que o vídeo)", () => {
  // Vídeo 2560x1080 mostrado em 1280x540: cada px da prévia vale 2 do vídeo.
  const r = previaParaVideo({ x: 100, y: 50, largura: 320, altura: 180 }, { largura: 1280, altura: 540 },
    { largura: 2560, altura: 1080 });
  assert.deepEqual(r, { x: 200, y: 100, largura: 640, altura: 360 });
});

test("previaParaVideo limita à borda e recusa área minúscula", () => {
  const r = previaParaVideo({ x: 900, y: 400, largura: 500, altura: 500 }, { largura: 1000, altura: 500 },
    { largura: 1000, altura: 500 });
  assert.deepEqual(r, { x: 900, y: 400, largura: 100, altura: 100 });
  assert.equal(previaParaVideo({ x: 10, y: 10, largura: 5, altura: 5 }, { largura: 100, altura: 100 },
    { largura: 100, altura: 100 }), null);
  assert.equal(previaParaVideo({ x: 0, y: 0, largura: 50, altura: 50 }, { largura: 100, altura: 100 },
    { largura: 0, altura: 0 }), null);
});

test("Cronometro desconta as pausas e congela ao parar", () => {
  let agora = 0;
  const c = new Cronometro(() => agora);
  c.iniciar();
  agora = 1000;
  c.pausar();
  assert.ok(c.pausado);
  agora = 5000;
  assert.equal(c.segundos, 1);
  c.continuar();
  agora = 6500;
  assert.equal(c.segundos, 2.5);
  c.parar();
  agora = 99000;
  assert.equal(c.segundos, 2.5);
  c.pausar(); // depois de parar não pausa mais
  assert.equal(c.pausado, false);
});

test("acaoDoAtalho: os mesmos atalhos do desktop", () => {
  const t = (key: string, ctrlKey = true, shiftKey = true, altKey = false) => acaoDoAtalho({ key, ctrlKey, shiftKey, altKey });
  assert.equal(t("F9"), "gravar");
  assert.equal(t("F10"), "pausar");
  assert.equal(t("F9", false), null);
  assert.equal(t("F9", true, true, true), null);
  assert.equal(t("F11"), null);
});

test("pico", () => {
  assert.equal(pico([0, -0.5, 0.25]), 0.5);
  assert.equal(pico([2]), 1);
  assert.equal(pico([]), 0);
});

test("bitsDeVideo entre 2 e 25 Mbit/s", () => {
  assert.equal(bitsDeVideo(320, 240, 15), 2e6);
  assert.equal(bitsDeVideo(1920, 1080, 30), 6220800);
  assert.equal(bitsDeVideo(3840, 2160, 60), 25e6);
});

test("versão do web igual à do desktop", () => {
  const web = JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf8")).version;
  const py = readFileSync(new URL("../../gravatela/__init__.py", import.meta.url), "utf8");
  assert.equal(/VERSAO = "([\d.]+)"/.exec(py)?.[1], web);
});
