from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from lens.domain.portfolio import Transaction, TxKind
from lens.storage.models import InstrumentRow, ThesisNote, TransactionRow


class LedgerRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def add(
        self,
        owner_id: int,
        instrument_id: int,
        *,
        kind: TxKind,
        day: date,
        currency: str,
        quantity: Decimal = Decimal(0),
        price: Decimal = Decimal(0),
        fee: Decimal = Decimal(0),
        amount: Decimal = Decimal(0),
        ratio: Decimal = Decimal(0),
        note: str | None = None,
    ) -> int:
        tx_id = await self.s.scalar(
            insert(TransactionRow)
            .values(
                owner_id=owner_id,
                instrument_id=instrument_id,
                kind=kind.value,
                day=day,
                currency=currency,
                quantity=quantity,
                price=price,
                fee=fee,
                amount=amount,
                ratio=ratio,
                note=note,
            )
            .returning(TransactionRow.id)
        )
        assert tx_id is not None
        return int(tx_id)

    async def transactions(self, owner_id: int) -> list[Transaction]:
        rows = await self.s.execute(
            select(TransactionRow, InstrumentRow.symbol)
            .join(InstrumentRow, InstrumentRow.id == TransactionRow.instrument_id)
            .where(TransactionRow.owner_id == owner_id)
            .order_by(TransactionRow.day, TransactionRow.id)
        )
        return [
            Transaction(
                r.id,
                symbol,
                TxKind(r.kind),
                r.day,
                r.currency,
                r.quantity,
                r.price,
                r.fee,
                r.amount,
                r.ratio,
                r.note,
            )
            for r, symbol in rows.all()
        ]

    async def set_note(self, owner_id: int, instrument_id: int, note: str) -> None:
        statement = insert(ThesisNote).values(
            owner_id=owner_id, instrument_id=instrument_id, note=note
        )
        await self.s.execute(
            statement.on_conflict_do_update(
                index_elements=[ThesisNote.owner_id, ThesisNote.instrument_id], set_={"note": note}
            )
        )

    async def notes(self, owner_id: int) -> dict[str, str]:
        rows = await self.s.execute(
            select(InstrumentRow.symbol, ThesisNote.note)
            .join(InstrumentRow, InstrumentRow.id == ThesisNote.instrument_id)
            .where(ThesisNote.owner_id == owner_id)
        )
        return dict(rows.all())
