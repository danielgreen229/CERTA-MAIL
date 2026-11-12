"""ТЕСТОВЫЙ мок-сервис внешних систем: TMS/статусы, тарифы, CRM и Telegram Bot API.

Только для контрактных проверок и демонстрации. Данные выдуманы и помечены
``"test_service": true``. Запуск: ``python -m lead_assistant.web.mockservice --port 8099``.
"""

from __future__ import annotations

import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

SHIPMENTS: dict[str, dict[str, Any]] = {
    "88104": {"status": "доставлено", "eta": None},
    "77812": {"status": "в пути", "eta": "2026-11-15"},
    "55120": {"status": "задержано на складе транзита", "eta": None},
}
TOKEN = "123456:TEST"
UPDATES = [
    {
        "update_id": 9001,
        "message": {
            "date": 1794470400,  # 2026-11-12 08:00 UTC
            "text": "Добрый день! Нужно перевезти 5 паллет из Казани в Москву до 20 ноября.",
            "from": {
                "id": 42,
                "first_name": "Тест",
                "last_name": "Клиент",
                "username": "test_client",
            },
        },
    }
]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - сигнатура базы
        return

    def _send(self, status: int, body: Any) -> None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        url = urlparse(self.path)
        parts = [p for p in url.path.split("/") if p]
        if url.path == "/health":
            self._send(200, {"ok": True, "test_service": True})
        elif len(parts) == 2 and parts[0] == "shipments":
            shipment = SHIPMENTS.get(parts[1])
            if shipment is None:
                self._send(404, {"error": "not found", "test_service": True})
            else:
                self._send(
                    200,
                    {
                        "number": parts[1],
                        **shipment,
                        "updated_at": "2026-11-12T08:00:00Z",
                        "test_service": True,
                    },
                )
        elif parts == ["quote"]:
            query = parse_qs(url.query)
            kg = float((query.get("kg") or ["0"])[0] or 0)
            self._send(
                200,
                {
                    "price": round(5000 + kg * 4.5, 2),
                    "currency": "RUB",
                    "valid_until": "2026-12-31",
                    "test_service": True,
                },
            )
        elif len(parts) == 2 and parts[0] == f"bot{TOKEN}":
            if parts[1] == "getMe":
                self._send(200, {"ok": True, "result": {"username": "certa_test_bot"}})
            elif parts[1] == "getUpdates":
                self._send(200, {"ok": True, "result": UPDATES})
            else:
                self._send(404, {"ok": False})
        else:
            self._send(404, {"error": "not found", "test_service": True})


def start(port: int = 0) -> tuple[ThreadingHTTPServer, str]:
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def main() -> None:
    parser = argparse.ArgumentParser(description="ТЕСТОВЫЙ мок-сервис внешних систем")
    parser.add_argument("--port", type=int, default=8099)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"ТЕСТОВЫЙ мок-сервис: http://{args.host}:{args.port} (токен бота {TOKEN})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        time.sleep(0)


if __name__ == "__main__":
    main()
