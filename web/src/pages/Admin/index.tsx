import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { ImageUp } from "lucide-react";
import { adminApi, categoriesApi, extractionApi, usersApi, vendorsApi } from "../../api";
import type { AppSetting, ExtractionResult, ExtractionTemplate, ExtractionTemplateWrite, FieldSpec, TemplateDocType, User, UserRole } from "../../types/api";
import { Badge, Button, Input, Modal, PasswordInput, Select, Table, useToast } from "../../components/ui";
import { EXTRACTION_FILE_ACCEPT, prepareExtractionImage } from "../../components/scanner/PhotoExtract";
import { formatDateTime } from "../../lib/format";
import { ErrorMessage, Loading, Page } from "../common";
import { BackupAdmin } from "./Backup";
const roleLabels: Record<UserRole, string> = { viewer: "Sola lettura", operator: "Operatore", admin: "Amministratore" };
const emptyUser = { username: "", full_name: "", email: "", role: "operator" as UserRole, password: "" };
// Nomi di tabella come li vede chi amministra, non come li vede il database:
// «17 righe in stock_movements» non dice niente a chi deve decidere.
// Singolare e plurale: la frase dice sempre un numero, e «1 operazioni» si
// vede. Il gemello di questo elenco sta in `api/app/api/v1/users.py`.
const traceLabels: Record<string, [string, string]> = {
  audit_log: ["operazione nel registro di sicurezza", "operazioni nel registro di sicurezza"],
  stock_movements: ["movimento di magazzino", "movimenti di magazzino"],
  delivery_notes: ["bolla registrata", "bolle registrate"],
  reservations: ["prenotazione", "prenotazioni"],
  extraction_templates: ["template di estrazione", "template di estrazione"],
  extraction_runs: ["lettura di documenti", "letture di documenti"],
  app_settings: ["impostazione modificata", "impostazioni modificate"],
};
const describeTraces = (traces: Record<string, number>) =>
  Object.entries(traces).map(([table, count]) => `${count} ${(traceLabels[table] ?? [table, table])[count === 1 ? 0 : 1]}`).join(", ");
