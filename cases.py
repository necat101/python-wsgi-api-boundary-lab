# cases.py
"""Fixed case manifest for python-wsgi-api-boundary-lab."""
import json
import io
from wsgiref.util import setup_testing_defaults
from app.wsgi_api import make_application

_CATALOG = ["bert-tiny", "distilgpt2", "whisper-tiny"]

def _json_bytes(obj):
    return json.dumps(obj, separators=(",", ":"), sort_keys=True).encode("utf-8")


# --- Body byte constants for Content-Length cases ---
# Do NOT manually repeat lengths – derive from len()
BODY_LABEL_POS = b'{"label":"pos"}'   # 15 bytes
BODY_LABEL_OK = b'{"label":"ok"}'      # 14 bytes
BODY_LABEL_Z = b'{"label":"z"}'        # 13 bytes
BODY_EMPTY_JSON = b'{}'                # 2 bytes


class InstrumentedInput:
    """WSGI input wrapper that records read behavior."""
    def __init__(self, data: bytes):
        self._buf = io.BytesIO(data)
        self._full_data = data
        self.read_requests = []  # list of requested sizes
        self.read_returns = []   # list of bytes returned per read

    def read(self, size=-1):
        self.read_requests.append(size)
        chunk = self._buf.read(size)
        self.read_returns.append(len(chunk))
        return chunk

    def tell(self):
        return self._buf.tell()

    def unread_bytes(self):
        pos = self._buf.tell()
        return len(self._full_data) - pos


def call_wsgi(app, method, path, query_string="", body_bytes=b"", content_length=None, content_type=None, extra_environ=None):
    """Call a WSGI app with constructed environ. Returns dict with observations."""
    environ = {}
    setup_testing_defaults(environ)
    environ["REQUEST_METHOD"] = method
    environ["PATH_INFO"] = path
    environ["QUERY_STRING"] = query_string
    # Correct WSGI keys: CONTENT_TYPE / CONTENT_LENGTH, not HTTP_CONTENT_*
    if content_type is not None:
        environ["CONTENT_TYPE"] = content_type
    # Instrumented input
    inp = InstrumentedInput(body_bytes)
    environ["wsgi.input"] = inp
    if content_length is not None:
        environ["CONTENT_LENGTH"] = str(content_length)
    elif "CONTENT_LENGTH" in environ:
        del environ["CONTENT_LENGTH"]
    if extra_environ:
        environ.update(extra_environ)

    start_info = {}
    def start_response(status, response_headers, exc_info=None):
        start_info["status"] = status
        start_info["headers"] = response_headers
        start_info["exc_info"] = exc_info
        start_info["call_count"] = start_info.get("call_count", 0) + 1
        return None

    result = app(environ, start_response)
    body_chunks = []
    iterated = False
    try:
        for chunk in result:
            iterated = True
            body_chunks.append(chunk)
    finally:
        close_fn = getattr(result, "close", None)
        if close_fn:
            close_fn()
            start_info["closed"] = True
        else:
            start_info["closed"] = False

    body = b"".join(body_chunks)
    return {
        "status": start_info.get("status"),
        "headers": start_info.get("headers", []),
        "body": body,
        "start_call_count": start_info.get("call_count", 0),
        "body_chunks": body_chunks,
        "closed": start_info.get("closed", False),
        "read_requests": inp.read_requests,
        "read_returns": inp.read_returns,
        "stream_pos": inp.tell(),
        "unread_bytes": inp.unread_bytes(),
        "total_bytes_read": sum(inp.read_returns),
    }


# --- Case manifest ---

