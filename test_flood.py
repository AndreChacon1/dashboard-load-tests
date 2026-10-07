import json
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(503 if self.path == '/fail' else 200)
        self.end_headers()
        self.wfile.write(b'test')

    def log_message(self, *args):
        pass


class LoadTest(unittest.TestCase):
    def test_metrics_success_and_failure(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                for route, expected in [('/', 0), ('/fail', 1)]:
                    output = Path(directory) / 'result.json'
                    run = subprocess.run([sys.executable, str(Path(__file__).with_name('flood.py')),
                        '127.0.0.1', str(server.server_port), '--path', route, '--duration', '1',
                        '--rps', '4', '--concurrency', '2', '--output', str(output)], capture_output=True, timeout=10)
                    self.assertEqual(run.returncode, expected, run.stderr)
                    result = json.loads(output.read_text())
                    self.assertGreater(result['total'], 0)
                    self.assertLessEqual(result['total'], 4)
                    self.assertEqual(result['success_percent'], 100 if expected == 0 else 0)
                    self.assertIsNotNone(result['p95_ms'])
        finally:
            server.shutdown()
            server.server_close()


if __name__ == '__main__':
    unittest.main()
