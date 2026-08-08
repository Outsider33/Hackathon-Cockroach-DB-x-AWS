"""Run the same handler on a laptop, with the page in front of it.

    py -3.12 api/local_server.py          # http://127.0.0.1:8000

Same file as the deployed Lambda, called through a fake Function URL event, so
what is tested here is what ships. It also serves web/ so the page can be seen
without an S3 bucket.
"""

import json
import os
import sys
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

ROOT = Path(__file__).resolve().parent.parent


def load_dotenv():
    path = ROOT / ".env"
    if not path.exists():
        sys.exit(".env not found. CRDB_URL never goes in a tracked file.")
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))


load_dotenv()
sys.path.insert(0, str(ROOT / "api"))
import handler  # noqa: E402  -- after the environment is populated


class Context:
    aws_request_id = "local"


class Server(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT / "web"), **kwargs)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path != "/api":
            return super().do_GET()
        parameters = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        event = {
            "queryStringParameters": parameters,
            "requestContext": {"http": {"method": "GET"}},
        }
        response = handler.lambda_handler(event, Context())
        body = response["body"].encode("utf-8")
        self.send_response(response["statusCode"])
        for key, value in response["headers"].items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    print(f"http://127.0.0.1:{port}   (api at /api?view=health)")
    HTTPServer(("127.0.0.1", port), Server).serve_forever()
