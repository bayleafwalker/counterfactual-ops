"""Local web application for decisions, experiments, and retained evidence."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
import re
import subprocess
import tempfile
from urllib.parse import parse_qs, unquote, urlsplit

from .engine import annotate, assess, run
from .model import Invalid, canonical, load, validate
from .store import Store


MAX_BODY = 1_000_000
ARTIFACT_RE = re.compile(r"^[0-9a-f]{64}$")
DECISION_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")


@dataclass(frozen=True)
class WebConfig:
    root: Path
    store: Path

    @property
    def static(self) -> Path:
        return Path(__file__).with_name("static")


class Application:
    def __init__(self, root: Path, store: Path):
        root = root.resolve()
        if not (root / ".git").exists():
            raise Invalid(f"repository root required: {root}")
        self.config = WebConfig(root, store.resolve())
        self.store = Store(self.config.store)

    def decision_paths(self) -> list[Path]:
        paths: list[Path] = []
        for directory in (self.config.root / "decisions", self.config.root / "examples"):
            if directory.is_dir():
                paths.extend(sorted(directory.glob("*.json")))
        return paths

    def decisions(self) -> list[tuple[Path, dict]]:
        found: list[tuple[Path, dict]] = []
        ids: set[str] = set()
        for path in self.decision_paths():
            try:
                decision = load(path)
            except (OSError, json.JSONDecodeError, Invalid) as exc:
                relative = path.relative_to(self.config.root)
                raise Invalid(f"invalid decision {relative}: {exc}") from exc
            if decision["id"] in ids:
                raise Invalid(f"duplicate decision id: {decision['id']}")
            ids.add(decision["id"])
            found.append((path, decision))
        return found

    def decision(self, decision_id: str) -> tuple[Path, dict]:
        for path, decision in self.decisions():
            if decision["id"] == decision_id:
                return path, decision
        raise KeyError(decision_id)

    def summary(self, path: Path, decision: dict) -> dict:
        assessment = assess(decision, self.store)
        return {
            "id": decision["id"],
            "objective": decision["objective"],
            "claim": decision["claim"]["statement"],
            "path": str(path.relative_to(self.config.root)),
            "implementation": decision["context"]["implementation"],
            "implementation_version": decision["context"]["implementation_version"],
            "status": assessment["status"],
            "next_experiments": assessment["next_experiments"],
            "obligations": sum(len(assessment[key]) for key in (
                "unresolved_material_assumptions", "incomplete_observation_windows",
                "changed_conditions", "counterexamples_awaiting_change",
                "unexpected_consequences_awaiting_review",
            )),
        }

    def overview(self) -> dict:
        decisions = [self.summary(path, decision) for path, decision in self.decisions()]
        events = self.store.read()
        return {
            "decisions": decisions,
            "counts": {
                "decisions": len(decisions),
                "supported": sum(item["status"] == "supported-under-tested-conditions" for item in decisions),
                "counterexamples": sum(item["status"] == "counterexample" for item in decisions),
                "reassessment": sum(item["status"] == "needs-reassessment" for item in decisions),
                "open_obligations": sum(item["obligations"] for item in decisions),
                "events": len(events),
            },
        }

    def detail(self, decision_id: str) -> dict:
        path, decision = self.decision(decision_id)
        assessment = assess(decision, self.store)
        experiments = []
        for experiment in decision["experiments"]:
            experiments.append({**experiment, "needed": experiment["id"] in assessment["next_experiments"]})
        return {
            "decision": decision,
            "path": str(path.relative_to(self.config.root)),
            "assessment": assessment,
            "experiments": experiments,
        }

    def events(self, decision_id: str | None = None) -> list[dict]:
        events = self.store.read()
        if decision_id is None:
            return list(reversed(events))
        plan_ids = {
            event["id"] for event in events
            if event["kind"] == "plan" and event["data"]["decision"]["id"] == decision_id
        }
        related = []
        related_ids = set(plan_ids)
        for event in events:
            data = event["data"]
            if event["id"] in plan_ids or data.get("plan") in plan_ids or data.get("target") in related_ids:
                related.append(event)
                related_ids.add(event["id"])
        return list(reversed(related))

    def save_decision(self, value: object) -> dict:
        decision = validate(value)
        if not DECISION_ID_RE.fullmatch(decision["id"]):
            raise Invalid("decision id must be a lowercase filesystem-safe identifier")
        if any(existing["id"] == decision["id"] for _path, existing in self.decisions()):
            raise Invalid(f"decision already exists: {decision['id']}")
        target_dir = self.config.root / "decisions"
        target_dir.mkdir(exist_ok=True)
        target = target_dir / f"{decision['id']}.json"
        if target.exists():
            raise Invalid(f"decision already exists: {decision['id']}")
        payload = json.dumps(decision, indent=2, ensure_ascii=False) + "\n"
        descriptor, temporary = tempfile.mkstemp(prefix=".decision-", dir=target_dir, text=True)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temporary, target)
            except FileExistsError as exc:
                raise Invalid(f"decision already exists: {decision['id']}") from exc
            directory = os.open(target_dir, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return {"id": decision["id"], "path": str(target.relative_to(self.config.root)), "state": "uncommitted"}

    def execute(self, value: object) -> dict:
        if not isinstance(value, dict) or set(value) - {"decision", "experiment", "all"}:
            raise Invalid("run body accepts decision, experiment, and all")
        decision_id = value.get("decision")
        if not isinstance(decision_id, str):
            raise Invalid("decision is required")
        experiment = value.get("experiment")
        if experiment is not None and not isinstance(experiment, str):
            raise Invalid("experiment must be a string")
        run_all = value.get("all", False)
        if type(run_all) is not bool:
            raise Invalid("all must be a boolean")
        if experiment is not None and run_all:
            raise Invalid("experiment and all are mutually exclusive")
        path, _decision = self.decision(decision_id)
        return {"plan": run(path, self.store, experiment, run_all), "decision": decision_id}

    def annotation(self, value: object) -> dict:
        if not isinstance(value, dict):
            raise Invalid("annotation body must be an object")
        kind, target, note = value.get("kind"), value.get("target"), value.get("note")
        if kind not in ("unexpected", "hypothesis", "resolution"):
            raise Invalid("kind must be unexpected, hypothesis, or resolution")
        if not isinstance(target, str) or not isinstance(note, str):
            raise Invalid("target and note are required strings")
        choice = value.get("choice")
        if kind == "resolution" and not isinstance(choice, str):
            raise Invalid("resolution choice is required")
        allowed = {"kind", "target", "note", "choice"} if kind == "resolution" else {"kind", "target", "note"}
        if set(value) != allowed:
            raise Invalid(f"{kind} body must contain exactly {', '.join(sorted(allowed))}")
        return annotate(self.store, kind if kind != "resolution" else "resolution", target, note, choice)


class Handler(BaseHTTPRequestHandler):
    server_version = "CounterfactualOps/0.2"

    @property
    def app(self) -> Application:
        return self.server.app  # type: ignore[attr-defined]

    def log_message(self, format: str, *args: object) -> None:
        print(f"{self.address_string()} - {format % args}")

    def json_response(self, status: HTTPStatus, value: object) -> None:
        payload = canonical(value)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; connect-src 'self'")
        self.end_headers()
        self.wfile.write(payload)

    def body(self) -> object:
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            raise Invalid("Content-Type must be application/json")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise Invalid("invalid Content-Length") from exc
        if length <= 0 or length > MAX_BODY:
            raise Invalid("request body must be between 1 byte and 1 MB")
        try:
            return json.loads(self.rfile.read(length))
        except json.JSONDecodeError as exc:
            raise Invalid("invalid JSON body") from exc

    def do_GET(self) -> None:
        try:
            route = urlsplit(self.path)
            path = unquote(route.path)
            query = parse_qs(route.query)
            if path == "/api/v1/health":
                self.json_response(HTTPStatus.OK, {"status": "ok", "events": len(self.app.store.read())})
            elif path == "/api/v1/overview" or path == "/api/v1/decisions":
                self.json_response(HTTPStatus.OK, self.app.overview())
            elif path.startswith("/api/v1/decisions/"):
                self.json_response(HTTPStatus.OK, self.app.detail(path.removeprefix("/api/v1/decisions/")))
            elif path == "/api/v1/events":
                decision = query.get("decision", [None])[0]
                self.json_response(HTTPStatus.OK, {"events": self.app.events(decision)})
            elif path.startswith("/api/v1/artifacts/"):
                self.artifact(path.removeprefix("/api/v1/artifacts/"))
            elif path.startswith("/api/"):
                self.json_response(HTTPStatus.NOT_FOUND, {"error": "route not found"})
            else:
                self.static_file(path)
        except KeyError:
            self.json_response(HTTPStatus.NOT_FOUND, {"error": "decision not found"})
        except (Invalid, ValueError, OSError, subprocess.SubprocessError) as exc:
            self.json_response(HTTPStatus.BAD_REQUEST, {"error": str(exc)})

    def do_POST(self) -> None:
        try:
            if self.headers.get("Origin") not in (None, self.origin()):
                raise Invalid("cross-origin mutation rejected")
            path = urlsplit(self.path).path
            value = self.body()
            if path == "/api/v1/decisions":
                result = self.app.save_decision(value)
                status = HTTPStatus.CREATED
            elif path == "/api/v1/runs":
                result = self.app.execute(value)
                status = HTTPStatus.CREATED
            elif path == "/api/v1/annotations":
                result = self.app.annotation(value)
                status = HTTPStatus.CREATED
            else:
                self.json_response(HTTPStatus.NOT_FOUND, {"error": "route not found"})
                return
            self.json_response(status, result)
        except KeyError:
            self.json_response(HTTPStatus.NOT_FOUND, {"error": "decision or event not found"})
        except (Invalid, ValueError, OSError, subprocess.SubprocessError) as exc:
            self.json_response(HTTPStatus.BAD_REQUEST, {"error": str(exc)})

    def origin(self) -> str:
        host = self.headers.get("Host", "")
        return f"http://{host}"

    def artifact(self, ref: str) -> None:
        if not ARTIFACT_RE.fullmatch(ref):
            raise Invalid("invalid artifact reference")
        payload = self.app.store.artifact(ref)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/vnd.sqlite3")
        self.send_header("Content-Disposition", f'attachment; filename="{ref}.sqlite"')
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "private, immutable")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(payload)

    def static_file(self, request_path: str) -> None:
        name = "index.html" if request_path in ("/", "") else request_path.lstrip("/")
        if name not in ("index.html", "app.js", "styles.css"):
            name = "index.html"
        path = self.app.config.static / name
        payload = path.read_bytes()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; connect-src 'self'")
        self.end_headers()
        self.wfile.write(payload)


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], app: Application):
        super().__init__(address, Handler)
        self.app = app


def make_server(root: Path, store: Path, host: str = "127.0.0.1", port: int = 8787) -> Server:
    if host not in ("127.0.0.1", "::1", "localhost"):
        raise Invalid("v0 web server only binds to a loopback address")
    return Server((host, port), Application(root, store))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Counterfactual Ops local web application")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--store", type=Path, default=Path("evidence"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args(argv)
    store = args.store if args.store.is_absolute() else args.root / args.store
    try:
        server = make_server(args.root, store, args.host, args.port)
    except (Invalid, OSError) as exc:
        parser.error(str(exc))
    print(f"Counterfactual Ops: http://{args.host}:{server.server_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
