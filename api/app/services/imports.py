"""Import da CSV: il catalogo e la giacenza di partenza.

Senza un import, passare dall'Excel a questo sistema vuol dire ribattere a
mano ogni articolo e ogni pezzo, oppure inventare bolle per merce arrivata
anni fa. Nessuno lo fa: il gestionale resta un secondo posto dove scrivere le
cose, e la fonte di verità continua a essere il foglio condiviso.

Due decisioni che vale la pena spiegare.

**Il formato è quello dell'esportazione.** Le colonne lette qui sono le stesse
che `GET /export` scrive: si esporta, si corregge in Excel, si reimporta. Un
formato inventato apposta avrebbe voluto dire una corrispondenza in più da
tenere allineata a mano, e un file che non si può verificare guardando quello
che il sistema già produce.

**La giacenza iniziale è un movimento, non un inserimento.** Passa dalla
stessa funzione che registra la merce senza bolla (§6.3), quindi ogni pezzo
importato ha la sua riga nel ledger, con data, autore e riferimento. Scrivere
le unità dritte nel database sarebbe stato più corto, e avrebbe scavalcato il
registro append-only al primo uso vero del sistema: qui la giacenza non è una
tabella, è la somma dei movimenti (§4.1).
"""

import csv
import io
import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ConfirmationRequiredError
from app.models.catalog import CatalogItem, Category, Location, Vendor
from app.models.enums import ItemCondition
from app.models.users import User
from app.services.receiving import FreeReceiveLine, SerialInput, receive_free_stock

# Riferimento che marca i movimenti nati da un import di giacenza iniziale.
# Serve a poterli riconoscere fra due anni: senza, sarebbero indistinguibili
# da una ricezione senza bolla fatta a mano.
RIFERIMENTO_INIZIALE = "GIACENZA-INIZIALE"

# Le intestazioni che scrive l'esportazione, più gli alias che una persona
# scrive spontaneamente. La chiave è l'intestazione normalizzata: minuscola,
# senza accenti e con gli spazi uniti.
COLONNE: dict[str, str] = {
    "codice_articolo": "part_number",
    "part_number": "part_number",
    "codice": "part_number",
    "nome": "nome",
    "descrizione": "nome",
    "fornitore": "vendor",
    "vendor": "vendor",
    "produttore": "vendor",
    "categoria": "categoria",
    "serializzato": "serializzato",
    "unita_di_misura": "uom",
    "uom": "uom",
    "punto_di_riordino": "riordino",
    "formato_seriale": "pattern",
    "seriale": "seriale",
    "serial_number": "seriale",
    "mac": "mac",
    "mac_address": "mac",
    "ubicazione": "ubicazione",
    "condizione": "condizione",
    "quantita": "quantita",
    "note": "note",
    "attivo": "attivo",
}

CONDIZIONI: dict[str, ItemCondition] = {
    "nuovo": ItemCondition.new,
    "new": ItemCondition.new,
    "ricondizionato": ItemCondition.refurbished,
    "refurbished": ItemCondition.refurbished,
    "usato": ItemCondition.used,
    "used": ItemCondition.used,
    "guasto": ItemCondition.faulty,
    "faulty": ItemCondition.faulty,
}

VERI = {"si", "sì", "s", "true", "vero", "1", "x", "yes", "y"}


@dataclass
class Rapporto:
    """Cosa farebbe (o ha fatto) l'import, riga per riga.

    Gli errori sono di riga e non fermano la lettura: un file di trecento
    righe con due sbagliate va corretto tutto in una volta, non due volte.
    """

    creati: int = 0
    saltati: list[str] = field(default_factory=list)
    errori: list[str] = field(default_factory=list)
    avvisi: list[str] = field(default_factory=list)

    @property
    def valido(self) -> bool:
        return not self.errori

    def stampa(self, *, applicato: bool) -> None:
        for riga in self.errori:
            print(f"  ERRORE   {riga}")
        for riga in self.avvisi:
            print(f"  AVVISO   {riga}")
        for riga in self.saltati:
            print(f"  saltata  {riga}")
        verbo = "creati" if applicato else "da creare"
        print(f"\n  {self.creati} {verbo}, {len(self.saltati)} saltati, {len(self.errori)} errori.")


