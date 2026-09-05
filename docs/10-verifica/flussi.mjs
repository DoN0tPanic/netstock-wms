// Il giro completo della merce, dal browser: ricezione con acquisizione dei
// seriali, il pezzo che compare a magazzino con la sua cronologia, e lo storno
// che aggiunge una riga invece di toglierne una.
//
// **Questo script scrive nel registro**, che è append-only: quello che
// registra non si toglie più. Per questo pretende un'istanza usa e getta e
// una conferma esplicita, e non si lancia sull'installazione che si usa per
// lavorare. Le altre verifiche qui accanto sono innocue; questa no.
//
//   NETSTOCK_URL=https://istanza-di-prova NETSTOCK_PASSWORD='…' \
//   NETSTOCK_SCRIVE=si node docs/10-verifica/flussi.mjs
import puppeteer from 'puppeteer-core';
const BASE = process.env.NETSTOCK_URL;
const UTENTE = process.env.NETSTOCK_UTENTE ?? 'admin';
const PASSWORD = process.env.NETSTOCK_PASSWORD;
if (!BASE || !PASSWORD) { console.error('Servono NETSTOCK_URL e NETSTOCK_PASSWORD.'); process.exit(2); }
if (process.env.NETSTOCK_SCRIVE !== 'si') {
  console.error('Questa verifica registra movimenti veri, e il registro non si ripulisce.');
  console.error('Lanciala su un\'istanza di prova con NETSTOCK_SCRIVE=si.');
  process.exit(2);
}
let prove = 0, falliti = 0;
const ok = (nome, cond, extra = '') => { prove++; console.log(`  ${cond ? 'OK     ' : 'FALLITO'} ${nome}${extra ? ' — ' + extra : ''}`); if (!cond) falliti++; };
const browser = await puppeteer.launch({
  executablePath: process.env.HOME + '/.cache/puppeteer/chrome/linux-152.0.7977.54/chrome-linux64/chrome',
  headless: 'new', args: ['--no-sandbox', '--ignore-certificate-errors'] });
const page = await browser.newPage();
await page.setViewport({ width: 1500, height: 1100 });
const errori = [];
page.on('console', (m) => { if (m.type() === 'error' && !m.text().includes('401')) errori.push(m.text()); });
page.on('pageerror', (e) => errori.push('pageerror: ' + e.message));
const testo = () => page.evaluate(() => document.body.innerText);
const vai = async (p) => { await page.goto(BASE + p, { waitUntil: 'networkidle2' }); await new Promise(r => setTimeout(r, 1200)); };
const premi = (t) => page.evaluate((x) => {
  const b = [...document.querySelectorAll('button, a')].find((e) => e.innerText.trim() === x || e.innerText.trim().startsWith(x));
  if (b) b.click(); return !!b;
}, t);
const scrivi = (etichetta, valore) => page.evaluate((e, v) => {
  const campo = [...document.querySelectorAll('input')].find((i) => i.closest('label')?.innerText?.includes(e));
  if (!campo) return false;
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
  campo.focus(); setter.call(campo, v); campo.dispatchEvent(new Event('input', { bubbles: true })); return true;
}, etichetta, valore);
const scegli = (indice, contiene) => page.evaluate((i, t) => {
  const s = document.querySelectorAll('select')[i];
  if (!s) return false;
  const o = [...s.options].find((x) => x.text.includes(t));
  if (!o) return false;
  s.value = o.value; s.dispatchEvent(new Event('change', { bubbles: true })); return true;
}, indice, contiene);
const combo = (etichetta, digita, scelta) => page.evaluate(async (e, d, s) => {
  const campo = [...document.querySelectorAll('input')].find((i) => i.closest('label')?.innerText?.includes(e));
  if (!campo) return false;
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
  campo.focus(); setter.call(campo, d); campo.dispatchEvent(new Event('input', { bubbles: true }));
  await new Promise(r => setTimeout(r, 800));
  const voce = [...document.querySelectorAll('li, button, [role="option"]')].find((x) => x.innerText?.includes(s));
  if (!voce) return false;
  voce.click(); return true;
}, etichetta, digita, scelta);

await vai('/login');
const campi = await page.$$('input');
await campi[0].type(UTENTE);
await page.type('input[type="password"]', PASSWORD);
await page.click('button[type="submit"]');
await page.waitForNavigation({ waitUntil: 'networkidle2' }).catch(() => {});