# Q1: environ query parsing
QUERY_CASES = [
    {
        "id": "q1",
        "classification": "environ_query",
        "method": "GET",
        "path": "/v1/models/bert-tiny",
        "query_string": "",
        "expected_status": "200 OK",
        "expected_query": {},
    },
    {
        "id": "q2",
        "classification": "environ_query",
        "method": "GET",
        "path": "/v1/models/bert-tiny",
        "query_string": "verbose=1",
        "expected_status": "200 OK",
        "expected_query": {"verbose": ["1"]},
    },
    {
        "id": "q3",
        "classification": "environ_query",
        "method": "GET",
        "path": "/v1/models/bert-tiny",
        "query_string": "tag=a&tag=b&tag=",
        "expected_status": "200 OK",
        "expected_query": {"tag": ["a", "b", ""]},
    },
    {
        "id": "q4",
        "classification": "environ_query",
        "method": "GET",
        "path": "/v1/models/bert-tiny",
        "query_string": "q=&x=1&q=2",
        "expected_status": "200 OK",
        "expected_query": {"q": ["", "2"], "x": ["1"]},
    },
    {
        "id": "q5",
        "classification": "environ_query",
        "method": "GET",
        "path": "/v1/models/distilgpt2",
        "query_string": "empty=&empty=",
        "expected_status": "200 OK",
        "expected_query": {"empty": ["", ""]},
    },
]

# Fill in expected_body for query cases
for c in QUERY_CASES:
    model = c["path"].split("/")[-1]
    body_obj = {"labels": [], "name": model, "query": c["expected_query"]}
    c["expected_body"] = _json_bytes(body_obj)


# Q2: wsgi.input / CONTENT_LENGTH
# Derive lengths from actual body constants
BODY_CASES = [
    {
        "id": "b1_empty",
        "classification": "body_input",
        "method": "POST",
        "path": "/v1/models/bert-tiny/labels",
        "body_bytes": b"",
        "content_length": 0,
        "send_content_length": True,
        "expected_status": "400 Bad Request",
        "expected_body": _json_bytes({"error": "empty_body"}),
        "expected_bytes_read": 0,
    },
    {
        "id": "b2_exact",
        "classification": "body_input",
        "method": "POST",
        "path": "/v1/models/bert-tiny/labels",
        "body_bytes": BODY_LABEL_POS,
        "content_length": len(BODY_LABEL_POS),
        "send_content_length": True,
        "expected_status": "201 Created",
        "expected_body": _json_bytes({"labels": ["pos"], "name": "bert-tiny"}),
        "expected_bytes_read": len(BODY_LABEL_POS),
    },
    {
        # declared shorter than available – app reads only declared bytes
        "id": "b3_short_declared",
        "classification": "body_input",
        "method": "POST",
        "path": "/v1/models/bert-tiny/labels",
        "body_bytes": BODY_LABEL_Z,  # 13 bytes available
        "content_length": 5,  # declared shorter
        "send_content_length": True,
        "expected_status": "400 Bad Request",
        "expected_body": _json_bytes({"error": "invalid_json"}),
        "expected_bytes_read": 5,
        "expected_unread_bytes": len(BODY_LABEL_Z) - 5,
    },
    {
        # declared longer than available – detect incomplete
        "id": "b4_long_declared",
        "classification": "body_input",
        "method": "POST",
        "path": "/v1/models/bert-tiny/labels",
        "body_bytes": BODY_LABEL_OK,  # 14 bytes available
        "content_length": 100,  # declared longer
        "send_content_length": True,
        "expected_status": "400 Bad Request",
        "expected_body": _json_bytes({"error": "incomplete_body"}),
        "expected_bytes_read": len(BODY_LABEL_OK),
    },
    {
        # missing CONTENT_LENGTH
        "id": "b5_missing_cl",
        "classification": "body_input",
        "method": "POST",
        "path": "/v1/models/bert-tiny/labels",
        "body_bytes": BODY_LABEL_Z,
        "content_length": None,
        "send_content_length": False,
        "expected_status": "411 Length Required",
        "expected_body": _json_bytes({"error": "length_required"}),
        "expected_bytes_read": 0,
    },
    {
        # invalid CONTENT_LENGTH
        "id": "b6_invalid_cl",
        "classification": "body_input",
        "method": "POST",
        "path": "/v1/models/bert-tiny/labels",
        "body_bytes": BODY_LABEL_Z,
        "content_length": "abc",
        "send_content_length": True,
        "raw_content_length": "abc",
        "expected_status": "400 Bad Request",
        "expected_body": _json_bytes({"error": "invalid_content_length"}),
        "expected_bytes_read": 0,
    },
    {
        # valid JSON but missing label field
        "id": "b7_empty_json",
        "classification": "body_input",
        "method": "POST",
        "path": "/v1/models/bert-tiny/labels",
        "body_bytes": BODY_EMPTY_JSON,
        "content_length": len(BODY_EMPTY_JSON),
        "send_content_length": True,
        "expected_status": "400 Bad Request",
        "expected_body": _json_bytes({"error": "missing_label"}),
        "expected_bytes_read": len(BODY_EMPTY_JSON),
    },
]

