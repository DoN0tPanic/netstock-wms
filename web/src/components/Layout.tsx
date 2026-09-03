import { useRef, useState } from 'react';
import { Boxes, FileText, FolderSearch, History, LayoutDashboard, MapPin, Menu, ScrollText, Settings, Shield, X } from 'lucide-react';
import { NavLink, Outlet } from 'react-router-dom';
import { Button, Modal } from './ui';
import { GlobalSearch } from './GlobalSearch';
import { useAuth } from '../hooks/useAuth';
import { useBarraRidotta } from '../hooks/useBarraRidotta';
import { useHotkeys } from '../hooks/useHotkeys';
const links = [{ to: '/', label: 'Dashboard', icon: LayoutDashboard }, { to: '/stock', label: 'Magazzino', icon: Boxes }, { to: '/movements', label: 'Movimenti', icon: ScrollText }, { to: '/locations', label: 'Ubicazioni', icon: MapPin }, { to: '/documents', label: 'Archivio bolle', icon: FolderSearch }];
const adminLinks = [{ to: '/admin/users', label: 'Utenti', icon: Shield }, { to: '/admin/templates', label: 'Template estrazione', icon: FileText }, { to: '/admin/audit', label: 'Audit', icon: History }, { to: '/admin/settings', label: 'Impostazioni', icon: Settings }];

// Ridotta, la voce è la sola icona centrata. `title` non è un di più: senza,
// un'icona da sola costringe a indovinare o a riaprire la barra per leggere
// dove porta.
const navClass = (ridotta: boolean) => ({ isActive }: { isActive: boolean }) =>
  `flex items-center gap-3 rounded-lg py-2 ${ridotta ? 'px-3 lg:justify-center lg:px-0' : 'px-3'} ${isActive ? 'bg-blue-600' : 'hover:bg-blue-800'}`;

export function Layout() {
  const { session, logout } = useAuth();
  const [menu, setMenu] = useState(false);
  const [help, setHelp] = useState(false);
  // La riduzione vale solo da `lg` in su: sotto, la barra è un cassetto che si
  // apre e si chiude, e ridurla a icone non libererebbe niente.
  const [ridotta, alterna] = useBarraRidotta();
  const searchRef = useRef<HTMLInputElement>(null);
  useHotkeys({ '?': () => setHelp(true), '/': () => searchRef.current?.focus() });
  const scostamento = ridotta ? 'lg:ml-16' : 'lg:ml-64';
  const voce = navClass(ridotta);
  return <div className="min-h-screen">
    <header className={`sticky top-0 z-30 flex h-16 items-center justify-between border-b bg-white px-4 transition-[margin] ${scostamento}`}>
      <button className="lg:hidden shrink-0" aria-label="Apri menu" onClick={() => setMenu(true)}><Menu/></button>
      <GlobalSearch ref={searchRef}/>
      <div className="flex items-center gap-2"><span className="hidden text-sm xl:block">{session?.full_name}</span><Button variant="ghost" onClick={() => setHelp(true)}>?</Button><Button variant="secondary" onClick={() => void logout()}>Esci</Button></div>
    </header>
    <aside id="barra-laterale" className={`fixed inset-y-0 left-0 z-40 w-64 overflow-y-auto overflow-x-hidden bg-blue-900 py-4 text-white transition-[transform,width] ${menu ? '' : '-translate-x-full'} lg:translate-x-0 ${ridotta ? 'px-4 lg:w-16 lg:px-2' : 'px-4 lg:w-64'}`}>
      <div className="mb-6 flex items-center justify-between gap-2">
        {/* Ridotta il marchio sparisce: in 64 pixel non ci sta accanto a un
            comando, e il posto in cima lo tiene il pulsante — che è quello
            che si cerca quando la barra è chiusa. */}
        <span className={`text-xl font-bold ${ridotta ? 'lg:hidden' : ''}`}>NetStock</span>
        {/* `aria-label` esplicita: il pulsante è una sola icona, senza nome
            accessibile un lettore di schermo leggerebbe «pulsante». */}
        <button type="button" onClick={alterna} aria-expanded={!ridotta} aria-controls="barra-laterale" aria-label={ridotta ? 'Espandi la barra' : 'Riduci la barra'} title={ridotta ? 'Espandi la barra' : 'Riduci la barra'} className={`hidden rounded-lg p-2 text-slate-300 hover:bg-blue-800 hover:text-white lg:block ${ridotta ? 'lg:mx-auto' : ''}`}>
          <Menu size={20}/>
        </button>
        <button className="lg:hidden" aria-label="Chiudi menu" onClick={() => setMenu(false)}><X/></button>
      </div>
      <nav className="space-y-1">
        {links.map(({ to, label, icon: Icon }) => <NavLink end={to === '/'} key={to} to={to} title={label} onClick={() => setMenu(false)} className={voce}><Icon size={19} className="shrink-0"/><span className={ridotta ? 'lg:hidden' : ''}>{label}</span></NavLink>)}
        {session?.role === 'admin' && <>
          {/* Ridotta l'intestazione della sezione non ci sta: al suo posto una
              riga che separa, così le voci di amministrazione restano
              riconoscibili come gruppo. */}
          <div className={`pt-5 text-xs uppercase text-slate-400 ${ridotta ? 'lg:hidden' : ''}`}>Amministrazione</div>
          <div className={`my-3 border-t border-blue-800 ${ridotta ? 'hidden lg:block' : 'hidden'}`}/>
          {adminLinks.map(({ to, label, icon: Icon }) => <NavLink key={to} to={to} title={label} onClick={() => setMenu(false)} className={voce}><Icon size={19} className="shrink-0"/><span className={ridotta ? 'lg:hidden' : ''}>{label}</span></NavLink>)}
        </>}
      </nav>
    </aside>
    <main className={`p-4 transition-[margin] lg:p-8 ${scostamento}`}><Outlet/></main>
    <Modal open={help} title="Scorciatoie da tastiera" onClose={() => setHelp(false)}><dl className="grid grid-cols-[auto_1fr] gap-3"><kbd>/</kbd><dd>Metti a fuoco la ricerca globale</dd><kbd>Invio</kbd><dd>Conferma un seriale durante la scansione</dd><kbd>Esc</kbd><dd>Chiude la finestra aperta</dd><kbd>?</kbd><dd>Apre questo riepilogo</dd></dl></Modal>
  </div>;
}
