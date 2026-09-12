"""SQLite com confirmação atômica e trilha local de pedidos/ações."""
import json
from pathlib import Path
import secrets
import sqlite3
import time

from domain import TERMINAL


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS orders (
            id TEXT PRIMARY KEY, user_id INTEGER NOT NULL,
            service_id INTEGER NOT NULL, service_name TEXT NOT NULL,
            kind TEXT NOT NULL, payload TEXT NOT NULL, target TEXT NOT NULL,
            rate TEXT NOT NULL, cost TEXT NOT NULL, currency TEXT NOT NULL,
            dry_run INTEGER NOT NULL, state TEXT NOT NULL DEFAULT 'DRAFT',
            provider_id TEXT UNIQUE, provider_status TEXT NOT NULL DEFAULT 'awaiting',
            status_json TEXT NOT NULL DEFAULT '{}', error TEXT NOT NULL DEFAULT '',
            notified_status TEXT NOT NULL DEFAULT 'awaiting',
            checked_at INTEGER NOT NULL DEFAULT 0,
            created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS orders_user ON orders(user_id, created_at);
        CREATE INDEX IF NOT EXISTS orders_target ON orders(service_id, target, state);
        CREATE TABLE IF NOT EXISTS actions (
            id TEXT PRIMARY KEY, order_id TEXT NOT NULL REFERENCES orders(id),
            user_id INTEGER NOT NULL, kind TEXT NOT NULL, dry_run INTEGER NOT NULL,
            state TEXT NOT NULL DEFAULT 'DRAFT', result_json TEXT NOT NULL DEFAULT '{}',
            error TEXT NOT NULL DEFAULT '', created_at INTEGER NOT NULL,
            expires_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS actions_order ON actions(order_id, created_at);
        """)
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    def recover(self) -> None:
        # Executar somente após obter trava de instância no processo principal.
        with self.db:
            self.db.execute("UPDATE orders SET state='UNKNOWN', error='Processo interrompido durante envio' WHERE state='SENDING'")
            self.db.execute("UPDATE actions SET state='UNKNOWN', error='Processo interrompido durante envio' WHERE state='SENDING'")

    def create_order(self, user_id: int, service, payload: dict, cost, currency: str, dry_run: bool) -> dict:
        token, now = secrets.token_hex(8), int(time.time())
        with self.db:
            # Confirmações antigas ainda não enviadas perdem a validade.
            self.db.execute("UPDATE orders SET state='ABORTED' WHERE user_id=? AND state='DRAFT'", (user_id,))
            self.db.execute("""INSERT INTO orders
                (id,user_id,service_id,service_name,kind,payload,target,rate,cost,currency,dry_run,created_at,expires_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (token, user_id, service.id, service.name, service.kind,
                 json.dumps(payload, ensure_ascii=False), payload['link'], str(service.rate),
                 str(cost), currency, int(dry_run), now, now+300, now))
        return self.order(token, user_id)

    def order(self, token: str, user_id: int) -> dict | None:
        row = self.db.execute("SELECT * FROM orders WHERE id=? AND user_id=?", (token, user_id)).fetchone()
        return dict(row) if row else None

    def by_provider(self, provider_id: str, user_id: int) -> dict | None:
        row = self.db.execute("SELECT * FROM orders WHERE provider_id=? AND user_id=?", (provider_id, user_id)).fetchone()
        return dict(row) if row else None

    def mark_order(self, token: str, state: str, *, error: str = '', provider_id: str | None = None) -> None:
        with self.db:
            self.db.execute("""UPDATE orders SET state=?,error=?,updated_at=?,provider_id=COALESCE(?,provider_id)
                WHERE id=?""", (state, error[:500], int(time.time()), provider_id, token))

    def abort_drafts(self, user_id: int) -> None:
        with self.db:
            self.db.execute("UPDATE orders SET state='ABORTED' WHERE user_id=? AND state='DRAFT'", (user_id,))
            self.db.execute("UPDATE actions SET state='ABORTED' WHERE user_id=? AND state='DRAFT'", (user_id,))

    def claim_order(self, token: str, user_id: int) -> bool:
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.order(token, user_id)
            if not row or row['state'] != 'DRAFT' or row['expires_at'] < int(time.time()):
                self.db.rollback()
                return False
            placeholders = ','.join('?' for _ in TERMINAL)
            duplicate = self.db.execute(f"""SELECT id FROM orders WHERE id<>? AND service_id=? AND target=?
                AND (state IN ('SENDING','UNKNOWN') OR (state='SUBMITTED' AND lower(provider_status) NOT IN ({placeholders})))
                LIMIT 1""", (token, row['service_id'], row['target'], *TERMINAL)).fetchone()
            if duplicate:
                raise ValueError("Já existe um pedido ativo ou incerto deste serviço para esse mesmo destino. Confira o histórico.")
            self.db.execute("UPDATE orders SET state='SENDING',updated_at=? WHERE id=?", (int(time.time()), token))
            self.db.commit()
            return True
        except BaseException:
            self.db.rollback()
            raise

    def list_orders(self, user_id: int, page: int, limit: int = 8) -> tuple[list[dict], int]:
        total = self.db.execute("SELECT count(*) FROM orders WHERE user_id=? AND state NOT IN ('DRAFT','ABORTED')", (user_id,)).fetchone()[0]
        rows = self.db.execute("""SELECT * FROM orders WHERE user_id=? AND state NOT IN ('DRAFT','ABORTED')
            ORDER BY created_at DESC, rowid DESC LIMIT ? OFFSET ?""", (user_id, limit, max(page,0)*limit)).fetchall()
        return [dict(x) for x in rows], total

    def update_status(self, token: str, data: dict) -> None:
        status = data.get('status')
        if not isinstance(status, str) or not status.strip():
            raise ValueError("Status vazio retornado pelo fornecedor.")
        with self.db:
            self.db.execute("UPDATE orders SET provider_status=?,status_json=?,checked_at=?,updated_at=? WHERE id=?",
                (status[:120], json.dumps(data, ensure_ascii=False), int(time.time()), int(time.time()), token))

    def watched(self, limit: int = 100) -> list[dict]:
        placeholders = ','.join('?' for _ in TERMINAL)
        rows = self.db.execute(f"""SELECT * FROM orders WHERE state='SUBMITTED' AND provider_id IS NOT NULL
            AND (lower(provider_status) NOT IN ({placeholders}) OR notified_status<>provider_status)
            ORDER BY checked_at ASC,created_at ASC LIMIT ?""", (*TERMINAL, limit)).fetchall()
        return [dict(x) for x in rows]

    def touched(self, token: str) -> None:
        with self.db:
            self.db.execute("UPDATE orders SET checked_at=? WHERE id=?", (int(time.time()), token))

    def notified(self, token: str, status: str) -> None:
        with self.db:
            self.db.execute("UPDATE orders SET notified_status=? WHERE id=?", (status, token))

    def create_action(self, order: dict, kind: str, dry_run: bool) -> dict:
        if kind not in {'refill', 'cancel'}:
            raise ValueError("Ação inválida.")
        token, now = secrets.token_hex(8), int(time.time())
        with self.db:
            self.db.execute("UPDATE actions SET state='ABORTED' WHERE user_id=? AND state='DRAFT'", (order['user_id'],))
            self.db.execute("""INSERT INTO actions (id,order_id,user_id,kind,dry_run,created_at,expires_at)
                VALUES (?,?,?,?,?,?,?)""", (token,order['id'],order['user_id'],kind,int(dry_run),now,now+300))
        return self.action(token, order['user_id'])

    def action(self, token: str, user_id: int) -> dict | None:
        row = self.db.execute("SELECT * FROM actions WHERE id=? AND user_id=?", (token,user_id)).fetchone()
        return dict(row) if row else None

    def claim_action(self, token: str, user_id: int) -> bool:
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.action(token,user_id)
            now = int(time.time())
            if not row or row['state'] != 'DRAFT' or row['expires_at'] < now:
                self.db.rollback()
                return False
            other = self.db.execute("""SELECT id FROM actions WHERE id<>? AND order_id=? AND kind=?
                AND (state IN ('SENDING','UNKNOWN') OR (state='SUBMITTED' AND (kind='cancel' OR created_at>?))) LIMIT 1""",
                (token,row['order_id'],row['kind'],now-86400)).fetchone()
            if other:
                raise ValueError("Já existe solicitação enviada/incerta. Reposição aceita tem intervalo local mínimo de 24 horas; confira o painel.")
            self.db.execute("UPDATE actions SET state='SENDING' WHERE id=?", (token,))
            self.db.commit()
            return True
        except BaseException:
            self.db.rollback()
            raise

    def mark_action(self, token: str, state: str, *, result: dict | None = None, error: str = '') -> None:
        with self.db:
            self.db.execute("UPDATE actions SET state=?,result_json=?,error=? WHERE id=?",
                (state,json.dumps(result or {},ensure_ascii=False),error[:500],token))

    def actions_for(self, order_id: str, user_id: int) -> list[dict]:
        return [dict(x) for x in self.db.execute("""SELECT * FROM actions WHERE order_id=? AND user_id=?
            AND state NOT IN ('DRAFT','ABORTED') ORDER BY created_at DESC,rowid DESC LIMIT 5""", (order_id,user_id))]
