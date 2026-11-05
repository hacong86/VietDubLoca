// Build extension MV3 bằng esbuild (có sẵn qua Vite). Không nạp code từ xa; mọi bundle nằm trong gói.
// node build.mjs [--watch] [--key <path extension-dev.json>]
import { build, context } from 'esbuild';
import { cpSync, existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, '../..');
const out = join(here, 'dist');
const watch = process.argv.includes('--watch');
const keyArg = process.argv.indexOf('--key');
const keyFile = keyArg > 0 ? process.argv[keyArg + 1] : process.env.VIETDUB_EXT_KEY ?? join(root, 'config/extension-public-key.json');
const pkg = JSON.parse(readFileSync(join(root, 'package.json'), 'utf8'));

rmSync(out, { recursive: true, force: true });
mkdirSync(out, { recursive: true });

const common = {
  bundle: true, minify: !watch, sourcemap: watch ? 'inline' : false, target: ['chrome116'], logLevel: 'info',
  define: { 'process.env.NODE_ENV': JSON.stringify(watch ? 'development' : 'production') },
  legalComments: 'external', jsx: 'automatic', loader: { '.json': 'json' },
};
const entries = [
  { entryPoints: [join(here, 'src/background/index.ts')], outfile: join(out, 'background.js'), format: 'esm' },
  { entryPoints: [join(here, 'src/content/index.ts')], outfile: join(out, 'content.js'), format: 'iife' },
  { entryPoints: [join(here, 'src/bridge/index.ts')], outfile: join(out, 'bridge.js'), format: 'iife' },
  { entryPoints: [join(here, 'src/offscreen/index.ts')], outfile: join(out, 'offscreen.js'), format: 'esm' },
  { entryPoints: [join(here, 'src/offscreen/capture-worklet.ts')], outfile: join(out, 'capture-worklet.js'), format: 'iife' },
  { entryPoints: [join(here, 'src/sidepanel/main.tsx')], outfile: join(out, 'sidepanel.js'), format: 'esm' },
  { entryPoints: [join(here, 'src/options/main.tsx')], outfile: join(out, 'options.js'), format: 'esm' },
];

cpSync(join(here, 'public'), out, { recursive: true });
for (const name of ['LICENSE', 'NOTICE', 'THIRD_PARTY_NOTICES.md']) cpSync(join(root, name), join(out, name));
cpSync(join(root, 'THIRD_PARTY_LICENSES'), join(out, 'THIRD_PARTY_LICENSES'), { recursive: true });
const manifest = JSON.parse(readFileSync(join(here, 'manifest.base.json'), 'utf8'));
manifest.version = pkg.version;
if (keyFile && existsSync(keyFile)) manifest.key = JSON.parse(readFileSync(keyFile, 'utf8')).key;   // ID ổn định cho Native Messaging
writeFileSync(join(out, 'manifest.json'), JSON.stringify(manifest, null, 2));

if (watch) {
  for (const e of entries) await (await context({ ...common, ...e })).watch();
} else {
  await Promise.all(entries.map((e) => build({ ...common, ...e }))).catch((err) => { console.error('BUILD FAILED'); process.exit(1); });
}
console.log('built', out, 'version', manifest.version, manifest.key ? '(stable key)' : '(no key)');
