"""Check local dashboard integration without printing or saving the JWT."""
import json
import os
from pathlib import Path
import urllib.request
import urllib.parse
import urllib.error

ROOT = Path(__file__).resolve().parent
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def request(url, data=None, headers=None, method=None):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with opener.open(req, timeout=15) as response:
            return response.status, response.headers, response.read()
    except urllib.error.HTTPError as error:
        status, response_headers = error.code, error.headers
        error.close()
        return status, response_headers, b''


def main():
    report = {}
    status, _, html = request('http://127.0.0.1:5173/')
    report['frontend_build_served'] = status == 200 and b'type="module"' in html
    status, _, _ = request('http://127.0.0.1:3001/api/games')
    report['unauthenticated_api_rejected'] = status == 401
    status, headers, _ = request('http://127.0.0.1:3001/api/games', method='OPTIONS', headers={
        'Origin': 'http://localhost:5173', 'Access-Control-Request-Method': 'GET',
        'Access-Control-Request-Headers': 'authorization'})
    report['cors_preflight'] = status == 204 and headers.get('Access-Control-Allow-Origin') == 'http://localhost:5173'
    form = urllib.parse.urlencode(dict(grant_type='password', client_id='fastapi-api',
        username=os.getenv('LAB_USERNAME', 'alice'), password=os.getenv('LAB_PASSWORD', 'alice123'))).encode()
    status, _, body = request('http://127.0.0.1:8081/realms/cybersecurity/protocol/openid-connect/token',
                              data=form, headers={'Content-Type': 'application/x-www-form-urlencoded'})
    token = json.loads(body).get('access_token') if status == 200 else None
    report['ldap_login_issues_jwt'] = bool(token)
    if token:
        status, _, body = request('http://127.0.0.1:3001/api/games', headers={'Authorization': f'Bearer {token}'})
        report['authenticated_api_accepted'] = status == 200 and isinstance(json.loads(body), list)
    (ROOT/'results'/'functional.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, indent=2))
    if not all(report.values()):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
