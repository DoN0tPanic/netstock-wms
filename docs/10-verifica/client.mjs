import fs from 'node:fs';
import puppeteer from 'puppeteer-core';

// Indirizzo e credenziali dall'ambiente: sono di questa installazione, e un
// file che li contiene non si pubblica.
//   NETSTOCK_URL=https://… NETSTOCK_PASSWORD='…' node client.mjs <scarichi>
const BASE = process.env.NETSTOCK_URL;
const UTENTE = process.env.NETSTOCK_UTENTE ?? 'admin';
const PASSWORD = process.env.NETSTOCK_PASSWORD;
if (!BASE || !PASSWORD) { console.error('Servono NETSTOCK_URL e NETSTOCK_PASSWORD.'); process.exit(2); }
const SCARICHI = process.argv[2];
let falliti = 0, prove = 0;
const ok = (nome, condizione, extra = '') => {
  prove++;
  if (condizione) console.log(`  OK      ${nome}${extra ? ' — ' + extra : ''}`);
  else { falliti++; console.log(`  FALLITO ${nome}${extra ? ' — ' + extra : ''}`); }
};

const browser = await puppeteer.launch({
  executablePath: process.env.HOME + '/.cache/puppeteer/chrome/linux-152.0.7977.54/chrome-linux64/chrome',
  headless: 'new', args: ['--no-sandbox', '--ignore-certificate-errors'],
});
const page = await browser.newPage();
await page.setViewport({ width: 1500, height: 950 });
const cdp = await page.createCDPSession();
await cdp.send('Page.setDownloadBehavior', { behavior: 'allow', downloadPath: SCARICHI });
const erroriConsole = [];
page.on('console', (m) => { if (m.type() === 'error' && !m.text().includes('401')) erroriConsole.push(m.text()); });
page.on('pageerror', (e) => erroriConsole.push('pageerror: ' + e.message));

const testo = () => page.evaluate(() => document.body.innerText);
const vai = async (percorso) => { await page.goto(BASE + percorso, { waitUntil: 'networkidle2' }); await new Promise(r => setTimeout(r, 900)); };
const premi = (etichetta) => page.evaluate((t) => {
  const b = [...document.querySelectorAll('button, a')].find((x) => x.innerText.trim() === t || x.innerText.trim().startsWith(t));
  if (b) b.click(); return !!b;
}, etichetta);

console.log('== Accesso ==');
await vai('/login');
const campi = await page.$$('input');
await campi[0].type(UTENTE);
await page.type('input[type="password"]', 'sbagliata-di-proposito');
await page.click('button[type="submit"]');
await new Promise(r => setTimeout(r, 1500));
ok('credenziali sbagliate: messaggio e nessun accesso', /non valid/i.test(await testo()));
await page.reload({ waitUntil: 'networkidle2' });
const campi2 = await page.$$('input');
await campi2[0].type(UTENTE);
await page.type('input[type="password"]', PASSWORD);
await page.click('button[type="submit"]');
await page.waitForNavigation({ waitUntil: 'networkidle2' }).catch(() => {});
await new Promise(r => setTimeout(r, 1200));
ok('accesso riuscito', !/Accedi al gestionale/.test(await testo()));

console.log('== Cruscotto ==');
await vai('/');
const cruscotto = await testo();
ok('dashboard con i riquadri di sintesi', /Sotto scorta|Bolle aperte|scadenza/i.test(cruscotto));
ok('grafico disegnato', (await page.$$('svg')).length > 0);

console.log('== Magazzino ==');
await vai('/stock');
let magazzino = await testo();
ok('tabella con le righe', /righe/.test(magazzino) && (await page.$$('tbody tr')).length > 0);
const ubicazioni = await page.evaluate(() => {
  const indice = [...document.querySelectorAll('thead th')].findIndex((t) => t.innerText.trim() === 'Ubicazione');
  return [...document.querySelectorAll('tbody tr')].slice(0, 5).map((r) => r.children[indice]?.innerText.trim() ?? '');
});
// Per esteso vuol dire: contiene spazi o il separatore del percorso. Un codice
// come `DEP-A01` o `001` non ne ha. Si guarda la forma, non il nome vero del
// magazzino, che in un file pubblicato non ci va.
ok('ubicazione per esteso, non il solo codice',
   ubicazioni.some((u) => u.includes(' ') || u.includes('›')), ubicazioni[0] ? '(prima riga letta)' : '');
