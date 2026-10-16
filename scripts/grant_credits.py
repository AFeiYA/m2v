"""Administrator-only credit grant with an idempotent reference.

Uses the configured DATABASE_URL. No web endpoint or payment is involved.
Run from the repository root: python -m scripts.grant_credits --help
"""
import argparse
import asyncio

from src.credits import grant
from src.database import async_session


async def main(args):
    async with async_session() as db:
        added = await grant(db, args.user_id, args.amount, args.reference, args.note)
        await db.commit()
        print('Credits added and recorded.' if added else 'Reference already recorded; balance unchanged.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--user-id', required=True)
    parser.add_argument('--amount', type=int, required=True)
    parser.add_argument('--reference', required=True, help='Unique reference; reuse it to safely retry the same grant')
    parser.add_argument('--note', default='Credits added by administrator')
    asyncio.run(main(parser.parse_args()))
