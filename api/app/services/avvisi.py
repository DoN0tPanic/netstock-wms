"""Gli avvisi che proteggono la produzione.

Ognuno viene da un guaio già successo e passato inosservato: due notti di
backup vuoti, un disco riempito dalla cache delle build, un orologio avanti di
due ore. Qui si controlla quello che il server vede da solo: le copie nella
cartella montata in sola lettura, l'esito che `scripts/backup.sh` scrive a
ogni giro, lo spazio su disco. L'orologio lo confronta il browser, che è
l'unico a conoscere l'altra ora.
"""

import json
import shutil
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.services.maintenance import CARTELLA_BACKUP

# Il timer gira alle 02:30: 36 ore lasciano passare una notte a macchina
# spenta (il timer recupera all'accensione) senza gridare al lupo.
ORE_MASSIME_SENZA_BACKUP = 36
# La prova di ripristino è settimanale: due settimane vuol dire che fallisce.
GIORNI_MASSIMI_SENZA_PROVA = 14
SOGLIA_DISCO = 0.85
SOGLIA_DISCO_CRITICA = 0.95
FILE_STATO = ".stato-backup.json"


@dataclass(frozen=True)
class Avviso:
    codice: str
    gravita: str  # "critico" oppure "attenzione"
    titolo: str
    dettaglio: str


def _quanto_fa(secondi: float) -> str:
    ore = int(secondi // 3600)
    return f"{ore // 24} giorni" if ore >= 48 else f"{ore} ore"


def _leggi_stato(file: Path) -> dict[str, object] | None:
    try:
        dati = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return dati if isinstance(dati, dict) else None


def controlla_backup(cartella: Path = CARTELLA_BACKUP, adesso: float | None = None) -> list[Avviso]:
    adesso = time.time() if adesso is None else adesso
    if not cartella.is_dir():
        return [Avviso(
            "backup_cartella_assente", "attenzione", "La cartella delle copie non è visibile",
            "Il servizio api non vede la cartella dei backup, quindi non può controllarli. "
            "Controlla il volume in docker-compose.yml e che il backup notturno sia installato "
            "(make backup-timer).",
        )]
    avvisi = []
    copie = [f for sotto in ("daily", "monthly") for f in (cartella / sotto).glob("*.dump")]
    buone = [f for f in copie if f.stat().st_size > 0]
    if not buone:
        avvisi.append(Avviso(
            "backup_assente", "critico", "Nessuna copia di sicurezza sul server",
            "Nella cartella dei backup non c'è nessun dump utilizzabile. Installa il backup "
            "notturno (make backup-timer) o lancia ./scripts/backup.sh.",
        ))
    else:
        eta = adesso - max(f.stat().st_mtime for f in buone)
        if eta > ORE_MASSIME_SENZA_BACKUP * 3600:
            avvisi.append(Avviso(
                "backup_vecchio", "critico", f"L'ultima copia buona ha {_quanto_fa(eta)}",
                "Il backup notturno non produce copie da troppo tempo. Controlla con "
                "systemctl status netstock-backup.timer e lancia ./scripts/backup.sh a mano.",
            ))
    if copie:
        piu_recente = max(copie, key=lambda f: f.stat().st_mtime)
        if piu_recente.stat().st_size == 0:
            avvisi.append(Avviso(
                "backup_vuoto", "critico", "L'ultima copia è vuota",
                f"{piu_recente.name} pesa 0 byte: il dump non è riuscito. Le copie buone "
                "restano quelle precedenti.",
            ))

    # L'esito dell'ultimo giro lo scrive backup.sh: le installazioni con uno
    # script più vecchio non lo hanno ancora, e allora non si dice niente.
    stato = _leggi_stato(cartella / FILE_STATO)
    if stato is None:
        return avvisi
    quando = str(stato.get("quando") or "")
    if stato.get("esito") == "fallito":
        avvisi.append(Avviso(
            "backup_fallito", "critico", "L'ultimo backup è fallito",
            f"Il giro del {quando} non è andato a buon fine. Il dettaglio è in "
            "journalctl -u netstock-backup.service.",
        ))
    remoto = stato.get("remoto")
    if remoto == "fallito":
        avvisi.append(Avviso(
            "backup_remoto_fallito", "critico", "La copia fuori dalla macchina non è riuscita",
            "Il dump c'è, ma non ha raggiunto BACKUP_REMOTE: se il disco si guasta, si perde "
            "con il database. Controlla che la destinazione sia raggiungibile.",
        ))
    elif remoto == "non configurato":
        avvisi.append(Avviso(
            "backup_solo_locale", "attenzione", "Le copie restano su questo disco",
            "Se il disco si guasta si perdono insieme il database e le sue copie. Imposta "
            "BACKUP_REMOTE nel .env: una cartella su un NAS o una condivisione di rete.",
        ))
    if stato.get("prova_ripristino") == "attiva":
        ultima = stato.get("ultima_prova_ripristino")
        try:
            eta = adesso - datetime.fromisoformat(str(ultima).replace("Z", "+00:00")).timestamp()
        except ValueError:
            eta = None
        if eta is None or eta > GIORNI_MASSIMI_SENZA_PROVA * 86400:
            avvisi.append(Avviso(
                "prova_ripristino_ferma", "attenzione",
                "La prova di ripristino non riesce da troppo tempo" if eta else
                "La prova di ripristino non è mai riuscita",
                "Una copia mai riaperta non è una copia sicura. Lancia make backup-verify e "
                "guarda cosa risponde.",
            ))
    return avvisi


def controlla_disco(percorsi: tuple[Path, ...] = (Path("/"), CARTELLA_BACKUP)) -> list[Avviso]:
    """Il disco del database, delle immagini e delle copie.

    Dal container si vede il filesystem che lo ospita: quello di Docker per
    «/», quello dei backup per la cartella montata. Conta il più pieno.
    """
    peggiore: tuple[float, int] | None = None
    for percorso in percorsi:
        if not percorso.exists():
            continue
        uso = shutil.disk_usage(percorso)
        quota = uso.used / uso.total if uso.total else 0.0
        if peggiore is None or quota > peggiore[0]:
            peggiore = (quota, uso.free)
    if peggiore is None or peggiore[0] < SOGLIA_DISCO:
        return []
    quota, libero = peggiore
    return [Avviso(
        "disco_quasi_pieno", "critico" if quota >= SOGLIA_DISCO_CRITICA else "attenzione",
        f"Disco quasi pieno: {int(quota * 100)}% occupato",
        f"Restano {libero / 1024**3:.1f} GB. A disco pieno il database non scrive più e i backup "
        "falliscono. La cache delle build e le immagini vecchie si liberano con docker builder "
        "prune e docker image prune; update.sh lo fa da solo dopo ogni aggiornamento riuscito.",
    )]
