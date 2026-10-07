# Práctica: Fail2Ban y carga HTTP del dashboard

## Estado real de la entrega

Práctica del 6 de octubre de 2026 (México; los JSON usan UTC del 7 de octubre). Docker Desktop y GitHub están disponibles al ejecutar con los permisos del usuario del equipo. Las imágenes se construyeron y arrancaron; login LDAP/Keycloak y consulta autenticada del backend funcionaron. Las mediciones y evidencias se guardan en `results/`.

El proyecto previo no tenía tres contenedores: autenticación incluye Keycloak, OpenLDAP, PostgreSQL y FastAPI. Keycloak emite el JWT. Se agregaron imágenes protegidas para frontend y backend y una imagen `auth-gateway` que protege Keycloak HTTP y OpenLDAP TLS. Se conserva esa separación en lugar de fusionar servicios.

## Cambios

- Frontend: compilación Vite servida por Nginx y Fail2Ban; eliminado `console.info` de JWT en `src/api.js` (no había un `console.log` del token).
- Backend: Express escucha internamente en 3002; Nginx y Fail2Ban reciben HTTP en 80, publicado en 3001. Datos persistidos en volumen.
- LDAP: `auth-gateway` publica 8081 → HTTP 80 y 636 → proxy TCP TLS → OpenLDAP 636. Keycloak y OpenLDAP ya no publican puertos que evadan el gateway. FastAPI y phpLDAPadmin quedan ligados a loopback para administración.
- HTTP: 60 peticiones por IP en 10 segundos provocan bloqueo de 60 segundos, en el puerto HTTP. Se cuentan todos los estados, incluidos errores y OPTIONS.
- LDAPS: hasta 10 conexiones concurrentes por IP, timeout de inactividad de 10 segundos y bloqueo de 636 tras 30 sesiones terminadas en 10 segundos. El registro TCP se escribe al finalizar cada sesión: no equivale a detectar contraseñas LDAP incorrectas. TLS pasa intacto hasta OpenLDAP; el cliente debe confiar en su CA. La federación interna Keycloak→LDAP conserva la configuración anterior en 389; esta práctica añade protección al acceso TLS externo.
- Fail2Ban y Nginx comparten contenedor y espacio de red: la acción `iptables-multiport` se aplica a INPUT del contenedor con `NET_ADMIN`, sin necesitar acceso al socket de Docker. El log usa la IP del socket, no un X-Forwarded-For controlado por el cliente.

Los límites anteriores son **configuración**, no capacidad medida. Fail2Ban no evita saturar el ancho de banda del host. No publicar el laboratorio en Internet con las credenciales de ejemplo existentes.

## Ejecución del original

`original/flood.py` es copia intacta de `attacker/flood.py` del ZIP del profesor. Se ejecutó fuera de Docker con `DURATION=1`, `CONCURRENCY=1`, `REQUESTS_PER_SECOND=1`: cada destino (`victim-protected`, `victim-unprotected`) produjo una petición fallida y cero respuestas 200. Esos nombres sólo son resolubles dentro del laboratorio original; esto **no mide** los servicios del dashboard.

Después de habilitar acceso a Docker, se ejecutó sin modificar en el laboratorio original aislado, desde su contenedor atacante (separado de las tres imágenes del dashboard): `DURATION=10`, `CONCURRENCY=8`, `REQUESTS_PER_SECOND=20`. Resultado: protegido 104 solicitudes, 68 respuestas 200 y 36 fallidas, con ban confirmado de `172.29.0.20`; sin protección 199/199 respuestas 200. Se conservaron [salida y estado del jail](results/original-lab.txt) y se detuvo el laboratorio de referencia. ZIP de origen: `fail2ban-ddos.zip`, SHA-256 `402DE74A027C9B36D5D19E67C86AE252DF865CB85B296BA9F1053EB5AF75D3DF`.

Para repetir esa comparación, extraer el ZIP suministrado y ejecutar desde su carpeta:

```sh
docker compose -p fail2ban-reference up -d --build
docker exec -e DURATION=10 -e CONCURRENCY=8 -e REQUESTS_PER_SECOND=20 http-attacker python /flood.py
docker exec http-victim-protected fail2ban-client status http-flood
docker compose -p fail2ban-reference down
```

## Modificación del script

`flood.py` reutiliza el limitador global de solicitudes del original y recibe `host`, `port`, `--path`, `--rps`, `--concurrency`, `--duration` y `--output`. Tiene límites de 300 segundos, 500 trabajadores y 500 RPS; timeout de 2 segundos, Ctrl+C y reporte JSON. Sólo admite IP privadas/loopback del laboratorio autorizado, fija la IP resuelta y no sigue redirecciones ni proxies. El cuerpo leído se limita a 1 MiB por respuesta.

Registra códigos HTTP, errores de conexión (`000`), solicitudes totales, tasa conseguida, porcentaje 2xx y latencia p95. Código de salida 1 significa errores o interrupción, no necesariamente caída. No registra JWT ni credenciales. La prueba es GET HTTP: no mide un flujo real de emisión de JWT ni consultas autenticadas del dashboard.

