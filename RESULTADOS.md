# Resultados medidos — 6 de octubre de 2026 (México)

Entorno: Docker Desktop 4.91.0, Engine 29.8.0, contenedores Linux; 16 CPU lógicas y 7,872,348,160 bytes de RAM asignados a Docker. Generador Python en Windows, fuera de las tres imágenes. JSON fechados en UTC.

## Con Fail2Ban activo

Exploración a 1, 4, 5 y 6 RPS durante 20 s. Confirmación de 5 RPS con tres pruebas de 60 s y concurrencias 4, 8 y 16. Las campañas protegidas de los tres servicios se ejecutaron simultáneamente. El valor es por IP y por servicio, para las rutas listadas, no una estimación de usuarios concurrentes ni del flujo completo de negocio.

| Servicio | Ruta | RPS solicitadas | RPS logradas (mín.) | Éxito | p95 peor | Peticiones |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| frontend | `/` | 5 | 5.00 | 100% | 16.0 ms | 900 |
| backend | `/health` | 5 | 5.00 | 100% | 16.0 ms | 900 |
| auth | `/realms/cybersecurity/.well-known/openid-configuration` | 5 | 5.00 | 100% | 31.0 ms | 900 |

A 6 RPS, el backend falló en la exploración de 20 s. Frontend y auth pasaron la prueba corta, pero fallaron en la de 60 s. Los registros muestran ban de la IP del host (`172.23.0.1`) y regla iptables sobre el puerto interno 80. Los observadores con otra IP siguieron respondiendo 200, sin reinicios. **Conclusión: 5 RPS por IP es el mayor escalón confirmado bajo esta política.** 6 RPS está en la frontera temporal y no es estable.

## Sin el jail HTTP durante la medición de capacidad

Pruebas secuenciales de 20 s a 20/100/250/500 RPS con 8/16/32/64 trabajadores. El jail HTTP se restauró después de cada servicio. LDAPS mantuvo su protección. Esta sección mide sólo las rutas HTTP anteriores.

| Servicio | Mayor escalón aceptable probado | RPS logradas | Éxito | p95 |
| --- | ---: | ---: | ---: | ---: |
| frontend | 500 RPS | 494.00 | 100.0% | 16.0 ms |
| backend | 500 RPS | 494.75 | 100.0% | 16.0 ms |
| auth | 500 RPS | 494.48 | 100.0% | 16.0 ms |

No se afirma un máximo absoluto: 500 RPS es el límite configurado del generador. Si pasa ese escalón, sólo se demuestra que sostuvo esa carga durante 20 segundos en este equipo. Las rutas de salud y descubrimiento no ejercitan la emisión de JWT, LDAP por cada login, ni escrituras de juegos.

## LDAPS y trazabilidad

La CA original estaba vencida. Se generó una CA local y un certificado con SAN para openldap, localhost y 127.0.0.1. El cliente verificó CA y nombre, negoció TLS 1.2 y realizó 40 conexiones acotadas con cinco trabajadores. Fail2Ban baneó 636; una conexión posterior falló mientras otro contenedor seguía validando TLS correctamente. Ver [evidencia LDAPS](results/ldaps-verification.json).

- [Resultados protegidos](results/protected/): métricas y snapshots del jail, iptables, observador y estado del contenedor.
- [Capacidad](results/capacity-http-jail-stopped/): métricas, estado y recursos.
- [Entorno](results/environment.json) y archivos `*-protection-restored.json`.
- Se conservaron los resultados fallidos; un ban no se contabilizó como caída del proceso ni como capacidad máxima de la aplicación.
