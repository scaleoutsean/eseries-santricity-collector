#!/usr/bin/env python3
"""
Generate NGINX proxy configuration and CA bundle.

This is a more robust replacement for the bash script. It:
- loads variables from .env
- builds a combined CA bundle from candidate paths
- copies server cert/key from candidate locations
- renders index.html from a simple template (if present)
- renders nginx.conf from nginx.conf.tpl performing safe variable substitution

Note: nginx runtime variables like $host, $remote_addr must be preserved; the
template uses double-dollar ($$host) where needed and this script will leave
them as single-dollar in the final rendered config.
"""
import os
import sys
import shutil
import stat
from pathlib import Path
import re
import time

ROOT = Path(__file__).resolve().parents[1]
NGINX_DIR = ROOT / 'data' / 'nginx'
SSL_DIR = NGINX_DIR / 'ssl'
NGINX_CONF_TPL = NGINX_DIR / 'nginx.conf.tpl'
NGINX_CONF_OUT = NGINX_DIR / 'nginx.conf'
INDEX_TPL = NGINX_DIR / 'index.html.tpl'
INDEX_OUT = NGINX_DIR / 'index.html'
ENV_FILE = ROOT / '.env'


def read_env(env_file: Path):
    env = {}
    if not env_file.exists():
        raise SystemExit(f"Error: {env_file} not found")
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if '=' not in line:
            continue
        k, v = line.split('=', 1)
        k = k.strip()
        v = v.split('#', 1)[0].strip()
        if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
            v = v[1:-1]
        env[k] = v
    return env


def ensure_dir(p: Path):
    p.mkdir(parents=True, exist_ok=True)


def copy_first_existing(candidates, dest: Path):
    for c in candidates:
        p = ROOT / c
        if p.exists():
            shutil.copy(p, dest)
            return p
    return None


def build_combined_ca(env):
    ensure_dir(SSL_DIR)
    combined = SSL_DIR / 'combined_ca.crt'
    combined.write_text('')
    internal_candidates = [
        'certs/_master/ca.crt',
        'certs/proxy/internal/ca.crt',
        'certs/proxy/ca.crt',
    ]
    external_candidates = [
        'certs/proxy/external/pub_ca.crt',
        'certs/proxy/external/ca.crt',
        'certs/proxy/external/root_ca.crt',
    ]
    added = 0
    for p in internal_candidates:
        src = ROOT / p
        if src.exists():
            combined.write_text(combined.read_text() + '\n' + src.read_text())
            print(f"Added internal CA from {p}")
            added += 1
            break
    if not added:
        print("Warning: no internal CA found")
    added_ext = 0
    for p in external_candidates:
        src = ROOT / p
        if src.exists():
            combined.write_text(combined.read_text() + '\n' + src.read_text())
            print(f"Appended external CA from {p}")
            added_ext += 1
            break
    if not added_ext:
        print('Warning: no external CA found')
    return combined


def copy_server_cert_key():
    cert_cands = [
        'certs/proxy/external/server.crt',
        'certs/proxy/server.crt',
        'certs/proxy/tls.crt',
    ]
    key_cands = [
        'certs/proxy/external/private.key',
        'certs/proxy/private.key',
        'certs/proxy/tls.key',
    ]
    cert = copy_first_existing(cert_cands, SSL_DIR / 'tls.crt')
    key = copy_first_existing(key_cands, SSL_DIR / 'tls.key')
    if cert:
        print(f'Copied server cert from {cert}')
    else:
        print('Warning: server cert not found')
    if key:
        print(f'Copied server key from {key}')
    else:
        print('Warning: server key not found')