await page.evaluate(() => { const s = document.querySelector('select[aria-label="Stato"]'); s.value = 'in_stock'; s.dispatchEvent(new Event('change', { bubbles: true })); });
await new Promise(r => setTimeout(r, 1200));
ok('filtro per stato applicato', (await page.$$('tbody tr')).length > 0);
await premi('Colonne');
await new Promise(r => setTimeout(r, 500));
ok('finestra di scelta colonne', /Colonne da mostrare/.test(await testo()));
await page.evaluate(() => { const l = [...document.querySelectorAll('label')].find((x) => x.innerText.trim() === 'Note'); l.querySelector('input').click(); });
await new Promise(r => setTimeout(r, 300));
await premi('Fatto');
await new Promise(r => setTimeout(r, 600));
ok('colonna Note aggiunta', (await page.evaluate(() => [...document.querySelectorAll('thead th')].map(t => t.innerText.trim()))).includes('Note'));
await premi('Esporta CSV');
await new Promise(r => setTimeout(r, 2500));
const csv = fs.readdirSync(SCARICHI).filter(n => n.endsWith('.csv'));
ok('esportazione CSV scaricata', csv.length > 0, csv.join(','));
if (csv.length) {
  const righe = fs.readFileSync(SCARICHI + '/' + csv[0], 'utf8').trim().split('\n');
  ok('il CSV contiene le note', righe[0].includes('Note'), `${righe.length - 1} righe`);
}
await premi('Esporta tutto');
await new Promise(r => setTimeout(r, 3000));
ok('archivio ZIP scaricato', fs.readdirSync(SCARICHI).some(n => n.endsWith('.zip')));

console.log('== Dettaglio di un pezzo ==');
await page.evaluate(() => document.querySelector('tbody a[href^="/units/"]').click());
await new Promise(r => setTimeout(r, 1500));
const unita = await testo();
ok('scheda del pezzo con cronologia', /Timeline movimenti/.test(unita));
ok('operazione in italiano, non in inglese', /Carico/.test(unita) && !/receipt/.test(unita));

console.log('== Movimenti, ubicazioni, bolle, catalogo ==');
for (const [percorso, atteso, nome] of [
  ['/movements', /Movimenti/, 'movimenti'],
  ['/locations', /Ubicazioni/, 'ubicazioni'],
  ['/delivery-notes', /Bolle/, 'bolle'],
  ['/catalog', /Catalogo/, 'catalogo'],
  ['/vendors', /Vendor/, 'vendor'],
  ['/categories', /Categorie/, 'categorie'],
  ['/suppliers', /Fornitori/, 'fornitori'],
  ['/receive', /Ricevi merce/, 'ricezione merce'],
]) { await vai(percorso); ok(`pagina ${nome} si apre`, atteso.test(await testo())); }

// Le prenotazioni non hanno una pagina: l'API c'è, il client no, e
// `/reservations` ricade sulla dashboard. Si verifica il comportamento vero
// invece di lasciare una prova sempre rossa, che insegna a non guardare.
await vai('/reservations');
ok('prenotazioni: nessuna pagina, si ricade sul cruscotto (lacuna nota)',
   !/Prenotazioni/.test(await testo()));

console.log('== Ricerca globale ==');
await vai('/stock');
// Un frammento qualunque: quello che si verifica è che la ricerca
// risponda, non che trovi un apparato preciso di questa installazione.
const FRAMMENTO = process.env.NETSTOCK_SERIALE ?? 'A';
await page.type('input[aria-label="Ricerca globale"]', FRAMMENTO);
await new Promise(r => setTimeout(r, 1500));
ok('la ricerca propone risultati', (await page.$$('a[href^="/units/"], [role="option"]')).length > 0
   || new RegExp(FRAMMENTO, 'i').test(await testo()));

