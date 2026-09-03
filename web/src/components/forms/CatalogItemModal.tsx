import { useEffect, useState } from 'react';
import { catalogApi, categoriesApi, vendorsApi } from '../../api';
import type { CatalogItem, Category, Vendor } from '../../types/api';
import { Button, Input, Modal, Select } from '../ui';

const messageOf = (reason: unknown) => reason instanceof Error ? reason.message : 'Operazione non riuscita.';
const emptyDraft = { part_number: '', name: '', vendor_id: '', category_id: '', is_serialized: true, reorder_point: '' };

/** Creating a catalog item is needed both while receiving goods and from the
 *  Catalogo page, and it always drags vendor/category creation along with it —
 *  so the whole thing lives here once instead of being duplicated. */
export function CatalogItemModal({ open, onClose, onCreated, item, prefill }: { open: boolean; onClose: () => void; onCreated: (item: CatalogItem) => void; item?: CatalogItem | null; prefill?: { part_number?: string; name?: string; is_serialized?: boolean } | null }) {
  const [draft, setDraft] = useState(emptyDraft);
  const [vendors, setVendors] = useState<Vendor[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [showVendor, setShowVendor] = useState(false); const [vendorDraft, setVendorDraft] = useState({ code: '', name: '' });
  const [showCategory, setShowCategory] = useState(false); const [categoryDraft, setCategoryDraft] = useState({ code: '', name: '' });
  const [busy, setBusy] = useState(false); const [error, setError] = useState('');

  useEffect(() => {
    if (!open) return;
    // `item` = modifica di un articolo esistente; `prefill` = creazione con i
    // valori letti da una bolla già compilati, così l'operatore non li ridigita.
    setDraft(item
      ? { part_number: item.part_number, name: item.name, vendor_id: item.vendor_id, category_id: item.category_id, is_serialized: item.is_serialized, reorder_point: item.reorder_point === null || item.reorder_point === undefined ? '' : String(item.reorder_point) }
      : { ...emptyDraft, part_number: prefill?.part_number ?? '', name: prefill?.name ?? '', is_serialized: prefill?.is_serialized ?? emptyDraft.is_serialized });
    setError('');
    void Promise.all([
      vendorsApi.list({ page_size: 200 }).then((p) => setVendors(p.items)),
      categoriesApi.list({ page_size: 200 }).then((p) => setCategories(p.items)),
    ]).catch((reason) => setError(messageOf(reason)));
    // Le dipendenze sono i singoli valori, non l'oggetto `prefill`: chi chiama
    // lo costruisce inline, quindi ha un'identità nuova a ogni render del
    // genitore. Con l'oggetto fra le dipendenze, un qualunque aggiornamento
    // del genitore mentre il modale è aperto — per esempio l'interrogazione
    // periodica della lettura in corso — rilanciava questo effetto e riscriveva
    // il modulo sotto le dita di chi lo stava compilando.
  }, [open, item, prefill?.part_number, prefill?.name, prefill?.is_serialized]);

  const createVendor = async () => {
    if (!vendorDraft.code.trim() || !vendorDraft.name.trim()) return;
    setBusy(true);
    try {
      const vendor = await vendorsApi.create({ code: vendorDraft.code.trim(), name: vendorDraft.name.trim() });
      setVendors((old) => [...old, vendor]);
      setDraft((old) => ({ ...old, vendor_id: vendor.id }));
      setVendorDraft({ code: '', name: '' }); setShowVendor(false);
    } catch (reason) { setError(messageOf(reason)); } finally { setBusy(false); }
  };
  const createCategory = async () => {
    if (!categoryDraft.code.trim() || !categoryDraft.name.trim()) return;
    setBusy(true);
    try {
      const category = await categoriesApi.create({ code: categoryDraft.code.trim(), name: categoryDraft.name.trim() });
      setCategories((old) => [...old, category]);
      setDraft((old) => ({ ...old, category_id: category.id }));
      setCategoryDraft({ code: '', name: '' }); setShowCategory(false);
    } catch (reason) { setError(messageOf(reason)); } finally { setBusy(false); }
  };
  const save = async () => {
    if (!draft.part_number.trim() || !draft.name.trim() || !draft.vendor_id || !draft.category_id) return;
    setBusy(true); setError('');
    // `uom` is left to the backend default ("PZ") so every item created
    // anywhere in the app agrees on one unit of measure.
    const body = {
      ...draft,
      part_number: draft.part_number.trim(),
      name: draft.name.trim(),
      reorder_point: draft.reorder_point.trim() === '' ? null : Number(draft.reorder_point),
    };
    try {
      onCreated(item ? await catalogApi.update(item.id, body) : await catalogApi.create(body));
      onClose();
    } catch (reason) { setError(messageOf(reason)); } finally { setBusy(false); }
  };

  const valid = Boolean(draft.part_number.trim() && draft.name.trim() && draft.vendor_id && draft.category_id);
  return <>
    <Modal open={open} title={item ? `Modifica ${item.part_number}` : 'Nuovo articolo'} onClose={() => !busy && onClose()}>
      <div className="space-y-3">
        {error && <p role="alert" className="rounded-lg bg-red-50 p-3 text-red-800">{error}</p>}
        {item && <p className="text-xs text-slate-500">Il tipo di tracciamento non è modificabile: cambiarlo renderebbe incoerenti i pezzi già a magazzino.</p>}
        <div className="grid gap-3 md:grid-cols-2">
          <Input label="Part number" required autoFocus value={draft.part_number} onChange={(e) => setDraft({ ...draft, part_number: e.target.value })}/>
          <Input label="Nome" required value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })}/>
          <Select label="Vendor" required value={draft.vendor_id} onChange={(e) => e.target.value === '__new' ? setShowVendor(true) : setDraft({ ...draft, vendor_id: e.target.value })}><option value="">Seleziona…</option>{vendors.map((v) => <option key={v.id} value={v.id}>{v.code} · {v.name}</option>)}<option value="__new">+ Nuovo vendor</option></Select>
          <Select label="Categoria" required value={draft.category_id} onChange={(e) => e.target.value === '__new' ? setShowCategory(true) : setDraft({ ...draft, category_id: e.target.value })}><option value="">Seleziona…</option>{categories.map((c) => <option key={c.id} value={c.id}>{c.code} · {c.name}</option>)}<option value="__new">+ Nuova categoria</option></Select>
          <Select label="Tracciamento" disabled={Boolean(item)} value={draft.is_serialized ? 'yes' : 'no'} onChange={(e) => setDraft({ ...draft, is_serialized: e.target.value === 'yes' })}><option value="yes">Serializzato (ogni pezzo ha un seriale)</option><option value="no">A quantità (cavi, minuteria)</option></Select>
          <Input label="Avvisami sotto (opzionale)" type="number" min="0" hint="Sotto questa quantità l'articolo compare in Dashboard fra quelli sotto scorta." value={draft.reorder_point} onChange={(e) => setDraft({ ...draft, reorder_point: e.target.value })}/>
        </div>
        <div className="flex justify-end gap-2"><Button variant="secondary" disabled={busy} onClick={onClose}>Annulla</Button><Button loading={busy} disabled={!valid} onClick={() => void save()}>{item ? 'Salva modifiche' : 'Crea articolo'}</Button></div>
      </div>
    </Modal>
    <Modal open={showVendor} title="Nuovo vendor" onClose={() => !busy && setShowVendor(false)}><div className="grid gap-3 md:grid-cols-2"><Input label="Codice" autoFocus value={vendorDraft.code} onChange={(e) => setVendorDraft({ ...vendorDraft, code: e.target.value })}/><Input label="Nome" value={vendorDraft.name} onChange={(e) => setVendorDraft({ ...vendorDraft, name: e.target.value })}/><Button className="md:col-span-2" loading={busy} disabled={!vendorDraft.code.trim() || !vendorDraft.name.trim()} onClick={() => void createVendor()}>Crea e seleziona</Button></div></Modal>
    <Modal open={showCategory} title="Nuova categoria" onClose={() => !busy && setShowCategory(false)}><div className="grid gap-3 md:grid-cols-2"><Input label="Codice" autoFocus value={categoryDraft.code} onChange={(e) => setCategoryDraft({ ...categoryDraft, code: e.target.value })}/><Input label="Nome" value={categoryDraft.name} onChange={(e) => setCategoryDraft({ ...categoryDraft, name: e.target.value })}/><Button className="md:col-span-2" loading={busy} disabled={!categoryDraft.code.trim() || !categoryDraft.name.trim()} onClick={() => void createCategory()}>Crea e seleziona</Button></div></Modal>
  </>;
}
