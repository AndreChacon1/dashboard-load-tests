"""Reproducible bounded localhost campaign; run on the Docker host, not in an image."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SERVICES = {
    'frontend': ('dashboard-frontend-frontend-1', 5173, '/', 'http://frontend/'),
    'backend': ('dashboard-backend-backend-1', 3001, '/health', 'http://backend/health'),
    'auth': ('ldap-keycloak-oauth2-lab-auth-gateway-1', 8081,
             '/realms/cybersecurity/.well-known/openid-configuration',
             'http://auth-gateway/realms/cybersecurity/.well-known/openid-configuration'),
}


def docker(*args):
    run = subprocess.run(['docker', *args], capture_output=True, text=True, timeout=40)
    if run.returncode:
        raise RuntimeError(run.stderr or run.stdout)
    return run.stdout


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2)+'\n', encoding='utf-8')


def observer(name, url):
    if name == 'backend':
        code = f'import urllib.request; print(urllib.request.urlopen({url!r}, timeout=5).status)'
        return docker('exec', SERVICES['frontend'][0], 'python3', '-c', code).strip()
    code = f'fetch({json.dumps(url)}, {{signal: AbortSignal.timeout(5000)}}).then(r=>console.log(r.status))'
    return docker('exec', SERVICES['backend'][0], 'node', '-e', code).strip()


def snapshot(name):
    container, _, _, url = SERVICES[name]
    state = json.loads(docker('inspect', '--format', '{{json .State}}', container))
    return dict(jail=docker('exec', container, 'fail2ban-client', 'status', 'http-flood'),
                firewall=docker('exec', container, 'iptables', '-S'),
                running=state['Running'], started_at=state['StartedAt'],
                restart_count=int(docker('inspect', '--format', '{{.RestartCount}}', container)),
                observer_status=observer(name, url))


def clear_ban(container):
    status = docker('exec', container, 'fail2ban-client', 'status', 'http-flood')
    ips = status.split('Banned IP list:', 1)[-1].split()
    for ip in ips:
        docker('exec', container, 'fail2ban-client', 'set', 'http-flood', 'unbanip', ip)
    # Let the previous failure window expire; no edits to counters or thresholds.
    time.sleep(11)


def load(name, mode, rps, concurrency, duration, repetition=0):
    _, port, path, _ = SERVICES[name]
    dest = ROOT / 'results' / mode / f'{name}-{rps}rps-c{concurrency}-{duration}s-{repetition}.json'
    run = subprocess.run([sys.executable, str(ROOT/'flood.py'), '127.0.0.1', str(port),
        '--path', path, '--rps', str(rps), '--concurrency', str(concurrency),
        '--duration', str(duration), '--output', str(dest)], capture_output=True, text=True,
        timeout=duration + 15)
    if run.returncode not in (0, 1) or not dest.exists():
        raise RuntimeError(run.stderr)
    result = json.loads(dest.read_text())
    print(f'{mode} {name}: requested={rps} achieved={result["achieved_rps"]:.2f} '
          f'success={result["success_percent"]:.1f}% p95={result["p95_ms"]:.1f}ms', flush=True)
    return dest, result


def acceptable(result):
    return (result['success_percent'] >= 99 and result['p95_ms'] <= 1000
            and result['achieved_rps'] >= .95 * result['requested_rps'])


def protected(name):
    container = SERVICES[name][0]
    candidate = None
    for rate in (1, 4, 5, 6, 10):
        clear_ban(container)
        before = snapshot(name)
        dest, result = load(name, 'protected', rate, 4, 20)
        after = snapshot(name)
        save(dest.with_suffix('.evidence.json'), dict(before=before, after=after))
        valid = (acceptable(result) and 'Currently banned:\t0' in after['jail']
                 and before['started_at'] == after['started_at'] and after['observer_status'] == '200')
        if not valid:
            break
        candidate = rate
    if candidate is None:
        raise RuntimeError(f'No passing rate: {name}')
    confirm(name, candidate)


def confirm(name, candidate):
    container = SERVICES[name][0]
    for repetition, concurrency in enumerate((4, 8, 16), 1):
        clear_ban(container)
        before = snapshot(name)
        dest, result = load(name, 'protected', candidate, concurrency, 60, repetition)
        after = snapshot(name)
        save(dest.with_suffix('.evidence.json'), dict(before=before, after=after))
        if not (acceptable(result) and 'Currently banned:\t0' in after['jail']
                and before['started_at'] == after['started_at'] and after['observer_status'] == '200'):
            raise RuntimeError(f'Repetition failed: {dest}')
    print(f'CONFIRMED {name}: {candidate} RPS, 3 x 60s', flush=True)


def capacity(name):
    container = SERVICES[name][0]
    clear_ban(container)
    docker('exec', container, 'fail2ban-client', 'stop', 'http-flood')
    try:
        for rate, concurrency in ((20, 8), (100, 16), (250, 32), (500, 64)):
            dest, result = load(name, 'capacity-http-jail-stopped', rate, concurrency, 20)
            save(dest.with_suffix('.evidence.json'), dict(
                jail_stopped=True, observer_status=observer(name, SERVICES[name][3]),
                state=json.loads(docker('inspect', '--format', '{{json .State}}', container)),
                stats=docker('stats', '--no-stream', '--format', '{{json .}}', container)))
            if not acceptable(result):
                break
    finally:
        # Restart from the on-disk configuration, even on a failed run.
        docker('exec', container, 'fail2ban-client', 'reload')
        time.sleep(2)
        clear_ban(container)
        save(ROOT/'results'/f'{name}-protection-restored.json', snapshot(name))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['protected', 'capacity', 'confirm'])
    parser.add_argument('--service', choices=list(SERVICES))
    parser.add_argument('--rps', type=int, default=5, choices=range(1, 501))
    args = parser.parse_args()
    save(ROOT/'results'/'environment.json', dict(
        docker_version=docker('version'),
        docker_resources=docker('info', '--format', '{{.NCPU}} CPUs; {{.MemTotal}} bytes RAM; {{.OperatingSystem}}'),
        note='Protected service campaigns run concurrently; capacity campaigns run sequentially.'))
    selected = [args.service] if args.service else list(SERVICES)
    if args.mode == 'protected':
        with ThreadPoolExecutor(max_workers=3) as executor:
            list(executor.map(protected, selected))
    elif args.mode == 'confirm':
        with ThreadPoolExecutor(max_workers=3) as executor:
            list(executor.map(lambda name: confirm(name, args.rps), selected))
    else:
        for name in selected:
            capacity(name)