# Response contract – compliant app cases (smoke)
# These reuse query cases but check WSGI contract properties
RESPONSE_CONTRACT_CASES = [
    {
        "id": "r1_get_ok",
        "classification": "response_contract",
        "method": "GET",
        "path": "/v1/models/bert-tiny",
        "query_string": "",
        "expected_status": "200 OK",
        "expected_body": _json_bytes({"labels": [], "name": "bert-tiny", "query": {}}),
    },
    {
        "id": "r2_post_created",
        "classification": "response_contract",
        "method": "POST",
        "path": "/v1/models/bert-tiny/labels",
        "body_bytes": BODY_LABEL_POS,
        "content_length": len(BODY_LABEL_POS),
        "send_content_length": True,
        "expected_status": "201 Created",
        "expected_body": _json_bytes({"labels": ["pos"], "name": "bert-tiny"}),
    },
    {
        "id": "r3_not_found",
        "classification": "response_contract",
        "method": "GET",
        "path": "/v1/models/unknown",
        "query_string": "",
        "expected_status": "404 Not Found",
        "expected_body": _json_bytes({"error": "not_found"}),
    },
]

# Malformed app cases
MALFORMED_CASES = [
    {
        "id": "m1_returns_str",
        "classification": "malformed",
        "module": "malformed.returns_str",
        "expected_exception": "AssertionError",
        "expected_stage": "iteration",  # validator catches on first yield
    },
    {
        "id": "m2_no_start_response",
        "classification": "malformed",
        "module": "malformed.no_start_response",
        "expected_exception": "AssertionError",
        "expected_stage": "exhaustion",  # validator checks after iteration
    },
    {
        "id": "m3_bad_headers",
        "classification": "malformed",
        "module": "malformed.bad_headers",
        "expected_exception": "AssertionError",
        "expected_stage": "call",  # validator catches at start_response call time
    },
]

# Middleware cases
MIDDLEWARE_CASES = [
    {
        "id": "mw1_normal",
        "classification": "middleware",
        "description": "normal bytes iterable",
        "expected_owned_header": ("X-Lab-Middleware", "applied"),
    },
    {
        "id": "mw2_close_spy",
        "classification": "middleware",
        "description": "close() forwarded exactly once",
        "expected_owned_header": ("X-Lab-Middleware", "applied"),
    },
    {
        "id": "mw3_iter_raise",
        "classification": "middleware",
        "description": "exception during iteration propagates, cleanup occurs",
        "expected_owned_header": ("X-Lab-Middleware", "applied"),
    },
    {
        "id": "mw4_replace_owned",
        "classification": "middleware",
        "description": "wrapped response already contains owned header – output has exactly one canonical entry",
        "expected_owned_header": ("X-Lab-Middleware", "applied"),
    },
]

ALL_CASE_IDS = (
    [c["id"] for c in QUERY_CASES]
    + [c["id"] for c in BODY_CASES]
    + [c["id"] for c in RESPONSE_CONTRACT_CASES]
    + [c["id"] for c in MALFORMED_CASES]
    + [c["id"] for c in MIDDLEWARE_CASES]
)
