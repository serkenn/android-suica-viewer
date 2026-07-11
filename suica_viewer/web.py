"""Local web GUI for Suica Viewer.

A browser cannot talk to the USB FeliCa reader or run the mutual-authentication
relay itself, so this module runs a small local FastAPI server that owns the
reader (reusing :mod:`suica_viewer.card_data`) and streams card data to the
page over Server-Sent Events. The page is served from ``web_static/index.html``.
"""

import argparse
import asyncio
import contextlib
import json
import threading
import webbrowser
from datetime import datetime
from importlib.resources import files
from typing import Any, Callable

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

from .auth_client import FelicaRemoteClient, FelicaRemoteClientError
from .card_data import CardDataService, resolve_server_url
from .reader_errors import describe_reader_error
from .station_code_lookup import StationCodeLookup
from .utils import SYSTEM_CODE

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765

WorkerFactory = Callable[["ReaderHub", CardDataService, str], threading.Thread]


# --------------------------------------------------------------------------- #
# Event helpers                                                               #
# --------------------------------------------------------------------------- #
def _status(state: str, message: str) -> dict[str, Any]:
    return {"type": "status", "state": state, "message": message}


def _progress(value: float) -> dict[str, Any]:
    return {"type": "progress", "value": round(float(value), 1)}


def _card_event(data: dict[str, Any]) -> dict[str, Any]:
    read_at = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    return {"type": "card", "read_at": read_at, "data": data}


def _error(message: str) -> dict[str, Any]:
    return {"type": "error", "message": message}


def format_sse(event: dict[str, Any]) -> str:
    """Encode an event dict as a single Server-Sent Events ``message``."""
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


# --------------------------------------------------------------------------- #
# SSE hub                                                                     #
# --------------------------------------------------------------------------- #
class ReaderHub:
    """Fans reader events out to connected browsers over SSE.

    The reader runs in a plain thread; subscribers live on the asyncio loop.
    ``publish`` bridges the two via ``loop.call_soon_threadsafe``.
    """

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._subscribers: set[asyncio.Queue] = set()
        self._lock = threading.Lock()
        self._last_status: dict[str, Any] = _status(
            "initializing", "NFC リーダーを初期化しています…"
        )
        self._last_card: dict[str, Any] | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=256)
        with self._lock:
            self._subscribers.add(queue)
            seed_status = self._last_status
            seed_card = self._last_card
        # Seed the newcomer with the current state so a freshly opened tab
        # immediately reflects an already-present card.
        queue.put_nowait(seed_status)
        if seed_card is not None:
            queue.put_nowait(seed_card)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        with self._lock:
            self._subscribers.discard(queue)

    def latest_card(self) -> dict[str, Any] | None:
        with self._lock:
            return self._last_card

    def publish(self, event: dict[str, Any]) -> None:
        with self._lock:
            event_type = event.get("type")
            if event_type == "status":
                self._last_status = event
            elif event_type == "card":
                self._last_card = event
            elif event_type == "removed":
                self._last_card = None
            loop = self._loop
            subscribers = list(self._subscribers)
        if loop is None:
            return
        for queue in subscribers:
            loop.call_soon_threadsafe(self._safe_put, queue, event)

    @staticmethod
    def _safe_put(queue: asyncio.Queue, event: dict[str, Any]) -> None:
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            pass


# --------------------------------------------------------------------------- #
# NFC reader worker                                                           #
# --------------------------------------------------------------------------- #
def _fix_ic_code_map() -> None:
    from nfc.tag.tt3_sony import FelicaStandard

    FelicaStandard.IC_CODE_MAP[0x31] = ("RC-S???", 1, 1)


class NfcReaderWorker(threading.Thread):
    """Owns the FeliCa reader and publishes card data to the hub."""

    def __init__(
        self, hub: ReaderHub, service: CardDataService, server_url: str
    ) -> None:
        super().__init__(daemon=True, name="nfc-reader")
        self.hub = hub
        self.service = service
        self.server_url = server_url
        self._stop = threading.Event()

    def run(self) -> None:
        import nfc

        _fix_ic_code_map()
        self.hub.publish(_status("initializing", "NFC リーダーを初期化しています…"))
        try:
            with nfc.ContactlessFrontend("usb") as clf:
                self.hub.publish(_status("waiting", "カードをかざしてください。"))
                while not self._stop.is_set():
                    try:
                        clf.connect(
                            rdwr={
                                "targets": ["212F", "424F"],
                                "on-connect": self._on_connect,
                                "on-release": self._on_release,
                            },
                            terminate=self._stop.is_set,
                        )
                    except Exception as exc:  # keep the loop alive on read errors
                        self.hub.publish(_status("waiting", f"読み取りエラー: {exc}"))
        except Exception as exc:
            # usb1's USBError is not an OSError, so nfcpy's `except IOError` misses
            # it; surface a helpful hint instead of dying silently.
            self.hub.publish(_error(describe_reader_error(exc)))

    def _on_connect(self, tag: Any) -> bool:
        from nfc.tag.tt3_sony import FelicaStandard

        if not isinstance(tag, FelicaStandard):
            self.hub.publish(_status("waiting", "FeliCa 以外のタグを検出しました。"))
            return True

        self.hub.publish(_status("reading", "カード情報を取得しています…"))
        self.hub.publish(_progress(5))
        try:
            polling_result = tag.polling(SYSTEM_CODE)
            if len(polling_result) != 2:
                raise RuntimeError("Polling 応答が不正です。")
            tag.idm, tag.pmm = polling_result

            client = FelicaRemoteClient(self.server_url, tag)
            try:
                card = self.service.collect(
                    client, progress_callback=lambda v: self.hub.publish(_progress(v))
                )
            finally:
                client.close()
            self.hub.publish(_card_event(card.to_serializable_dict()))
            self.hub.publish(_status("done", "カード情報を読み取りました。"))
        except FelicaRemoteClientError as exc:
            self.hub.publish(_status("waiting", f"サーバ通信エラー: {exc}"))
        except Exception as exc:
            self.hub.publish(
                _status("waiting", f"カード情報の取得に失敗しました: {exc}")
            )
        return True

    def _on_release(self, tag: Any) -> bool:
        self.hub.publish({"type": "removed"})
        self.hub.publish(_status("waiting", "カードをかざしてください。"))
        return True

    def stop(self) -> None:
        self._stop.set()