## Arranque (Docker Desktop Linux o Linux con Docker Compose)

Requisitos: Docker Desktop con contenedores Linux, Python 3.10+ y los cuatro repositorios en la misma carpeta. El generador de certificados requiere `cryptography`; el script de carga sólo usa la biblioteca estándar. Desde la carpeta padre:

```powershell
docker network create dashboard-lab
python -m pip install -r ldap-keycloak-oauth2-lab/requirements-lab.txt
python ldap-keycloak-oauth2-lab/generate-lab-certs.py
docker compose -f ldap-keycloak-oauth2-lab/docker-compose.yml up -d --build
docker compose -f dashboard-backend/compose.yml up -d --build
docker compose -f dashboard-frontend/compose.yml up -d --build
```

Si la red ya existe, omitir el primer comando. Si ya hay certificados, el generador se niega a sobrescribirlos: conservarlos mientras sean válidos. Se reemplazó la CA vencida incluida en la imagen antigua por una CA local de un año y certificado LDAPS de 90 días. Los archivos están excluidos de Git; la clave privada de la CA no se conserva. Cargar los usuarios siguiendo el README de LDAP; abrir http://localhost:5173 y comprobar login, listado y alta. Esperar a que Keycloak termine de iniciar antes de probar.

## Verificación de Fail2Ban

Ejemplo frontend; repetir con backend y auth-gateway y sus respectivos archivos Compose:

```powershell
docker compose -f dashboard-frontend/compose.yml exec frontend fail2ban-client status http-flood
docker compose -f dashboard-frontend/compose.yml exec frontend fail2ban-regex /var/log/nginx/access.log /etc/fail2ban/filter.d/http-flood.conf
python dashboard-load-tests/flood.py 127.0.0.1 5173 --rps 20 --concurrency 8 --duration 15 --output dashboard-load-tests/results/frontend-ban.json
docker compose -f dashboard-frontend/compose.yml exec frontend fail2ban-client status http-flood
docker compose -f dashboard-frontend/compose.yml exec frontend iptables -S
docker compose -f dashboard-frontend/compose.yml exec frontend tail -n 30 /var/log/fail2ban.log
```

Registrar IP vista en access.log, coincidencias, IP baneada, regla de firewall y solicitudes efectivamente bloqueadas. En Docker Desktop el NAT puede agrupar clientes bajo la misma IP; si el origen aparece como loopback estará excluido. Para evidencias válidas, ejecutar el script desde otra máquina/VM privada autorizada con IP distinguible. Una segunda IP debe seguir obteniendo respuestas correctas durante el ban; comprobar además que el contenedor no se reinicie. Esperar 70 segundos entre pruebas o desbanear exclusivamente la IP observada con `fail2ban-client set http-flood unbanip IP`.

Para LDAPS, desde una máquina con OpenSSL y la CA del laboratorio:

```sh
openssl s_client -connect HOST_LAB:636 -servername openldap -CAfile ca.crt -verify_return_error </dev/null
docker compose -f ldap-keycloak-oauth2-lab/docker-compose.yml exec auth-gateway fail2ban-client status ldaps-connections
docker compose -f ldap-keycloak-oauth2-lab/docker-compose.yml exec auth-gateway fail2ban-regex /var/log/nginx/ldaps.log /etc/fail2ban/filter.d/ldaps-connections.conf
```

En Linux, crear 35 conexiones TLS breves al host del laboratorio (máximo 2 segundos cada una) para comprobar el segundo jail:

```sh
for i in $(seq 1 35); do timeout 2 openssl s_client -connect HOST_LAB:636 -servername openldap -CAfile ca.crt -verify_return_error </dev/null >/dev/null 2>&1 & done
wait
```

Verificar ban en `ldaps-connections`, regla de 636, rechazo de nuevas conexiones de esa IP y acceso TLS desde otra IP. Un error de certificado no prueba un bloqueo; validar TLS individualmente antes del ensayo. La verificación automatizada `python dashboard-load-tests/verify_ldaps.py` pasó: TLS 1.2 con CA y nombre verificados, 40 conexiones con 5 trabajadores, ban de la IP de origen, bloqueo de la conexión posterior y conexión válida de otro contenedor. Evidencia: `results/ldaps-verification.json`. Esperar a que expire el ban antes de repetir.

## Cómo obtener una carga sostenible