def _normalizza(testo: str) -> str:
    senza_accenti = "".join(
        c for c in unicodedata.normalize("NFD", testo) if unicodedata.category(c) != "Mn"
    )
    return senza_accenti.strip().lower().replace(" ", "_").replace("-", "_")


def leggi_csv(testo: str) -> list[dict[str, str]]:
    """Le righe del file, con le intestazioni ricondotte a nomi interni.

    Il separatore si deduce dalla prima riga: il punto e virgola è quello che
    scrive l'esportazione e quello che Excel in italiano si aspetta, ma un
    file salvato altrove arriva con la virgola e non è un motivo per
    rifiutarlo.
    """
    testo = testo.lstrip("﻿")
    prima = testo.splitlines()[0] if testo.strip() else ""
    separatore = ";" if prima.count(";") >= prima.count(",") else ","
    lettore = csv.DictReader(io.StringIO(testo), delimiter=separatore)
    righe = []
    for grezza in lettore:
        riga = {}
        for intestazione, valore in grezza.items():
            if intestazione is None:
                continue
            campo = COLONNE.get(_normalizza(intestazione))
            if campo is not None:
                riga[campo] = (valore or "").strip()
        righe.append(riga)
    return righe


async def _per_codice(db: AsyncSession, modello: type, codice: str) -> object | None:
    stmt = select(modello).where(func.lower(modello.code) == codice.strip().lower())
    return (await db.execute(stmt)).scalar_one_or_none()


async def importa_catalogo(db: AsyncSession, righe: list[dict[str, str]]) -> Rapporto:
    """Crea gli articoli che mancano. Non ne modifica nessuno.

    Vendor e categoria devono esistere: crearli al volo da un CSV significa
    che un «CSICO» battuto male diventa un fornitore nuovo, e da lì in avanti
    metà del magazzino sta sotto un nome sbagliato.
    """
    rapporto = Rapporto()
    for numero, riga in enumerate(righe, start=2):  # 1 è l'intestazione
        part_number = riga.get("part_number", "")
        if not part_number:
            rapporto.errori.append(f"riga {numero}: manca il codice articolo")
            continue
        vendor = await _per_codice(db, Vendor, riga.get("vendor", ""))
        categoria = await _per_codice(db, Category, riga.get("categoria", ""))
        if vendor is None:
            rapporto.errori.append(
                f"riga {numero} ({part_number}): fornitore «{riga.get('vendor', '')}» inesistente"
            )
            continue
        if categoria is None:
            rapporto.errori.append(
                f"riga {numero} ({part_number}): "
                f"categoria «{riga.get('categoria', '')}» inesistente"
            )
            continue
        esistente = (
            await db.execute(
                select(CatalogItem).where(
                    CatalogItem.vendor_id == vendor.id,
                    func.lower(CatalogItem.part_number) == part_number.lower(),
                )
            )
        ).scalar_one_or_none()
        if esistente is not None:
            rapporto.saltati.append(f"riga {numero}: {part_number} è già in catalogo")
            continue

        riordino = riga.get("riordino", "")
        db.add(
            CatalogItem(
                vendor_id=vendor.id,
                category_id=categoria.id,
                part_number=part_number,
                name=riga.get("nome") or part_number,
                is_serialized=_normalizza(riga.get("serializzato", "si")) in VERI,
                uom=riga.get("uom") or "PZ",
                reorder_point=int(riordino) if riordino.isdigit() else None,
                serial_pattern=riga.get("pattern") or None,
                notes=riga.get("note") or None,
            )
        )
        rapporto.creati += 1
    await db.flush()
    return rapporto


@dataclass
class _Gruppo:
    item: CatalogItem
    condizione: ItemCondition
    seriali: list[SerialInput] = field(default_factory=list)
    quantita: Decimal = Decimal("0")


