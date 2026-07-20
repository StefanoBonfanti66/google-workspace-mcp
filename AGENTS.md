# google-workspace-mcp

## Current Focus

**Completato:**
- Implementati `create_draft` e `send_email` in `gmail_server/main.py` con supporto attachment
- Aggiunto scope `gmail.compose` al bootstrap script
- Rigenerati token OAuth per account `info` e `personal` con scopes `readonly` + `compose`
- Testati `create_draft` e `send_email` (entrambi funzionanti)
- Committato e pushato
- Implementati `list_labels`, `apply_label`, `remove_label` in `gmail_server/main.py`
- Aggiunti scope `gmail.modify` e `gmail.labels` al bootstrap script
- Rigenerati token OAuth per account `info` e `personal` con nuovi scopes
- Testati `list_labels`, `apply_label`, `remove_label` (tutti funzionanti)
- Committato e pushato
- Implementati `list_filters`, `create_filter`, `delete_filter` in `gmail_server/main.py` per la gestione dei filtri
- Testati `list_filters`, `create_filter`, `delete_filter` con successo tramite script di test locale
- Aggiunto lo script di test CLI [scripts/test_filters_cli.py](file:///home/sbonfanti/Scrivania/Progetti/google-workspace-mcp/scripts/test_filters_cli.py) per permettere all'utente di ispezionare i propri filtri
- Committato e pushato
- Implementato interamente il server Drive in `drive_server/main.py` (con `search_files`, `download_file`, `list_folder_contents`, `move_file`)
- Creato lo script `scripts/bootstrap_drive_token.py` per l'autorizzazione di Drive ed eseguito il bootstrap iniziale

**Stato working tree:**
- `drive_server/main.py` — modificato
- `scripts/bootstrap_drive_token.py` — aggiunto
- `AGENTS.md` — modificato

**Prossimi possibili step:** Abilitare le API di Google Drive sulla Google Cloud Console e rieseguire la ricerca della fattura.
