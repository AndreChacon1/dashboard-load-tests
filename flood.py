#!/usr/bin/env python3
"""Prueba HTTP acotada, derivada de original/flood.py; ejecutar fuera de Docker."""
import argparse
import ipaddress
import json
import math
import socket
import threading
import time
import urllib.request
import urllib.error
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from original.flood import RateLimiter


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def bounded(maximum):
    def parse(value):
        number = int(value)
        if not 1 <= number <= maximum:
            raise argparse.ArgumentTypeError(f'Debe estar entre 1 y {maximum}')
        return number
    return parse


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('host', help='IP o nombre del laboratorio local autorizado')
    parser.add_argument('port', type=bounded(65535))
    parser.add_argument('--path', default='/')
    parser.add_argument('--duration', type=bounded(300), default=20)
    parser.add_argument('--concurrency', type=bounded(500), default=4)
    parser.add_argument('--rps', type=bounded(500), default=2)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not args.path.startswith('/') or any(c in args.path for c in '\r\n'):
        parser.error('--path debe empezar con / y no contener saltos de línea')
    try:
        addresses = socket.getaddrinfo(args.host, args.port, type=socket.SOCK_STREAM)
    except socket.gaierror as error:
        parser.error(str(error))
    permitted = [ipaddress.ip_network(n) for n in ('127.0.0.0/8', '10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', '::1/128', 'fc00::/7')]
    if not all(any(ipaddress.ip_address(a[4][0]) in n for n in permitted) for a in addresses):
        parser.error('Usa únicamente direcciones privadas o loopback del laboratorio autorizado')
    # Fijar la IP evita cambios DNS durante la prueba. No seguir redirects ni proxies.
    ip = addresses[0][4][0]
    authority = f'[{ip}]' if ':' in ip else ip
    url = f'http://{authority}:{args.port}{args.path}'
    host_header = f'[{args.host}]:{args.port}' if ':' in args.host else f'{args.host}:{args.port}'
    counts, latencies = Counter(), []
    lock, stop = threading.Lock(), threading.Event()
    limiter = RateLimiter(args.rps)
    start = time.monotonic()
    deadline = start + args.duration
    interrupted = False

    def worker():
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        while time.monotonic() < deadline and not stop.is_set():
            if not limiter.wait_for_turn(stop) or time.monotonic() >= deadline:
                break
            began = time.monotonic()
            req = urllib.request.Request(url, headers={'Host': host_header, 'Connection': 'close'})
            try:
                with opener.open(req, timeout=2) as response:
                    response.read(1024 * 1024)
                    code = str(response.status)
            except urllib.error.HTTPError as error:
                code = str(error.code)
                error.close()
            except (urllib.error.URLError, TimeoutError, OSError):
                code = '000'
            with lock:
                counts[code] += 1
                latencies.append((time.monotonic() - began) * 1000)

    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = [executor.submit(worker) for _ in range(args.concurrency)]
        try:
            while time.monotonic() < deadline:
                stop.wait(max(0, min(1, deadline - time.monotonic())))
        except KeyboardInterrupt:
            interrupted = True
        finally:
            stop.set()
        for future in futures:
            future.result()
    elapsed = time.monotonic() - start
    total = sum(counts.values())
    ok = sum(v for k, v in counts.items() if k.startswith('2'))
    ordered = sorted(latencies)
    result = dict(timestamp_utc=datetime.now(timezone.utc).isoformat(), host=args.host,
                  resolved_ip=ip, port=args.port, path=args.path, duration=args.duration,
                  concurrency=args.concurrency, requested_rps=args.rps, elapsed_seconds=elapsed,
                  total=total, successful=ok, status_counts=dict(counts),
                  achieved_rps=total / elapsed, success_percent=100 * ok / total if total else 0,
                  p95_ms=ordered[math.ceil(.95 * total)-1] if total else None,
                  interrupted=interrupted)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2))
    return 0 if total and ok == total and not interrupted else 1


if __name__ == '__main__':
    raise SystemExit(main())