async def importa_giacenza(
    db: AsyncSession,
    righe: list[dict[str, str]],
    *,
    performer: User,
    quando: datetime | None = None,
    conferma_anomalie: bool = False,
) -> Rapporto:
    """Registra la giacenza di partenza come movimenti di carico.

    Una chiamata per ubicazione, con dentro tutte le righe di quella
    ubicazione: è la stessa forma che ha una ricezione senza bolla fatta a
    mano, e passa dallo stesso codice — quindi eredita i controlli sui
    seriali duplicati e sul formato senza doverli riscrivere qui.
    """
    rapporto = Rapporto()
    per_ubicazione: dict[uuid.UUID, dict[tuple[uuid.UUID, ItemCondition], _Gruppo]] = {}

    for numero, riga in enumerate(righe, start=2):
        part_number = riga.get("part_number", "")
        codice_ubicazione = riga.get("ubicazione", "")
        if not part_number:
            rapporto.errori.append(f"riga {numero}: manca il codice articolo")
            continue
        ubicazione = await _per_codice(db, Location, codice_ubicazione)
        if ubicazione is None:
            rapporto.errori.append(
                f"riga {numero} ({part_number}): ubicazione «{codice_ubicazione}» inesistente"
            )
            continue

        stmt = select(CatalogItem).where(
            func.lower(CatalogItem.part_number) == part_number.lower()
        )
        articoli = list((await db.execute(stmt)).scalars().all())
        if not articoli:
            rapporto.errori.append(
                f"riga {numero}: articolo «{part_number}» non in catalogo "
                "(importa prima il catalogo)"
            )
            continue
        if len(articoli) > 1:
            # Lo stesso codice sotto due fornitori diversi esiste (un ricambio
            # rimarchiato), e qui non c'è modo di indovinare quale sia.
            rapporto.errori.append(
                f"riga {numero}: «{part_number}» esiste per più fornitori: "
                "disambigua il catalogo prima di importare"
            )
            continue
        item = articoli[0]

        condizione = CONDIZIONI.get(_normalizza(riga.get("condizione", "nuovo")), ItemCondition.new)
        chiave = (item.id, condizione)
        gruppo = per_ubicazione.setdefault(ubicazione.id, {}).get(chiave)
        if gruppo is None:
            gruppo = _Gruppo(item=item, condizione=condizione)
            per_ubicazione[ubicazione.id][chiave] = gruppo

        seriale = riga.get("seriale", "")
        if item.is_serialized:
            if not seriale:
                rapporto.errori.append(
                    f"riga {numero}: «{part_number}» è serializzato ma la riga non ha seriale"
                )
                continue
            gruppo.seriali.append(
                SerialInput(serial_number=seriale, mac_address=riga.get("mac") or None)
            )
        else:
            if seriale:
                rapporto.avvisi.append(
                    f"riga {numero}: «{part_number}» non è serializzato, "
                    f"il seriale «{seriale}» viene ignorato"
                )
            grezza = (riga.get("quantita") or "1").replace(",", ".")
            try:
                quantita = Decimal(grezza)
            except InvalidOperation:
                rapporto.errori.append(f"riga {numero}: quantità «{grezza}» non è un numero")
                continue
            if quantita <= 0:
                rapporto.errori.append(f"riga {numero}: quantità dev'essere maggiore di zero")
                continue
            gruppo.quantita += quantita

    if not rapporto.valido:
        return rapporto

    for location_id, gruppi in per_ubicazione.items():
        linee = [
            FreeReceiveLine(
                catalog_item_id=gruppo.item.id,
                condition=gruppo.condizione,
                serials=gruppo.seriali,
                quantity=gruppo.quantita if not gruppo.seriali else None,
            )
            for gruppo in gruppi.values()
        ]
        try:
            esito = await receive_free_stock(
                db,
                performer=performer,
                location_id=location_id,
                lines=linee,
                confirm_warnings=set(),
                occurred_at=quando,
                reference=RIFERIMENTO_INIZIALE,
            )
        except ConfirmationRequiredError as anomalia:
            avvisi = anomalia.details.get("warnings", [])
            if not conferma_anomalie:
                for avviso in avvisi:
                    rapporto.errori.append(
                        f"{avviso.get('serial', avviso.get('code'))}: {avviso.get('message', '')} "
                        "(rilancia con --conferma-anomalie per accettarlo)"
                    )
                return rapporto
            for avviso in avvisi:
                rapporto.avvisi.append(
                    f"{avviso.get('serial', avviso.get('code'))}: {avviso.get('message', '')}"
                )
            esito = await receive_free_stock(
                db,
                performer=performer,
                location_id=location_id,
                lines=linee,
                confirm_warnings={a["code"] for a in avvisi if "code" in a},
                occurred_at=quando,
                reference=RIFERIMENTO_INIZIALE,
            )
        rapporto.creati += len(esito.movement_ids)

    return rapporto