export function UsersAdmin() {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [showDeleted, setShowDeleted] = useState(false);
  const query = useQuery({
    queryKey: ["users", showDeleted],
    queryFn: () => usersApi.list({ page_size: 200, include_deleted: showDeleted }),
  });
  const [creating, setCreating] = useState(false);
  const [draft, setDraft] = useState(emptyUser);
  const [busy, setBusy] = useState(false);
  const [resetFor, setResetFor] = useState<User | null>(null);
  const [temporaryPassword, setTemporaryPassword] = useState("");
  const [deleting, setDeleting] = useState<User | null>(null);
  const [purging, setPurging] = useState<User | null>(null);

  const create = async () => {
    if (!draft.username.trim() || !draft.full_name.trim() || draft.password.length < 12) return;
    setBusy(true);
    try {
      await usersApi.create({ username: draft.username.trim(), full_name: draft.full_name.trim(), email: draft.email.trim() || null, role: draft.role, initial_password: draft.password });
      toast.show("Utente creato.", "success");
      setDraft(emptyUser); setCreating(false);
      await queryClient.invalidateQueries({ queryKey: ["users"] });
    } catch (reason) { toast.show(reason instanceof Error ? reason.message : "Impossibile creare l'utente.", "error"); }
    finally { setBusy(false); }
  };
  const toggleActive = async (user: User) => {
    try {
      await usersApi.update(user.id, { is_active: !user.is_active });
      toast.show(user.is_active ? "Utente disattivato." : "Utente riattivato.", "success");
      await queryClient.invalidateQueries({ queryKey: ["users"] });
    } catch (reason) { toast.show(reason instanceof Error ? reason.message : "Operazione non riuscita.", "error"); }
  };
  const resetPassword = async (user: User) => {
    setBusy(true);
    try {
      const result = await usersApi.resetPassword(user.id);
      setResetFor(user); setTemporaryPassword(result.temporary_password);
    } catch (reason) { toast.show(reason instanceof Error ? reason.message : "Reimpostazione non riuscita.", "error"); }
    finally { setBusy(false); }
  };
  // Eliminare chiude l'account: esce dall'elenco ma non dal database. Il
  // filtro degli eliminati si accende da solo, altrimenti la riga sparisce
  // sotto gli occhi di chi l'ha appena chiusa e l'esito è indistinguibile da
  // un'operazione fallita — che è esattamente com'era prima.
  const remove = async (user: User) => {
    setBusy(true);
    try {
      const result = await usersApi.remove(user.id);
      setDeleting(null);
      setShowDeleted(true);
      toast.show(result.purgeable
        ? `Account ${result.username} chiuso. Non ha lasciato tracce: da «Mostra anche gli eliminati» puoi ripristinarlo o toglierlo del tutto.`
        : `Account ${result.username} chiuso: resta nel registro come firma di ${describeTraces(result.traces)}.`, "success");
      await queryClient.invalidateQueries({ queryKey: ["users"] });
    } catch (reason) { toast.show(reason instanceof Error ? reason.message : "Eliminazione non riuscita.", "error"); }
    finally { setBusy(false); }
  };
  // Il secondo passo, e l'unico che non si disfa: vale solo per un account
  // chiuso che nessuna riga di registro cita.
  const purge = async (user: User) => {
    setBusy(true);
    try {
      const result = await usersApi.purge(user.id);
      setPurging(null);
      toast.show(`Utente ${result.username} rimosso dal database. Il nome è di nuovo libero.`, "success");
      await queryClient.invalidateQueries({ queryKey: ["users"] });
    } catch (reason) { toast.show(reason instanceof Error ? reason.message : "Rimozione non riuscita.", "error"); }
    finally { setBusy(false); }
  };
  // Chiudere un account ne cancella la password: non c'è niente da rimettere
  // com'era, e riaprirlo significa consegnare una password nuova.
  const restore = async (user: User) => {
    setBusy(true);
    try {
      const result = await usersApi.restore(user.id);
      setResetFor(user); setTemporaryPassword(result.temporary_password);
      await queryClient.invalidateQueries({ queryKey: ["users"] });
    } catch (reason) { toast.show(reason instanceof Error ? reason.message : "Ripristino non riuscito.", "error"); }
    finally { setBusy(false); }
  };

  return (
    <Page title="Utenti" description="Chi può accedere e con quali permessi" actions={<div className="flex flex-wrap items-center gap-2"><label className="inline-flex min-h-11 items-center gap-2 text-sm"><input type="checkbox" className="size-4" checked={showDeleted} onChange={(e) => setShowDeleted(e.target.checked)}/>Mostra anche gli eliminati</label><Button onClick={() => setCreating(true)}>Nuovo utente</Button></div>}>
      {query.isLoading ? (
        <Loading />
      ) : query.isError || !query.data ? (
        <ErrorMessage />
      ) : (
        <Table
          rows={query.data.items}
          keyOf={(row) => row.id}
          empty="Nessun utente disponibile."
          columns={[
            { key: "username", label: "Utente", render: (row) => <strong>{row.username}</strong> },
            { key: "name", label: "Nome", render: (row) => row.full_name },
            { key: "role", label: "Ruolo", render: (row) => roleLabels[row.role] ?? row.role },
            {
              key: "active",
              label: "Stato",
              render: (row) => row.deleted_at
                ? <Badge tone="danger">Eliminato</Badge>
                : <Badge tone={row.is_active ? "success" : "neutral"}>{row.is_active ? "Attivo" : "Disattivato"}</Badge>,
            },
            {
              key: "actions",
              label: "",
              render: (row) => row.deleted_at
                ? <div className="flex flex-wrap items-center gap-2"><Button variant="secondary" disabled={busy} onClick={() => void restore(row)}>Ripristina</Button>{row.can_purge
                    ? <Button variant="ghost" className="text-red-700" disabled={busy} onClick={() => setPurging(row)}>Elimina definitivamente</Button>
                    : <span className="text-xs text-slate-500">Resta nel registro: ha firmato operazioni</span>}</div>
                : <div className="flex flex-wrap gap-2"><Button variant="ghost" disabled={busy} onClick={() => void resetPassword(row)}>Reimposta password</Button><Button variant="ghost" onClick={() => void toggleActive(row)}>{row.is_active ? "Disattiva" : "Riattiva"}</Button><Button variant="ghost" className="text-red-700" disabled={busy} onClick={() => setDeleting(row)}>Elimina</Button></div>,
            },
          ]}
        />
      )}
      <Modal open={creating} title="Nuovo utente" onClose={() => !busy && setCreating(false)}>
        <div className="space-y-3">
          <div className="grid gap-3 md:grid-cols-2">
            <Input label="Nome utente" required autoFocus value={draft.username} onChange={(e) => setDraft({ ...draft, username: e.target.value })}/>
            <Input label="Nome e cognome" required value={draft.full_name} onChange={(e) => setDraft({ ...draft, full_name: e.target.value })}/>
            <Input label="Email (opzionale)" type="email" value={draft.email} onChange={(e) => setDraft({ ...draft, email: e.target.value })}/>
            <Select label="Ruolo" value={draft.role} onChange={(e) => setDraft({ ...draft, role: e.target.value as UserRole })}>{(Object.keys(roleLabels) as UserRole[]).map((role) => <option key={role} value={role}>{roleLabels[role]}</option>)}</Select>
          </div>
          <PasswordInput label="Password iniziale" required hint="Almeno 12 caratteri. L'utente dovrà cambiarla al primo accesso." value={draft.password} onChange={(e) => setDraft({ ...draft, password: e.target.value })}/>
          <div className="flex justify-end gap-2"><Button variant="secondary" disabled={busy} onClick={() => setCreating(false)}>Annulla</Button><Button loading={busy} disabled={!draft.username.trim() || !draft.full_name.trim() || draft.password.length < 12} onClick={() => void create()}>Crea utente</Button></div>
        </div>
      </Modal>
      <Modal open={deleting !== null} title={`Elimina ${deleting?.username ?? ""}`} onClose={() => !busy && setDeleting(null)}>
        <div className="space-y-3 text-sm">
          <p>Stai per eliminare <strong>{deleting?.full_name}</strong> ({deleting?.username}). L'accesso viene tolto subito e le sessioni aperte vengono chiuse.</p>
          {/* In magazzino ogni movimento porta la firma di chi l'ha fatto, e
              quella firma non si può togliere senza riscrivere il registro:
              eliminare vuol dire chiudere l'account, non farlo sparire. */}
          <p className="rounded-lg bg-slate-100 p-3">L'account viene <strong>chiuso</strong>: esce dall'elenco, non può più entrare, ma resta come firma leggibile sotto le operazioni che ha fatto. Lo ritrovi con <strong>«Mostra anche gli eliminati»</strong>, da dove puoi ripristinarlo con una password nuova — o, se non ha mai registrato nulla, toglierlo del tutto dal database.</p>
          <p>Finché l'account esiste, il suo nome utente resta riservato a lui.</p>
          <div className="flex justify-end gap-2"><Button variant="secondary" disabled={busy} onClick={() => setDeleting(null)}>Annulla</Button><Button variant="danger" loading={busy} onClick={() => deleting && void remove(deleting)}>Elimina</Button></div>
        </div>
      </Modal>
      <Modal open={purging !== null} title={`Elimina definitivamente ${purging?.username ?? ""}`} onClose={() => !busy && setPurging(null)}>
        <div className="space-y-3 text-sm">
          <p>Stai per togliere <strong>{purging?.full_name}</strong> ({purging?.username}) dal database. Si può fare perché questo account non compare in nessuna riga del registro: non c'è niente da conservare.</p>
          <p className="rounded-lg bg-red-50 p-3">L'operazione <strong>non si annulla</strong> e non lascia traccia dell'account. Il nome utente torna libero e potrà essere riassegnato.</p>
          <div className="flex justify-end gap-2"><Button variant="secondary" disabled={busy} onClick={() => setPurging(null)}>Annulla</Button><Button variant="danger" loading={busy} onClick={() => purging && void purge(purging)}>Elimina definitivamente</Button></div>
        </div>
      </Modal>
      <Modal open={resetFor !== null} title="Password reimpostata" onClose={() => { setResetFor(null); setTemporaryPassword(""); }}>
        <div className="space-y-3">
          <p className="text-sm text-slate-600">Password temporanea per <strong>{resetFor?.username}</strong>. Comunicagliela di persona: non sarà più visibile dopo aver chiuso questa finestra, e dovrà cambiarla al primo accesso.</p>
          <p className="select-all rounded-lg bg-slate-100 p-3 font-mono text-lg">{temporaryPassword}</p>
          <div className="flex justify-end"><Button onClick={() => { setResetFor(null); setTemporaryPassword(""); }}>Ho preso nota</Button></div>
        </div>
      </Modal>
    </Page>
  );
}
export function TemplatesAdmin() {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [editing, setEditing] = useState<ExtractionTemplate | "new" | null>(null);
  const query = useQuery({
    queryKey: ["templates"],
    queryFn: () => extractionApi.templates.list(),
  });
  const vendors = useQuery({ queryKey: ["vendors", "template-editor"], queryFn: () => vendorsApi.list() });
  const categories = useQuery({ queryKey: ["categories", "template-editor"], queryFn: () => categoriesApi.list() });
  return (
    <Page
      title="Template estrazione"
      description="Configura regole e prova immagini senza scrivere in magazzino"
      actions={<Button onClick={() => setEditing("new")}>Nuovo template</Button>}
    >
      {query.isLoading ? (
        <Loading />
      ) : query.isError || !query.data ? (
        <ErrorMessage />
      ) : (
        <Table
          rows={query.data}
          keyOf={(row) => row.id}
          empty="Nessun template configurato. Crea un template per abilitare l’estrazione guidata."
          columns={[
            { key: "name", label: "Nome", render: (row) => row.name },
            { key: "type", label: "Documento", render: (row) => row.doc_type },
            { key: "version", label: "Versione", render: (row) => row.version },
            { key: "active", label: "Attivo", render: (row) => row.is_active ? "Sì" : "No" },
            { key: "actions", label: "", render: (row) => <Button variant="ghost" onClick={() => setEditing(row)}>Modifica</Button> },
          ]}
        />
      )}
      <TemplateEditor open={editing !== null} template={editing} vendors={vendors.data?.items ?? []} categories={categories.data?.items ?? []} onClose={() => setEditing(null)} onSaved={() => { void queryClient.invalidateQueries({ queryKey: ["templates"] }); setEditing(null); toast.show("Template salvato", "success"); }}/>
    </Page>
  );
}

