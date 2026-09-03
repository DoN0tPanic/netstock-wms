import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Plus, AlertTriangle, Columns3, SlidersHorizontal } from "lucide-react";
import { Bar, BarChart, CartesianGrid, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { catalogApi, categoriesApi, deliveryNotesApi, exportApi, inventoryApi, locationsApi, movementsApi, suppliersApi, unitsApi, vendorsApi } from "../api";
import {
  useCategories,
  useCatalog,
  useDashboard,
  useDeliveryNotes,
  useInventory,
  useLocations,
  useMovements,
  useSuppliers,
  useVendors,
} from "../api/queries";
import { COLONNE_MAGAZZINO, COLONNE_PREDEFINITE, leggiColonne, scriviColonne, type ColonnaMagazzino } from "./inventoryColumns";
import { percorsoUbicazione } from "../lib/locations";
import { CatalogItemModal } from "../components/forms/CatalogItemModal";
import { ReceiveForm } from "../components/forms/ReceiveForm";
import { Badge, Button, Combobox, Input, Modal, Select, Table, useToast } from "../components/ui";
import { formatDate, formatDateTime, formatQuantity } from "../lib/format";
import { useAuth } from "../hooks/useAuth";
import { can } from "../lib/permissions";
import { ErrorMessage, Loading, Page } from "./common";
import { readInventoryFilters, type InventoryFilters } from "./inventoryFilters";
import type { BulkItemRequest, CatalogItem, Category, DeliveryNote, InventoryRow, ItemCondition, Location, LocationType, MovementType, StockAvailability, StockMovement, Supplier, UnitStatus, Vendor } from "../types/api";

// One place for the user-facing wording of the backend enums, so a status
// never shows up as a raw English identifier in one table and translated in
// the next.
// `lost` is only ever reached by reversing a carico (the adjust endpoint has
// no UI), so it means "that receipt should never have been recorded" rather
// than a piece gone missing — hence the wording.
export const unitStatusLabels: Record<UnitStatus, string> = { in_stock: "In magazzino", reserved: "Prenotato", issued: "Consegnato", in_rma: "In RMA", scrapped: "Rottamato", lost: "Rimosso per errore di inserimento" };
export const conditionLabels: Record<ItemCondition, string> = { new: "Nuovo", refurbished: "Ricondizionato", used: "Usato", faulty: "Guasto" };
const statusTone = (status: UnitStatus) => status === "scrapped" || status === "lost" ? "danger" : status === "in_stock" ? "success" : "warning";

// Moving between locations is the only bulk movement the app offers: per the
// product model, goods never leave the archive — a destination (a person, a
// customer site, a van) is modelled as a location, so there is no "issue"
// counterpart here.
function TransferModal({ open, locations, destinationId, moving, setDestinationId, onClose, onConfirm, subject = "righe selezionate" }: {
  open: boolean;
  locations: Location[];
  destinationId: string;
  moving: boolean;
  setDestinationId: (value: string) => void;
  onClose: () => void;
  onConfirm: () => void;
  subject?: string;
}) {
  return <Modal open={open} title={`Sposta ${subject}`} onClose={onClose}><div className="space-y-4"><Select label="Ubicazione di destinazione" required value={destinationId} onChange={(event) => setDestinationId(event.target.value)}><option value="">Seleziona…</option>{locations.map((location) => <option key={location.id} value={location.id}>{percorsoUbicazione(locations, location.id)}</option>)}</Select><Button loading={moving} disabled={!destinationId} onClick={onConfirm}>Conferma spostamento</Button></div></Modal>;
}

export function Dashboard() {
  const query = useDashboard();
  const { session } = useAuth();
  // Serve solo al riquadro delle anomalie, che mostra un'ubicazione: senza,
  // lì resterebbe il codice nudo che questa pagina non spiega a nessuno.
  const ubicazioni = useLocations();
  if (query.isLoading) return <Loading />;
  if (query.isError || !query.data) return <ErrorMessage />;
  const data = query.data;
  return (
    <Page title="Dashboard" description="Situazione aggiornata del magazzino">
      <div className="grid gap-4 sm:grid-cols-3">
        <Card label="Sotto scorta" value={String(data.below_reorder.length)} warning={data.below_reorder.length > 0}/>
        <Card label="Bolle aperte" value={String(data.open_delivery_notes)}/>
        <Card label="Garanzie in scadenza" value={String(data.expiring_warranties.length)} warning={data.expiring_warranties.length > 0}/>
      </div>
      {session?.role === "admin" && data.reconciliation_errors > 0 && (
        <section className="space-y-3 rounded-xl border border-amber-300 bg-amber-50 p-4">
          <div>
            <h2 className="font-semibold text-amber-900">{data.reconciliation_errors === 1 ? "Una quantità non torna" : `${data.reconciliation_errors} quantità non tornano`}</h2>
            <p className="text-sm text-amber-900">Per questi articoli il numero di pezzi <em>registrato dai movimenti</em> non coincide con quello <em>effettivamente a scaffale</em>. Di solito è il segno di una correzione fatta a metà.</p>
          </div>
          <div className="overflow-x-auto rounded-lg border border-amber-200 bg-white">
            <table className="w-full text-left text-sm">
              <thead className="bg-amber-100/60"><tr><th className="px-3 py-2 font-semibold">Articolo</th><th className="px-3 py-2 font-semibold">Ubicazione</th><th className="px-3 py-2 font-semibold">Dai movimenti</th><th className="px-3 py-2 font-semibold">A scaffale</th></tr></thead>
              <tbody className="divide-y divide-amber-100">
                {data.reconciliation_error_rows.map((row, index) => (
                  <tr key={`${row.catalog_item_id}-${row.location_id ?? "none"}-${index}`}>
                    <td className="px-3 py-2"><strong>{row.part_number ?? "—"}</strong><div className="text-xs text-slate-500">{row.catalog_item_name}</div></td>
                    <td className="px-3 py-2">{percorsoUbicazione(ubicazioni.data?.items ?? [], row.location_id)}</td>
                    <td className="px-3 py-2">{formatQuantity(Number(row.qty_ledger))}</td>
                    <td className="px-3 py-2">{formatQuantity(Number(row.qty_projection))}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-sm text-amber-900"><strong>Cosa fare:</strong> conta fisicamente i pezzi nelle ubicazioni elencate. Se lo scarto nasce da un movimento registrato male, stornalo dai <Link className="underline" to="/movements">Movimenti</Link>: è il modo pulito, perché rimette a posto sia il conteggio sia la storia. L&apos;avviso sparisce da solo appena i due numeri coincidono. Nel frattempo puoi continuare a lavorare: la segnalazione non blocca nulla.</p>
        </section>
      )}
      {/* Barre orizzontali: i nomi delle categorie sono parole, e su un asse
          verticale si accavallerebbero o andrebbero ruotate. Una serie sola,
          quindi nessuna legenda — il titolo la nomina — e il valore scritto in
          fondo a ogni barra al posto dell'asse, che sarebbe la stessa
          informazione due volte. L'altezza cresce con le categorie invece di
          essere fissa: a tre resterebbe mezzo riquadro vuoto, a dodici
          starebbero strette. */}
      <section>
        <h2 className="mb-3 text-lg font-semibold">Giacenza per categoria</h2>
        <div className="rounded-xl border border-slate-200 bg-white p-4">
          {data.total_by_category.length ? (
            <ResponsiveContainer width="100%" height={Math.max(120, data.total_by_category.length * 42 + 16)}>
              <BarChart data={data.total_by_category} layout="vertical" margin={{ top: 4, right: 60, bottom: 4, left: 4 }}>
                <CartesianGrid horizontal={false} stroke="#e8e8e6"/>
                <XAxis type="number" hide/>
                <YAxis type="category" dataKey="category_name" width={140} tickLine={false} axisLine={false} tick={{ fill: "#52514e", fontSize: 13 }}/>
                <Tooltip cursor={{ fill: "rgba(15,23,42,0.04)" }} formatter={(value) => [formatQuantity(Number(value), "pz"), "In giacenza"] as [string, string]}/>
                <Bar dataKey="quantity" fill="#2a6fb8" radius={[0, 4, 4, 0]} maxBarSize={18} isAnimationActive={false}>
                  <LabelList dataKey="quantity" position="right" fill="#0b0b0b" fontSize={13} formatter={(value: ReactNode) => formatQuantity(Number(value), "pz")}/>
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <p className="py-6 text-center text-slate-500">Nessuna giacenza da mostrare: il grafico comparirà dopo il primo carico.</p>
          )}
        </div>
      </section>
      <h2 className="text-lg font-semibold">Articoli sotto soglia</h2>
      <StockTable rows={data.below_reorder} />
      <h2 className="text-lg font-semibold">Ultimi movimenti</h2>
      <Table rows={data.recent_movements} keyOf={(row) => row.id} empty="Nessun movimento registrato." columns={[{ key: "date", label: "Data", render: (row) => formatDateTime(row.occurred_at) }, { key: "type", label: "Tipo", render: (row) => movementTypeLabels[row.type] ?? row.type }, { key: "what", label: "Pezzo", render: (row) => row.part_number ?? "—" }, { key: "quantity", label: "Quantità", render: (row) => formatQuantity(row.quantity) }, { key: "reference", label: "Riferimento", render: (row) => row.reference ?? "—" }]}/>
      <h2 className="text-lg font-semibold">Garanzie in scadenza</h2>
      <Table rows={data.expiring_warranties} keyOf={(row) => row.id} empty="Nessuna garanzia in scadenza nei prossimi 60 giorni." columns={[{ key: "serial", label: "Seriale", render: (row) => <Link className="text-blue-700 underline" to={`/units/${row.id}`}>{row.serial_number}</Link> }, { key: "warranty", label: "Scadenza garanzia", render: (row) => formatDate(row.warranty_end) }]}/>
    </Page>
  );
}
/** Riquadro di sintesi.
 *
 * Lo stato di allerta non è affidato al solo colore del bordo: chi non
 * distingue l'ambra dal grigio vedrebbe tre riquadri identici. Accanto al
 * numero compare un'icona con la sua parola.
 */
function Card({
  label,
  value,
  warning,
  hint,
}: {
  label: string;
  value: string;
  warning?: boolean;
  hint?: string;
}) {
  return (
    <div className={`rounded-xl border p-5 ${warning ? "border-amber-400 bg-amber-50" : "border-slate-200 bg-white"}`}>
      <p className="text-sm text-slate-600">{label}</p>
      <p className="mt-1 text-3xl font-semibold text-slate-900">{value}</p>
      {warning ? (
        <p className="mt-2 flex items-center gap-1.5 text-sm font-medium text-amber-800">
          <AlertTriangle size={15} aria-hidden/>Da controllare
        </p>
      ) : (
        hint && <p className="mt-2 text-sm text-slate-500">{hint}</p>
      )}
    </div>
  );
}
function StockTable({
  rows,
}: {
  rows: StockAvailability[];
}) {
  return (
    <Table
      rows={rows}
      keyOf={(row) => row.catalog_item_id}
      empty="Nessuna giacenza disponibile. Registra una bolla da Ricevi merce."
      columns={[
        {
          key: "item",
          label: "Articolo",
          render: (row) => (
            <>
              <strong>{row.part_number}</strong>
              <div>{row.name}</div>
            </>
          ),
        },
        {
          key: "on",
          label: "In giacenza",
          render: (row) => formatQuantity(row.qty_on_hand),
        },
        {
          key: "available",
          label: "Disponibile",
          render: (row) => (
            <Badge tone={row.below_reorder_point ? "warning" : "success"}>
              {formatQuantity(row.qty_available)}
            </Badge>
          ),
        },
        {
          key: "threshold",
          label: "Soglia",
          render: (row) => formatQuantity(row.reorder_point),
        },
      ]}
    />
  );
}
export function Stock() {
  const { session } = useAuth();
  const toast = useToast();
  const queryClient = useQueryClient();
  const storageKey = `netstock:inventory-filters:${session?.username}`;
  const colonneKey = `netstock:inventory-columns:${session?.username}`;
  const [colonne, setColonne] = useState<ColonnaMagazzino[]>(() => leggiColonne(colonneKey));
  const [sceltaColonne, setSceltaColonne] = useState(false);
  const [filters, setFilters] = useState<InventoryFilters>(() => readInventoryFilters(storageKey));
  const locations = useLocations(); const vendors = useVendors(); const categories = useCategories();
  const queryParams = { ...filters, page_size: 25 };
  const query = useInventory(queryParams);
  const [selected, setSelected] = useState<Map<string, InventoryRow>>(new Map());
  const [filtriAperti, setFiltriAperti] = useState(false);
  const [transferring, setTransferring] = useState(false);
  const [destinationId, setDestinationId] = useState("");
  const [moving, setMoving] = useState(false);
  useEffect(() => { localStorage.setItem(storageKey, JSON.stringify(filters)); }, [filters, storageKey]);
  useEffect(() => { scriviColonne(colonneKey, colonne); }, [colonne, colonneKey]);
  // L'ordine è quello dichiarato in COLONNE_MAGAZZINO, non quello in cui sono
  // state spuntate: una tabella che cambia ordine a ogni scelta si rilegge da capo.
  const alternaColonna = (chiave: ColonnaMagazzino) => setColonne((attuali) => attuali.includes(chiave)
    ? attuali.filter((voce) => voce !== chiave)
    : COLONNE_MAGAZZINO.filter((colonna) => attuali.includes(colonna.chiave) || colonna.chiave === chiave).map((colonna) => colonna.chiave));
  const change = (key: keyof InventoryFilters, value: string | number) => setFilters((current) => ({ ...current, [key]: value, page: key === "page" ? Number(value) : 1 }));
  // L'ancora viene agganciata al documento e l'indirizzo temporaneo liberato
  // dopo, non nello stesso istante del clic: revocarlo subito può annullare
  // lo scaricamento appena avviato.
  const scarica = (blob: Blob, nome: string) => {
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url; anchor.download = nome; anchor.style.display = "none";
    document.body.appendChild(anchor);
    anchor.click();
    window.setTimeout(() => { anchor.remove(); URL.revokeObjectURL(url); }, 0);
  };
  const exportCsv = async () => { try { scarica(await inventoryApi.export("csv", { q: filters.q, location: filters.location, vendor: filters.vendor, category: filters.category, condition: filters.condition, status: filters.status }), "magazzino.csv"); } catch { toast.show("Impossibile esportare il magazzino.", "error"); } };
  // Il CSV qui sopra è quello che si sta guardando, filtri compresi. Questo è
  // tutt'altro: ogni tabella del magazzino in un file, in un archivio solo,
  // per chi deve portare via i dati e non una schermata.
  const [esportando, setEsportando] = useState(false);
  const exportAll = async () => {
    setEsportando(true);
    try {
      scarica(await exportApi.everything(), `netstock-${new Date().toISOString().slice(0, 10)}.zip`);
      toast.show("Esportazione completa scaricata.", "success");
    } catch { toast.show("Impossibile generare l'esportazione completa.", "error"); }
    finally { setEsportando(false); }
  };
  const actionClass = "inline-flex min-h-9 items-center rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium hover:bg-slate-50";
  const rows = query.data?.items ?? [];
  const attivi = [filters.q, filters.location, filters.vendor, filters.category, filters.condition, filters.status].filter(Boolean).length;
  const hasFilters = attivi > 0;
  const allVisibleSelected = rows.length > 0 && rows.every((row) => selected.has(row.row_key));
  const toggle = (row: InventoryRow) => setSelected((current) => { const next = new Map(current); if (next.has(row.row_key)) next.delete(row.row_key); else next.set(row.row_key, row); return next; });
  const toggleAll = () => setSelected((current) => { const next = new Map(current); if (allVisibleSelected) rows.forEach((row) => next.delete(row.row_key)); else rows.forEach((row) => next.set(row.row_key, row)); return next; });
  const closeAction = () => { if (!moving) setTransferring(false); };
  const runTransfer = async () => {
    if (!destinationId) return;
    // Rows are grouped by their current location because each transfer
    // movement records a single from→to pair in the ledger.
    const groups = new Map<string, InventoryRow[]>();
    selected.forEach((row) => { const key = row.location_id ?? ""; groups.set(key, [...(groups.get(key) ?? []), row]); });
    setMoving(true);
    const results = await Promise.all([...groups.entries()].map(async ([locationId, group]) => {
      const label = percorsoUbicazione(locations.data?.items ?? [], group[0]?.location_id, "senza ubicazione");
      const unitIds = group.filter((row) => row.kind === "unit").map((row) => row.row_key);
      const bulkItems: BulkItemRequest[] = group.filter((row) => row.kind === "bulk").map((row) => ({ catalog_item_id: row.catalog_item_id, quantity: Number(row.quantity), condition: row.condition }));
      // Bulk quantities have no identity to follow, so they genuinely need a
      // source location; serialized units without one can still be placed.
      if (!locationId && bulkItems.length) return { label, ok: false, error: "materiale sfuso senza ubicazione di partenza" };
      try {
        await movementsApi.transfer({ location_from_id: locationId || null, location_to_id: destinationId, unit_ids: unitIds, bulk_items: bulkItems });
        return { label, ok: true, error: "" };
      } catch (reason) { return { label, ok: false, error: reason instanceof Error ? reason.message : "errore sconosciuto" }; }
    }));
    const succeeded = results.filter((result) => result.ok);
    const failed = results.filter((result) => !result.ok);
    const detail = failed.map((result) => `${result.label}: ${result.error}`).join("; ");
    toast.show(failed.length ? `Spostamento parziale: ${succeeded.length} riusciti, ${failed.length} falliti. ${detail}` : `Spostamento completato.`, failed.length ? "error" : "success");
    setSelected(new Map()); setTransferring(false); setDestinationId("");
    await queryClient.invalidateQueries({ queryKey: ["inventory"] });
    setMoving(false);
  };
  return (
    <Page
      title="Magazzino"
      description="Unità serializzate e materiale sfuso"
      actions={<>{can(session?.role, "operate") && <Link className="inline-flex min-h-9 items-center gap-2 rounded-lg bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700" to="/receive"><Plus size={17}/>Aggiungi merce</Link>}<Link className={actionClass} to="/delivery-notes">Bolle</Link><Link className={actionClass} to="/catalog">Catalogo</Link><Link className={actionClass} to="/vendors">Vendor</Link><Link className={actionClass} to="/categories">Categorie</Link><Link className={actionClass} to="/suppliers">Fornitori</Link></>}
    >
      {/* Su telefono i sei filtri occupavano tutto il primo schermo: si arrivava
          alla merce solo dopo averli scorsi tutti. Richiusi dietro un riepilogo
          che dice quanti ne sono attivi — e aperti da subito se qualcuno lo è,
          perché un elenco filtrato senza dirlo è peggio di un filtro nascosto.
          Da tablet in su restano sempre visibili, lo spazio c'è. */}
      {/* Niente <details>: il suo contenuto resta nascosto finché l'elemento
          non è `open`, e su schermo largo non lo apre nessuno — i filtri
          sparivano del tutto. Qui la visibilità è decisa dalle classi, che
          sanno rispondere alla larghezza: nascosti sul telefono finché non li
          si apre, sempre presenti da tablet in su. */}
      <div className="rounded-xl border border-slate-200 bg-white">
        <button type="button" aria-expanded={filtriAperti || hasFilters} className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left font-medium md:hidden" onClick={() => setFiltriAperti((valore) => !valore)}>
          <span className="flex items-center gap-2"><SlidersHorizontal size={17} aria-hidden/>Filtri</span>
          <span className="text-sm font-normal text-slate-600">{attivi ? `${attivi} attiv${attivi === 1 ? "o" : "i"}` : "nessuno"}</span>
        </button>
      <div className={`${filtriAperti || hasFilters ? "grid" : "hidden"} gap-3 p-4 md:grid md:grid-cols-3 xl:grid-cols-6`}><Input aria-label="Cerca nel magazzino" placeholder="Seriale, MAC, modello, bolla" value={filters.q} onChange={(event) => change("q", event.target.value)}/><Select aria-label="Ubicazione" value={filters.location} onChange={(event) => change("location", event.target.value)}><option value="">Tutte le ubicazioni</option>{locations.data?.items.map((row) => <option key={row.id} value={row.id}>{percorsoUbicazione(locations.data?.items ?? [], row.id)}</option>)}</Select><Select aria-label="Vendor" value={filters.vendor} onChange={(event) => change("vendor", event.target.value)}><option value="">Tutti i vendor</option>{vendors.data?.items.map((row) => <option key={row.id} value={row.id}>{row.code} — {row.name}</option>)}</Select><Select aria-label="Categoria" value={filters.category} onChange={(event) => change("category", event.target.value)}><option value="">Tutte le categorie</option>{categories.data?.items.map((row) => <option key={row.id} value={row.id}>{row.code} — {row.name}</option>)}</Select><Select aria-label="Condizione" value={filters.condition} onChange={(event) => change("condition", event.target.value)}><option value="">Tutte le condizioni</option>{(Object.keys(conditionLabels) as ItemCondition[]).map((value) => <option key={value} value={value}>{conditionLabels[value]}</option>)}</Select><Select aria-label="Stato" value={filters.status} onChange={(event) => change("status", event.target.value)}><option value="">Tutti gli stati</option>{(Object.keys(unitStatusLabels) as UnitStatus[]).map((value) => <option key={value} value={value}>{unitStatusLabels[value]}</option>)}</Select></div>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-slate-600" aria-live="polite">{query.data ? `${query.data.total} ${query.data.total === 1 ? "riga" : "righe"}` : ""}</p>
        <div className="flex flex-wrap gap-2"><Button variant="ghost" onClick={() => setSceltaColonne(true)}><Columns3 size={17}/>Colonne</Button><Button variant="secondary" onClick={() => void exportCsv()}>Esporta CSV</Button><Button variant="ghost" loading={esportando} onClick={() => void exportAll()}>Esporta tutto (ZIP)</Button></div>
      </div>
      {selected.size > 0 && <div className="flex flex-wrap items-center gap-3 rounded-xl border border-blue-200 bg-blue-50 p-3"><strong className="text-sm">{selected.size} righe selezionate</strong><Button onClick={() => setTransferring(true)}>Sposta</Button><Button variant="ghost" onClick={() => setSelected(new Map())}>Deseleziona</Button></div>}
      {query.isLoading ? <Loading/> : query.isError || !query.data ? <ErrorMessage/> : <><Table rows={query.data.items} keyOf={(row) => row.row_key} empty={hasFilters
          ? <span>Nessun pezzo corrisponde ai filtri. <button type="button" className="text-blue-700 underline" onClick={() => setFilters({ ...readInventoryFilters(storageKey), q: "", location: "", vendor: "", category: "", condition: "", status: "", page: 1 })}>Azzera i filtri</button></span>
          : <span>Il magazzino è vuoto. Inizia da <Link className="text-blue-700 underline" to="/receive">Aggiungi merce</Link>.</span>} columns={[{ key: "select", label: "", render: (row: InventoryRow) => <input type="checkbox" className="h-4 w-4" aria-label={`Seleziona ${row.part_number}`} checked={selected.has(row.row_key)} onChange={() => toggle(row)}/> }, ...colonne.map((chiave) => inventoryColumns(locations.data?.items ?? [])[chiave])]}/>{rows.length > 0 && <><label className="inline-flex items-center gap-2 text-sm"><input type="checkbox" className="h-4 w-4" checked={allVisibleSelected} onChange={toggleAll}/>Seleziona tutte le righe della pagina</label><div className="flex flex-wrap items-center justify-between gap-3"><span className="text-sm text-slate-600">{query.data.total} righe totali</span>{query.data.total > query.data.page_size && <div className="flex items-center gap-2"><Button variant="secondary" disabled={filters.page <= 1} onClick={() => change("page", filters.page - 1)}>Precedente</Button><span className="text-sm">Pagina {filters.page} di {Math.max(1, Math.ceil(query.data.total / query.data.page_size))}</span><Button variant="secondary" disabled={filters.page * query.data.page_size >= query.data.total} onClick={() => change("page", filters.page + 1)}>Successiva</Button></div>}</div></>}</>}
      <Modal open={sceltaColonne} title="Colonne da mostrare" onClose={() => setSceltaColonne(false)}>
        <div className="space-y-3">
          <p className="text-sm text-slate-600">Vale per te e per questo browser. L'esportazione non ne risente: nel file esce sempre tutto, note comprese.</p>
          <div className="grid gap-2 sm:grid-cols-2">
            {COLONNE_MAGAZZINO.map(({ chiave, etichetta, sempre }) => (
              <label key={chiave} className={`inline-flex min-h-11 items-center gap-2 text-sm ${sempre ? "text-slate-400" : ""}`}>
                <input type="checkbox" className="size-4" checked={colonne.includes(chiave)} disabled={sempre} onChange={() => alternaColonna(chiave)}/>
                {etichetta}{sempre && <span className="text-xs">(sempre)</span>}
              </label>
            ))}
          </div>
          <div className="flex justify-between gap-2">
            <Button variant="ghost" onClick={() => setColonne(COLONNE_PREDEFINITE)}>Ripristina le predefinite</Button>
            <Button onClick={() => setSceltaColonne(false)}>Fatto</Button>
          </div>
        </div>
      </Modal>
      <TransferModal open={transferring} locations={locations.data?.items ?? []} destinationId={destinationId} moving={moving} setDestinationId={setDestinationId} onClose={closeAction} onConfirm={() => void runTransfer()}/>
    </Page>
  );
}

// Ogni colonna disegnata una volta sola, indicizzata per chiave: quali poi
// compaiano lo decide la preferenza di chi guarda (`inventoryColumns.ts`).
const inventoryColumns = (ubicazioni: Location[]): Record<ColonnaMagazzino, { key: string; label: string; render: (row: InventoryRow) => ReactNode }> => ({
  serial: { key: "serial", label: "Seriale / MAC", render: (row) => row.kind === "unit" ? <><Link className="font-medium text-blue-700 underline" to={`/units/${row.row_key}`}>{row.serial_number ?? "—"}</Link>{row.mac_address && <div className="text-xs text-slate-500">{row.mac_address}</div>}</> : "—" },
  model: { key: "model", label: "Modello", render: (row) => <><strong>{row.part_number}</strong><div>{row.name}</div></> },
  vendor: { key: "vendor", label: "Fornitore", render: (row) => row.vendor_code },
  category: { key: "category", label: "Categoria", render: (row) => row.category_code },
  location: { key: "location", label: "Ubicazione", render: (row) => <span title={row.location_code ?? ""}>{percorsoUbicazione(ubicazioni, row.location_id)}</span> },
  condition: { key: "condition", label: "Condizione", render: (row) => <Badge>{conditionLabels[row.condition] ?? row.condition}</Badge> },
  state: { key: "state", label: "Stato / Quantità", render: (row) => row.kind === "bulk" ? <Badge tone="info">{formatQuantity(Number(row.quantity), "pz")} (sfuso)</Badge> : row.status ? <Badge tone={statusTone(row.status)}>{unitStatusLabels[row.status]}</Badge> : "—" },
  note: { key: "note", label: "Bolla", render: (row) => row.delivery_note_number ?? "—" },
  warranty: { key: "warranty", label: "Garanzia", render: (row) => formatDate(row.warranty_end) },
  purchase: { key: "purchase", label: "Data acquisto", render: (row) => formatDate(row.purchase_date) },
  contract: { key: "contract", label: "Riferimento contratto", render: (row) => row.contract_ref ?? "—" },
  // Le note sono testo libero: senza un limite una riga lunga allargherebbe
  // la tabella oltre lo schermo e stringerebbe tutte le altre colonne.
  notes: { key: "notes", label: "Note", render: (row) => row.notes ? <span className="line-clamp-2 max-w-56 whitespace-pre-wrap" title={row.notes}>{row.notes}</span> : "—" },
});

export function UnitDetail() {
  const { id = "" } = useParams();
  const toast = useToast();
  const queryClient = useQueryClient();
  const locations = useLocations();
  const { session } = useAuth();
  const [editingDetails, setEditingDetails] = useState(false);
  const [detailsDraft, setDetailsDraft] = useState({ serial_number: "", mac_address: "", location_id: "", warranty_end: "", contract_ref: "", notes: "" });
  const [savingDetails, setSavingDetails] = useState(false);
  const [deliveryNoteQuery, setDeliveryNoteQuery] = useState("");
  const [deliveryNoteOptions, setDeliveryNoteOptions] = useState<DeliveryNote[]>([]);
  const [deliveryNoteSearching, setDeliveryNoteSearching] = useState(false);
  const [attachingNote, setAttachingNote] = useState(false);
  const [scrapping, setScrapping] = useState(false);
  const [scrapReason, setScrapReason] = useState("");
  const [showScrap, setShowScrap] = useState(false);
  const query = useQuery({
    queryKey: ["unit", id],
    queryFn: () => unitsApi.get(id),
    enabled: Boolean(id),
  });
  // GET /units/{id} never embeds movements (see StockUnitResponse in the
  // backend) — the timeline lives behind its own endpoint. Fetching it
  // separately here fixes a timeline that was silently empty for every unit.
  const movementsQuery = useQuery({
    queryKey: ["unit", id, "movements"],
    queryFn: () => unitsApi.movements(id),
    enabled: Boolean(id),
  });
  useEffect(() => {
    if (!editingDetails || query.data?.delivery_note_line_id) return;
    setDeliveryNoteSearching(true);
    const timer = window.setTimeout(() => {
      void deliveryNotesApi
        .list({ q: deliveryNoteQuery || undefined, page_size: 8 })
        .then((page) => setDeliveryNoteOptions(page.items))
        .catch(() => {})
        .finally(() => setDeliveryNoteSearching(false));
    }, 300);
    return () => window.clearTimeout(timer);
  }, [deliveryNoteQuery, editingDetails, query.data?.delivery_note_line_id]);
  const attachNote = async (deliveryNoteId: string) => {
    setAttachingNote(true);
    try {
      await unitsApi.attachDeliveryNote(id, deliveryNoteId);
      toast.show("Bolla collegata.", "success");
      setDeliveryNoteQuery("");
      await Promise.all([queryClient.invalidateQueries({ queryKey: ["unit", id] }), queryClient.invalidateQueries({ queryKey: ["inventory"] })]);
    } catch (reason) {
      toast.show(reason instanceof Error ? reason.message : "Impossibile collegare la bolla.", "error");
    } finally { setAttachingNote(false); }
  };
  const scrapUnit = async () => {
    const unit = query.data;
    if (!unit || !unit.location_id || scrapReason.trim().length < 10) return;
    setScrapping(true);
    try {
      await movementsApi.scrap({
        reason: scrapReason.trim(),
        location_from_id: unit.location_id,
        unit_id: unit.id,
      });
      toast.show("Pezzo rottamato.", "success");
      setShowScrap(false);
      setScrapReason("");
      await Promise.all([queryClient.invalidateQueries({ queryKey: ["unit", id] }), queryClient.invalidateQueries({ queryKey: ["inventory"] })]);
    } catch (reason) {
      toast.show(reason instanceof Error ? reason.message : "Impossibile rottamare il pezzo.", "error");
    } finally { setScrapping(false); }
  };
  const openDetailsEditor = () => {
    const unit = query.data;
    if (!unit) return;
    setDetailsDraft({
      serial_number: unit.serial_number,
      mac_address: unit.mac_address ?? "",
      location_id: unit.location_id ?? "",
      warranty_end: unit.warranty_end ?? "",
      contract_ref: unit.contract_ref ?? "",
      notes: unit.notes ?? "",
    });
    setEditingDetails(true);
  };
  const saveDetails = async () => {
    const unit = query.data;
    if (!unit) return;
    setSavingDetails(true);
    try {
      // Location is deliberately never a plain field edit: it always goes
      // through a real transfer movement, so the ledger stays the single
      // source of truth for where a piece is and when it moved there.
      if (detailsDraft.location_id && detailsDraft.location_id !== unit.location_id) {
        await movementsApi.transfer({
          // L'ora la mette il server: quella del browser può essere avanti, e
          // un movimento «nel futuro» verrebbe rifiutato.
          location_from_id: unit.location_id,
          location_to_id: detailsDraft.location_id,
          unit_ids: [unit.id],
          bulk_items: [],
        });
      }
      await unitsApi.update(id, {
        serial_number: detailsDraft.serial_number.trim(),
        mac_address: detailsDraft.mac_address.trim() || null,
        warranty_end: detailsDraft.warranty_end || null,
        contract_ref: detailsDraft.contract_ref.trim() || null,
        notes: detailsDraft.notes.trim() || null,
      });
      toast.show("Dettagli aggiornati.", "success");
      setEditingDetails(false);
      await Promise.all([queryClient.invalidateQueries({ queryKey: ["unit", id] }), queryClient.invalidateQueries({ queryKey: ["inventory"] })]);
      // ["unit", id] also matches ["unit", id, "movements"] as a prefix, so the line above already covers it.
    } catch (reason) {
      toast.show(reason instanceof Error ? reason.message : "Impossibile salvare i dettagli.", "error");
    } finally { setSavingDetails(false); }
  };
  if (query.isLoading) return <Loading />;
  if (query.isError || !query.data) return <ErrorMessage />;
  const unit = query.data;
  return (
    <Page
      title={unit.serial_number}
      description="Dettaglio e cronologia completa"
      actions={<>{can(session?.role, "operate") && <Button variant="secondary" onClick={openDetailsEditor}>Modifica</Button>}{can(session?.role, "adjust") && unit.status !== "scrapped" && <Button variant="danger" onClick={() => setShowScrap(true)}>Rottama</Button>}</>}
    >
      <div className="grid gap-4 rounded-xl border bg-white p-5 sm:grid-cols-3">
        <Data label="Seriale" value={unit.serial_number} />
        <Data label="MAC" value={unit.mac_address ?? "—"} />
        <Data label="Stato" value={unitStatusLabels[unit.status] ?? unit.status} />
        {/* Il percorso, non il codice: «001» dice dove andare solo a chi il
            magazzino ce l'ha già in testa. Il codice resta sotto, in piccolo,
            perché è quello che si scrive sull'etichetta dello scaffale e
            quello con cui l'import riconosce l'ubicazione. */}
        <Data label="Ubicazione" value={<>{percorsoUbicazione(locations.data?.items ?? [], unit.location_id)}{unit.location_code && <div className="text-xs font-normal text-slate-500">{unit.location_code}</div>}</>} />
        <Data label="Modello" value={unit.part_number ? `${unit.part_number} · ${unit.catalog_item_name}` : "—"} />
        <Data label="Bolla" value={unit.delivery_note_number ?? "—"} />
        <Data label="Condizione" value={conditionLabels[unit.condition] ?? unit.condition} />
        <Data label="Garanzia" value={formatDate(unit.warranty_end)} />
        <Data label="Riferimento contratto" value={unit.contract_ref ?? "—"} />
        <Data label="Note" value={unit.notes ?? "—"} />
      </div>
      <Modal open={editingDetails} onClose={() => !savingDetails && setEditingDetails(false)} title="Modifica unità">
        <div className="space-y-3">
          <Input label="Seriale" required value={detailsDraft.serial_number} onChange={(e) => setDetailsDraft({ ...detailsDraft, serial_number: e.target.value })} />
          <Input label="MAC" value={detailsDraft.mac_address} onChange={(e) => setDetailsDraft({ ...detailsDraft, mac_address: e.target.value })} />
          <Select label="Ubicazione" value={detailsDraft.location_id} onChange={(e) => setDetailsDraft({ ...detailsDraft, location_id: e.target.value })}>
            <option value="">Seleziona…</option>
            {(locations.data?.items ?? []).map((location) => <option key={location.id} value={location.id}>{percorsoUbicazione(locations.data?.items ?? [], location.id)}</option>)}
          </Select>
          <p className="text-sm text-slate-500">Modello: {unit.part_number ? `${unit.part_number} · ${unit.catalog_item_name}` : "—"}{unit.delivery_note_line_id && ` · Bolla: ${unit.delivery_note_number ?? "—"}`} <span className="block text-xs">Non modificabili qui: per correggere un errore di ricezione, rottama questo pezzo e ricevine uno nuovo.</span></p>
          {!unit.delivery_note_line_id && <Combobox
            label="Bolla"
            placeholder="Cerca per numero bolla…"
            query={deliveryNoteQuery}
            onQueryChange={setDeliveryNoteQuery}
            loading={deliveryNoteSearching}
            disabled={attachingNote}
            options={deliveryNoteOptions.map((note) => ({ id: note.id, label: note.number, sublabel: note.note_date }))}
            onSelect={(noteId) => void attachNote(noteId)}
            hint="Questo pezzo è stato ricevuto senza bolla: collegala qui appena disponibile."
          />}
          <Input label="Scadenza garanzia" type="date" value={detailsDraft.warranty_end} onChange={(e) => setDetailsDraft({ ...detailsDraft, warranty_end: e.target.value })} />
          <Input label="Riferimento contratto" value={detailsDraft.contract_ref} onChange={(e) => setDetailsDraft({ ...detailsDraft, contract_ref: e.target.value })} />
          <Input label="Note" value={detailsDraft.notes} onChange={(e) => setDetailsDraft({ ...detailsDraft, notes: e.target.value })} />
          <div className="flex justify-end gap-2">
            <Button variant="secondary" disabled={savingDetails} onClick={() => setEditingDetails(false)}>Annulla</Button>
            <Button disabled={savingDetails || !detailsDraft.serial_number.trim()} onClick={() => void saveDetails()}>Salva</Button>
          </div>
        </div>
      </Modal>
      <Modal open={showScrap} onClose={() => !scrapping && setShowScrap(false)} title="Rottama unità">
        <div className="space-y-3">
          <p className="text-sm text-slate-600">Registra questo pezzo come rottamato. Puoi sempre correggere per errore assegnandogli di nuovo un&apos;ubicazione da &quot;Modifica&quot;.</p>
          {!unit.location_id && <p className="text-sm text-red-700">Il pezzo non ha un&apos;ubicazione nota: assegnane una da &quot;Modifica&quot; prima di poterlo rottamare.</p>}
          <Input label="Motivo (minimo 10 caratteri)" required value={scrapReason} onChange={(e) => setScrapReason(e.target.value)} />
          <div className="flex justify-end gap-2">
            <Button variant="secondary" disabled={scrapping} onClick={() => setShowScrap(false)}>Annulla</Button>
            <Button variant="danger" disabled={scrapping || !unit.location_id || scrapReason.trim().length < 10} onClick={() => void scrapUnit()}>Rottama</Button>
          </div>
        </div>
      </Modal>
      <h2 className="text-lg font-semibold">Timeline movimenti</h2>
      {movementsQuery.isLoading ? <Loading /> : <Table
        rows={movementsQuery.data ?? []}
        keyOf={(row) => row.id}
        empty="Nessun movimento registrato per questa unità."
        columns={[
          {
            key: "when",
            label: "Quando",
            render: (row) => formatDateTime(row.occurred_at),
          },
          // `receipt` è la lingua dello schema, non quella di chi legge la
          // cronologia di un apparato: le etichette esistono già, mancava
          // solo di usarle qui. E l'ubicazione di arrivo, che di un movimento
          // è la metà che interessa.
          { key: "type", label: "Operazione", render: (row) => movementTypeLabels[row.type] ?? row.type },
          { key: "where", label: "Dove", render: (row) => `${percorsoUbicazione(locations.data?.items ?? [], row.location_from_id, "esterno")} → ${percorsoUbicazione(locations.data?.items ?? [], row.location_to_id, "esterno")}` },
          {
            key: "ref",
            label: "Riferimento",
            render: (row) => row.reference ?? "—",
          },
        ]}
      />}
    </Page>
  );
}
function Data({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div>
      <dt className="text-sm text-slate-500">{label}</dt>
      <dd className="font-medium">{value}</dd>
    </div>
  );
}
export function DeliveryNotes() {
  const query = useDeliveryNotes();
  const suppliers = useSuppliers();
  const queryClient = useQueryClient();
  const toast = useToast();
  const [showCreate, setShowCreate] = useState(false);
  const [showSupplier, setShowSupplier] = useState(false);
  const [supplierName, setSupplierName] = useState("");
  const [draft, setDraft] = useState({ number: "", note_date: new Date().toISOString().slice(0, 10), supplier_id: "", po_number: "" });
  const [busy, setBusy] = useState(false);
  const [deleting, setDeleting] = useState<DeliveryNote | null>(null);
  const createSupplier = async () => {
    if (!supplierName.trim()) return;
    setBusy(true);
    try {
      const supplier = await suppliersApi.create({ name: supplierName.trim() });
      await queryClient.invalidateQueries({ queryKey: ["suppliers"] });
      setDraft((current) => ({ ...current, supplier_id: supplier.id }));
      setSupplierName(""); setShowSupplier(false);
    } catch (reason) { toast.show(reason instanceof Error ? reason.message : "Impossibile creare il fornitore.", "error"); }
    finally { setBusy(false); }
  };
  const createNote = async () => {
    if (!draft.number.trim() || !draft.note_date || !draft.supplier_id) return;
    setBusy(true);
    try {
      await deliveryNotesApi.create({ ...draft, number: draft.number.trim(), po_number: draft.po_number.trim() || null, lines: [] });
      await queryClient.invalidateQueries({ queryKey: ["delivery-notes"] });
      toast.show("Bolla creata.", "success");
      setDraft({ number: "", note_date: new Date().toISOString().slice(0, 10), supplier_id: "", po_number: "" });
      setShowCreate(false);
    } catch (reason) { toast.show(reason instanceof Error ? reason.message : "Impossibile creare la bolla.", "error"); }
    finally { setBusy(false); }
  };
  const removeNote = async (note: DeliveryNote) => {
    setBusy(true);
    try {
      await deliveryNotesApi.remove(note.id);
      toast.show(`Bolla ${note.number} eliminata.`, "success");
      setDeleting(null);
      await queryClient.invalidateQueries({ queryKey: ["delivery-notes"] });
    } catch (reason) { toast.show(reason instanceof Error ? reason.message : "Impossibile eliminare la bolla.", "error"); }
    finally { setBusy(false); }
  };
  return (
    <Page title="Bolle" description="Bolle aperte e ricezioni completate" actions={<Button onClick={() => setShowCreate(true)}><Plus size={18}/>Nuova bolla</Button>}>
      {query.isLoading ? (
        <Loading />
      ) : query.isError || !query.data ? (
        <ErrorMessage />
      ) : (
        <Table
          rows={query.data.items}
          keyOf={(row) => row.id}
          empty={
            <span>
              Nessuna bolla registrata. Inizia da{" "}
              <Link to="/receive" className="text-blue-700 underline">
                Ricevi merce
              </Link>
              .
            </span>
          }
          columns={[
            {
              key: "number",
              label: "Numero",
              render: (row) => (
                <Link
                  to={`/delivery-notes/${row.id}`}
                  className="text-blue-700 underline"
                >
                  {row.number}
                </Link>
              ),
            },
            {
              key: "date",
              label: "Data",
              render: (row) => formatDate(row.note_date),
            },
            { key: "po", label: "PO", render: (row) => row.po_number ?? "—" },
            {
              key: "state",
              label: "Stato",
              render: (row) => (
                <Badge tone={row.is_closed ? "success" : "warning"}>
                  {row.is_closed ? "Chiusa" : "Da completare"}
                </Badge>
              ),
            },
            {
              key: "actions",
              label: "",
              render: (row) => <Button variant="ghost" onClick={() => setDeleting(row)}>Elimina</Button>,
            },
          ]}
        />
      )}
      <Modal open={deleting !== null} title="Elimina bolla" onClose={() => !busy && setDeleting(null)}>
        <div className="space-y-3">
          <p className="text-sm text-slate-600">Elimini la bolla <strong>{deleting?.number}</strong>. È possibile solo finché non è stato ricevuto nessun pezzo: se della merce è già entrata, la bolla fa parte della sua storia e va invece corretta con uno storno dai Movimenti.</p>
          <div className="flex justify-end gap-2"><Button variant="secondary" disabled={busy} onClick={() => setDeleting(null)}>Annulla</Button><Button variant="danger" loading={busy} onClick={() => deleting && void removeNote(deleting)}>Elimina</Button></div>
        </div>
      </Modal>
      <Modal open={showCreate} title="Nuova bolla" onClose={() => !busy && setShowCreate(false)}><div className="grid gap-3 md:grid-cols-2"><Input label="Numero bolla" required autoFocus value={draft.number} onChange={(event) => setDraft({ ...draft, number: event.target.value })}/><Input label="Data" type="date" required value={draft.note_date} onChange={(event) => setDraft({ ...draft, note_date: event.target.value })}/><Select label="Fornitore" required value={draft.supplier_id} onChange={(event) => event.target.value === "__new" ? setShowSupplier(true) : setDraft({ ...draft, supplier_id: event.target.value })}><option value="">Seleziona…</option>{suppliers.data?.items.map((supplier) => <option key={supplier.id} value={supplier.id}>{supplier.name}</option>)}<option value="__new">+ Nuovo fornitore</option></Select><Input label="Numero ordine (opzionale)" value={draft.po_number} onChange={(event) => setDraft({ ...draft, po_number: event.target.value })}/><Button className="md:col-span-2" loading={busy} disabled={!draft.number.trim() || !draft.note_date || !draft.supplier_id} onClick={() => void createNote()}>Crea bolla</Button></div></Modal>
      <Modal open={showSupplier} title="Nuovo fornitore" onClose={() => !busy && setShowSupplier(false)}><div className="space-y-4"><Input label="Nome" autoFocus value={supplierName} onChange={(event) => setSupplierName(event.target.value)}/><Button loading={busy} disabled={!supplierName.trim()} onClick={() => void createSupplier()}>Crea e seleziona</Button></div></Modal>
    </Page>
  );
}
export function DeliveryNoteDetail() {
  const { id = "" } = useParams();
  const catalog = useCatalog();
  const locations = useLocations();
  const query = useQuery({
    queryKey: ["delivery-note", id],
    queryFn: () => deliveryNotesApi.get(id),
  });
  const units = useInventory({ delivery_note: id, page_size: 200 });
  if (query.isLoading) return <Loading />;
  if (!query.data || query.isError) return <ErrorMessage />;
  return (
    <Page
      title={`Bolla ${query.data.number}`}
      description={`Data ${formatDate(query.data.note_date)} · ${query.data.is_closed ? "chiusa" : "da completare"}`}
    >
      <Table
        rows={query.data.lines ?? []}
        keyOf={(row) => row.id}
        empty="Questa bolla non contiene righe."
        columns={[
          { key: "line", label: "Riga", render: (row) => row.line_number },
          {
            key: "item",
            label: "Modello",
            render: (row) => { const item = catalog.data?.items.find((candidate) => candidate.id === row.catalog_item_id); return item ? <><strong>{item.part_number}</strong><div className="text-xs text-slate-500">{item.name}</div></> : "—"; },
          },
          {
            key: "expected",
            label: "Attesi",
            render: (row) => formatQuantity(row.qty_expected),
          },
          {
            key: "received",
            label: "Ricevuti",
            render: (row) => Number(row.qty_received) >= Number(row.qty_expected)
              ? <Badge tone="success">{formatQuantity(row.qty_received)}</Badge>
              : <Badge tone="warning">{formatQuantity(row.qty_received)}</Badge>,
          },
        ]}
      />
      <h2 className="text-lg font-semibold">Pezzi ricevuti con questa bolla</h2>
      <Table
        rows={units.data?.items ?? []}
        keyOf={(row) => row.row_key}
        empty="Nessun pezzo ancora ricevuto su questa bolla."
        columns={[
          { key: "serial", label: "Seriale", render: (row) => row.kind === "unit" ? <Link className="font-mono text-blue-700 underline" to={`/units/${row.row_key}`}>{row.serial_number}</Link> : <span className="text-slate-500">sfuso</span> },
          { key: "model", label: "Modello", render: (row) => row.part_number },
          { key: "location", label: "Ubicazione", render: (row) => percorsoUbicazione(locations.data?.items ?? [], row.location_id) },
          { key: "status", label: "Stato", render: (row) => row.kind === "bulk" ? formatQuantity(Number(row.quantity), "pz") : <Badge>{unitStatusLabels[row.status ?? "in_stock"]}</Badge> },
        ]}
      />
    </Page>
  );
}
export function Receive() {
  const toast = useToast();
  return (
    <Page
      title="Ricevi merce"
      description="Registra la bolla e acquisisci i seriali senza lasciare la tastiera"
    >
      <ReceiveForm
        onSuccess={(createdUnits) => toast.show(
          createdUnits > 0 ? `Ricezione registrata: ${createdUnits} unità create.` : "Ricezione registrata con successo.",
          "success",
        )}
      />
    </Page>
  );
}
export const movementTypeLabels: Record<MovementType, string> = { receipt: "Carico", issue: "Uscita", transfer: "Spostamento", return: "Reso", rma_out: "Invio RMA", rma_in: "Rientro RMA", adjustment: "Rettifica", scrap: "Rottamazione" };
const emptyMovementFilters = { type: "", location: "", reference: "", date_from: "", date_to: "", page: 1 };
export function Movements() {
  const [filters, setFilters] = useState(emptyMovementFilters);
  const locations = useLocations();
  const query = useMovements(filters);
  const queryClient = useQueryClient();
  const toast = useToast();
  const { session } = useAuth();
  const [reversing, setReversing] = useState<StockMovement | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const change = (key: keyof typeof emptyMovementFilters, value: string | number) => setFilters((current) => ({ ...current, [key]: value, page: key === "page" ? Number(value) : 1 }));
  const exportCsv = async () => {
    try {
      const blob = await movementsApi.export("csv", filters.date_from || undefined, filters.date_to || undefined);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url; anchor.download = "movimenti.csv"; anchor.click();
      URL.revokeObjectURL(url);
    } catch { toast.show("Impossibile esportare i movimenti.", "error"); }
  };
  const runReverse = async () => {
    if (!reversing || reason.trim().length < 10) return;
    setBusy(true);
    try {
      await movementsApi.reverse(reversing.id, reason.trim());
      toast.show("Movimento stornato.", "success");
      setReversing(null); setReason("");
      await Promise.all([queryClient.invalidateQueries({ queryKey: ["movements"] }), queryClient.invalidateQueries({ queryKey: ["inventory"] })]);
    } catch (cause) { toast.show(cause instanceof Error ? cause.message : "Impossibile stornare il movimento.", "error"); }
    finally { setBusy(false); }
  };
  return (
    <Page title="Movimenti" description="Registro cronologico: ogni riga è immutabile, si corregge solo con uno storno">
      <div className="grid gap-3 rounded-xl border bg-white p-4 md:grid-cols-2 xl:grid-cols-5">
        <Select aria-label="Tipo di movimento" value={filters.type} onChange={(event) => change("type", event.target.value)}><option value="">Tutti i tipi</option>{(Object.keys(movementTypeLabels) as MovementType[]).map((value) => <option key={value} value={value}>{movementTypeLabels[value]}</option>)}</Select>
        <Select aria-label="Ubicazione" value={filters.location} onChange={(event) => change("location", event.target.value)}><option value="">Tutte le ubicazioni</option>{locations.data?.items.map((row) => <option key={row.id} value={row.id}>{percorsoUbicazione(locations.data?.items ?? [], row.id)}</option>)}</Select>
        <Input aria-label="Riferimento" placeholder="Riferimento" value={filters.reference} onChange={(event) => change("reference", event.target.value)}/>
        <Input aria-label="Dal giorno" type="date" value={filters.date_from} onChange={(event) => change("date_from", event.target.value)}/>
        <Input aria-label="Al giorno" type="date" value={filters.date_to} onChange={(event) => change("date_to", event.target.value)}/>
      </div>
      <div className="flex flex-wrap justify-end gap-2">
        <Button variant="ghost" onClick={() => setFilters(emptyMovementFilters)}>Azzera filtri</Button>
        <Button variant="secondary" onClick={() => void exportCsv()}>Esporta CSV</Button>
      </div>
      {query.isLoading ? (
        <Loading />
      ) : query.isError || !query.data ? (
        <ErrorMessage />
      ) : (
        <Table
          rows={query.data.items}
          keyOf={(row) => row.id}
          empty="Nessun movimento registrato. I movimenti appariranno dopo il primo carico."
          columns={[
            { key: "when", label: "Data", render: (row) => formatDateTime(row.occurred_at) },
            { key: "type", label: "Tipo", render: (row) => <Badge tone={row.type === "scrap" ? "danger" : row.type === "receipt" ? "success" : "neutral"}>{movementTypeLabels[row.type] ?? row.type}</Badge> },
            {
              key: "what",
              label: "Pezzo",
              render: (row) => (
                <>
                  <strong>{row.part_number ?? "—"}</strong>
                  {row.serial_number ? <div className="font-mono text-xs">{row.stock_unit_id ? <Link className="text-blue-700 underline" to={`/units/${row.stock_unit_id}`}>{row.serial_number}</Link> : row.serial_number}</div> : <div className="text-xs text-slate-500">sfuso</div>}
                </>
              ),
            },
            { key: "qty", label: "Q.tà", render: (row) => formatQuantity(row.quantity) },
            { key: "where", label: "Da → A", render: (row) => `${percorsoUbicazione(locations.data?.items ?? [], row.location_from_id, "esterno")} → ${percorsoUbicazione(locations.data?.items ?? [], row.location_to_id, "esterno")}` },
            { key: "who", label: "Da chi", render: (row) => row.performed_by_username ?? "—" },
            { key: "reference", label: "Riferimento", render: (row) => row.reference ?? row.reason ?? "—" },
            {
              key: "actions",
              label: "",
              render: (row) =>
                row.is_reversed ? <Badge tone="warning">Stornato</Badge>
                : can(session?.role, "reverse") ? <Button variant="ghost" onClick={() => { setReversing(row); setReason(""); }}>Storna</Button>
                : "—",
            },
          ]}
        />
      )}
      {query.data && query.data.total > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <span className="text-sm text-slate-600">{query.data.total} movimenti</span>
          <div className="flex items-center gap-2">
            <Button variant="secondary" disabled={filters.page <= 1} onClick={() => change("page", filters.page - 1)}>Precedente</Button>
            <span className="text-sm">Pagina {filters.page} di {Math.max(1, Math.ceil(query.data.total / query.data.page_size))}</span>
            <Button variant="secondary" disabled={filters.page * query.data.page_size >= query.data.total} onClick={() => change("page", filters.page + 1)}>Successiva</Button>
          </div>
        </div>
      )}
      <Modal open={reversing !== null} title="Storna movimento" onClose={() => !busy && setReversing(null)}>
        <div className="space-y-3">
          <p className="text-sm text-slate-600">Il movimento resta nel registro: viene creato un movimento opposto che ne annulla l&apos;effetto sulla giacenza. Un movimento può essere stornato una sola volta.</p>
          {reversing && <p className="rounded-lg bg-slate-100 p-3 text-sm">{movementTypeLabels[reversing.type] ?? reversing.type} · {reversing.part_number ?? "—"}{reversing.serial_number ? ` · ${reversing.serial_number}` : ""} · {formatDateTime(reversing.occurred_at)}</p>}
          <Input label="Motivo (minimo 10 caratteri)" required autoFocus value={reason} onChange={(e) => setReason(e.target.value)}/>
          <div className="flex justify-end gap-2"><Button variant="secondary" disabled={busy} onClick={() => setReversing(null)}>Annulla</Button><Button variant="danger" loading={busy} disabled={reason.trim().length < 10} onClick={() => void runReverse()}>Conferma storno</Button></div>
        </div>
      </Modal>
    </Page>
  );
}
export function Catalog() {
  const query = useCatalog();
  const queryClient = useQueryClient();
  const toast = useToast();
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<CatalogItem | null>(null);
  const toggleActive = useToggleActive(catalogApi, "catalog", { on: "Articolo riattivato.", off: "Articolo disattivato." });
  const remove = useDeleteEntry<CatalogItem>(catalogApi, "catalog", (row) => row.part_number);
  return (
    <MasterPage
      title="Catalogo"
      description="I modelli che puoi ricevere a magazzino"
      empty="Nessun articolo nel catalogo. Crea il primo articolo per iniziare."
      query={query}
      onNew={() => setCreating(true)}
      newLabel="Nuovo articolo"
      onEdit={(row) => setEditing(row)}
      onToggleActive={toggleActive}
      onDelete={remove.ask}
      columns={[
        { key: "code", label: "Part number", render: (row) => <strong>{row.part_number}</strong> },
        { key: "name", label: "Nome", render: (row) => row.name },
        {
          key: "type",
          label: "Tracciamento",
          render: (row) => <Badge tone={row.is_serialized ? "info" : "neutral"}>{row.is_serialized ? "Serializzato" : "A quantità"}</Badge>,
        },
        { key: "reorder", label: "Avvisa sotto", render: (row) => row.reorder_point ?? "—" },
        { key: "active", label: "Attivo", render: (row) => <Badge tone={row.is_active ? "success" : "neutral"}>{row.is_active ? "Sì" : "No"}</Badge> },
      ]}
    >
      {remove.dialog}
      <CatalogItemModal open={creating || editing !== null} item={editing} onClose={() => { setCreating(false); setEditing(null); }} onCreated={(item) => { toast.show(`Articolo ${item.part_number} ${editing ? "aggiornato" : "creato"}.`, "success"); void queryClient.invalidateQueries({ queryKey: ["catalog"] }); }}/>
    </MasterPage>
  );
}
const locationTypeLabels: Record<LocationType, string> = { warehouse: "Magazzino", shelf: "Scaffale", box: "Contenitore", remote_site: "Sede remota", transit: "In transito" };
export function Locations() {
  const query = useLocations();
  const queryClient = useQueryClient();
  const toast = useToast();
  const [creating, setCreating] = useState(false);
  const [draft, setDraft] = useState({ code: "", name: "", type: "shelf" as LocationType, address: "" });
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState<Location | null>(null);
  const toggleActive = useToggleActive(locationsApi, "locations", { on: "Ubicazione riattivata.", off: "Ubicazione disattivata." });
  const remove = useDeleteEntry<Location>(locationsApi, "locations", (row) => row.code);
  const openEditor = (row: Location) => { setDraft({ code: row.code, name: row.name, type: row.type, address: row.address ?? "" }); setEditing(row); };
  const closeEditor = () => { setCreating(false); setEditing(null); setDraft({ code: "", name: "", type: "shelf", address: "" }); };
  const save = async () => {
    if (!draft.name.trim()) return;
    setBusy(true);
    try {
      // In creazione il codice non si manda: lo ricava il server dal nome
      // («Scaffale A01» → `SCAFFALE-A01`), e chi crea un'ubicazione non deve
      // inventarsi una sigla per una cosa che poi legge sempre per esteso.
      // In modifica invece si manda, perché lì è visibile e correggibile.
      const body = { name: draft.name.trim(), type: draft.type, address: draft.address.trim() || null };
      if (editing) await locationsApi.update(editing.id, { ...body, code: draft.code.trim() });
      else await locationsApi.create(body);
      toast.show(editing ? "Ubicazione aggiornata." : "Ubicazione creata.", "success");
      closeEditor();
      await queryClient.invalidateQueries({ queryKey: ["locations"] });
    } catch (reason) { toast.show(reason instanceof Error ? reason.message : "Operazione non riuscita.", "error"); }
    finally { setBusy(false); }
  };
  return (
    <MasterPage
      title="Ubicazioni"
      description="Dove si trova la merce: magazzini, scaffali, sedi, persone"
      empty="Nessuna ubicazione configurata. Crea il magazzino e i suoi scaffali."
      query={query}
      onNew={() => setCreating(true)}
      newLabel="Nuova ubicazione"
      onEdit={openEditor}
      onToggleActive={toggleActive}
      onDelete={remove.ask}
      columns={[
        { key: "code", label: "Codice", render: (row) => <strong>{row.code}</strong> },
        { key: "name", label: "Nome", render: (row) => row.name },
        { key: "type", label: "Tipo", render: (row) => locationTypeLabels[row.type] ?? row.type },
        { key: "address", label: "Indirizzo", render: (row) => row.address ?? "—" },
      ]}
    >
      {remove.dialog}
      <Modal open={creating || editing !== null} title={editing ? `Modifica ${editing.code}` : "Nuova ubicazione"} onClose={() => !busy && closeEditor()}>
        <div className="space-y-3">
          <div className="grid gap-3 md:grid-cols-2">
            <Input label="Nome" required autoFocus value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} hint={editing ? undefined : "Il codice viene ricavato da qui: «Scaffale A01» diventa SCAFFALE-A01."}/>
            {/* Il codice compare solo in modifica. Alla creazione sarebbe una
                sigla da inventare per una cosa che poi si legge sempre per
                esteso; dopo, resta correggibile — ma è stampato su
                un'etichetta, quindi cambiarlo è una scelta, non un effetto
                collaterale del rinominare. */}
            {editing && <Input label="Codice" required value={draft.code} onChange={(e) => setDraft({ ...draft, code: e.target.value })} hint="Finisce sull'etichetta dello scaffale e nei file di import."/>}
            <Select label="Tipo" value={draft.type} onChange={(e) => setDraft({ ...draft, type: e.target.value as LocationType })}>{(Object.keys(locationTypeLabels) as LocationType[]).map((type) => <option key={type} value={type}>{locationTypeLabels[type]}</option>)}</Select>
            <Input label="Indirizzo (opzionale)" value={draft.address} onChange={(e) => setDraft({ ...draft, address: e.target.value })}/>
          </div>
          <div className="flex justify-end gap-2"><Button variant="secondary" disabled={busy} onClick={closeEditor}>Annulla</Button><Button loading={busy} disabled={!draft.name.trim() || (editing !== null && !draft.code.trim())} onClick={() => void save()}>{editing ? "Salva modifiche" : "Crea ubicazione"}</Button></div>
        </div>
      </Modal>
    </MasterPage>
  );
}
// Deactivating hides an entry from every dropdown without deleting history;
// reactivating goes through PATCH because the deactivate endpoint is one-way.
function useToggleActive<T extends { id: string; is_active?: boolean }>(
  api: { deactivate: (id: string) => Promise<unknown>; update: (id: string, body: { is_active: boolean }) => Promise<unknown> },
  queryKey: string,
  labels: { on: string; off: string },
) {
  const queryClient = useQueryClient();
  const toast = useToast();
  return async (row: T) => {
    try {
      if (row.is_active === false) await api.update(row.id, { is_active: true });
      else await api.deactivate(row.id);
      toast.show(row.is_active === false ? labels.on : labels.off, "success");
      await queryClient.invalidateQueries({ queryKey: [queryKey] });
    } catch (reason) { toast.show(reason instanceof Error ? reason.message : "Operazione non riuscita.", "error"); }
  };
}
// Eliminare vale solo per una voce appena inserita per errore: se qualcosa la
// referenzia già, l'API rifiuta e suggerisce la disattivazione. Il messaggio
// che arriva dal backend viene mostrato così com'è.
function useDeleteEntry<T extends { id: string }>(
  api: { remove: (id: string) => Promise<unknown> },
  queryKey: string,
  labelOf: (row: T) => string,
) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [target, setTarget] = useState<T | null>(null);
  const [busy, setBusy] = useState(false);
  const confirm = async () => {
    if (!target) return;
    setBusy(true);
    try {
      await api.remove(target.id);
      toast.show(`${labelOf(target)} eliminato.`, "success");
      setTarget(null);
      await queryClient.invalidateQueries({ queryKey: [queryKey] });
    } catch (reason) { toast.show(reason instanceof Error ? reason.message : "Impossibile eliminare.", "error"); }
    finally { setBusy(false); }
  };
  const dialog = (
    <Modal open={target !== null} title="Elimina definitivamente" onClose={() => !busy && setTarget(null)}>
      <div className="space-y-3">
        <p className="text-sm text-slate-600">Elimini <strong>{target ? labelOf(target) : ""}</strong>. È possibile solo se non è ancora stata usata da nessun pezzo o movimento; in caso contrario ti verrà proposto di disattivarla.</p>
        <div className="flex justify-end gap-2"><Button variant="secondary" disabled={busy} onClick={() => setTarget(null)}>Annulla</Button><Button variant="danger" loading={busy} onClick={() => void confirm()}>Elimina</Button></div>
      </div>
    </Modal>
  );
  return { ask: setTarget, dialog };
}
export function Vendors() {
  const query = useVendors();
  const queryClient = useQueryClient();
  const toast = useToast();
  const [creating, setCreating] = useState(false);
  const [draft, setDraft] = useState({ code: "", name: "", notes: "" });
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState<Vendor | null>(null);
  const toggleActive = useToggleActive(vendorsApi, "vendors", { on: "Vendor riattivato.", off: "Vendor disattivato." });
  const remove = useDeleteEntry<Vendor>(vendorsApi, "vendors", (row) => row.code);
  const openEditor = (row: Vendor) => { setDraft({ code: row.code, name: row.name, notes: row.notes ?? "" }); setEditing(row); };
  const closeEditor = () => { setCreating(false); setEditing(null); setDraft({ code: "", name: "", notes: "" }); };
  const save = async () => {
    if (!draft.code.trim() || !draft.name.trim()) return;
    setBusy(true);
    try {
      const body = { code: draft.code.trim(), name: draft.name.trim(), notes: draft.notes.trim() || null };
      if (editing) await vendorsApi.update(editing.id, body); else await vendorsApi.create(body);
      toast.show(editing ? "Vendor aggiornato." : "Vendor creato.", "success");
      closeEditor();
      await queryClient.invalidateQueries({ queryKey: ["vendors"] });
    } catch (reason) { toast.show(reason instanceof Error ? reason.message : "Operazione non riuscita.", "error"); }
    finally { setBusy(false); }
  };
  return (
    <MasterPage
      title="Vendor"
      description="I produttori degli apparati a catalogo (Cisco, Meraki, ...)"
      empty="Nessun vendor registrato. Creane uno prima di aggiungere un articolo a catalogo."
      query={query}
      onNew={() => setCreating(true)}
      newLabel="Nuovo vendor"
      onEdit={openEditor}
      onToggleActive={toggleActive}
      onDelete={remove.ask}
      columns={[
        { key: "code", label: "Codice", render: (row) => <strong>{row.code}</strong> },
        { key: "name", label: "Nome", render: (row) => row.name },
        { key: "notes", label: "Note", render: (row) => row.notes ?? "\u2014" },
        { key: "active", label: "Attivo", render: (row) => <Badge tone={row.is_active ? "success" : "neutral"}>{row.is_active ? "S\u00ec" : "No"}</Badge> },
      ]}
    >
      {remove.dialog}
      <Modal open={creating || editing !== null} title={editing ? `Modifica ${editing.code}` : "Nuovo vendor"} onClose={() => !busy && closeEditor()}>
        <div className="space-y-3">
          <div className="grid gap-3 md:grid-cols-2">
            <Input label="Codice" required autoFocus hint="Es. CISCO" value={draft.code} onChange={(e) => setDraft({ ...draft, code: e.target.value })}/>
            <Input label="Nome" required value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })}/>
          </div>
          <Input label="Note (opzionale)" value={draft.notes} onChange={(e) => setDraft({ ...draft, notes: e.target.value })}/>
          <div className="flex justify-end gap-2"><Button variant="secondary" disabled={busy} onClick={closeEditor}>Annulla</Button><Button loading={busy} disabled={!draft.code.trim() || !draft.name.trim()} onClick={() => void save()}>{editing ? "Salva modifiche" : "Crea vendor"}</Button></div>
        </div>
      </Modal>
    </MasterPage>
  );
}
export function Categories() {
  const query = useCategories();
  const queryClient = useQueryClient();
  const toast = useToast();
  const [creating, setCreating] = useState(false);
  const [draft, setDraft] = useState({ code: "", name: "", parent_id: "" });
  const [busy, setBusy] = useState(false);
  const create = async () => {
    if (!draft.code.trim() || !draft.name.trim()) return;
    setBusy(true);
    try {
      await categoriesApi.create({ code: draft.code.trim(), name: draft.name.trim(), parent_id: draft.parent_id || null });
      toast.show("Categoria creata.", "success");
      setDraft({ code: "", name: "", parent_id: "" });
      setCreating(false);
      await queryClient.invalidateQueries({ queryKey: ["categories"] });
    } catch (reason) { toast.show(reason instanceof Error ? reason.message : "Impossibile creare la categoria.", "error"); }
    finally { setBusy(false); }
  };
  const remove = useDeleteEntry<Category>(categoriesApi, "categories", (row) => row.code);
  const nameOf = (id: string | null) => query.data?.items.find((row) => row.id === id)?.name ?? "\u2014";
  return (
    <MasterPage
      title="Categorie"
      description="Come raggruppi gli articoli: switch, access point, transceiver, ..."
      empty="Nessuna categoria registrata. Creane una prima di aggiungere un articolo a catalogo."
      query={query}
      onNew={() => setCreating(true)}
      newLabel="Nuova categoria"
      onDelete={remove.ask}
      columns={[
        { key: "code", label: "Codice", render: (row) => <strong>{row.code}</strong> },
        { key: "name", label: "Nome", render: (row) => row.name },
        { key: "parent", label: "Categoria padre", render: (row) => nameOf(row.parent_id) },
      ]}
    >
      {remove.dialog}
      <Modal open={creating} title="Nuova categoria" onClose={() => !busy && setCreating(false)}>
        <div className="space-y-3">
          <div className="grid gap-3 md:grid-cols-2">
            <Input label="Codice" required autoFocus hint="Es. SWITCH" value={draft.code} onChange={(e) => setDraft({ ...draft, code: e.target.value })}/>
            <Input label="Nome" required value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })}/>
          </div>
          <Select label="Categoria padre (opzionale)" value={draft.parent_id} onChange={(e) => setDraft({ ...draft, parent_id: e.target.value })}><option value="">Nessuna</option>{(query.data?.items ?? []).map((row) => <option key={row.id} value={row.id}>{row.code} \u00b7 {row.name}</option>)}</Select>
          <div className="flex justify-end gap-2"><Button variant="secondary" disabled={busy} onClick={() => setCreating(false)}>Annulla</Button><Button loading={busy} disabled={!draft.code.trim() || !draft.name.trim()} onClick={() => void create()}>Crea categoria</Button></div>
        </div>
      </Modal>
    </MasterPage>
  );
}
export function Suppliers() {
  const query = useSuppliers();
  const queryClient = useQueryClient();
  const toast = useToast();
  const [creating, setCreating] = useState(false);
  const [draft, setDraft] = useState({ name: "", vat_number: "", contact_ref: "" });
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState<Supplier | null>(null);
  const toggleActive = useToggleActive(suppliersApi, "suppliers", { on: "Fornitore riattivato.", off: "Fornitore disattivato." });
  const remove = useDeleteEntry<Supplier>(suppliersApi, "suppliers", (row) => row.name);
  const openEditor = (row: Supplier) => { setDraft({ name: row.name, vat_number: row.vat_number ?? "", contact_ref: row.contact_ref ?? "" }); setEditing(row); };
  const closeEditor = () => { setCreating(false); setEditing(null); setDraft({ name: "", vat_number: "", contact_ref: "" }); };
  const save = async () => {
    if (!draft.name.trim()) return;
    setBusy(true);
    try {
      const body = { name: draft.name.trim(), vat_number: draft.vat_number.trim() || null, contact_ref: draft.contact_ref.trim() || null };
      if (editing) await suppliersApi.update(editing.id, body); else await suppliersApi.create(body);
      toast.show(editing ? "Fornitore aggiornato." : "Fornitore creato.", "success");
      closeEditor();
      await queryClient.invalidateQueries({ queryKey: ["suppliers"] });
    } catch (reason) { toast.show(reason instanceof Error ? reason.message : "Operazione non riuscita.", "error"); }
    finally { setBusy(false); }
  };
  return (
    <MasterPage
      title="Fornitori"
      description="Chi ti consegna la merce"
      empty="Nessun fornitore registrato. Aggiungine uno prima di creare una bolla."
      query={query}
      onNew={() => setCreating(true)}
      newLabel="Nuovo fornitore"
      onEdit={openEditor}
      onToggleActive={toggleActive}
      onDelete={remove.ask}
      columns={[
        { key: "name", label: "Nome", render: (row) => <strong>{row.name}</strong> },
        { key: "vat", label: "Partita IVA", render: (row) => row.vat_number ?? "—" },
        { key: "contact", label: "Contatto", render: (row) => row.contact_ref ?? "—" },
      ]}
    >
      {remove.dialog}
      <Modal open={creating || editing !== null} title={editing ? `Modifica ${editing.name}` : "Nuovo fornitore"} onClose={() => !busy && closeEditor()}>
        <div className="space-y-3">
          <Input label="Nome" required autoFocus value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })}/>
          <div className="grid gap-3 md:grid-cols-2">
            <Input label="Partita IVA (opzionale)" value={draft.vat_number} onChange={(e) => setDraft({ ...draft, vat_number: e.target.value })}/>
            <Input label="Contatto (opzionale)" value={draft.contact_ref} onChange={(e) => setDraft({ ...draft, contact_ref: e.target.value })}/>
          </div>
          <div className="flex justify-end gap-2"><Button variant="secondary" disabled={busy} onClick={closeEditor}>Annulla</Button><Button loading={busy} disabled={!draft.name.trim()} onClick={() => void save()}>{editing ? "Salva modifiche" : "Crea fornitore"}</Button></div>
        </div>
      </Modal>
    </MasterPage>
  );
}
function MasterPage<T extends { id: string; is_active?: boolean }>({
  title,
  description,
  empty,
  query,
  columns,
  onNew,
  newLabel = "Nuovo",
  onToggleActive,
  onEdit,
  onDelete,
  children,
}: {
  title: string;
  description?: string;
  empty: string;
  query: { isLoading: boolean; isError: boolean; data?: { items: T[] } };
  columns: Array<{
    key: string;
    label: string;
    render: (row: T) => React.ReactNode;
  }>;
  onNew?: () => void;
  newLabel?: string;
  onToggleActive?: (row: T) => void | Promise<void>;
  onEdit?: (row: T) => void;
  onDelete?: (row: T) => void;
  children?: React.ReactNode;
}) {
  const { session } = useAuth();
  // Retiring an entry is a shared concern of every registry page, so the
  // button lives here rather than being re-implemented (and drifting) in each.
  const canWrite = can(session?.role, "manage_master_data");
  const allColumns = [
    ...columns,
    ...(onEdit && canWrite ? [{ key: "edit", label: "", render: (row: T) => <Button variant="ghost" onClick={() => onEdit(row)}>Modifica</Button> }] : []),
    ...(onToggleActive && can(session?.role, "deactivate") ? [{ key: "toggle", label: "", render: (row: T) => <Button variant="ghost" onClick={() => void onToggleActive(row)}>{row.is_active === false ? "Riattiva" : "Disattiva"}</Button> }] : []),
    ...(onDelete && can(session?.role, "deactivate") ? [{ key: "delete", label: "", render: (row: T) => <Button variant="ghost" onClick={() => onDelete(row)}>Elimina</Button> }] : []),
  ];
  return (
    <Page title={title} description={description} actions={onNew && canWrite ? <Button onClick={onNew}><Plus size={18}/>{newLabel}</Button> : undefined}>
      {query.isLoading ? (
        <Loading />
      ) : query.isError || !query.data ? (
        <ErrorMessage />
      ) : (
        <Table
          rows={query.data.items}
          keyOf={(row) => row.id}
          empty={empty}
          columns={allColumns}
        />
      )}
      {children}
    </Page>
  );
}
