from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text


async def _ensure_item(session: AsyncSession, item_code: str, item_name: str, uom: str = "EA") -> None:
    await session.execute(
        text(
            """
            INSERT INTO item_master(item_code, item_name, uom, status)
            VALUES (:c, :n, :u, 'active')
            ON CONFLICT (item_code) DO NOTHING
            """
        ),
        {"c": item_code, "n": item_name, "u": uom},
    )


async def _ensure_balance_row(
    session: AsyncSession, item_code: str, wh: str, batch: str | None, serial: str | None
) -> None:
    await session.execute(
        text(
            """
            INSERT INTO inventory_balance(item_code, warehouse_code, batch, serial, qty)
            VALUES (:i, :w, :b, :s, 0)
            ON CONFLICT (item_code, warehouse_code, COALESCE(batch,''), COALESCE(serial,'')) DO NOTHING
            """
        ),
        {"i": item_code, "w": wh, "b": batch, "s": serial},
    )


async def add_stock(
    session: AsyncSession,
    item_code: str,
    wh: str,
    qty: float,
    batch: str | None,
    serial: str | None,
) -> None:
    await _ensure_balance_row(session, item_code, wh, batch, serial)
    await session.execute(
        text(
            """
            UPDATE inventory_balance
               SET qty = qty + :q
             WHERE item_code=:i AND warehouse_code=:w
               AND COALESCE(batch,'')=COALESCE(:b,'') AND COALESCE(serial,'')=COALESCE(:s,'')
            """
        ),
        {"q": qty, "i": item_code, "w": wh, "b": batch, "s": serial},
    )


async def sub_stock(
    session: AsyncSession,
    item_code: str,
    wh: str,
    qty: float,
    batch: str | None,
    serial: str | None,
    enforce: bool = True,
) -> None:
    await _ensure_balance_row(session, item_code, wh, batch, serial)
    if enforce:
        result = await session.execute(
            text(
                """
                SELECT qty FROM inventory_balance
                WHERE item_code=:i AND warehouse_code=:w
                  AND COALESCE(batch,'')=COALESCE(:b,'') AND COALESCE(serial,'')=COALESCE(:s,'')
                """
            ),
            {"i": item_code, "w": wh, "b": batch, "s": serial},
        )
        available = result.scalar_one_or_none() or 0
        if float(available) < float(qty):
            raise ValueError(f"Stock insuficiente: dispon {available}, requerido {qty}")
    await session.execute(
        text(
            """
            UPDATE inventory_balance
               SET qty = qty - :q
             WHERE item_code=:i AND warehouse_code=:w
               AND COALESCE(batch,'')=COALESCE(:b,'') AND COALESCE(serial,'')=COALESCE(:s,'')
            """
        ),
        {"q": qty, "i": item_code, "w": wh, "b": batch, "s": serial},
    )