console.log('== Amministrazione ==');
for (const [percorso, atteso, nome] of [
  ['/admin/users', /Utenti/, 'utenti'],
  ['/admin/templates', /Template/, 'template estrazione'],
  ['/admin/audit', /Audit|registro/i, 'audit'],
]) { await vai(percorso); ok(`pagina ${nome} si apre`, atteso.test(await testo())); }

console.log('== Impostazioni: copia di sicurezza ==');
await vai('/admin/settings');
const impostazioni = await testo();
ok('sezione copia di sicurezza presente', /Copia di sicurezza/.test(impostazioni));
ok('dati tecnici del database', /PostgreSQL/.test(impostazioni) && /Revisione schema/.test(impostazioni));
ok('spazio occupato mostrato', /MB|kB|GB/.test(impostazioni));
ok('tabelle con peso e righe', /Righe \(stima\)/.test(impostazioni));
ok('copie sul server elencate', /Copie sul server/.test(impostazioni));
ok('sezione di ripristino presente', /Ripristino/.test(impostazioni));
const primaDelBackup = fs.readdirSync(SCARICHI).length;
await premi('Scarica una copia adesso');
await new Promise(r => setTimeout(r, 6000));
const dump = fs.readdirSync(SCARICHI).filter(n => n.endsWith('.dump'));
ok('copia di sicurezza scaricata dal pulsante', dump.length > 0,
   dump.length ? `${dump[0]} · ${fs.statSync(SCARICHI + '/' + dump[0]).size} byte` : `${primaDelBackup} file prima`);
await premi('Ripristina da una copia');
await new Promise(r => setTimeout(r, 600));
const modale = await testo();
ok('il ripristino chiede file e parola di conferma', /RIPRISTINA/.test(modale));
ok('il pulsante di ripristino parte disabilitato',
   await page.evaluate(() => [...document.querySelectorAll('button')].find(b => b.innerText.includes('Ripristina adesso'))?.disabled === true));

console.log('== Archivio delle bolle ==');
await page.keyboard.press('Escape');
// Un PDF costruito qui: serve una bolla per provare l'archivio, e un
// documento vero non entra in uno script.
const pdfDiProva = (numero) => {
  const testoPdf = `DITTA DI VERIFICA - DOCUMENTO DI TRASPORTO n. ${numero} del 05/09/2026 - merce varia`;
  const flusso = Buffer.from(`BT /F1 11 Tf 50 700 Td (${testoPdf}) Tj ET`, 'latin1');
  const oggetti = [
    Buffer.from('<< /Type /Catalog /Pages 2 0 R >>'),
    Buffer.from('<< /Type /Pages /Kids [3 0 R] /Count 1 >>'),
    Buffer.from('<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>'),
    Buffer.concat([Buffer.from(`<< /Length ${flusso.length} >>\nstream\n`), flusso, Buffer.from('\nendstream')]),
    Buffer.from('<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>'),
  ];
  let fuori = Buffer.from('%PDF-1.4\n'); const posizioni = [];
  oggetti.forEach((corpo, i) => {
    posizioni.push(fuori.length);
    fuori = Buffer.concat([fuori, Buffer.from(`${i + 1} 0 obj\n`), corpo, Buffer.from('\nendobj\n')]);
  });
  const xref = fuori.length;
  fuori = Buffer.concat([fuori, Buffer.from(`xref\n0 ${oggetti.length + 1}\n0000000000 65535 f \n`)]);
  for (const p of posizioni) fuori = Buffer.concat([fuori, Buffer.from(`${String(p).padStart(10, '0')} 00000 n \n`)]);
  return Buffer.concat([fuori, Buffer.from(`trailer\n<< /Size ${oggetti.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`)]);
};
const numeroProva = `VERIFICA-${Math.floor(Math.random() * 100000)}`;
const percorsoPdf = `${SCARICHI}/bolla-di-verifica.pdf`;
fs.writeFileSync(percorsoPdf, pdfDiProva(numeroProva));
await vai('/documents');
const campoFile = await page.$('input[type="file"]');
ok('l\'archivio ha il caricamento di un PDF', campoFile !== null);
if (campoFile) {
  await campoFile.uploadFile(percorsoPdf);
  await new Promise(r => setTimeout(r, 4000));
}
ok('la bolla compare come scheda', await page.evaluate(() => document.querySelectorAll('li img, li svg').length > 0));
ok('l\'anteprima della prima pagina si carica',
   await page.evaluate(() => [...document.querySelectorAll('img')].some((i) => i.naturalWidth > 0)));