def render_index(env):
    if not INDEX_TPL.exists():
        print(f'Warning: index template {INDEX_TPL} not found; skipping')
        return
    tpl = INDEX_TPL.read_text()
    # simple replacements
    # Support multiple placeholder styles in the template: {{ VAR }}, ${VAR} and $VAR
    keys = ('PROXY_HOST', 'PROXY_EXPLORER_PORT', 'PROXY_GRAFANA_PORT', 'PROXY_INFLUXDB_PORT', 'PROXY_PROMETHEUS_PORT')
    for k in keys:
        val = env.get(k, '')
        # {{ VAR }}
        tpl = tpl.replace('{{ ' + k + ' }}', val)
        tpl = tpl.replace('{{' + k + '}}', val)
        # ${VAR}
        tpl = tpl.replace('${' + k + '}', val)
        # $VAR (avoid replacing $$ which is used for nginx runtime vars)
        tpl = tpl.replace('$' + k, val)
    # If the index target exists and is a directory, refuse to proceed and
    # instruct the user to remove it. If it's a regular file, back it up
    # before overwriting so we don't lose data.
    if INDEX_OUT.exists():
        if INDEX_OUT.is_dir():
            raise SystemExit(
                f"Error: expected {INDEX_OUT} to be a file but it's a directory.\n"
                "This can happen if nginx was started before configuration was generated.\n"
                "Please remove or rename the directory and re-run this script."
            )
        # backup existing file
        bak = INDEX_OUT.with_name(INDEX_OUT.name + f'.bak.{int(time.time())}')
        shutil.copy2(INDEX_OUT, bak)
        print(f'Backed up existing {INDEX_OUT} -> {bak}')
    INDEX_OUT.write_text(tpl)
    print(f'Rendered {INDEX_OUT}')


def render_nginx_conf(env):
    if not NGINX_CONF_TPL.exists():
        print(f'Error: {NGINX_CONF_TPL} not found')
        return
    tpl = NGINX_CONF_TPL.read_text()
    # envsubst-like substitution for ${VAR} only, leave $$host and nginx vars intact
    def sub_var(m):
        name = m.group(1)
        return env.get(name, '')
    out = re.sub(r"\$\{([A-Za-z0-9_]+)\}", sub_var, tpl)
    # Now convert double-dollar $$host to single-dollar $host for nginx runtime variables
    out = out.replace('$$', '$')

    # Defensive checks: if the target path is a directory (this happens when
    # nginx has been started and created a directory at the expected conf
    # filename), refuse to overwrite and give a clear instruction. If it's a
    # regular file, back it up before writing.
    if NGINX_CONF_OUT.exists():
        if NGINX_CONF_OUT.is_dir():
            raise SystemExit(
                f"Error: expected {NGINX_CONF_OUT} to be a file but it's a directory.\n"
                "This commonly occurs when 'docker compose up' started nginx before\n"
                "you generated the configuration and nginx created a directory in its place.\n"
                "Please remove or rename that directory and re-run this script."
            )
        # backup existing file
        bak = NGINX_CONF_OUT.with_name(NGINX_CONF_OUT.name + f'.bak.{int(time.time())}')
        shutil.copy2(NGINX_CONF_OUT, bak)
        print(f'Backed up existing {NGINX_CONF_OUT} -> {bak}')

    # Ensure the parent directory exists (in case a previous step removed it)
    ensure_dir(NGINX_CONF_OUT.parent)

    NGINX_CONF_OUT.write_text(out)
    print(f'Rendered {NGINX_CONF_OUT}')


def main():
    env = read_env(ENV_FILE)
    # defaults
    env.setdefault('EXPLORER_PORT', '443')
    env.setdefault('GRAFANA_PORT', '3443')
    env.setdefault('INFLUXDB_PORT', '8181')
    env.setdefault('PROXY_HOST', 'localhost')

    print('Setting up NGINX proxy...')
    ensure_dir(SSL_DIR)
    build_combined_ca(env)
    copy_server_cert_key()
    render_index(env)
    render_nginx_conf(env)

    print('\nQuick checks:')
    print('  docker compose exec proxy nginx -t')
    print('  docker compose exec proxy openssl s_client -connect influxdb:%s -servername influxdb -CAfile /etc/nginx/ssl/combined_ca.crt' % env.get('INFLUXDB_PORT'))


if __name__ == '__main__':
    main()
