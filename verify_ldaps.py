"""Verify lab TLS with its CA and exercise the separate LDAPS jail."""
import concurrent.futures
import json
import re
import socket
import ssl
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
GATEWAY = 'ldap-keycloak-oauth2-lab-auth-gateway-1'


def docker(*args):
    run = subprocess.run(['docker', *args], capture_output=True, text=True, timeout=30)
    if run.returncode:
        raise RuntimeError(run.stderr)
    return run.stdout


def main():
    results = ROOT / 'results'
    results.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as directory:
        ca = Path(directory) / 'ca.crt'
        ca.write_text(docker('exec', 'openldap', 'cat', '/container/service/slapd/assets/certs/ca.crt'), encoding='ascii')
        subject = docker('exec', 'openldap', 'openssl', 'x509', '-in',
                         '/container/service/slapd/assets/certs/ldap.crt', '-noout', '-subject')
        hostname = re.search(r'CN\s*=\s*([^,\s]+)', subject).group(1)
        context = ssl.create_default_context(cafile=str(ca))

        def connect():
            try:
                with socket.create_connection(('127.0.0.1', 636), timeout=2) as sock:
                    with context.wrap_socket(sock, server_hostname=hostname) as tls:
                        return {'ok': True, 'tls_version': tls.version()}
            except OSError as error:
                return {'ok': False, 'error': type(error).__name__, 'detail': str(error)}

        baseline = connect()
        if not baseline['ok']:
            raise RuntimeError(f'TLS baseline failed: {baseline}')
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            attempts = list(executor.map(lambda _: connect(), range(40)))
        time.sleep(3)
        after = connect()
        status = docker('exec', GATEWAY, 'fail2ban-client', 'status', 'ldaps-connections')
        rules = docker('exec', GATEWAY, 'iptables', '-S')
        regex = docker('exec', GATEWAY, 'fail2ban-regex', '/var/log/nginx/ldaps.log',
                       '/etc/fail2ban/filter.d/ldaps-connections.conf')
        # A distinct container/source IP should remain able to use the same TLS listener.
        observer = subprocess.run(['docker', 'exec', '-i', 'openldap', 'openssl', 's_client',
            '-connect', 'auth-gateway:636', '-servername', hostname, '-verify_hostname', hostname,
            '-CAfile', '/container/service/slapd/assets/certs/ca.crt', '-verify_return_error'],
            input='', capture_output=True, text=True, timeout=10)
        report = dict(baseline=baseline, certificate_hostname=hostname, attempts=attempts,
                      blocked_probe=after, jail=status, firewall=rules, regex=regex,
                      observer_verified=observer.returncode == 0 and 'Verify return code: 0' in observer.stdout)
        (results / 'ldaps-verification.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
        print(json.dumps(report, indent=2))
        if after['ok'] or not report['observer_verified'] or 'Currently banned:\t1' not in status:
            raise SystemExit('LDAPS blocking verification failed; inspect report')


if __name__ == '__main__':
    main()
