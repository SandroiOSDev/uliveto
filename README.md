# Uliveto

Uliveto è un piccolo registro personale per seguire gli alberi del proprio uliveto. Ogni pianta ha una scheda con codice, cultivar, zona e coordinate facoltative. Visite e interventi finiscono in una cronologia unica; il cruscotto mostra l'ultimo stato di salute registrato per ogni albero.

È un progetto in sviluppo attivo, nato per essere usato sul campo con dati reali. La prima versione privilegia la registrazione affidabile delle informazioni e l'esportazione, senza account né servizi esterni.

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
- Esportare tutti i dati in un unico CSV leggibile anche da un foglio di calcolo.

Non ci sono dati di esempio: il registro parte vuoto. Le coordinate, quando presenti, aprono OpenStreetMap in una nuova scheda.

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
- `uliveto/static/style.css`: interfaccia adattiva.
- `tests/`: test dei flussi dati e dei principali vincoli.

## Prossimi passi

La priorità dopo l'uso reale è rendere più rapida la registrazione sul campo da telefono, aggiungere foto alle osservazioni e una vista della mappa. Le scelte dipenderanno da ciò che risulterà utile nell'uliveto, senza introdurre funzionalità fittizie.

## Licenza

MIT. Vedi [LICENSE](LICENSE).
