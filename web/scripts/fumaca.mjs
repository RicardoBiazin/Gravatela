/*
 * Fumaça do Gravatela web num Chrome/Edge headless de verdade (CDP).
 *
 *   node scripts/fumaca.mjs                       contra o `vite preview` (http://localhost:4180)
 *   node scripts/fumaca.mjs --url=https://...     contra o site publicado
 *   node scripts/fumaca.mjs --so-pagina           só carrega a página (sem gravar)
 *
 * O navegador abre com tela e microfone falsos (--use-fake-*-for-media-stream), então a
 * gravação acontece de verdade sem pedir nada a ninguém. Confere: versão na tela, sem
 * violação de CSP, gravação com pausa (o arquivo baixado tem a duração sem a pausa),
 * áudio no arquivo e gravação de uma área (o arquivo tem o tamanho da área).
 * Os arquivos baixados são conferidos com o ffprobe (precisa estar no PATH).
 */

import { execFileSync, spawn } from "node:child_process";
import { existsSync, mkdtempSync, readdirSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const arg = (n) => process.argv.find((a) => a.startsWith(`--${n}=`))?.split("=").slice(1).join("=");
const URL_APP = (arg("url") ?? "http://localhost:4180").replace(/\/?$/, "/");
const SO_PAGINA = process.argv.includes("--so-pagina");
const versao = JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf8")).version;

const chrome = [process.env.CHROME, "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", "C:/Program Files/Microsoft/Edge/Application/msedge.exe",
  "/usr/bin/google-chrome", "/usr/bin/chromium"].filter(Boolean).find((c) => existsSync(c));
if (!chrome) {
  console.log("Nenhum Chrome/Edge encontrado; defina CHROME=caminho.");
  process.exit(2);
}

const espera = (ms) => new Promise((r) => setTimeout(r, ms));
const falhas = [];
const ok = (cond, msg) => {
  console.log(`${cond ? "ok    " : "FALHOU"} ${msg}`);
  if (!cond) falhas.push(msg);
};

const perfil = join(tmpdir(), "gravatela-fumaca-perfil");
const downloads = mkdtempSync(join(tmpdir(), "gravatela-fumaca-"));
rmSync(perfil, { recursive: true, force: true });
const nav = spawn(chrome, ["--headless=new", "--remote-debugging-port=9335", `--user-data-dir=${perfil}`, "--no-first-run",
  "--no-default-browser-check", "--disable-component-update", "--window-size=1280,900",
  "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream", "--autoplay-policy=no-user-gesture-required",
  "about:blank"], { stdio: "ignore" });
let alvo;
for (let i = 0; i < 50 && !alvo; i++) {
  try {
    alvo = (await (await fetch("http://127.0.0.1:9335/json")).json()).find((t) => t.type === "page");
  } catch { /* abrindo */ }
  await espera(200);
}
if (!alvo) throw new Error("não conectou ao navegador");
const ws = new WebSocket(alvo.webSocketDebuggerUrl);
await new Promise((r) => ws.addEventListener("open", r, { once: true }));
let seq = 0;
const pend = new Map();
const erros = [];
ws.addEventListener("message", (ev) => {
  const m = JSON.parse(ev.data);
  if (m.id && pend.has(m.id)) {
    const p = pend.get(m.id);
    pend.delete(m.id);
    m.error ? p.no(new Error(m.error.message)) : p.ok(m.result);
  } else if (m.method === "Runtime.exceptionThrown") {
    erros.push("exceção: " + (m.params.exceptionDetails.exception?.description ?? m.params.exceptionDetails.text));
  } else if (m.method === "Log.entryAdded" && m.params.entry.level === "error") {
    erros.push("log: " + m.params.entry.text);
  }
});
const cdp = (method, params = {}, ms = 20000) => new Promise((res, no) => {
  const id = ++seq;
  const t = setTimeout(() => {
    pend.delete(id);
    no(new Error(`${method}: sem resposta`));
  }, ms);
  pend.set(id, { ok: (v) => (clearTimeout(t), res(v)), no: (e) => (clearTimeout(t), no(e)) });
  ws.send(JSON.stringify({ id, method, params }));
});
const avaliar = async (expr) => {
  const r = await cdp("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true, userGesture: true });
  if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description ?? r.exceptionDetails.text);
  return r.result.value;
};
const aguardar = async (expr, ms = 30000) => {
  for (const fim = Date.now() + ms; Date.now() < fim; await espera(150)) {
    try {
      if (await avaliar(expr)) return true;
    } catch { /* página trocando */ }
  }
  return false;
};
const clicar = (id) => avaliar(`document.getElementById(${JSON.stringify(id)}).click()`);

/** Espera um download novo terminar e devolve o caminho. */
async function baixado(antes) {
  for (let i = 0; i < 100; i++) {
    const novos = readdirSync(downloads).filter((f) => !antes.includes(f) && !f.endsWith(".crdownload") && !f.endsWith(".tmp"));
    if (novos.length) return join(downloads, novos[0]);
    await espera(200);
  }
  return null;
}

function sondar(arquivo) {
  const saida = execFileSync("ffprobe", ["-v", "error", "-show_entries", "stream=codec_type,codec_name,width,height:format=duration",
    "-of", "json", arquivo], { encoding: "utf8" });
  const j = JSON.parse(saida);
  // O MP4 do MediaRecorder às vezes não traz duration no format; aí decodifica para medir.
  let duracao = Number(j.format?.duration);
  if (!Number.isFinite(duracao)) {
    const t = execFileSync("ffprobe", ["-v", "error", "-select_streams", "v:0", "-count_packets", "-show_entries",
      "stream=nb_read_packets,r_frame_rate", "-of", "json", arquivo], { encoding: "utf8" });
    const s = JSON.parse(t).streams[0];
    const [n, d] = s.r_frame_rate.split("/").map(Number);
    duracao = Number(s.nb_read_packets) / (n / d);
  }
  return { duracao, streams: j.streams };
}

try {
  await cdp("Page.enable");
  await cdp("Runtime.enable");
  await cdp("Log.enable");
  await cdp("Browser.setDownloadBehavior", { behavior: "allow", downloadPath: downloads });
  await cdp("Page.navigate", { url: URL_APP });
  ok(await aguardar("!!document.getElementById('versao')?.textContent", 30000), "app carregou");
  ok(await avaliar("document.getElementById('versao').textContent") === versao, `versão ${versao} na tela`);
  ok(await avaliar("!document.getElementById('bt-gravar').disabled"), "botão Gravar habilitado");
  const mp4 = await avaliar("MediaRecorder.isTypeSupported('video/mp4;codecs=avc1.640028,mp4a.40.2')");
  console.log(`       (navegador ${mp4 ? "grava MP4" : "não grava MP4; vai WebM"})`);

  if (!SO_PAGINA) {
    // 1) Tela + "áudio do PC" + microfone falsos, com uma pausa de 1,5 s no meio.
    await avaliar(`(() => { for (const [id, v] of [['ck-audio-pc', true], ['ck-microfone', true], ['ck-area', false]]) {
      const c = document.getElementById(id); c.checked = v; c.dispatchEvent(new Event('change')); } })()`);
    let antes = readdirSync(downloads);
    await clicar("bt-gravar");
    ok(await aguardar("document.getElementById('tempo').classList.contains('gravando')", 15000), "gravação começou");
    await espera(1500);
    ok(await avaliar("!document.getElementById('niveis').hidden"), "medidores de nível visíveis");
    await clicar("bt-pausar");
    ok(await aguardar("document.getElementById('tempo').textContent.includes('pausado')", 3000), "pausou");
    await espera(1500);
    await clicar("bt-pausar");
    ok(await aguardar("!document.getElementById('tempo').textContent.includes('pausado')", 3000), "continuou");
    await espera(1500);
    await clicar("bt-gravar");
    ok(await aguardar("!document.getElementById('painel-resultado').hidden", 15000), "gravação pronta");
    const info = await avaliar("document.getElementById('info-resultado').textContent");
    console.log(`       ${info}`);
    const arquivo = await baixado(antes);
    ok(!!arquivo, `arquivo baixado (${arquivo})`);
    if (arquivo) {
      ok(/Gravatela_\d{4}-\d\d-\d\d_\d\d-\d\d-\d\d\.(mp4|webm)$/.test(arquivo), "nome no padrão do desktop");
      const s = sondar(arquivo);
      const tipos = s.streams.map((x) => `${x.codec_type}:${x.codec_name}`);
      console.log(`       ${tipos.join(", ")}; ${s.duracao.toFixed(2)} s`);
      ok(tipos.some((t) => t.startsWith("video:")), "arquivo tem vídeo");
      ok(tipos.some((t) => t.startsWith("audio:")), "arquivo tem áudio (mixer)");
      ok(s.duracao > 2.2 && s.duracao < 4.0, `duração ~3 s, sem a pausa de 1,5 s (${s.duracao.toFixed(2)} s)`);
    }

    // 2) Só uma área: arrasta sobre a prévia e confere o tamanho do vídeo.
    await avaliar(`(() => { const c = document.getElementById('ck-area'); c.checked = true; c.dispatchEvent(new Event('change'));
      const m = document.getElementById('ck-microfone'); m.checked = false; m.dispatchEvent(new Event('change')); })()`);
    antes = readdirSync(downloads);
    await clicar("bt-gravar");
    ok(await aguardar("!document.getElementById('acoes-area').hidden && document.getElementById('previa').videoWidth > 0", 15000),
      "modo de escolher área");
    const g = await avaliar(`(() => { const r = document.getElementById('camada').getBoundingClientRect();
      const v = document.getElementById('previa'); return { x: r.left, y: r.top, w: r.width, h: r.height, vw: v.videoWidth, vh: v.videoHeight }; })()`);
    // Arrasta do centro-esquerda até 40% x 40% da prévia.
    const p1 = { x: g.x + g.w * 0.1, y: g.y + g.h * 0.1 };
    const p2 = { x: g.x + g.w * 0.5, y: g.y + g.h * 0.5 };
    await cdp("Input.dispatchMouseEvent", { type: "mousePressed", x: p1.x, y: p1.y, button: "left", clickCount: 1 });
    await cdp("Input.dispatchMouseEvent", { type: "mouseMoved", x: (p1.x + p2.x) / 2, y: (p1.y + p2.y) / 2, button: "left" });
    await cdp("Input.dispatchMouseEvent", { type: "mouseMoved", x: p2.x, y: p2.y, button: "left" });
    await cdp("Input.dispatchMouseEvent", { type: "mouseReleased", x: p2.x, y: p2.y, button: "left", clickCount: 1 });
    ok(await aguardar("!document.getElementById('bt-comecar').disabled", 3000), "área escolhida arrastando");
    const texto = await avaliar("document.getElementById('tamanho-area').textContent");
    const [, aw, ah] = /(\d+) x (\d+)/.exec(texto) ?? [];
    console.log(`       ${texto} (vídeo de origem ${g.vw}x${g.vh})`);
    await clicar("bt-comecar");
    ok(await aguardar("document.getElementById('tempo').classList.contains('gravando')", 10000), "gravação da área começou");
    await espera(2000);
    await clicar("bt-gravar");
    ok(await aguardar("!document.getElementById('painel-resultado').hidden", 15000), "gravação da área pronta");
    const arquivoArea = await baixado(antes);
    ok(!!arquivoArea, "arquivo da área baixado");
    if (arquivoArea) {
      const v = sondar(arquivoArea).streams.find((x) => x.codec_type === "video");
      ok(v && String(v.width) === aw && String(v.height) === ah, `vídeo com o tamanho da área (${v?.width}x${v?.height})`);
    }
  }

  // Com --use-fake-device-for-media-stream o Chrome simula a captura de tela como se fosse uma
  // câmera e esbarra no camera=() da Permissions-Policy. A página nunca pede câmera; num
  // navegador normal esse aviso não aparece.
  const relevantes = erros.filter((e) => !/Permissions policy violation: camera is not allowed/.test(e));
  const csp = relevantes.filter((e) => /Content Security Policy|Refused|Permissions policy/.test(e));
  ok(csp.length === 0, `sem violação de CSP/permissão${csp.length ? ": " + csp.join(" | ") : ""}`);
  const outros = relevantes.filter((e) => !csp.includes(e));
  ok(outros.length === 0, `sem erro de console${outros.length ? ": " + outros.join(" | ") : ""}`);
} catch (e) {
  ok(false, "roteiro: " + e.message);
  if (erros.length) console.log("Erros do navegador:", erros);
} finally {
  ws.close();
  nav.kill();
  rmSync(downloads, { recursive: true, force: true });
}
console.log(falhas.length ? `\n${falhas.length} FALHA(S)` : "\nFUMAÇA OK");
process.exit(falhas.length ? 1 : 0);
