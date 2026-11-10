# Uliveto

Uliveto è un registro personale per seguire gli alberi e il terreno del proprio uliveto. Ogni pianta ha una scheda con codice, cultivar, zona e coordinate facoltative. Visite e interventi finiscono in una cronologia unica; la dashboard sensori mostra umidità e temperatura nei punti strategici del terreno.

È un progetto in sviluppo attivo, nato per essere usato sul campo. Si possono generare letture sintetiche, chiaramente identificate, per provare il flusso iniziale. Una piccola API locale riceve poi letture reali da un gateway quando i sensori saranno installati.

## Avvio

Serve Python 3.10 o successivo. Non occorre installare pacchetti.

```bash
python3 -m uliveto.app
```

Apri **http://127.0.0.1:8765** nel browser. Il file `data/uliveto.sqlite3` viene creato al primo avvio; la cartella `data/` è esclusa da Git. Per un percorso diverso:

```bash
python3 -m uliveto.app --db /percorso/privato/uliveto.sqlite3 --port 8765
```

## Cosa puoi fare

- Registrare e modificare gli ulivi con codice univoco, cultivar, zona, anno d'impianto e coordinate facoltative.
- Aggiungere osservazioni periodiche con data, stato di salute, sintomi e note.
- Annotare potature, irrigazioni, concimazioni, trattamenti, raccolte e altri interventi.
- Consultare lo storico cronologico di ciascun albero e filtrare il registro per stato.
- Registrare punti di misura per zona, profondità e soglia di umidità; vedere andamento, letture recenti e segnali sotto soglia o non aggiornati.
- Generare sette giorni di letture sintetiche per un punto e passarlo poi alla modalità reale senza confondere le due origini.
- Esportare separatamente anagrafica/storico degli ulivi e letture dei sensori in CSV.

Non ci sono dati di esempio precaricati: il registro parte vuoto. La simulazione parte solo quando premi il pulsante sul punto di misura. Le coordinate, quando presenti nelle schede degli ulivi, aprono OpenStreetMap in una nuova scheda.

## Sensori e dati reali

Per ogni punto di misura scegli un codice stabile e la stessa zona usata nelle schede degli ulivi. L'associazione è per zona: un punto può rappresentare più alberi. La soglia è configurabile, ma va calibrata sul sensore e sul terreno. Un valore sotto soglia segnala un controllo da fare: **non è una diagnosi della salute dell'albero**.

Il percorso per collegare un gateway locale, il formato JSON, l'autenticazione e la migrazione sono descritti in [docs/sensors.md](docs/sensors.md). L'API di acquisizione è disabilitata finché non viene configurato `ULIVETO_INGEST_TOKEN`.

## Dati e backup

Uliveto ascolta soltanto su `127.0.0.1`, quindi è pensato per l'uso sul computer su cui viene avviato. I dati sono in SQLite: per un backup completo, **ferma l'app e copia il file** `data/uliveto.sqlite3` in un luogo sicuro. Il CSV è utile per leggere e analizzare i dati, ma non è ancora una funzione di ripristino.

Non pubblicare il database: può contenere coordinate e note private. `.gitignore` esclude `data/` e i file SQLite dal repository.

## Verifica

```bash
python3 -m unittest discover -s tests -v
```

## Struttura

- `uliveto/db.py`: schema SQLite, validazioni e query.
- `uliveto/app.py`: server HTTP locale, pagine e esportazione CSV.
- `uliveto/sensors.py`: punti di misura, validazioni e generazione sintetica.
- `uliveto/static/`: interfaccia adattiva.
- `tests/`: test dei flussi dati e dei principali vincoli.

## Prossimi passi

La priorità dopo la prova con dati sintetici è scegliere hardware e protocollo del gateway, calibrare le soglie per il terreno reale e verificare le misure con osservazioni sul campo. Per un accesso da telefono fuori dal computer serviranno hosting, autenticazione e una connessione sicura; questa versione locale non li include.

## Licenza

MIT. Vedi [LICENSE](LICENSE).
