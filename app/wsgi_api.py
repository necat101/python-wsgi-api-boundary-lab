# app/wsgi_api.py
# Plain WSGI application – ML-metadata API surface, no ML
import json
import io
from urllib.parse import parse_qs
from http import HTTPStatus


_CATALOG = ["bert-tiny", "distilgpt2", "whisper-tiny"]


def _json_bytes(obj):
    return json.dumps(obj, separators=(",", ":"), sort_keys=True).encode("utf-8")


def make_application(label_store=None):
    """Application factory. label_store: dict model_name -> list[str].
    Returns a fresh WSGI callable with its own isolated store.
    """
    if label_store is None:
        label_store = {name: [] for name in _CATALOG}
    
    def application(environ, start_response):
        method = environ.get("REQUEST_METHOD", "GET")
        path_info = environ.get("PATH_INFO", "")
        query_string = environ.get("QUERY_STRING", "")

        # Route: GET /v1/models/<name>
        if method == "GET" and path_info.startswith("/v1/models/"):
            name = path_info[len("/v1/models/"):]
            if "/" in name or not name:
                status = HTTPStatus.NOT_FOUND
                body = _json_bytes({"error": "not_found"})
                headers = [("Content-Type", "application/json")]
                start_response(f"{status.value} {status.phrase}", headers)
                return [body]
            if name not in _CATALOG:
                status = HTTPStatus.NOT_FOUND
                body = _json_bytes({"error": "not_found"})
                headers = [("Content-Type", "application/json")]
                start_response(f"{status.value} {status.phrase}", headers)
                return [body]
            # Parse query for boundary observation
            q = parse_qs(query_string, keep_blank_values=True)
            labels = label_store.get(name, [])
            status = HTTPStatus.OK
            body_obj = {"name": name, "labels": labels, "query": q}
            body = _json_bytes(body_obj)
            headers = [("Content-Type", "application/json")]
            start_response(f"{status.value} {status.phrase}", headers)
            return [body]

        # Route: POST /v1/models/<name>/labels
        if method == "POST" and path_info.startswith("/v1/models/") and path_info.endswith("/labels"):
            name = path_info[len("/v1/models/"):-len("/labels")]
            if name not in _CATALOG:
                status = HTTPStatus.NOT_FOUND
                body = _json_bytes({"error": "not_found"})
                headers = [("Content-Type", "application/json")]
                start_response(f"{status.value} {status.phrase}", headers)
                return [body]

            # --- CONTENT_LENGTH policy ---
            cl_raw = environ.get("CONTENT_LENGTH", None)
            if cl_raw is None:
                # Missing CONTENT_LENGTH on POST endpoint
                status = HTTPStatus.LENGTH_REQUIRED
                body = _json_bytes({"error": "length_required"})
                headers = [("Content-Type", "application/json")]
                start_response(f"{status.value} {status.phrase}", headers)
                return [body]
            try:
                content_length = int(cl_raw) if cl_raw != "" else 0
            except ValueError:
                status = HTTPStatus.BAD_REQUEST
                body = _json_bytes({"error": "invalid_content_length"})
                headers = [("Content-Type", "application/json")]
                start_response(f"{status.value} {status.phrase}", headers)
                return [body]
            if content_length < 0:
                status = HTTPStatus.BAD_REQUEST
                body = _json_bytes({"error": "invalid_content_length"})
                headers = [("Content-Type", "application/json")]
                start_response(f"{status.value} {status.phrase}", headers)
                return [body]
            if content_length == 0:
                status = HTTPStatus.BAD_REQUEST
                body = _json_bytes({"error": "empty_body"})
                headers = [("Content-Type", "application/json")]
                start_response(f"{status.value} {status.phrase}", headers)
                return [body]

            wsgi_input = environ["wsgi.input"]
            body_bytes = wsgi_input.read(content_length)
            # Detect incomplete transport: declared longer than available
            if len(body_bytes) < content_length:
                status = HTTPStatus.BAD_REQUEST
                body = _json_bytes({"error": "incomplete_body"})
                headers = [("Content-Type", "application/json")]
                start_response(f"{status.value} {status.phrase}", headers)
                return [body]

            # Parse JSON
            try:
                payload = json.loads(body_bytes.decode("utf-8"))
            except Exception:
                status = HTTPStatus.BAD_REQUEST
                body = _json_bytes({"error": "invalid_json"})
                headers = [("Content-Type", "application/json")]
                start_response(f"{status.value} {status.phrase}", headers)
                return [body]

            label = payload.get("label")
            if not isinstance(label, str):
                status = HTTPStatus.BAD_REQUEST
                body = _json_bytes({"error": "missing_label"})
                headers = [("Content-Type", "application/json")]
                start_response(f"{status.value} {status.phrase}", headers)
                return [body]

            # Store label
            store = label_store.setdefault(name, [])
            store.append(label)
            status = HTTPStatus.CREATED
            body = _json_bytes({"name": name, "labels": store})
            headers = [("Content-Type", "application/json")]
            start_response(f"{status.value} {status.phrase}", headers)
            return [body]

        # Fallthrough 404
        status = HTTPStatus.NOT_FOUND
        body = _json_bytes({"error": "not_found"})
        headers = [("Content-Type", "application/json")]
        start_response(f"{status.value} {status.phrase}", headers)
        return [body]

    return application


# Default export for WSGI servers (not used in the lab harness)
application = make_application()
