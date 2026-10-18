"""Inspect/retry interrupted local work: python -m main_service.recovery --database PATH list|retry ORDER_ID."""
import argparse
import json
from pathlib import Path

from .store import ConflictError, MissingRequestError, RequestStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True, type=Path)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('list')
    retry = commands.add_parser('retry')
    retry.add_argument('order_id')
    args = parser.parse_args()
    if not args.database.is_file():
        parser.error('database must be an existing MS database')
    store = RequestStore(args.database)
    try:
        result = store.interrupted() if args.command == 'list' else store.retry_interrupted(args.order_id)
    except (ConflictError, MissingRequestError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
