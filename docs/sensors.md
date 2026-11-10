# Acquisizione delle letture del terreno

## Modello

Un **punto di misura** ha codice univoco, zona, coordinate e profondità facoltative, soglia di umidità e modalità `synthetic` o `real`. Le schede degli ulivi con lo stesso nome di zona sono elencate nel punto. Una **lettura** conserva data e ora UTC, umidità percentuale, temperatura facoltativa e origine. La chiave `(punto, data/ora, origine)` rende innocui i reinvii della stessa lettura.

Le letture sintetiche e reali restano distinte anche dopo il cambio di modalità. La dashboard mostra solo l'origine attiva del punto; l'esportazione CSV conserva entrambe. Al cambio in modalità reale la dashboard riparte senza letture finché non arrivano misure reali.

## Prova con dati sintetici

1. Apri **Sensori → Nuovo punto** e scegli **Sintetici**.
2. Apri il punto e premi **Genera 7 giorni sintetici**. Vengono create 15 letture ogni 12 ore, con valori deterministici e riconoscibili come simulazione.
3. Controlla grafico, storico e soglia. Ripetere l'azione nella stessa ora non duplica i dati.

Questi valori servono a provare l'app: non descrivono il terreno dell'uliveto.

## Collegare un gateway locale

1. Imposta il punto su **Reali**.
2. Avvia l'app con un token segreto scelto da te nella variabile d'ambiente `ULIVETO_INGEST_TOKEN`. Non salvarlo nel repository.
3. Configura il gateway per inviare una richiesta HTTP `POST` a `http://127.0.0.1:8765/api/v1/readings` con `Content-Type: application/json` e `Authorization: Bearer <token>`.

Corpo della richiesta:

```json
{
  "station_code": "CODICE_DEL_PUNTO",
  "measured_at": "2026-11-10T12:00:00Z",
  "moisture_pct": 24.5,
  "temperature_c": 18.2
}
```

`temperature_c` è facoltativa. L'umidità deve essere tra 0 e 100; la temperatura tra −40 e 80 °C. La data deve contenere un fuso orario e non può essere oltre cinque minuti nel futuro. L'API risponde `201` quando crea una lettura, `200` per un duplicato, `401` per un token errato e `422` per dati non validi.

Il server ascolta solo su `127.0.0.1`. Un gateway esterno deve quindi girare sullo stesso computer oppure passare attraverso un collegamento sicuro configurato dall'utente. **Non esporre questa porta direttamente su Internet**: prima di un servizio remoto servono TLS, autenticazione, gestione dei dispositivi e backup.

## Interpretazione

La dashboard mostra **Sotto soglia** quando l'ultima umidità è inferiore alla soglia configurata, **Dati non recenti** quando l'ultima lettura ha più di 48 ore e **Senza dati** prima della prima lettura. La soglia predefinita del 20% è solo un valore iniziale da calibrare per tipo di sonda, profondità, terreno e cultivar. Le osservazioni umane nella scheda dell'albero restano la fonte dello stato di salute dell'ulivo; i sensori descrivono condizioni del terreno.
