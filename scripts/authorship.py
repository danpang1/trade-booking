"""Who booked a trade, and who last touched it.

`user_id` is CREATED BY and never changes. Every amend used to stamp it from
the session, so if Danny booked a deal and Francis corrected it, the deal
looked like Francis's -- the one fact a blotter must not lose, because it is
how you find out who to ask about a trade.

The amender is not discarded, it moves to `updated_by`. trades_* are SCD Type
2, so each version row now says both who originated the deal and who made that
particular version.

The original is read from the FIRST version of the deal_ref rather than from
whatever the client sent: a client that can name the creator can forge one.
"""
from __future__ import annotations


def original_user_id(cur, table, deal_ref):
    """`user_id` from the earliest version of this deal_ref, or None.

    None means the deal has no history yet (a fresh insert), in which case the
    caller's stamped value IS the original.
    """
    if not deal_ref:
        return None
    cur.execute(
        f"SELECT user_id FROM {table} "
        " WHERE deal_ref = %s "
        " ORDER BY effective_start ASC "
        " LIMIT 1",
        (deal_ref,),
    )
    row = cur.fetchone()
    return row[0] if row else None


def apply_on_amend(cur, table, payload, deal_ref):
    """Rewrite `payload` in place so an amend keeps its original author.

    `user_id`    -> the deal's first-version author (unchanged if this is the
                    first version, or if the deal has no history).
    `updated_by` -> whoever the caller stamped, i.e. the person amending.

    Returns the payload for convenience.
    """
    if not isinstance(payload, dict):
        return payload
    acting = payload.get("user_id")
    original = original_user_id(cur, table, deal_ref)
    if original:
        payload["user_id"] = original
        payload["updated_by"] = acting
    else:
        # No prior version: this caller IS the author. Leave user_id alone and
        # record no amender, so a plain insert reads the same as it always did.
        payload.setdefault("updated_by", None)
    return payload