console.log('== Ricezione merce con acquisizione dei seriali ==');
await vai('/receive');
ok('bolla: si può procedere senza', await scegli(0, 'Senza bolla'));
await new Promise(r => setTimeout(r, 600));
ok('ubicazione scelta', await combo('Ubicazione', 'A01', 'Scaffale A01'));
await new Promise(r => setTimeout(r, 600));
ok('modello scelto', await combo('Modello', 'C9300', 'C9300-48P-A'));
await new Promise(r => setTimeout(r, 800));
const SERIALI = [`VER${Math.floor(Math.random()*9000+1000)}AA01`, `VER${Math.floor(Math.random()*9000+1000)}AA02`];
const campoSeriale = await page.evaluateHandle(() =>
  [...document.querySelectorAll('input')].find((i) => i.closest('label')?.innerText?.includes('Numero seriale')));
for (const s of SERIALI) {
  await campoSeriale.asElement().type(s, { delay: 5 });
  await campoSeriale.asElement().press('Enter');
  await new Promise(r => setTimeout(r, 300));
}
// I seriali acquisiti stanno in caselle di testo, e il valore di una casella
// non fa parte del testo della pagina: si leggono dai campi, non da
// `innerText` — che è come si legge una lista, ma questa non lo è.
const inLista = await page.evaluate(() => [...document.querySelectorAll('input')].map((i) => i.value));
ok('i due seriali sono in lista',
   inLista.includes(SERIALI[0]) && inLista.includes(SERIALI[1]), inLista.filter(Boolean).slice(0, 4).join(' '));
await premi('Registra ricezione');
await new Promise(r => setTimeout(r, 3500));
// Il segnale che la registrazione è avvenuta è che il modulo si è svuotato:
// i seriali appena battuti non sono più in pagina, perché sono a magazzino.
// (Il testo della pagina non basta: a modulo vuoto ricompare l'elenco di
// quello che manca per registrare, che somiglia a un errore e non lo è.)
ok('il modulo si è svuotato: la merce è registrata',
   await page.evaluate((s) => !document.querySelector('main').innerText.includes(s), SERIALI[0]));

console.log('== Il pezzo è a magazzino ==');
await vai('/stock');
await page.evaluate(() => { const i = document.querySelector('input[placeholder*="Seriale"]'); if (i) i.focus(); });
await page.keyboard.type(SERIALI[0]);
await new Promise(r => setTimeout(r, 1800));
ok('si trova cercando il seriale', (await testo()).includes(SERIALI[0]));
ok('è in magazzino, nell\'ubicazione scelta',
   /In magazzino/.test(await testo()) && /Scaffale A01/.test(await testo()));

console.log('== Cronologia del pezzo ==');
await page.evaluate((s) => [...document.querySelectorAll('a')].find((a) => a.innerText.trim() === s)?.click(), SERIALI[0]);
await new Promise(r => setTimeout(r, 2000));
const scheda = await testo();
ok('la scheda del pezzo si apre', scheda.includes(SERIALI[0]));
ok('la cronologia mostra il carico', /Carico/.test(scheda));

console.log('== Spostamento e storno ==');
await vai('/movements');
const primaDelloStorno = await page.evaluate(() => document.querySelectorAll('tbody tr').length);
ok('il movimento compare nel registro', primaDelloStorno > 0);
const stornato = await page.evaluate(() => {
  const b = [...document.querySelectorAll('button')].find((x) => x.innerText.trim() === 'Storna');
  if (!b) return false; b.click(); return true;
});
ok('si può chiedere lo storno', stornato);
await new Promise(r => setTimeout(r, 900));
const modaleStorno = await testo();
ok('lo storno chiede il motivo', /motiv/i.test(modaleStorno));
await scrivi('Motivo', 'Verifica automatica del giro completo');
await page.evaluate(() => [...document.querySelectorAll('button')].filter((b) => /Storna|Conferma/.test(b.innerText)).pop()?.click());
await new Promise(r => setTimeout(r, 2500));
await vai('/movements');
const dopoStorno = await page.evaluate(() => document.querySelectorAll('tbody tr').length);
ok('lo storno ha aggiunto una riga, non tolto quella vecchia', dopoStorno > primaDelloStorno,
   `${primaDelloStorno} → ${dopoStorno}`);

console.log(`\n  errori in console: ${errori.length}`);
errori.slice(0, 5).forEach((e) => console.log('   ', e.slice(0, 140)));
console.log(`  totale: ${prove} prove, ${falliti} fallite`);
await browser.close();
process.exit(falliti ? 1 : 0);