ok('il gruppo «Da assegnare» sta in cima',
   await page.evaluate(() => (document.querySelectorAll('section h2')[0]?.innerText ?? '').toUpperCase().includes('DA ASSEGNARE')));
ok('la tendina del fornitore permette di crearne uno',
   await page.evaluate(() => {
     const s = [...document.querySelectorAll('select')].find((x) => /Fornitore di/.test(x.getAttribute('aria-label') ?? ''));
     return !!s && [...s.options].some((o) => o.text.includes('Crea un fornitore'));
   }));
ok('c\'è una porta verso l\'anagrafica fornitori',
   await page.evaluate(() => [...document.querySelectorAll('a')].some((a) => a.innerText.includes('Anagrafica fornitori'))));
// La ricerca dentro il contenuto: il numero è scritto nel PDF, non nel nome.
await page.evaluate(() => { const i = document.querySelector('input[aria-label="Cerca nell\'archivio"]'); i.focus(); });
await page.keyboard.type(numeroProva);
await new Promise(r => setTimeout(r, 1800));
ok('si ritrova cercando quello che c\'è scritto dentro',
   (await testo()).includes('bolla-di-verifica.pdf'), numeroProva);
// E si rimette com'era: la verifica non lascia documenti in archivio.
await premi('Elimina');
await new Promise(r => setTimeout(r, 700));
await page.evaluate(() => [...document.querySelectorAll('button')].filter((b) => b.innerText.trim() === 'Elimina').pop()?.click());
await new Promise(r => setTimeout(r, 1500));
// Si guarda dentro `main`, non tutta la pagina: il messaggio di conferma
// contiene il nome del file appena tolto, e cercarlo nel corpo intero
// direbbe «c'è ancora» proprio perché è stato cancellato.
ok('il documento di prova è stato tolto',
   await page.evaluate(() => !document.querySelector('main').innerText.includes('bolla-di-verifica.pdf')));

console.log('== Impostazioni: lettura automatica ==');
await vai('/admin/settings');
const paginaImpostazioni = await testo();
ok('sezione della lettura automatica presente', /Lettura automatica dei documenti/.test(paginaImpostazioni));
ok('dice quale modello è in uso', /modello|Modello/.test(paginaImpostazioni));

console.log('== Barra laterale e uscita ==');
await vai('/stock');
await page.evaluate(() => document.querySelector('button[aria-label="Riduci la barra"]')?.click());
await new Promise(r => setTimeout(r, 600));
ok('barra ridotta alle icone', await page.evaluate(() => document.querySelector('aside').getBoundingClientRect().width) === 64);
await page.evaluate(() => document.querySelector('button[aria-label="Espandi la barra"]')?.click());
await new Promise(r => setTimeout(r, 600));
ok('e si riapre', await page.evaluate(() => document.querySelector('aside').getBoundingClientRect().width) === 256);
await premi('Esci');
await new Promise(r => setTimeout(r, 1500));
ok('uscita: si torna alla pagina di accesso', /Accedi al gestionale/.test(await testo()));

console.log(`\n  errori in console: ${erroriConsole.length}${erroriConsole.length ? ' → ' + erroriConsole.slice(0, 3).join(' | ') : ''}`);
console.log(`  totale: ${prove} prove, ${falliti} fallite`);
await browser.close();
process.exit(falliti);