class DemoReaderWorker(threading.Thread):
    """Feeds a built-in sample card so the UI can be previewed without a reader."""

    def __init__(
        self, hub: ReaderHub, service: CardDataService, server_url: str
    ) -> None:
        super().__init__(daemon=True, name="nfc-demo")
        self.hub = hub
        self._stop = threading.Event()
        self._card = load_demo_card()

    def run(self) -> None:
        self.hub.publish(_status("waiting", "デモモード: 疑似カードを読み取ります…"))
        if self._stop.wait(0.8):
            return
        self.hub.publish(_status("reading", "カード情報を取得しています…"))
        for value in (20, 45, 70, 90, 100):
            if self._stop.wait(0.12):
                return
            self.hub.publish(_progress(value))
        self.hub.publish(_card_event(self._card))
        self.hub.publish(_status("done", "デモカードを読み取りました。"))

    def stop(self) -> None:
        self._stop.set()


# --------------------------------------------------------------------------- #
# Static assets                                                               #
# --------------------------------------------------------------------------- #
def _read_static(name: str) -> str:
    return (
        files("suica_viewer").joinpath("web_static", name).read_text(encoding="utf-8")
    )


def load_index_html() -> str:
    return _read_static("index.html")


def load_demo_card() -> dict[str, Any]:
    return json.loads(_read_static("demo_card.json"))


# --------------------------------------------------------------------------- #
# App factory                                                                 #
# --------------------------------------------------------------------------- #
def create_app(
    *,
    server_url: str | None = None,
    worker_factory: WorkerFactory = NfcReaderWorker,
) -> FastAPI:
    hub = ReaderHub()
    lookup = StationCodeLookup()
    service = CardDataService(lookup)
    resolved_server = resolve_server_url(server_url)

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        hub.bind_loop(asyncio.get_running_loop())
        worker = worker_factory(hub, service, resolved_server)
        worker.start()
        app.state.worker = worker
        try:
            yield
        finally:
            stop = getattr(worker, "stop", None)
            if callable(stop):
                stop()

    app = FastAPI(title="Suica Viewer Web", lifespan=lifespan)
    app.state.hub = hub

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return load_index_html()

    @app.get("/api/card")
    def latest_card() -> JSONResponse:
        card = hub.latest_card()
        if card is None:
            return JSONResponse({"card": None})
        return JSONResponse({"card": card.get("data"), "read_at": card.get("read_at")})

    @app.get("/api/stream")
    async def stream(request: Request) -> StreamingResponse:
        queue = hub.subscribe()

        async def event_source():
            try:
                while True:
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=15.0)
                        yield format_sse(event)
                    except asyncio.TimeoutError:
                        yield ": keep-alive\n\n"
                    if await request.is_disconnected():
                        break
            finally:
                hub.unsubscribe(queue)

        return StreamingResponse(
            event_source(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return app


# --------------------------------------------------------------------------- #
# Entry point                                                                 #
# --------------------------------------------------------------------------- #
def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="suica-viewer-web",
        description="Suica Viewer のローカル Web GUI を起動します。",
    )
    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help=f"バインドするホスト（既定: {DEFAULT_HOST}）。LAN 公開時はカード情報が"
        "ネットワークに流れる点に注意してください。",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"ポート（既定: {DEFAULT_PORT}）。",
    )
    parser.add_argument(
        "--server",
        metavar="URL",
        default=None,
        help="認証サーバの URL（未指定なら AUTH_SERVER_URL 環境変数か既定値）。",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="起動時にブラウザを自動で開かない。",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="リーダーを使わず、疑似カードで UI をプレビューする。",
    )
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    worker_factory: WorkerFactory = DemoReaderWorker if args.demo else NfcReaderWorker
    app = create_app(server_url=args.server, worker_factory=worker_factory)

    url = f"http://{args.host}:{args.port}/"
    print(f"Suica Viewer Web GUI: {url}")
    if args.demo:
        print("（デモモード: 実際のリーダーは使用しません）")
    if not args.no_browser:
        # uvicorn.run blocks, so open the browser from a short-lived timer.
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
