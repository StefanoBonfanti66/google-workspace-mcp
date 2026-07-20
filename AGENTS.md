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
- Committato e pushato

**Stato working tree:**
- pulito

**Prossimi possibili step:** definire nuove caratteristiche da aggiungere o procedere con altri server.
