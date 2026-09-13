"""Persistência SQLite: carteira, pagamentos e pedidos com operações atômicas."""
import json
import secrets
import sqlite3
import time
import uuid
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from domain import TERMINAL


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=15)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY, username TEXT NOT NULL DEFAULT '',
            display_name TEXT NOT NULL DEFAULT '', created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL, referred_by INTEGER NOT NULL DEFAULT 0,
            referred_at INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS wallets (
            user_id INTEGER PRIMARY KEY REFERENCES users(user_id),
            balance_cents INTEGER NOT NULL DEFAULT 0, updated_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS wallet_ledger (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(user_id),
            amount_cents INTEGER NOT NULL, kind TEXT NOT NULL, reference TEXT NOT NULL UNIQUE,
            description TEXT NOT NULL DEFAULT '', created_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS wallet_ledger_user ON wallet_ledger(user_id, created_at DESC);
        CREATE TABLE IF NOT EXISTS payments (
            id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(user_id),
            amount_cents INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'CREATED',
            idempotency_key TEXT NOT NULL UNIQUE, cakto_order_id TEXT UNIQUE,
            cakto_ref_id TEXT, provider_status TEXT NOT NULL DEFAULT 'waiting_payment',
            qr_code TEXT NOT NULL DEFAULT '', checkout_url TEXT NOT NULL DEFAULT '',
            expires_at TEXT NOT NULL DEFAULT '', customer_json TEXT NOT NULL DEFAULT '{}',
            error TEXT NOT NULL DEFAULT '', notified_status TEXT NOT NULL DEFAULT '',
            checked_at INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS payments_user ON payments(user_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS payments_watch ON payments(status, checked_at);
        CREATE TABLE IF NOT EXISTS payment_requests (
            user_id INTEGER NOT NULL REFERENCES users(user_id), request_id TEXT NOT NULL,
            payment_id TEXT NOT NULL REFERENCES payments(id), request_hash TEXT NOT NULL,
            PRIMARY KEY(user_id, request_id)
        );
        CREATE TABLE IF NOT EXISTS admin_credits (
            reference TEXT PRIMARY KEY, admin_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
            amount_cents INTEGER NOT NULL CHECK(amount_cents>0), reason TEXT NOT NULL,
            created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS orders (
            id TEXT PRIMARY KEY, user_id INTEGER NOT NULL,
            service_id INTEGER NOT NULL, service_name TEXT NOT NULL,
            kind TEXT NOT NULL, payload TEXT NOT NULL, target TEXT NOT NULL,
            rate TEXT NOT NULL, provider_cost TEXT NOT NULL DEFAULT '0',
            cost TEXT NOT NULL, currency TEXT NOT NULL,
            dry_run INTEGER NOT NULL DEFAULT 0, state TEXT NOT NULL DEFAULT 'DRAFT',
            provider_id TEXT UNIQUE, provider_status TEXT NOT NULL DEFAULT 'awaiting',
            status_json TEXT NOT NULL DEFAULT '{}', error TEXT NOT NULL DEFAULT '',
            notified_status TEXT NOT NULL DEFAULT 'awaiting', checked_at INTEGER NOT NULL DEFAULT 0,
            created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS orders_user ON orders(user_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS orders_target ON orders(service_id, target, state);
        CREATE TABLE IF NOT EXISTS actions (
            id TEXT PRIMARY KEY, order_id TEXT NOT NULL REFERENCES orders(id),
            user_id INTEGER NOT NULL, kind TEXT NOT NULL, dry_run INTEGER NOT NULL DEFAULT 0,
            state TEXT NOT NULL DEFAULT 'DRAFT', result_json TEXT NOT NULL DEFAULT '{}',
            error TEXT NOT NULL DEFAULT '', created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS actions_order ON actions(order_id, created_at DESC);
        CREATE TABLE IF NOT EXISTS fulfillment_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT, order_id TEXT NOT NULL REFERENCES orders(id),
            actor_id INTEGER NOT NULL, event TEXT NOT NULL, note TEXT NOT NULL, created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS pricing_policy (
            id INTEGER PRIMARY KEY CHECK(id=1), multiplier TEXT NOT NULL DEFAULT '', revision INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS shop_banners (
            slot INTEGER PRIMARY KEY CHECK(slot BETWEEN 1 AND 3),
            title TEXT NOT NULL, target TEXT NOT NULL, fit TEXT NOT NULL,
            position TEXT NOT NULL, image BLOB, mime TEXT NOT NULL DEFAULT '',
            revision INTEGER NOT NULL, admin_id INTEGER NOT NULL, updated_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS product_banners (
            service_id INTEGER PRIMARY KEY, identity TEXT NOT NULL,
            fit TEXT NOT NULL, position TEXT NOT NULL, image BLOB,
            mime TEXT NOT NULL DEFAULT '', revision INTEGER NOT NULL,
            admin_id INTEGER NOT NULL, updated_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS platform_banners (
            platform TEXT PRIMARY KEY, identity TEXT NOT NULL,
            fit TEXT NOT NULL, position TEXT NOT NULL, image BLOB,
            mime TEXT NOT NULL DEFAULT '', revision INTEGER NOT NULL,
            admin_id INTEGER NOT NULL, updated_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id TEXT NOT NULL UNIQUE REFERENCES orders(id),
            user_id INTEGER NOT NULL REFERENCES users(user_id),
            display_name TEXT NOT NULL, rating INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),
            comment TEXT NOT NULL, created_at INTEGER NOT NULL
        );
        INSERT OR IGNORE INTO pricing_policy(id) VALUES(1);
        CREATE TABLE IF NOT EXISTS price_overrides (
            service_id INTEGER PRIMARY KEY, identity TEXT NOT NULL, unit_price TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS pricing_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT, admin_id INTEGER NOT NULL, service_id INTEGER,
            operation TEXT NOT NULL, old_value TEXT NOT NULL, new_value TEXT NOT NULL,
            reason TEXT NOT NULL, created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS affiliate_commissions (
            payment_id TEXT PRIMARY KEY REFERENCES payments(id),
            referred_user_id INTEGER NOT NULL REFERENCES users(user_id),
            referrer_id INTEGER NOT NULL REFERENCES users(user_id),
            amount_cents INTEGER NOT NULL CHECK(amount_cents>0),
            status TEXT NOT NULL CHECK(status IN ('ACTIVE','REVERSED')),
            created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS affiliate_referrer ON affiliate_commissions(referrer_id,created_at DESC);
        CREATE TABLE IF NOT EXISTS broadcasts (
            id TEXT PRIMARY KEY, request_id TEXT NOT NULL UNIQUE, admin_id INTEGER NOT NULL,
            message TEXT NOT NULL, button_text TEXT NOT NULL DEFAULT '',
            button_target TEXT NOT NULL DEFAULT 'none', status TEXT NOT NULL,
            total INTEGER NOT NULL DEFAULT 0, sent INTEGER NOT NULL DEFAULT 0,
            failed INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL,
            started_at INTEGER NOT NULL DEFAULT 0, finished_at INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS broadcast_deliveries (
            broadcast_id TEXT NOT NULL REFERENCES broadcasts(id),
            user_id INTEGER NOT NULL REFERENCES users(user_id), status TEXT NOT NULL DEFAULT 'PENDING',
            error TEXT NOT NULL DEFAULT '', updated_at INTEGER NOT NULL,
            PRIMARY KEY(broadcast_id,user_id)
        );
        CREATE INDEX IF NOT EXISTS broadcast_pending ON broadcast_deliveries(broadcast_id,status,user_id);
        CREATE TABLE IF NOT EXISTS interest_events (
            id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(user_id),
            platform TEXT NOT NULL, service_id INTEGER NOT NULL DEFAULT 0,
            label TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'ACTIVE',
            created_at INTEGER NOT NULL, first_due_at INTEGER NOT NULL,
            second_due_at INTEGER NOT NULL, first_sent_at INTEGER NOT NULL DEFAULT 0,
            second_sent_at INTEGER NOT NULL DEFAULT 0, updated_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS interest_due ON interest_events(status,first_sent_at,second_sent_at,first_due_at,second_due_at);
        CREATE UNIQUE INDEX IF NOT EXISTS interest_one_active_user ON interest_events(user_id) WHERE status='ACTIVE';
        CREATE TABLE IF NOT EXISTS raffle_campaigns (
            id TEXT PRIMARY KEY, title TEXT NOT NULL, prize TEXT NOT NULL,
            status TEXT NOT NULL, scheduled_at INTEGER NOT NULL,
            result_chat TEXT NOT NULL, draw_count INTEGER NOT NULL DEFAULT 5,
            created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
            started_at INTEGER NOT NULL DEFAULT 0, completed_at INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS raffle_participants (
            campaign_id TEXT NOT NULL REFERENCES raffle_campaigns(id),
            user_id INTEGER NOT NULL REFERENCES users(user_id),
            referrer_id INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'PENDING',
            joined_at INTEGER NOT NULL, verified_at INTEGER NOT NULL DEFAULT 0,
            disqualified_reason TEXT NOT NULL DEFAULT '',
            PRIMARY KEY(campaign_id,user_id)
        );
        CREATE INDEX IF NOT EXISTS raffle_referrals ON raffle_participants(campaign_id,referrer_id,status);
        CREATE TABLE IF NOT EXISTS raffle_cards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_id TEXT NOT NULL REFERENCES raffle_campaigns(id),
            user_id INTEGER NOT NULL REFERENCES users(user_id),
            source TEXT NOT NULL, source_user_id INTEGER NOT NULL DEFAULT 0,
            numbers TEXT NOT NULL, created_at INTEGER NOT NULL,
            UNIQUE(campaign_id,user_id,source,source_user_id),
            UNIQUE(campaign_id,numbers)
        );
        CREATE INDEX IF NOT EXISTS raffle_cards_user ON raffle_cards(campaign_id,user_id,id);
        CREATE TABLE IF NOT EXISTS raffle_rolls (
            campaign_id TEXT NOT NULL REFERENCES raffle_campaigns(id),
            winner_position INTEGER NOT NULL, roll_position INTEGER NOT NULL,
            value INTEGER NOT NULL CHECK(value BETWEEN 1 AND 6),
            message_id INTEGER NOT NULL, created_at INTEGER NOT NULL,
            PRIMARY KEY(campaign_id,winner_position,roll_position)
        );
        CREATE TABLE IF NOT EXISTS raffle_winners (
            campaign_id TEXT NOT NULL REFERENCES raffle_campaigns(id),
            position INTEGER NOT NULL, user_id INTEGER NOT NULL REFERENCES users(user_id),
            card_id INTEGER NOT NULL REFERENCES raffle_cards(id), numbers TEXT NOT NULL,
            dice_values TEXT NOT NULL, dice_message_ids TEXT NOT NULL,
            distance INTEGER NOT NULL, exact_positions INTEGER NOT NULL,
            prize_choice TEXT NOT NULL DEFAULT '', chosen_at INTEGER NOT NULL DEFAULT 0,
            delivered_at INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL,
            PRIMARY KEY(campaign_id,position), UNIQUE(campaign_id,user_id)
        );
        """)
        user_columns = {row[1] for row in self.db.execute("PRAGMA table_info(users)")}
        if "referred_by" not in user_columns:
            self.db.execute("ALTER TABLE users ADD COLUMN referred_by INTEGER NOT NULL DEFAULT 0")
        if "referred_at" not in user_columns:
            self.db.execute("ALTER TABLE users ADD COLUMN referred_at INTEGER NOT NULL DEFAULT 0")
        if "recovery_opt_out" not in user_columns:
            self.db.execute("ALTER TABLE users ADD COLUMN recovery_opt_out INTEGER NOT NULL DEFAULT 0")
        self.db.execute("CREATE INDEX IF NOT EXISTS users_referrer ON users(referred_by,created_at)")
        now = int(time.time())
        self.db.execute(
            """INSERT OR IGNORE INTO raffle_campaigns
            (id,title,prize,status,scheduled_at,result_chat,draw_count,created_at,updated_at)
            VALUES('set26','Sorteio Mais Popular','1 acesso por 30 dias: Crunchyroll Premium ou Netflix 4K',
            'OPEN',1790809200,'@MaisPopular',5,?,?)""",
            (now, now),
        )
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(orders)")}
        if "provider_cost" not in columns:
            self.db.execute("ALTER TABLE orders ADD COLUMN provider_cost TEXT NOT NULL DEFAULT '0'")
        for name, definition in {"retry_at": "INTEGER NOT NULL DEFAULT 0", "queue_reason": "TEXT NOT NULL DEFAULT ''",
                                 "queue_notice_sent": "INTEGER NOT NULL DEFAULT 0", "manual_admin_id": "INTEGER NOT NULL DEFAULT 0",
                                 "pricing_revision": "INTEGER NOT NULL DEFAULT 0"}.items():
            if name not in columns:
                self.db.execute(f"ALTER TABLE orders ADD COLUMN {name} {definition}")
        self.db.execute("CREATE INDEX IF NOT EXISTS orders_queue ON orders(state,retry_at,created_at)")
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    def register_user(self, user_id: int, username: str = "", display_name: str = "") -> None:
        now = int(time.time())
        with self.db:
            self.db.execute("""INSERT INTO users(user_id,username,display_name,created_at,updated_at)
                VALUES(?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET
                username=excluded.username,display_name=excluded.display_name,updated_at=excluded.updated_at""",
                (user_id, username[:80], display_name[:160], now, now))
            self.db.execute("INSERT OR IGNORE INTO wallets(user_id,balance_cents,updated_at) VALUES(?,0,?)", (user_id, now))

    def balance_cents(self, user_id: int) -> int:
        row = self.db.execute("SELECT balance_cents FROM wallets WHERE user_id=?", (user_id,)).fetchone()
        return int(row[0]) if row else 0

    def bind_referrer(self, user_id: int, referrer_id: int) -> bool:
        if user_id == referrer_id:
            raise ValueError("Você não pode usar o próprio link de afiliado.")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            user = self.db.execute(
                "SELECT referred_by FROM users WHERE user_id=?", (user_id,)
            ).fetchone()
            referrer = self.db.execute(
                "SELECT 1 FROM users WHERE user_id=?", (referrer_id,)
            ).fetchone()
            if not user or not referrer:
                raise ValueError("Link de afiliado inválido.")
            cycle = self.db.execute(
                """WITH RECURSIVE chain(user_id,referred_by,depth) AS (
                SELECT user_id,referred_by,0 FROM users WHERE user_id=?
                UNION ALL SELECT u.user_id,u.referred_by,chain.depth+1 FROM users u
                JOIN chain ON u.user_id=chain.referred_by WHERE chain.referred_by<>0 AND chain.depth<50)
                SELECT 1 FROM chain WHERE user_id=? LIMIT 1""",
                (referrer_id, user_id),
            ).fetchone()
            if cycle:
                raise ValueError("Esta indicação criaria um vínculo inválido.")
            if user["referred_by"]:
                self.db.commit()
                return int(user["referred_by"]) == referrer_id
            if self.db.execute(
                "SELECT 1 FROM payments WHERE user_id=? AND status IN ('PAID','REVERSED') LIMIT 1",
                (user_id,),
            ).fetchone():
                raise ValueError("A indicação precisa ser registrada antes da primeira recarga.")
            self.db.execute(
                "UPDATE users SET referred_by=?,referred_at=? WHERE user_id=? AND referred_by=0",
                (referrer_id, int(time.time()), user_id),
            )
            self.db.commit()
            return True
        except BaseException:
            self.db.rollback()
            raise

    def affiliate_summary(self, user_id: int) -> dict:
        user = self.db.execute(
            "SELECT referred_by FROM users WHERE user_id=?", (user_id,)
        ).fetchone()
        earned = self.db.execute(
            "SELECT COALESCE(sum(CASE status WHEN 'ACTIVE' THEN amount_cents ELSE 0 END),0) FROM affiliate_commissions WHERE referrer_id=?",
            (user_id,),
        ).fetchone()[0]
        rows = self.db.execute(
            """SELECT u.user_id,u.username,u.display_name,u.created_at,
            COALESCE(sum(CASE c.status WHEN 'ACTIVE' THEN c.amount_cents ELSE 0 END),0) earned_cents
            FROM users u LEFT JOIN affiliate_commissions c ON c.referred_user_id=u.user_id
            WHERE u.referred_by=? GROUP BY u.user_id ORDER BY u.created_at DESC LIMIT 50""",
            (user_id,),
        ).fetchall()
        return {
            "referredBy": int(user["referred_by"]) if user else 0,
            "invited": len(rows),
            "earnedCents": int(earned),
            "people": [dict(row) for row in rows],
        }

    @staticmethod
    def _raffle_numbers() -> str:
        return ",".join(str(secrets.randbelow(6) + 1) for _ in range(6))

    def _create_raffle_card(self, campaign_id: str, user_id: int, source: str,
                            source_user_id: int = 0) -> bool:
        now = int(time.time())
        for _ in range(250):
            try:
                inserted = self.db.execute(
                    """INSERT OR IGNORE INTO raffle_cards
                    (campaign_id,user_id,source,source_user_id,numbers,created_at)
                    VALUES(?,?,?,?,?,?)""",
                    (campaign_id, user_id, source, source_user_id,
                     self._raffle_numbers(), now),
                ).rowcount
            except sqlite3.IntegrityError:
                inserted = 0
            if inserted:
                return True
            existing = self.db.execute(
                """SELECT 1 FROM raffle_cards WHERE campaign_id=? AND user_id=?
                AND source=? AND source_user_id=?""",
                (campaign_id, user_id, source, source_user_id),
            ).fetchone()
            if existing:
                return False
        raise RuntimeError("Não foi possível gerar uma cartela exclusiva.")

    def raffle_campaign(self, campaign_id: str = "set26") -> dict:
        row = self.db.execute(
            "SELECT * FROM raffle_campaigns WHERE id=?", (campaign_id,)
        ).fetchone()
        if not row:
            raise ValueError("Campanha não encontrada.")
        return dict(row)

    def join_raffle(self, user_id: int, referrer_id: int = 0,
                    campaign_id: str = "set26") -> dict:
        if referrer_id == user_id:
            referrer_id = 0
        now = int(time.time())
        self.db.execute("BEGIN IMMEDIATE")
        try:
            campaign = self.raffle_campaign(campaign_id)
            if campaign["status"] != "OPEN" or campaign["scheduled_at"] <= now:
                raise ValueError("As inscrições desta rodada foram encerradas.")
            if referrer_id and not self.db.execute(
                """SELECT 1 FROM raffle_participants WHERE campaign_id=? AND user_id=?
                AND status='ELIGIBLE'""", (campaign_id, referrer_id)
            ).fetchone():
                referrer_id = 0
            self.db.execute(
                """INSERT OR IGNORE INTO raffle_participants
                (campaign_id,user_id,referrer_id,status,joined_at)
                VALUES(?,?,?,'PENDING',?)""",
                (campaign_id, user_id, referrer_id, now),
            )
            self.db.commit()
            return self.raffle_summary(user_id, campaign_id)
        except BaseException:
            self.db.rollback()
            raise

    def verify_raffle_participant(self, user_id: int,
                                  campaign_id: str = "set26") -> dict:
        now = int(time.time())
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute(
                "SELECT * FROM raffle_participants WHERE campaign_id=? AND user_id=?",
                (campaign_id, user_id),
            ).fetchone()
            if not row:
                raise ValueError("Abra primeiro o link oficial do sorteio.")
            campaign = self.raffle_campaign(campaign_id)
            if campaign["status"] != "OPEN" or campaign["scheduled_at"] <= now:
                raise ValueError("As inscrições desta rodada foram encerradas.")
            self.db.execute(
                """UPDATE raffle_participants SET status='ELIGIBLE',verified_at=?,
                disqualified_reason='' WHERE campaign_id=? AND user_id=?""",
                (now, campaign_id, user_id),
            )
            self._create_raffle_card(campaign_id, user_id, "BASE")
            bonus_referrer = 0
            referrer_id = int(row["referrer_id"])
            if referrer_id and self.db.execute(
                """SELECT 1 FROM raffle_participants WHERE campaign_id=? AND user_id=?
                AND status='ELIGIBLE'""", (campaign_id, referrer_id)
            ).fetchone():
                if self._create_raffle_card(
                    campaign_id, referrer_id, "REFERRAL", user_id
                ):
                    bonus_referrer = referrer_id
            self.db.commit()
            result = self.raffle_summary(user_id, campaign_id)
            result["bonusReferrer"] = bonus_referrer
            return result
        except BaseException:
            self.db.rollback()
            raise

    def raffle_summary(self, user_id: int, campaign_id: str = "set26") -> dict:
        campaign = self.raffle_campaign(campaign_id)
        participant = self.db.execute(
            "SELECT * FROM raffle_participants WHERE campaign_id=? AND user_id=?",
            (campaign_id, user_id),
        ).fetchone()
        cards = self.db.execute(
            "SELECT * FROM raffle_cards WHERE campaign_id=? AND user_id=? ORDER BY id",
            (campaign_id, user_id),
        ).fetchall()
        referrals = self.db.execute(
            """SELECT count(*) FROM raffle_participants WHERE campaign_id=?
            AND referrer_id=? AND status='ELIGIBLE'""", (campaign_id, user_id)
        ).fetchone()[0]
        winner = self.db.execute(
            "SELECT * FROM raffle_winners WHERE campaign_id=? AND user_id=?",
            (campaign_id, user_id),
        ).fetchone()
        return {
            "campaign": campaign,
            "participant": dict(participant) if participant else None,
            "cards": [dict(row) for row in cards],
            "referrals": int(referrals),
            "winner": dict(winner) if winner else None,
        }

    def raffle_admin_summary(self, campaign_id: str = "set26") -> dict:
        campaign = self.raffle_campaign(campaign_id)
        counts = self.db.execute(
            """SELECT count(*) participants,
            sum(status='ELIGIBLE') eligible FROM raffle_participants WHERE campaign_id=?""",
            (campaign_id,),
        ).fetchone()
        cards = self.db.execute(
            "SELECT count(*) FROM raffle_cards WHERE campaign_id=?", (campaign_id,)
        ).fetchone()[0]
        winners = self.db.execute(
            """SELECT w.*,u.display_name,u.username FROM raffle_winners w
            JOIN users u ON u.user_id=w.user_id WHERE w.campaign_id=? ORDER BY w.position""",
            (campaign_id,),
        ).fetchall()
        return {
            "campaign": campaign,
            "participants": int(counts["participants"] or 0),
            "eligible": int(counts["eligible"] or 0),
            "cards": int(cards),
            "winners": [dict(row) for row in winners],
        }

    def due_raffle(self, now: int | None = None) -> dict | None:
        row = self.db.execute(
            """SELECT * FROM raffle_campaigns WHERE status IN ('OPEN','DRAWING')
            AND scheduled_at<=? ORDER BY scheduled_at LIMIT 1""",
            (int(time.time()) if now is None else now,),
        ).fetchone()
        return dict(row) if row else None

    def begin_raffle(self, campaign_id: str) -> bool:
        self.db.execute("BEGIN IMMEDIATE")
        try:
            campaign = self.raffle_campaign(campaign_id)
            eligible = self.db.execute(
                """SELECT count(*) FROM raffle_participants
                WHERE campaign_id=? AND status='ELIGIBLE'""", (campaign_id,)
            ).fetchone()[0]
            if eligible < campaign["draw_count"]:
                self.db.rollback()
                return False
            if campaign["status"] == "OPEN":
                self.db.execute(
                    "UPDATE raffle_campaigns SET status='DRAWING',started_at=?,updated_at=? WHERE id=?",
                    (int(time.time()), int(time.time()), campaign_id),
                )
            self.db.commit()
            return True
        except BaseException:
            self.db.rollback()
            raise

    def raffle_rolls(self, campaign_id: str, position: int) -> list[dict]:
        return [dict(row) for row in self.db.execute(
            """SELECT * FROM raffle_rolls WHERE campaign_id=? AND winner_position=?
            ORDER BY roll_position""", (campaign_id, position)
        )]

    def save_raffle_roll(self, campaign_id: str, position: int, roll_position: int,
                         value: int, message_id: int) -> None:
        if not 1 <= value <= 6 or not 1 <= roll_position <= 6:
            raise ValueError("Resultado do dado inválido.")
        with self.db:
            self.db.execute(
                """INSERT OR IGNORE INTO raffle_rolls
                (campaign_id,winner_position,roll_position,value,message_id,created_at)
                VALUES(?,?,?,?,?,?)""",
                (campaign_id, position, roll_position, value, message_id, int(time.time())),
            )

    def raffle_candidates(self, campaign_id: str, dice_values: list[int],
                          position: int) -> list[dict]:
        import hashlib

        excluded = {int(row[0]) for row in self.db.execute(
            "SELECT user_id FROM raffle_winners WHERE campaign_id=?", (campaign_id,)
        )}
        rows = self.db.execute(
            """SELECT c.*,u.display_name,u.username FROM raffle_cards c
            JOIN raffle_participants p ON p.campaign_id=c.campaign_id AND p.user_id=c.user_id
            JOIN users u ON u.user_id=c.user_id
            WHERE c.campaign_id=? AND p.status='ELIGIBLE'""", (campaign_id,)
        ).fetchall()
        result = []
        for raw in rows:
            row = dict(raw)
            if int(row["user_id"]) in excluded:
                continue
            numbers = [int(value) for value in row["numbers"].split(",")]
            row["distance"] = sum(abs(a - b) for a, b in zip(numbers, dice_values))
            row["exact_positions"] = sum(a == b for a, b in zip(numbers, dice_values))
            tie = f"{campaign_id}:{position}:{','.join(map(str,dice_values))}:{row['id']}"
            row["tie"] = hashlib.sha256(tie.encode()).hexdigest()
            result.append(row)
        return sorted(result, key=lambda row: (
            row["distance"], -row["exact_positions"], row["tie"]
        ))

    def disqualify_raffle_user(self, campaign_id: str, user_id: int,
                               reason: str) -> None:
        with self.db:
            self.db.execute(
                """UPDATE raffle_participants SET status='DISQUALIFIED',
                disqualified_reason=? WHERE campaign_id=? AND user_id=?""",
                (reason[:160], campaign_id, user_id),
            )

    def save_raffle_winner(self, campaign_id: str, position: int, candidate: dict,
                           dice_values: list[int], message_ids: list[int]) -> bool:
        with self.db:
            return bool(self.db.execute(
                """INSERT OR IGNORE INTO raffle_winners
                (campaign_id,position,user_id,card_id,numbers,dice_values,dice_message_ids,
                distance,exact_positions,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (campaign_id, position, candidate["user_id"], candidate["id"],
                 candidate["numbers"], json.dumps(dice_values), json.dumps(message_ids),
                 candidate["distance"], candidate["exact_positions"], int(time.time())),
            ).rowcount)

    def finish_raffle(self, campaign_id: str) -> None:
        with self.db:
            count = self.db.execute(
                "SELECT count(*) FROM raffle_winners WHERE campaign_id=?", (campaign_id,)
            ).fetchone()[0]
            campaign = self.raffle_campaign(campaign_id)
            if count >= campaign["draw_count"]:
                now = int(time.time())
                self.db.execute(
                    """UPDATE raffle_campaigns SET status='COMPLETED',completed_at=?,
                    updated_at=? WHERE id=?""", (now, now, campaign_id)
                )

    def choose_raffle_prize(self, campaign_id: str, user_id: int,
                            choice: str) -> dict:
        if choice not in {"crunchyroll", "netflix"}:
            raise ValueError("Escolha Crunchyroll Premium ou Netflix 4K.")
        with self.db:
            row = self.db.execute(
                "SELECT * FROM raffle_winners WHERE campaign_id=? AND user_id=?",
                (campaign_id, user_id),
            ).fetchone()
            if not row:
                raise ValueError("Esta opção está disponível somente para vencedores.")
            if row["prize_choice"] and row["prize_choice"] != choice:
                raise ValueError("A escolha do prêmio já foi registrada.")
            self.db.execute(
                """UPDATE raffle_winners SET prize_choice=?,chosen_at=CASE WHEN chosen_at=0
                THEN ? ELSE chosen_at END WHERE campaign_id=? AND user_id=?""",
                (choice, int(time.time()), campaign_id, user_id),
            )
        return dict(self.db.execute(
            "SELECT * FROM raffle_winners WHERE campaign_id=? AND user_id=?",
            (campaign_id, user_id),
        ).fetchone())

    def track_interest(self, user_id: int, platform: str, label: str,
                       service_id: int = 0, *, now: int | None = None) -> dict | None:
        current = int(time.time()) if now is None else now
        platform, label = platform.strip()[:80], label.strip()[:160]
        if not platform or not label or service_id < 0:
            raise ValueError("Interesse inválido.")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            user = self.db.execute(
                "SELECT recovery_opt_out FROM users WHERE user_id=?", (user_id,)
            ).fetchone()
            if not user or user[0]:
                self.db.rollback()
                return None
            active = self.db.execute(
                "SELECT * FROM interest_events WHERE user_id=? AND status='ACTIVE'",
                (user_id,),
            ).fetchone()
            if active and active["platform"] == platform and int(active["service_id"]) == service_id:
                self.db.commit()
                return dict(active)
            self.db.execute(
                "UPDATE interest_events SET status='SUPERSEDED',updated_at=? WHERE user_id=? AND status='ACTIVE'",
                (current, user_id),
            )
            token = secrets.token_hex(10)
            self.db.execute(
                """INSERT INTO interest_events
                (id,user_id,platform,service_id,label,status,created_at,first_due_at,
                second_due_at,updated_at) VALUES(?,?,?,?,?,'ACTIVE',?,?,?,?)""",
                (token, user_id, platform, service_id, label, current,
                 current + 1800, current + 86400, current),
            )
            self.db.commit()
            return dict(self.db.execute(
                "SELECT * FROM interest_events WHERE id=?", (token,)
            ).fetchone())
        except BaseException:
            self.db.rollback()
            raise

    def convert_interests(self, user_id: int, service_id: int) -> None:
        with self.db:
            self.db.execute(
                """UPDATE interest_events SET status='CONVERTED',updated_at=?
                WHERE user_id=? AND status='ACTIVE' AND (service_id=0 OR service_id=?)""",
                (int(time.time()), user_id, service_id),
            )

    def claim_interest_notification(self, *, now: int | None = None) -> tuple[dict, int] | None:
        current = int(time.time()) if now is None else now
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute(
                """SELECT i.*,u.display_name,u.username FROM interest_events i
                JOIN users u ON u.user_id=i.user_id WHERE i.status='ACTIVE' AND
                ((i.first_sent_at=0 AND i.first_due_at<=?) OR
                 (i.first_sent_at>0 AND i.second_sent_at=0 AND i.second_due_at<=?))
                ORDER BY CASE WHEN i.first_sent_at=0 THEN i.first_due_at ELSE i.second_due_at END LIMIT 1""",
                (current, current),
            ).fetchone()
            if not row:
                self.db.rollback()
                return None
            stage = 1 if int(row["first_sent_at"]) == 0 else 2
            column = "first_sent_at" if stage == 1 else "second_sent_at"
            self.db.execute(
                f"UPDATE interest_events SET {column}=-1,updated_at=? WHERE id=?",
                (current, row["id"]),
            )
            self.db.commit()
            return dict(row), stage
        except BaseException:
            self.db.rollback()
            raise

    def finish_interest_notification(self, token: str, stage: int, success: bool,
                                     *, terminal: bool = False) -> None:
        column = "first_sent_at" if stage == 1 else "second_sent_at"
        with self.db:
            if terminal:
                self.db.execute(
                    "UPDATE interest_events SET status='UNREACHABLE',updated_at=? WHERE id=?",
                    (int(time.time()), token),
                )
            else:
                self.db.execute(
                    f"UPDATE interest_events SET {column}=?,updated_at=? WHERE id=?",
                    (int(time.time()) if success else 0, int(time.time()), token),
                )
                if success and stage == 2:
                    self.db.execute(
                        "UPDATE interest_events SET status='COMPLETED' WHERE id=?", (token,)
                    )

    def recovery_opt_out(self, user_id: int) -> None:
        with self.db:
            self.db.execute(
                "UPDATE users SET recovery_opt_out=1,updated_at=? WHERE user_id=?",
                (int(time.time()), user_id),
            )
            self.db.execute(
                "UPDATE interest_events SET status='OPTOUT',updated_at=? WHERE user_id=? AND status='ACTIVE'",
                (int(time.time()), user_id),
            )

    def ledger(self, user_id: int, limit: int = 10) -> list[dict]:
        return [dict(x) for x in self.db.execute(
            "SELECT * FROM wallet_ledger WHERE user_id=? ORDER BY id DESC LIMIT ?", (user_id, limit))]

    def _adjust_wallet(self, user_id: int, amount_cents: int, kind: str, reference: str,
                       description: str = "") -> bool:
        now = int(time.time())
        inserted = self.db.execute("""INSERT OR IGNORE INTO wallet_ledger
            (user_id,amount_cents,kind,reference,description,created_at) VALUES(?,?,?,?,?,?)""",
            (user_id, amount_cents, kind, reference, description[:200], now)).rowcount
        if inserted:
            self.db.execute("UPDATE wallets SET balance_cents=balance_cents+?,updated_at=? WHERE user_id=?",
                            (amount_cents, now, user_id))
        return bool(inserted)

    def create_payment(self, user_id: int, amount_cents: int, customer: dict,
                       request_id: str | None = None) -> dict:
        import hashlib
        serialized = json.dumps(customer, ensure_ascii=False, sort_keys=True)
        digest = hashlib.sha256(f"{amount_cents}:{serialized}".encode()).hexdigest()
        token, now = secrets.token_hex(10), int(time.time())
        self.db.execute("BEGIN IMMEDIATE")
        try:
            if request_id:
                existing = self.db.execute("SELECT * FROM payment_requests WHERE user_id=? AND request_id=?",
                                           (user_id, request_id)).fetchone()
                if existing:
                    if existing["request_hash"] != digest:
                        raise ValueError("Esta tentativa já foi usada com outros dados.")
                    self.db.commit()
                    return self.payment(existing["payment_id"], user_id)
                count = self.db.execute("SELECT count(*) FROM payments WHERE user_id=? AND created_at>?",
                                        (user_id, now - 900)).fetchone()[0]
                if count >= 5:
                    raise ValueError("Você já gerou várias recargas. Use um Pix pendente ou aguarde 15 minutos.")
            self.db.execute("""INSERT INTO payments
                (id,user_id,amount_cents,idempotency_key,customer_json,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?)""",
                (token, user_id, amount_cents, str(uuid.uuid4()),
                 serialized, now, now))
            if request_id:
                self.db.execute("INSERT INTO payment_requests VALUES(?,?,?,?)", (user_id, request_id, token, digest))
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise
        return self.payment(token, user_id)

    def credit_by_admin(self, admin_id: int, user_id: int, cents: int, reason: str, request_id: str) -> dict:
        if not 1 <= cents <= 500000 or not reason.strip():
            raise ValueError("Informe de R$ 0,01 a R$ 5.000,00 e um motivo.")
        reference = f"admin:{admin_id}:{request_id}"
        self.db.execute("BEGIN IMMEDIATE")
        try:
            if not self.db.execute("SELECT 1 FROM wallets WHERE user_id=?", (user_id,)).fetchone():
                raise ValueError("Usuário não encontrado. Ele precisa abrir o bot primeiro.")
            existing = self.db.execute("SELECT * FROM admin_credits WHERE reference=?", (reference,)).fetchone()
            if existing:
                if (existing["user_id"], existing["amount_cents"], existing["reason"]) != (user_id, cents, reason):
                    raise ValueError("Esta confirmação já foi usada com outros dados.")
            else:
                self.db.execute("INSERT INTO admin_credits VALUES(?,?,?,?,?,?)",
                                (reference, admin_id, user_id, cents, reason, int(time.time())))
                self._adjust_wallet(user_id, cents, "ADMIN_CREDIT", reference, f"Crédito administrativo: {reason}")
            self.db.commit()
            return {"userId": user_id, "amountCents": cents, "balanceCents": self.balance_cents(user_id),
                    "repeated": bool(existing)}
        except BaseException:
            self.db.rollback()
            raise

    def payment(self, token: str, user_id: int | None = None) -> dict | None:
        if user_id is None:
            row = self.db.execute("SELECT * FROM payments WHERE id=?", (token,)).fetchone()
        else:
            row = self.db.execute("SELECT * FROM payments WHERE id=? AND user_id=?", (token, user_id)).fetchone()
        return dict(row) if row else None

    def claim_payment(self, token: str, user_id: int) -> bool:
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.payment(token, user_id)
            if not row or row["status"] not in {"CREATED", "UNKNOWN"}:
                self.db.rollback()
                return False
            self.db.execute("UPDATE payments SET status='CREATING',error='',updated_at=? WHERE id=?",
                            (int(time.time()), token))
            self.db.commit()
            return True
        except BaseException:
            self.db.rollback()
            raise

    def payment_created(self, token: str, data: dict) -> None:
        pix = data.get("pix") if isinstance(data.get("pix"), dict) else {}
        with self.db:
            self.db.execute("""UPDATE payments SET status='PENDING',cakto_order_id=?,cakto_ref_id=?,
                provider_status=?,qr_code=?,checkout_url=?,expires_at=?,customer_json='{}',error='',updated_at=?
                WHERE id=?""", (str(data.get("id", "")), str(data.get("refId", "")),
                str(data.get("status", "waiting_payment")), str(pix.get("qrCode", "")),
                str(data.get("checkoutUrl", "")), str(pix.get("expirationDate", "")),
                int(time.time()), token))

    def payment_failed(self, token: str, status: str, error: str) -> None:
        if status not in {"FAILED", "UNKNOWN"}:
            raise ValueError("Estado de pagamento inválido.")
        with self.db:
            self.db.execute("""UPDATE payments SET status=?,error=?,
                customer_json=CASE WHEN ?='FAILED' THEN '{}' ELSE customer_json END,updated_at=? WHERE id=?""",
                (status, error[:500], status, int(time.time()), token))

    def update_payment_status(self, token: str, provider_status: str) -> tuple[dict, bool]:
        """Atualiza e credita/reverte uma vez. Retorna (pagamento, saldo_alterado)."""
        status = provider_status.strip().lower()
        if not status:
            raise ValueError("Status de pagamento vazio.")
        changed = False
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.payment(token)
            if not row:
                raise ValueError("Pagamento não encontrado.")
            now = int(time.time())
            local = row["status"]
            # Concurrent polling can return an older status after a refund.
            if local == "REVERSED" and status not in {"refunded", "chargedback"} or local == "PAID" and status not in {"paid", "refunded", "chargedback"}:
                status = row["provider_status"]
            if status == "paid":
                changed = self._adjust_wallet(row["user_id"], row["amount_cents"], "DEPOSIT",
                                              f"payment:{token}", "Recarga Pix aprovada")
                if changed:
                    referred = self.db.execute(
                        "SELECT referred_by FROM users WHERE user_id=?", (row["user_id"],)
                    ).fetchone()
                    referrer_id = int(referred["referred_by"]) if referred else 0
                    if referrer_id:
                        commission = int(
                            (Decimal(row["amount_cents"]) * Decimal("0.15")).quantize(
                                Decimal(1), rounding=ROUND_HALF_UP
                            )
                        )
                        self.db.execute(
                            """INSERT OR IGNORE INTO affiliate_commissions
                            (payment_id,referred_user_id,referrer_id,amount_cents,status,created_at,updated_at)
                            VALUES(?,?,?,?, 'ACTIVE',?,?)""",
                            (token, row["user_id"], referrer_id, commission, now, now),
                        )
                        self._adjust_wallet(
                            referrer_id, commission, "AFFILIATE_COMMISSION",
                            f"affiliate:{token}", "Comissão de afiliado sobre recarga aprovada",
                        )
                local = "PAID"
            elif status in {"refunded", "chargedback"}:
                if self.db.execute("SELECT 1 FROM wallet_ledger WHERE reference=?", (f"payment:{token}",)).fetchone():
                    changed = self._adjust_wallet(row["user_id"], -row["amount_cents"], "REVERSAL",
                                                  f"reversal:{token}", "Recarga estornada")
                commission = self.db.execute(
                    "SELECT * FROM affiliate_commissions WHERE payment_id=? AND status='ACTIVE'", (token,)
                ).fetchone()
                if commission:
                    self._adjust_wallet(
                        commission["referrer_id"], -commission["amount_cents"],
                        "AFFILIATE_REVERSAL", f"affiliate-reversal:{token}",
                        "Estorno de comissão de afiliado",
                    )
                    self.db.execute(
                        "UPDATE affiliate_commissions SET status='REVERSED',updated_at=? WHERE payment_id=?",
                        (now, token),
                    )
                local = "REVERSED"
            elif status in {"refused", "blocked", "canceled", "acquirer_error"}:
                local = "FAILED"
            elif local not in {"PAID", "REVERSED"}:
                local = "PENDING"
            self.db.execute("""UPDATE payments SET status=?,provider_status=?,checked_at=?,updated_at=?
                WHERE id=?""", (local, status, now, now, token))
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise
        return self.payment(token), changed

    def pending_payments(self, limit: int = 100) -> list[dict]:
        rows = self.db.execute("""SELECT * FROM payments WHERE cakto_order_id IS NOT NULL
            AND (status IN ('PENDING','PAID') OR provider_status<>notified_status)
            ORDER BY checked_at ASC,created_at ASC LIMIT ?""", (limit,)).fetchall()
        return [dict(x) for x in rows]

    def payment_notified(self, token: str, status: str) -> None:
        with self.db:
            self.db.execute("UPDATE payments SET notified_status=? WHERE id=?", (status, token))

    def create_order(self, user_id: int, service, payload: dict, provider_cost, sell_price,
                     currency: str = "BRL", dry_run: bool = False, pricing_revision: int = 0) -> dict:
        token, now = secrets.token_hex(8), int(time.time())
        with self.db:
            self.db.execute("UPDATE orders SET state='ABORTED' WHERE user_id=? AND state='DRAFT'", (user_id,))
            self.db.execute("""INSERT INTO orders
                (id,user_id,service_id,service_name,kind,payload,target,rate,provider_cost,cost,
                 currency,dry_run,created_at,expires_at,updated_at,pricing_revision)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (token, user_id, service.id, service.name, service.kind,
                 json.dumps(payload, ensure_ascii=False), payload["link"], str(service.rate),
                 str(provider_cost), str(sell_price), currency, int(dry_run), now, now + 300, now, pricing_revision))
        return self.order(token, user_id)

    def order(self, token: str, user_id: int | None = None) -> dict | None:
        if user_id is None:
            row = self.db.execute("SELECT * FROM orders WHERE id=?", (token,)).fetchone()
        else:
            row = self.db.execute("SELECT * FROM orders WHERE id=? AND user_id=?", (token, user_id)).fetchone()
        return dict(row) if row else None

    def by_provider(self, provider_id: str, user_id: int) -> dict | None:
        row = self.db.execute("SELECT * FROM orders WHERE provider_id=? AND user_id=?", (provider_id, user_id)).fetchone()
        return dict(row) if row else None

    def mark_order(self, token: str, state: str, *, error: str = "", provider_id: str | None = None) -> None:
        with self.db:
            self.db.execute("""UPDATE orders SET state=?,error=?,updated_at=?,provider_id=COALESCE(?,provider_id)
                WHERE id=?""", (state, error[:500], int(time.time()), provider_id, token))

    def refund_order(self, token: str, reason: str) -> bool:
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.order(token)
            if not row:
                raise ValueError("Pedido não encontrado.")
            cents = int((Decimal(row["cost"]) * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))
            changed = self._adjust_wallet(row["user_id"], cents, "ORDER_REFUND", f"refund:{token}", reason)
            self.db.commit()
            return changed
        except BaseException:
            self.db.rollback()
            raise

    def reject_order_and_refund(self, token: str, reason: str, error: str) -> bool:
        """Marca uma recusa e devolve o saldo na mesma transação SQLite."""
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.order(token)
            if not row:
                raise ValueError("Pedido não encontrado.")
            cents = int((Decimal(row["cost"]) * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))
            changed = self._adjust_wallet(row["user_id"], cents, "ORDER_REFUND",
                                          f"refund:{token}", reason)
            self.db.execute("""UPDATE orders SET state='REJECTED',provider_status='canceled',error=?,updated_at=?
                WHERE id=?""", (error[:500], int(time.time()), token))
            self.db.commit()
            return changed
        except BaseException:
            self.db.rollback()
            raise

    def abort_drafts(self, user_id: int) -> None:
        with self.db:
            self.db.execute("UPDATE orders SET state='ABORTED' WHERE user_id=? AND state='DRAFT'", (user_id,))
            self.db.execute("UPDATE actions SET state='ABORTED' WHERE user_id=? AND state='DRAFT'", (user_id,))

    def claim_order(self, token: str, user_id: int, *, queued: bool = False, pricing_revision: int | None = None) -> bool:
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.order(token, user_id)
            if pricing_revision is not None and self.db.execute("SELECT revision FROM pricing_policy WHERE id=1").fetchone()[0] != pricing_revision:
                raise ValueError("Os preços foram atualizados. Revise um novo orçamento antes de confirmar.")
            if not row or row["state"] != "DRAFT" or row["expires_at"] < int(time.time()):
                self.db.rollback()
                return False
            placeholders = ",".join("?" for _ in TERMINAL)
            duplicate = self.db.execute(f"""SELECT id FROM orders WHERE id<>? AND service_id=? AND target=?
                AND (state IN ('QUEUED','MANUAL','SENDING','UNKNOWN') OR (state='SUBMITTED' AND lower(provider_status) NOT IN ({placeholders})))
                LIMIT 1""", (token, row["service_id"], row["target"], *TERMINAL)).fetchone()
            if duplicate:
                raise ValueError("Já existe um pedido ativo desse serviço para o mesmo destino.")
            cents = int((Decimal(row["cost"]) * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))
            if self.balance_cents(user_id) < cents:
                raise ValueError("Saldo insuficiente. Adicione saldo via Pix e tente novamente.")
            if not self._adjust_wallet(user_id, -cents, "ORDER", f"order:{token}", row["service_name"]):
                self.db.rollback()
                return False
            self.db.execute("UPDATE orders SET state=?,updated_at=? WHERE id=?", ("QUEUED" if queued else "SENDING", int(time.time()), token))
            self.db.execute(
                """UPDATE interest_events SET status='CONVERTED',updated_at=?
                WHERE user_id=? AND status='ACTIVE' AND (service_id=0 OR service_id=?)""",
                (int(time.time()), user_id, row["service_id"]),
            )
            self.db.commit()
            return True
        except BaseException:
            self.db.rollback()
            raise

    def list_orders(self, user_id: int, page: int, limit: int = 8) -> tuple[list[dict], int]:
        total = self.db.execute("SELECT count(*) FROM orders WHERE user_id=? AND state NOT IN ('DRAFT','ABORTED')", (user_id,)).fetchone()[0]
        rows = self.db.execute("""SELECT * FROM orders WHERE user_id=? AND state NOT IN ('DRAFT','ABORTED')
            ORDER BY created_at DESC,rowid DESC LIMIT ? OFFSET ?""", (user_id, limit, max(page, 0) * limit)).fetchall()
        return [dict(x) for x in rows], total

    def update_status(self, token: str, data: dict) -> None:
        status = data.get("status")
        if not isinstance(status, str) or not status.strip():
            raise ValueError("Status vazio retornado pelo serviço.")
        with self.db:
            self.db.execute("UPDATE orders SET provider_status=?,status_json=?,checked_at=?,updated_at=? WHERE id=?",
                (status[:120], json.dumps(data, ensure_ascii=False), int(time.time()), int(time.time()), token))

    def watched(self, limit: int = 100) -> list[dict]:
        placeholders = ",".join("?" for _ in TERMINAL)
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

    def create_action(self, order: dict, kind: str, dry_run: bool = False) -> dict:
        if kind not in {"refill", "cancel"}:
            raise ValueError("Ação inválida.")
        token, now = secrets.token_hex(8), int(time.time())
        with self.db:
            self.db.execute("UPDATE actions SET state='ABORTED' WHERE user_id=? AND state='DRAFT'", (order["user_id"],))
            self.db.execute("""INSERT INTO actions (id,order_id,user_id,kind,dry_run,created_at,expires_at)
                VALUES (?,?,?,?,?,?,?)""", (token, order["id"], order["user_id"], kind, int(dry_run), now, now + 300))
        return self.action(token, order["user_id"])

    def action(self, token: str, user_id: int) -> dict | None:
        row = self.db.execute("SELECT * FROM actions WHERE id=? AND user_id=?", (token, user_id)).fetchone()
        return dict(row) if row else None

    def claim_action(self, token: str, user_id: int) -> bool:
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.action(token, user_id)
            now = int(time.time())
            if not row or row["state"] != "DRAFT" or row["expires_at"] < now:
                self.db.rollback()
                return False
            other = self.db.execute("""SELECT id FROM actions WHERE id<>? AND order_id=? AND kind=?
                AND (state IN ('SENDING','UNKNOWN') OR (state='SUBMITTED' AND (kind='cancel' OR created_at>?))) LIMIT 1""",
                (token, row["order_id"], row["kind"], now - 86400)).fetchone()
            if other:
                raise ValueError("Já existe uma solicitação enviada ou em análise.")
            self.db.execute("UPDATE actions SET state='SENDING' WHERE id=?", (token,))
            self.db.commit()
            return True
        except BaseException:
            self.db.rollback()
            raise

    def mark_action(self, token: str, state: str, *, result: dict | None = None, error: str = "") -> None:
        with self.db:
            self.db.execute("UPDATE actions SET state=?,result_json=?,error=? WHERE id=?",
                (state, json.dumps(result or {}, ensure_ascii=False), error[:500], token))

    def actions_for(self, order_id: str, user_id: int) -> list[dict]:
        return [dict(x) for x in self.db.execute("""SELECT * FROM actions WHERE order_id=? AND user_id=?
            AND state NOT IN ('DRAFT','ABORTED') ORDER BY created_at DESC,rowid DESC LIMIT 5""", (order_id, user_id))]

    def recover(self) -> None:
        with self.db:
            self.db.execute("UPDATE orders SET state='UNKNOWN',error='Processo interrompido durante envio' WHERE state='SENDING'")
            self.db.execute("UPDATE actions SET state='UNKNOWN',error='Processo interrompido durante envio' WHERE state='SENDING'")
            self.db.execute("UPDATE payments SET status='UNKNOWN',error='Processo interrompido ao gerar Pix' WHERE status='CREATING'")
            self.db.execute("UPDATE broadcast_deliveries SET status='FAILED',error='Envio interrompido',updated_at=? WHERE status='SENDING'", (int(time.time()),))
            self.db.execute("UPDATE broadcasts SET status='QUEUED' WHERE status='RUNNING'")
            self.db.execute("UPDATE interest_events SET first_sent_at=0 WHERE first_sent_at=-1")
            self.db.execute("UPDATE interest_events SET second_sent_at=0 WHERE second_sent_at=-1")

    def create_broadcast(self, admin_id: int, request_id: str, message: str,
                         button_text: str, button_target: str) -> dict:
        now, token = int(time.time()), secrets.token_hex(10)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            existing = self.db.execute(
                "SELECT * FROM broadcasts WHERE request_id=?", (request_id,)
            ).fetchone()
            if existing:
                if (existing["admin_id"], existing["message"], existing["button_text"], existing["button_target"]) != (
                    admin_id, message, button_text, button_target
                ):
                    raise ValueError("Esta confirmação já foi usada com outro conteúdo.")
                self.db.commit()
                return dict(existing)
            if self.db.execute(
                "SELECT 1 FROM broadcasts WHERE status IN ('QUEUED','RUNNING') LIMIT 1"
            ).fetchone():
                raise ValueError("Já existe uma transmissão em andamento.")
            self.db.execute(
                """INSERT INTO broadcasts(id,request_id,admin_id,message,button_text,button_target,status,created_at)
                VALUES(?,?,?,?,?,?, 'QUEUED',?)""",
                (token, request_id, admin_id, message, button_text, button_target, now),
            )
            self.db.execute(
                """INSERT INTO broadcast_deliveries(broadcast_id,user_id,updated_at)
                SELECT ?,user_id,? FROM users""", (token, now)
            )
            total = self.db.execute(
                "SELECT count(*) FROM broadcast_deliveries WHERE broadcast_id=?", (token,)
            ).fetchone()[0]
            self.db.execute("UPDATE broadcasts SET total=? WHERE id=?", (total, token))
            self.db.commit()
            return dict(self.db.execute("SELECT * FROM broadcasts WHERE id=?", (token,)).fetchone())
        except BaseException:
            self.db.rollback()
            raise

    def broadcasts(self, limit: int = 20) -> list[dict]:
        return [dict(row) for row in self.db.execute(
            "SELECT * FROM broadcasts ORDER BY created_at DESC,rowid DESC LIMIT ?", (limit,)
        )]

    def claim_broadcast_delivery(self) -> tuple[dict, int] | None:
        now = int(time.time())
        self.db.execute("BEGIN IMMEDIATE")
        try:
            job = self.db.execute(
                "SELECT * FROM broadcasts WHERE status IN ('QUEUED','RUNNING') ORDER BY created_at LIMIT 1"
            ).fetchone()
            if not job:
                self.db.rollback()
                return None
            delivery = self.db.execute(
                "SELECT user_id FROM broadcast_deliveries WHERE broadcast_id=? AND status='PENDING' ORDER BY user_id LIMIT 1",
                (job["id"],),
            ).fetchone()
            if not delivery:
                self.db.execute(
                    "UPDATE broadcasts SET status='COMPLETED',finished_at=? WHERE id=?",
                    (now, job["id"]),
                )
                self.db.commit()
                return None
            self.db.execute(
                "UPDATE broadcasts SET status='RUNNING',started_at=CASE WHEN started_at=0 THEN ? ELSE started_at END WHERE id=?",
                (now, job["id"]),
            )
            self.db.execute(
                "UPDATE broadcast_deliveries SET status='SENDING',updated_at=? WHERE broadcast_id=? AND user_id=?",
                (now, job["id"], delivery["user_id"]),
            )
            self.db.commit()
            return dict(job), int(delivery["user_id"])
        except BaseException:
            self.db.rollback()
            raise

    def finish_broadcast_delivery(self, broadcast_id: str, user_id: int,
                                  status: str, error: str = "") -> None:
        if status not in {"SENT", "FAILED", "PENDING"}:
            raise ValueError("Estado de transmissão inválido.")
        with self.db:
            self.db.execute(
                "UPDATE broadcast_deliveries SET status=?,error=?,updated_at=? WHERE broadcast_id=? AND user_id=? AND status='SENDING'",
                (status, error[:200], int(time.time()), broadcast_id, user_id),
            )
            counts = self.db.execute(
                "SELECT sum(status='SENT'),sum(status='FAILED') FROM broadcast_deliveries WHERE broadcast_id=?",
                (broadcast_id,),
            ).fetchone()
            self.db.execute(
                "UPDATE broadcasts SET sent=?,failed=? WHERE id=?",
                (int(counts[0] or 0), int(counts[1] or 0), broadcast_id),
            )

    def cancel_broadcast(self, token: str) -> dict:
        now = int(time.time())
        with self.db:
            row = self.db.execute("SELECT * FROM broadcasts WHERE id=?", (token,)).fetchone()
            if not row:
                raise ValueError("Transmissão não encontrada.")
            if row["status"] not in {"QUEUED", "RUNNING"}:
                return dict(row)
            self.db.execute(
                "UPDATE broadcasts SET status='CANCELLED',finished_at=? WHERE id=?", (now, token)
            )
            self.db.execute(
                "UPDATE broadcast_deliveries SET status='CANCELLED',updated_at=? WHERE broadcast_id=? AND status='PENDING'",
                (now, token),
            )
        return dict(self.db.execute("SELECT * FROM broadcasts WHERE id=?", (token,)).fetchone())

    def admin_stats(self) -> dict:
        return {
            "users": self.db.execute("SELECT count(*) FROM users").fetchone()[0],
            "wallet_cents": self.db.execute("SELECT COALESCE(sum(balance_cents),0) FROM wallets").fetchone()[0],
            "paid_cents": self.db.execute("SELECT COALESCE(sum(amount_cents),0) FROM payments WHERE status='PAID'").fetchone()[0],
            "orders": self.db.execute("SELECT count(*) FROM orders WHERE state NOT IN ('DRAFT','ABORTED')").fetchone()[0],
            "unknown_orders": self.db.execute("SELECT count(*) FROM orders WHERE state='UNKNOWN'").fetchone()[0],
            "pending_payments": self.db.execute("SELECT count(*) FROM payments WHERE status IN ('PENDING','UNKNOWN')").fetchone()[0],
            "affiliate_cents": self.db.execute("SELECT COALESCE(sum(CASE status WHEN 'ACTIVE' THEN amount_cents ELSE 0 END),0) FROM affiliate_commissions").fetchone()[0],
        }
