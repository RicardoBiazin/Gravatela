import { readFileSync } from "node:fs";
import { defineConfig } from "vite";

const pacote = JSON.parse(readFileSync(new URL("./package.json", import.meta.url), "utf8"));

// O `vite preview` usa os MESMOS cabeçalhos do netlify.toml, para pegar violação de CSP
// ou permissão bloqueada (tela/microfone) antes do deploy.
const netlify = readFileSync(new URL("./netlify.toml", import.meta.url), "utf8");
const cabecalho = (nome: string) => new RegExp(`${nome} = "([^"]+)"`).exec(netlify)?.[1] ?? "";

export default defineConfig({
  define: { __VERSAO__: JSON.stringify(pacote.version) },
  preview: {
    headers: {
      "Content-Security-Policy": cabecalho("Content-Security-Policy"),
      "Permissions-Policy": cabecalho("Permissions-Policy"),
      "X-Content-Type-Options": "nosniff",
    },
  },
  build: { target: "es2022", outDir: "dist", sourcemap: false },
});
