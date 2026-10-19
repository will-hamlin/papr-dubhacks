"""Local operator commands. No public signup can choose a company or spending limit."""
import argparse
import getpass
import json
from pathlib import Path

from .accounts import AccountStore, PASSWORDS
from .oauth import client_config
from .service import Settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=Settings.from_env().var_dir / 'accounts.sqlite3')
    commands = parser.add_subparsers(dest='command', required=True)
    company = commands.add_parser('company', help='Import/update an operator-approved Policy JSON file')
    company.add_argument('file', type=Path)
    create = commands.add_parser('create-user', help='Create a login from a User JSON file (or selected user in a list)')
    create.add_argument('--company', required=True)
    create.add_argument('--file', type=Path, required=True)
    create.add_argument('--user-id')
    update = commands.add_parser('update-user', help='Update permissions; keeps login email and company membership')
    update.add_argument('account_id')
    update.add_argument('file', type=Path)
    client = commands.add_parser('client', help='Register a public OAuth client with exact callback URLs')
    client.add_argument('--name', required=True)
    client.add_argument('--redirect-uri', action='append', required=True)
    for name in ('disable', 'revoke', 'reset-password'):
        command = commands.add_parser(name)
        command.add_argument('account_id')
    commands.add_parser('list', help='List login IDs and company membership (no credentials)')
    args = parser.parse_args()
    store = AccountStore(args.database)

    def password():
        value = getpass.getpass('New password (12+ characters): ')
        if not 12 <= len(value) <= 1024 or value != getpass.getpass('Confirm password: '):
            parser.error('passwords must match and contain 12 to 1024 characters')
        return value

    try:
        if args.command == 'company':
            print(store.company(json.loads(args.file.read_text(encoding='utf-8'))))
        elif args.command == 'create-user':
            raw = json.loads(args.file.read_text(encoding='utf-8'))
            if isinstance(raw, list):
                matches = [user for user in raw if user.get('id') == args.user_id]
                if len(matches) != 1:
                    parser.error('select exactly one user with --user-id')
                raw = matches[0]
            print(store.create_account(args.company, raw, password()))
        elif args.command == 'update-user':
            store.update_user(args.account_id, json.loads(args.file.read_text(encoding='utf-8')))
        elif args.command == 'client':
            config = client_config({'client_name': args.name, 'redirect_uris': args.redirect_uri})
            print(store.save_client(config))
        elif args.command == 'disable':
            store.disable(args.account_id)
        elif args.command == 'revoke':
            store.revoke_account(args.account_id)
        elif args.command == 'reset-password':
            hashed = PASSWORDS.hash(password())
            with store.db() as db:
                if not db.execute('UPDATE accounts SET password=? WHERE id=?', (hashed, args.account_id)).rowcount:
                    parser.error('unknown account')
            store.revoke_account(args.account_id)
        elif args.command == 'list':
            with store.db() as db:
                for row in db.execute('SELECT id,email,company_id,enabled FROM accounts ORDER BY email'):
                    print(dict(row))
    except (ValueError, OSError) as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    main()
