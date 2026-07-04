# google-workspace-mcp

## Current Focus

**Completato:**
- Implementati `create_draft` e `send_email` in `gmail_server/main.py` con supporto attachment
- Aggiunto scope `gmail.compose` al bootstrap script
- Rigenerati token OAuth per account `info` e `personal` con scopes `readonly` + `compose`
- Testati `create_draft` e `send_email` (entrambi funzionanti)
- Committato e pushato

**Stato working tree:**
- `gmail_server/main.py` — modificato (nuove funzioni: `create_draft`, `send_email`)
- `scripts/bootstrap_gmail_token.py` — modificato (scope compose)
- `AGENTS.md` — aggiunto

**Prossimi possibili step:** implementare `apply_label` o altre funzionalità Gmail.
