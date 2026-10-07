"""Build the measured report from saved JSON, without inventing missing data."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
lines = [
    '# Resultados medidos — 6 de octubre de 2026 (México)', '',
    'Entorno: Docker Desktop 4.91.0, Engine 29.8.0, contenedores Linux; '
    '16 CPU lógicas y 7,872,348,160 bytes de RAM asignados a Docker. '
    'Generador Python en Windows, fuera de las tres imágenes. JSON fechados en UTC.', '',
    '## Con Fail2Ban activo', '',
    'Exploración a 1, 4, 5 y 6 RPS durante 20 s. '
    'Confirmación de 5 RPS con tres pruebas de 60 s y concurrencias 4, 8 y 16. '
    'Las campañas protegidas de los tres servicios se ejecutaron simultáneamente. '
    'El valor es por IP y por servicio, para las rutas listadas, no una estimación '
    'de usuarios concurrentes ni del flujo completo de negocio.', '',
    '| Servicio | Ruta | RPS solicitadas | RPS logradas (mín.) | Éxito | p95 peor | Peticiones |',
    '| --- | --- | ---: | ---: | ---: | ---: | ---: |',
]
for name in ('frontend', 'backend', 'auth'):
    files = sorted((ROOT/'results'/'protected').glob(f'{name}-5rps-c*-60s-*.json'))
    files = [p for p in files if not p.name.endswith('.evidence.json')]
    if len(files) != 3:
        raise SystemExit(f'Missing three confirmations for {name}')
    rows = [json.loads(p.read_text()) for p in files]
    evidence = [json.loads(p.with_suffix('.evidence.json').read_text()) for p in files]
    if any(r['success_percent'] < 99 or r['achieved_rps'] < 4.75 or r['p95_ms'] > 1000 for r in rows):
        raise SystemExit(f'Confirmation failed for {name}')
    if any(e['before']['started_at'] != e['after']['started_at']
           or 'Currently banned:\t0' not in e['after']['jail']
           or e['after']['observer_status'] != '200' for e in evidence):
        raise SystemExit(f'Bad evidence for {name}')
    lines.append(f'| {name} | `{rows[0]["path"]}` | 5 | '
                 f'{min(r["achieved_rps"] for r in rows):.2f} | '
                 f'{min(r["success_percent"] for r in rows):.0f}% | '
                 f'{max(r["p95_ms"] for r in rows):.1f} ms | '
                 f'{sum(r["total"] for r in rows)} |')
lines += ['', 'A 6 RPS, el backend falló en la exploración de 20 s. Frontend y auth '
          'pasaron la prueba corta, pero fallaron en la de 60 s. Los registros muestran '
          'ban de la IP del host (`172.23.0.1`) y regla iptables sobre el puerto interno 80. '
          'Los observadores con otra IP siguieron respondiendo 200, sin reinicios. '
          '**Conclusión: 5 RPS por IP es el mayor escalón confirmado bajo esta política.** '
          '6 RPS está en la frontera temporal y no es estable.', '',
          '## Sin el jail HTTP durante la medición de capacidad', '',
          'Pruebas secuenciales de 20 s a 20/100/250/500 RPS con '
          '8/16/32/64 trabajadores. El jail HTTP se restauró después de cada servicio. '
          'LDAPS mantuvo su protección. Esta sección mide sólo las rutas HTTP anteriores.', '',
          '| Servicio | Mayor escalón aceptable probado | RPS logradas | Éxito | p95 |',
          '| --- | ---: | ---: | ---: | ---: |']
for name in ('frontend', 'backend', 'auth'):
    files = (ROOT/'results'/'capacity-http-jail-stopped').glob(f'{name}-*.json')
    rows = [json.loads(p.read_text()) for p in files if not p.name.endswith('.evidence.json')]
    accepted = [r for r in rows if r['success_percent'] >= 99 and r['p95_ms'] <= 1000
                and r['achieved_rps'] >= .95*r['requested_rps']]
    if not accepted:
        raise SystemExit(f'Missing capacity evidence for {name}')
    best = max(accepted, key=lambda r: r['requested_rps'])
    restored = json.loads((ROOT/'results'/f'{name}-protection-restored.json').read_text())
    if not restored['running'] or restored['observer_status'] != '200':
        raise SystemExit(f'Protection restoration failed: {name}')
    lines.append(f'| {name} | {best["requested_rps"]} RPS | {best["achieved_rps"]:.2f} | '
                 f'{best["success_percent"]:.1f}% | {best["p95_ms"]:.1f} ms |')
lines += ['', 'No se afirma un máximo absoluto: 500 RPS es el límite configurado '
          'del generador. Si pasa ese escalón, sólo se demuestra que sostuvo esa carga '
          'durante 20 segundos en este equipo. Las rutas de salud y descubrimiento no '
          'ejercitan la emisión de JWT, LDAP por cada login, ni escrituras de juegos.', '',
          '## LDAPS y trazabilidad', '',
          'La CA original estaba vencida. Se generó una CA local y un certificado con '
          'SAN para openldap, localhost y 127.0.0.1. El cliente verificó CA y nombre, '
          'negoció TLS 1.2 y realizó 40 conexiones acotadas con cinco trabajadores. '
          'Fail2Ban baneó 636; una conexión posterior falló mientras otro contenedor '
          'seguía validando TLS correctamente. Ver [evidencia LDAPS](results/ldaps-verification.json).', '',
          '- [Resultados protegidos](results/protected/): métricas y snapshots del jail, '
          'iptables, observador y estado del contenedor.',
          '- [Capacidad](results/capacity-http-jail-stopped/): métricas, estado y recursos.',
          '- [Entorno](results/environment.json) y archivos `*-protection-restored.json`.',
          '- Se conservaron los resultados fallidos; un ban no se contabilizó como '
          'caída del proceso ni como capacidad máxima de la aplicación.', '']
(ROOT/'RESULTADOS.md').write_text('\n'.join(lines), encoding='utf-8')
print('\n'.join(lines))