const emptyField = (): FieldSpec => ({ name: "", target: "", regex: "", keywords: [], keyword_window: 5, required: false, match_against_catalog: false, ocr_fixes: true });
const emptyTemplate = (): ExtractionTemplateWrite => ({ name: "", doc_type: "delivery_note", vendor_id: null, category_id: null, priority: 0, is_active: true, field_specs: { fields: [emptyField()], llm_instructions: "" } });
const confidenceTone = { high: "success", medium: "warning", low: "danger" } as const;
function TemplateEditor({ open, template, vendors, categories, onClose, onSaved }: { open: boolean; template: ExtractionTemplate | "new" | null; vendors: Array<{id: string; name: string}>; categories: Array<{id: string; name: string}>; onClose: () => void; onSaved: () => void }) {
  const [draft, setDraft] = useState<ExtractionTemplateWrite>(emptyTemplate());
  const [busy, setBusy] = useState(false); const [error, setError] = useState(""); const [testResult, setTestResult] = useState<ExtractionResult | null>(null);
  useEffect(() => { if (!open) return; setDraft(template && template !== "new" ? { name: template.name, doc_type: template.doc_type, vendor_id: template.vendor_id, category_id: template.category_id, priority: template.priority, is_active: template.is_active, field_specs: { fields: template.field_specs.fields.map((field) => ({ ...field, keywords: [...field.keywords] })), llm_instructions: template.field_specs.llm_instructions ?? "" } } : emptyTemplate()); setError(""); setTestResult(null); }, [open, template]);
  const changeField = (index: number, change: Partial<FieldSpec>) => setDraft((old) => ({ ...old, field_specs: { ...old.field_specs, fields: old.field_specs.fields.map((field, i) => i === index ? { ...field, ...change } : field) } }));
  const save = async () => { if (!draft.name.trim() || draft.field_specs.fields.some((field) => !field.name.trim() || !field.target.trim())) { setError("Compila nome template, nome e target di tutti i campi."); return; } setBusy(true); setError(""); try { if (template && template !== "new") await extractionApi.templates.update(template.id, draft); else await extractionApi.templates.create(draft); onSaved(); } catch (reason) { setError(reason instanceof Error ? reason.message : "Salvataggio non riuscito."); } finally { setBusy(false); } };
  const test = async (files: FileList | null) => { if (!files?.length || !template || template === "new") return; if (files.length > 5) { setError("Puoi inviare al massimo 5 immagini."); return; } setBusy(true); setError(""); try { const prepared = await Promise.all(Array.from(files).map(prepareExtractionImage)); setTestResult(await extractionApi.templates.test(template.id, prepared, draft.field_specs)); } catch (reason) { setError(reason instanceof Error ? reason.message : "Prova non riuscita."); } finally { setBusy(false); } };
  return <Modal open={open} title={template === "new" ? "Nuovo template" : "Modifica template"} onClose={onClose}><div className="space-y-5">
    {error && <p role="alert" className="rounded-lg bg-red-50 p-3 text-red-800">{error}</p>}
    <div className="grid gap-3 sm:grid-cols-2"><Input label="Nome" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })}/><Select label="Tipo documento" value={draft.doc_type} onChange={(e) => setDraft({ ...draft, doc_type: e.target.value as TemplateDocType })}><option value="device_label">Etichetta dispositivo</option><option value="box_label">Etichetta scatola</option><option value="delivery_note">Bolla</option><option value="packing_list">Packing list</option></Select><Select label="Vendor (opzionale)" value={draft.vendor_id ?? ""} onChange={(e) => setDraft({ ...draft, vendor_id: e.target.value || null })}><option value="">Tutti</option>{vendors.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}</Select><Select label="Categoria (opzionale)" value={draft.category_id ?? ""} onChange={(e) => setDraft({ ...draft, category_id: e.target.value || null })}><option value="">Tutte</option>{categories.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}</Select><Input label="Priorità" type="number" value={draft.priority ?? 0} onChange={(e) => setDraft({ ...draft, priority: Number(e.target.value) })}/><label className="flex items-center gap-2 self-end pb-3 text-sm"><input type="checkbox" checked={draft.is_active ?? true} onChange={(e) => setDraft({ ...draft, is_active: e.target.checked })}/>Template attivo</label></div>
    <div className="space-y-3"><div className="flex items-center justify-between"><h3 className="font-semibold">Campi da estrarre</h3><Button type="button" variant="secondary" onClick={() => setDraft((old) => ({ ...old, field_specs: { ...old.field_specs, fields: [...old.field_specs.fields, emptyField()] } }))}>+ Campo</Button></div>{draft.field_specs.fields.map((field, index) => <fieldset key={index} className="space-y-3 rounded-lg border bg-slate-50 p-3"><div className="flex justify-between"><legend className="font-medium">Campo {index + 1}</legend><Button type="button" variant="ghost" disabled={draft.field_specs.fields.length === 1} onClick={() => setDraft((old) => ({ ...old, field_specs: { ...old.field_specs, fields: old.field_specs.fields.filter((_, i) => i !== index) } }))}>Rimuovi</Button></div><div className="grid gap-3 sm:grid-cols-2"><Input label="Nome campo" value={field.name} onChange={(e) => changeField(index, { name: e.target.value })}/><Input label="Target" placeholder="unit.serial_number" value={field.target} onChange={(e) => changeField(index, { target: e.target.value })}/><Input label="Regex" value={field.regex} onChange={(e) => changeField(index, { regex: e.target.value })}/><Input label="Parole chiave" hint="Separate da virgola" value={field.keywords.join(", ")} onChange={(e) => changeField(index, { keywords: e.target.value.split(",").map((v) => v.trim()).filter(Boolean) })}/><Input label="Finestra parole chiave" type="number" min="0" value={field.keyword_window ?? 0} onChange={(e) => changeField(index, { keyword_window: Number(e.target.value) })}/></div><div className="flex flex-wrap gap-4 text-sm"><label className="flex gap-2"><input type="checkbox" checked={field.required} onChange={(e) => changeField(index, { required: e.target.checked })}/>Obbligatorio</label><label className="flex gap-2"><input type="checkbox" checked={field.match_against_catalog ?? false} disabled={field.name !== "part_number"} onChange={(e) => changeField(index, { match_against_catalog: e.target.checked })}/>Confronta con catalogo</label><label className="flex gap-2"><input type="checkbox" checked={field.ocr_fixes ?? false} onChange={(e) => changeField(index, { ocr_fixes: e.target.checked })}/>Correggi confusioni OCR</label></div></fieldset>)}</div>
    <label className="block text-sm font-medium text-slate-700">Istruzioni aggiuntive per il modello<textarea className="mt-1 min-h-24 w-full rounded-lg border border-slate-300 p-3" value={draft.field_specs.llm_instructions ?? ""} onChange={(e) => setDraft((old) => ({ ...old, field_specs: { ...old.field_specs, llm_instructions: e.target.value } }))}/></label>
    <section className="space-y-3 rounded-lg border border-blue-200 bg-blue-50 p-3"><div><h3 className="font-semibold">Banco prova</h3><p className="text-sm text-slate-600">Usa i valori correnti senza salvarli.</p></div>{template === "new" ? <p className="text-sm text-amber-800">Salva il template prima di provarlo.</p> : <label className="flex cursor-pointer items-center justify-center gap-2 rounded-lg border-2 border-dashed border-blue-300 bg-white p-4"><ImageUp size={20}/><span>Prova su un’immagine</span><input className="sr-only" type="file" accept={EXTRACTION_FILE_ACCEPT} multiple disabled={busy} onChange={(e) => void test(e.target.files)}/></label>}{testResult && <div className="space-y-2">{Object.entries(testResult.fields).map(([target, field]) => <div key={target} className="rounded border bg-white p-2"><div className="flex flex-wrap items-center gap-2"><strong>{field.field || target}</strong><Badge tone={confidenceTone[field.confidence]}>Confidenza {field.confidence}</Badge>{field.corrected && <Badge tone="warning">Corretto OCR</Badge>}</div><p className="font-mono">{field.value || "—"}</p>{(field.field === "part_number" || target.includes("part_number")) && testResult.matched_catalog_item && <p className="text-xs text-green-700">Catalogo: {testResult.matched_catalog_item.part_number} · {testResult.matched_catalog_item.name}</p>}</div>)}</div>}</section>
    <div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={onClose}>Annulla</Button><Button type="button" loading={busy} onClick={() => void save()}>Salva template</Button></div>
  </div></Modal>;
}
export function AuditAdmin() {
  const query = useQuery({
    queryKey: ["audit"],
    queryFn: () => adminApi.audit(),
  });
  return (
    <Page title="Audit log" description="Registro immutabile delle operazioni">
      {query.isLoading ? (
        <Loading />
      ) : query.isError || !query.data ? (
        <ErrorMessage />
      ) : (
        <Table
          rows={query.data.items}
          keyOf={(row) => String(row.id)}
          empty="Nessun evento di audit disponibile."
          columns={[
            {
              key: "when",
              label: "Data",
              render: (row) => formatDateTime(row.ts),
            },
            {
              key: "actor",
              label: "Utente",
              render: (row) => row.actor_username,
            },
            { key: "action", label: "Azione", render: (row) => row.action },
            {
              key: "entity",
              label: "Entità",
              render: (row) => row.entity_type ?? "—",
            },
          ]}
        />
      )}
    </Page>
  );
}
export function SettingsAdmin() {
  const queryClient = useQueryClient();
  const toast = useToast();
  const query = useQuery({
    queryKey: ["settings"],
    queryFn: adminApi.settings,
  });
  const [editing, setEditing] = useState<AppSetting | null>(null);
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const open = (setting: AppSetting) => { setEditing(setting); setValue(JSON.stringify(setting.value, null, 2)); setError(""); };
  const save = async () => {
    if (!editing) return;
    // Settings are stored as JSONB, so the value has to be valid JSON before
    // it is worth sending — parsing here gives an immediate, precise error
    // instead of a generic 422 from the API.
    let parsed: unknown;
    try { parsed = JSON.parse(value); } catch { setError("Il valore non è JSON valido. Il testo va fra virgolette, es. \"ciao\"; i numeri e true/false senza."); return; }
    setBusy(true); setError("");
    try {
      await adminApi.updateSetting(editing.key, parsed);
      toast.show("Impostazione salvata.", "success");
      setEditing(null);
      await queryClient.invalidateQueries({ queryKey: ["settings"] });
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Salvataggio non riuscito."); }
    finally { setBusy(false); }
  };
  return (
    <Page title="Impostazioni" description="Parametri applicativi. Modificali solo se sai cosa fanno.">
      {query.isLoading ? (
        <Loading />
      ) : query.isError || !query.data ? (
        <ErrorMessage />
      ) : (
        <Table
          rows={query.data}
          keyOf={(row) => row.key}
          empty="Nessuna impostazione applicativa."
          columns={[
            { key: "key", label: "Chiave", render: (row) => <strong className="font-mono text-sm">{row.key}</strong> },
            {
              key: "value",
              label: "Valore",
              render: (row) => <span className="font-mono text-sm">{JSON.stringify(row.value)}</span>,
            },
            { key: "actions", label: "", render: (row) => <Button variant="ghost" onClick={() => open(row)}>Modifica</Button> },
          ]}
        />
      )}
      {/* Copia e ripristino stanno qui e non in una voce di menù a parte: si
          cercano dove si cercano le cose di sistema, e la sidebar è già stata
          ridotta apposta a quattro voci operative. */}
      <BackupAdmin/>
      <Modal open={editing !== null} title={`Modifica ${editing?.key ?? ""}`} onClose={() => !busy && setEditing(null)}>
        <div className="space-y-3">
          {error && <p role="alert" className="rounded-lg bg-red-50 p-3 text-red-800">{error}</p>}
          <label className="block text-sm font-medium text-slate-700">Valore (JSON)<textarea className="mt-1 min-h-32 w-full rounded-lg border border-slate-300 p-3 font-mono text-sm" value={value} onChange={(e) => setValue(e.target.value)}/></label>
          <div className="flex justify-end gap-2"><Button variant="secondary" disabled={busy} onClick={() => setEditing(null)}>Annulla</Button><Button loading={busy} onClick={() => void save()}>Salva</Button></div>
        </div>
      </Modal>
    </Page>
  );
}
