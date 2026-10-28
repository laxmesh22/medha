// Pack the demo build into one self-contained HTML page for sharing (claude.ai Artifact): inline CSS + JS,
// in-memory routing, forced demo data (a shared page cannot reach Supabase). Usage: npm run artifact
import { execSync } from "node:child_process";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const out = join(root, "dist-artifact");
execSync("npx vite build --outDir dist-artifact --emptyOutDir", {
  cwd: root, stdio: "inherit", env: { ...process.env, VITE_ROUTER: "memory", VITE_FORCE_DEMO: "1" },
});
const html = readFileSync(join(out, "index.html"), "utf8");
const js = [...html.matchAll(/<script[^>]*src="([^"]+)"[^>]*><\/script>/g)].map((m) => readFileSync(join(out, m[1]), "utf8"));
const css = [...html.matchAll(/<link[^>]*rel="stylesheet"[^>]*href="([^"]+)"[^>]*>/g)]
  .filter((m) => !/^https?:/.test(m[1])) // the web font stays a link (below)
  .map((m) => readFileSync(join(out, m[1]), "utf8"));
const safeJs = js.join("\n").replace(/<\/script/gi, "<\/script").replace(/<!--/g, "<\!--");
const page = `<title>Auri Clinician</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Jost:wght@500&display=swap">
<style>
html, body { background: #f5f2ea; color: #10201f; }
${css.join("\n")}
</style>
<div id="root"></div>
<script type="module">
${safeJs}
</script>
`;
mkdirSync(out, { recursive: true });
writeFileSync(join(out, "physio-buddy-clinician.html"), page);
console.log(`artifact page: ${join(out, "physio-buddy-clinician.html")} (${(page.length / 1024).toFixed(0)} KB)`);