1. Registrar CPU/RAM, SO, Docker, commits, ruta probada, IP de cliente y configuración. Mantener misma máquina y escenario durante comparaciones; guardar `docker stats --no-stream` y estado/reinicios antes/después.
2. Probar frontend `/`, backend `/health` y autenticación `/realms/cybersecurity/.well-known/openid-configuration`. Son pruebas de disponibilidad HTTP de esas rutas; no representan todo el trabajo de negocio.
3. Explorar RPS `1, 4, 5, 6` con concurrencia 4 y duración 20 s. Esperar/desbanear entre corridas. Detener la escalada ante ban, errores o p95 > 1000 ms. Confirmar el último escalón aceptable con tres corridas de 60 s y concurrencias 4, 8 y 16. Si una repetición falla, bajar al escalón anterior. La campaña reproducible también permite un escalón de 10 RPS para demostrar el ban si 6 RPS pasa la exploración. Conservar todos los JSON, incluidos los fallidos.
4. Criterio previo: al menos 99% 2xx, p95 ≤ 1000 ms, RPS conseguida ≥ 95% de la solicitada, sin reinicios, sin ban y respuesta correcta desde el observador. La carga sostenible reportada es el mayor escalón que cumple en las tres repeticiones; el siguiente fallido da una cota, no un máximo universal.
5. Distinguir límite de política y saturación: 60 solicitudes/10 s implican que aproximadamente 6 RPS por IP pueden provocar ban. **No afirmar que ésa es la capacidad del servidor.** Para medir capacidad de la aplicación, en un laboratorio aislado detener temporalmente sólo el jail HTTP, repetir escalones acotados y volver a iniciarlo incluso si la prueba falla. Etiquetar esos resultados como protección desactivada. Para carga distribuida real se necesitan varios generadores autorizados.

```powershell
python dashboard-load-tests/flood.py 127.0.0.1 5173 --rps 4 --concurrency 4 --duration 60 --output dashboard-load-tests/results/frontend-4rps-1.json
python dashboard-load-tests/flood.py 127.0.0.1 3001 --path /health --rps 4 --concurrency 4 --duration 60 --output dashboard-load-tests/results/backend-4rps-1.json
python dashboard-load-tests/flood.py 127.0.0.1 8081 --path /realms/cybersecurity/.well-known/openid-configuration --rps 4 --concurrency 4 --duration 60 --output dashboard-load-tests/results/auth-4rps-1.json
```

| Servicio | Carga protegida confirmada por IP | Evidencia |
| --- | --- | --- |
| Frontend | 5 RPS, 3 × 60 s, 100% éxito | `results/protected/frontend-5rps-*.json` |
| Backend | 5 RPS, 3 × 60 s, 100% éxito | `results/protected/backend-5rps-*.json` |
| Autenticación | 5 RPS, 3 × 60 s, 100% éxito | `results/protected/auth-5rps-*.json` |

A 6 RPS aparecieron bans: backend en la exploración de 20 s y frontend/auth en la repetición de 60 s. Se redujo a 5 RPS y se confirmó con concurrencias 4, 8 y 16. El observador de otra IP siguió respondiendo y los contenedores no se reiniciaron. El análisis completo se genera con `python dashboard-load-tests/summarize.py` en [RESULTADOS.md](RESULTADOS.md).

## Comprobaciones y publicación

`python dashboard-load-tests/test_flood.py` valida el límite global y métricas contra un servidor local efímero, con casos HTTP 200 y 503. Las 8 pruebas existentes del backend pasaron. El frontend compiló tanto en Windows como en Docker; se actualizó `source-map-js` a 1.2.2 y `npm audit` reportó cero vulnerabilidades.

`python dashboard-load-tests/verify_app.py` comprueba el build servido, rechazo 401 sin JWT, preflight CORS, login LDAP/Keycloak y consulta autenticada; guarda sólo booleanos, nunca el token. Usa los usuarios de demostración existentes; opcionalmente acepta `LAB_USERNAME` y `LAB_PASSWORD` en el entorno.

Las campañas se ejecutan desde el host:

```powershell
python dashboard-load-tests/run_campaign.py protected
python dashboard-load-tests/run_campaign.py confirm --service auth --rps 5
python dashboard-load-tests/run_campaign.py capacity
```

La campaña protegida ejecuta los tres servicios simultáneamente sobre el mismo host; cada uno recibe la tasa indicada. Las corridas de capacidad se ejecutan una por una, con sólo el jail HTTP del destino temporalmente detenido y restaurado mediante `finally`. LDAPS conserva su jail. La capacidad se explora a 20, 100, 250 y 500 RPS durante 20 s, variando concurrencia 8, 16, 32 y 64. El límite de 500 RPS del generador no debe presentarse como el máximo absoluto del servicio.

Los cambios se entregan en los tres repositorios originales y este cuarto repositorio. Los SHA de los servicios están en `results/source-commits.json`. Para publicar una copia propia del cuarto repositorio, desde esta carpeta y tras `gh auth login`:

```powershell
git add .
git commit -m "Add bounded HTTP load lab and measurement procedure"
gh repo create TU_USUARIO/dashboard-load-tests --public --source . --remote origin --push
```

Repositorios de la entrega: [LDAP](https://github.com/AndreChacon1/ldap-keycloak-oauth2-lab), [backend](https://github.com/AndreChacon1/dashboard-backend), [frontend](https://github.com/AndreChacon1/dashboard-frontend) y [pruebas](https://github.com/AndreChacon1/dashboard-load-tests).

Referencias: [jails oficiales de Fail2Ban](https://github.com/fail2ban/fail2ban/blob/master/config/jail.conf), [acción iptables-multiport](https://github.com/fail2ban/fail2ban/blob/master/config/action.d/iptables-multiport.conf), y práctica `fail2ban-ddos.zip` proporcionada.
