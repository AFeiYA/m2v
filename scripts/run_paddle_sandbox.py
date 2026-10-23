"""Run the real app with a local sandbox DB/storage; never touch production data."""
import argparse
import os
from pathlib import Path
import secrets
import subprocess
import sys
from dotenv import dotenv_values


def sandbox_environment(root, inherited, values, port):
    env = {**inherited, **{k: v for k, v in values.items() if v is not None}}
    for name in list(env):
        if name.startswith(('R2_', 'S3_')):
            env[name] = ''
    folder = root / 'work' / 'paddle-sandbox'
    env.update(BILLING_ENABLED='true', BILLING_PROVIDER='paddle', BILLING_ALLOW_TEST_TRANSACTIONS='true',
        PADDLE_ENVIRONMENT='sandbox', PADDLE_LIVE_ENABLED='false', DATABASE_URL='sqlite+aiosqlite:///' + str(folder / 'sandbox.db'),
        STORAGE_BACKEND='local', UPLOAD_DIR=str(folder / 'uploads'), OUTPUT_DIR=str(folder / 'output'),
        HOST='127.0.0.1', PORT=str(port), DEBUG='false', SECRET_KEY=secrets.token_hex(32),
        DRAFT_EXPORT_CREDITS='0', CLIP_EXPORT_CREDITS='0', SEPARATION_CREDITS='0')
    return env


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8896)
    parser.add_argument('--config', default='work/paddle-sandbox.env')
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    # Direct invocation starts Python with scripts/, not the repository, on sys.path.
    sys.path.insert(0, str(root))
    values = {**dotenv_values(root / '.env'), **dotenv_values(root / args.config)}
    env = sandbox_environment(root, os.environ, values, args.port)
    missing = [name for name in ('PADDLE_CLIENT_TOKEN', 'PADDLE_WEBHOOK_SECRET', 'BILLING_PRODUCTS_JSON') if not env.get(name)]
    if not (env.get('PADDLE_API_KEY') or env.get('PADDLE_SANDBOX_API_KEY') or '').startswith('pdl_sdbx_'):
        missing.append('PADDLE_SANDBOX_API_KEY')
    if missing:
        print('Sandbox setup incomplete. Configure: ' + ', '.join(missing))
        return 2
    if not env['PADDLE_CLIENT_TOKEN'].startswith('test_'):
        print('Sandbox client token required; live configuration rejected.')
        return 2
    try:
        from src.settings import Settings
        from src.paddle_config import configured
        configured(Settings(_env_file=None, **{k: v for k, v in env.items() if k in Settings.model_fields}))
    except Exception:
        print('Sandbox configuration is invalid. Check the catalogue, tokens and return URL; no secrets displayed.')
        return 2
    print(f'Isolated Paddle sandbox: http://localhost:{args.port}/app')
    print('Database and media: work/paddle-sandbox/. Production DB and R2 are not used.')
    if args.check:
        return 0
    (root / 'work' / 'paddle-sandbox').mkdir(parents=True, exist_ok=True)
    return subprocess.call([sys.executable, '-m', 'src.api_server'], cwd=root, env=env)


if __name__ == '__main__':
    raise SystemExit(main())
