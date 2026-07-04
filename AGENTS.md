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

**Stato working tree:**
- `gmail_server/main.py` — modificato (nuove funzioni: `list_labels`, `apply_label`, `remove_label`)
- `scripts/bootstrap_gmail_token.py` — modificato (scope modify + labels)

**Prossimi possibili step:** implementare `manage_filters`.
