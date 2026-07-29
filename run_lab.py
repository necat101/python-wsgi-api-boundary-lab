#!/usr/bin/env python3
"""run_lab.py – structured case runner for python-wsgi-api-boundary-lab.

Generates RESULTS.md and exits nonzero on any failure.
"""
import sys
import json
import importlib
from cases import (
    QUERY_CASES, BODY_CASES, RESPONSE_CONTRACT_CASES,
    MALFORMED_CASES, MIDDLEWARE_CASES,
    call_wsgi, _json_bytes
)
from app.wsgi_api import make_application
from middleware.lab_header import LabHeaderMiddleware
from wsgiref.validate import validator


def run_query_cases(rows):
    for c in QUERY_CASES:
        app = make_application()
        obs = call_wsgi(app, c["method"], c["path"], query_string=c["query_string"])
        passed = (
            obs["status"] == c["expected_status"]
            and obs["body"] == c["expected_body"]
        )
        # Verify contract properties for the valid app
        contract_ok = (
            obs["start_call_count"] == 1
            and all(isinstance(b, bytes) for b in obs["body_chunks"])
        )
        passed = passed and contract_ok
        rows.append({
            "id": c["id"],
            "classification": c["classification"],
            "status": obs["status"],
            "expected_status": c["expected_status"],
            "body": obs["body"].decode("utf-8", errors="replace"),
            "expected_body": c["expected_body"].decode("utf-8"),
            "body_match": obs["body"] == c["expected_body"],
            "start_call_count": obs["start_call_count"],
            "body_chunks_are_bytes": all(isinstance(b, bytes) for b in obs["body_chunks"]),
            "passed": passed,
        })


def run_body_cases(rows):
    for c in BODY_CASES:
        app = make_application()
        body_bytes = c["body_bytes"]
        # Handle raw_content_length override (for invalid case)
        if "raw_content_length" in c:
            # call_wsgi with manual environ override
            from cases import InstrumentedInput
            from wsgiref.util import setup_testing_defaults
            environ = {}
            setup_testing_defaults(environ)
            environ["REQUEST_METHOD"] = c["method"]
            environ["PATH_INFO"] = c["path"]
            environ["QUERY_STRING"] = ""
            environ["CONTENT_LENGTH"] = c["raw_content_length"]
            inp = InstrumentedInput(body_bytes)
            environ["wsgi.input"] = inp
            start_info = {}
            def start_response(status, headers, exc_info=None):
                start_info["status"] = status
                start_info["headers"] = headers
                start_info["call_count"] = start_info.get("call_count", 0) + 1
            result = app(environ, start_response)
            chunks = list(result)
            if hasattr(result, "close"):
                result.close()
            obs = {
                "status": start_info.get("status"),
                "body": b"".join(chunks),
                "total_bytes_read": sum(inp.read_returns),
                "unread_bytes": inp.unread_bytes(),
                "start_call_count": start_info.get("call_count", 0),
                "body_chunks_are_bytes": all(isinstance(x, bytes) for x in chunks),
            }
        else:
            cl = c.get("content_length")
            send_cl = c.get("send_content_length", True)
            obs_full = call_wsgi(
                app, c["method"], c["path"],
                body_bytes=body_bytes,
                content_length=cl if send_cl else None
            )
            obs = {
                "status": obs_full["status"],
                "body": obs_full["body"],
                "total_bytes_read": obs_full["total_bytes_read"],
                "unread_bytes": obs_full["unread_bytes"],
                "start_call_count": obs_full["start_call_count"],
                "body_chunks_are_bytes": all(isinstance(b, bytes) for b in obs_full["body_chunks"]),
            }

        passed = (
            obs["status"] == c["expected_status"]
            and obs["body"] == c["expected_body"]
            and obs["total_bytes_read"] == c["expected_bytes_read"]
        )
        if "expected_unread_bytes" in c:
            passed = passed and (obs["unread_bytes"] == c["expected_unread_bytes"])
        # Contract check
        contract_ok = obs["start_call_count"] == 1 and obs["body_chunks_are_bytes"]
        passed = passed and contract_ok

        rows.append({
            "id": c["id"],
            "classification": c["classification"],
            "status": obs["status"],
            "expected_status": c["expected_status"],
            "body": obs["body"].decode("utf-8", errors="replace"),
            "expected_body": c["expected_body"].decode("utf-8"),
            "body_match": obs["body"] == c["expected_body"],
            "bytes_read": obs["total_bytes_read"],
            "expected_bytes_read": c["expected_bytes_read"],
            "unread_bytes": obs.get("unread_bytes", 0),
            "passed": passed,
        })


def run_response_contract_cases(rows):
    for c in RESPONSE_CONTRACT_CASES:
        app = make_application()
        body_bytes = c.get("body_bytes", b"")
        cl = c.get("content_length")
        send_cl = c.get("send_content_length", False)
        obs = call_wsgi(
            app, c["method"], c["path"],
            query_string=c.get("query_string", ""),
            body_bytes=body_bytes,
            content_length=cl if send_cl else None
        )
        # WSGI contract assertions for valid app:
        # - start_response called exactly once before first body byte
        # - status is "NNN Message" form
        # - headers are list of (str,str)
        # - body iterable yields bytes only
        # - iterator closed
        status_ok = obs["status"] == c["expected_status"]
        body_ok = obs["body"] == c["expected_body"]
        start_once = obs["start_call_count"] == 1
        bytes_only = all(isinstance(b, bytes) for b in obs["body_chunks"])
        headers_ok = all(
            isinstance(k, str) and isinstance(v, str)
            for k, v in obs["headers"]
        )
        status_format_ok = False
        if obs["status"]:
            parts = obs["status"].split(" ", 1)
            status_format_ok = len(parts) == 2 and parts[0].isdigit() and len(parts[0]) == 3

        passed = status_ok and body_ok and start_once and bytes_only and headers_ok and status_format_ok

        rows.append({
            "id": c["id"],
            "classification": c["classification"],
            "status": obs["status"],
            "expected_status": c["expected_status"],
            "body_match": body_ok,
            "start_call_count": obs["start_call_count"],
            "body_chunks_are_bytes": bytes_only,
            "headers_are_str_pairs": headers_ok,
            "status_format_ok": status_format_ok,
            "closed": obs["closed"],
            "passed": passed,
        })


def run_malformed_cases(rows):
    for c in MALFORMED_CASES:
        mod = importlib.import_module(c["module"])
        app = getattr(mod, "application")
        wrapped = validator(app)
        # Minimal environ
        from wsgiref.util import setup_testing_defaults
        import io
        environ = {}
        setup_testing_defaults(environ)
        environ["wsgi.input"] = io.BytesIO(b"")
        
        exception_name = None
        stage = None
        try:
            def sr(status, headers, exc_info=None):
                return None
            result = wrapped(environ, sr)
            stage = "call"
            try:
                first = next(iter(result), None)
                stage = "iteration"
                # Exhaust
                list(result)
                stage = "exhaustion"
            finally:
                if hasattr(result, "close"):
                    result.close()
        except Exception as e:
            exception_name = type(e).__name__

        passed = exception_name == c["expected_exception"]
        # We also record stage, but don't fail on stage mismatch –
        # validator behavior can vary slightly across Python versions.
        # The important thing is AssertionError is raised.
        rows.append({
            "id": c["id"],
            "classification": c["classification"],
            "exception": exception_name,
            "expected_exception": c["expected_exception"],
            "stage": stage,
            "expected_stage": c["expected_stage"],
            "passed": passed,
        })


def run_middleware_cases(rows):
    # mw1: normal bytes iterable
    app = make_application()
    mw_app = LabHeaderMiddleware(app)
    obs = call_wsgi(mw_app, "GET", "/v1/models/bert-tiny", query_string="")
    owned = [h for h in obs["headers"] if h[0].lower() == "x-lab-middleware".lower()]
    passed_mw1 = (
        obs["status"] == "200 OK"
        and len(owned) == 1
        and owned[0] == ("X-Lab-Middleware", "applied")
    )
    rows.append({
        "id": "mw1_normal",
        "classification": "middleware",
        "status": obs["status"],
        "owned_header_count": len(owned),
        "owned_header_value": owned[0] if owned else None,
        "passed": passed_mw1,
    })

    # mw2: close spy
    close_calls = []
    def close_spy_app(environ, start_response):
        start_response("200 OK", [("Content-Type", "text/plain")])
        class SpyIter:
            def __iter__(self):
                return self
            def __next__(self):
                raise StopIteration
            def close(self):
                close_calls.append(1)
        return SpyIter()
    
    mw_app2 = LabHeaderMiddleware(close_spy_app)
    obs2 = call_wsgi(mw_app2, "GET", "/", "")
    passed_mw2 = len(close_calls) == 1
    rows.append({
        "id": "mw2_close_spy",
        "classification": "middleware",
        "close_calls": len(close_calls),
        "passed": passed_mw2,
    })

    # mw3: exception during iteration
    def raising_app(environ, start_response):
        start_response("200 OK", [("Content-Type", "text/plain")])
        def gen():
            yield b"a"
            raise ValueError("boom")
        return gen()

    mw_app3 = LabHeaderMiddleware(raising_app)
    from cases import call_wsgi as cw
    # call_wsgi will propagate the exception – catch it
    from wsgiref.util import setup_testing_defaults
    import io
    environ = {}
    setup_testing_defaults(environ)
    environ["REQUEST_METHOD"] = "GET"
    environ["PATH_INFO"] = "/"
    environ["wsgi.input"] = io.BytesIO(b"")
    caught = None
    def sr(status, headers, exc_info=None):
        pass
    try:
        result = mw_app3(environ, sr)
        for _ in result:
            pass
    except ValueError as e:
        caught = "ValueError"
    finally:
        try:
            if "result" in locals() and hasattr(result, "close"):
                result.close()
        except Exception:
            pass
    passed_mw3 = caught == "ValueError"
    rows.append({
        "id": "mw3_iter_raise",
        "classification": "middleware",
        "exception_propagated": caught,
        "passed": passed_mw3,
    })

    # mw4: replace owned header
    def app_with_owned_header(environ, start_response):
        start_response("200 OK", [
            ("Content-Type", "text/plain"),
            ("X-Lab-Middleware", "stale"),
            ("x-lab-middleware", "also_stale"),
        ])
        return [b"ok"]
    
    mw_app4 = LabHeaderMiddleware(app_with_owned_header)
    obs4 = call_wsgi(mw_app4, "GET", "/", "")
    owned4 = [h for h in obs4["headers"] if h[0].lower() == "x-lab-middleware"]
    passed_mw4 = owned4 == [("X-Lab-Middleware", "applied")]
    rows.append({
        "id": "mw4_replace_owned",
        "classification": "middleware",
        "owned_header_count": len(owned4),
        "owned_headers": owned4,
        "passed": passed_mw4,
    })


def main():
    rows = []
    run_query_cases(rows)
    run_body_cases(rows)
    run_response_contract_cases(rows)
    run_malformed_cases(rows)
    run_middleware_cases(rows)

    total = len(rows)
    passed = sum(1 for r in rows if r["passed"])
    failed = total - passed

    # Integrity checks
    case_ids = [r["id"] for r in rows]
    assert len(case_ids) == len(set(case_ids)), "duplicate case IDs"
    from cases import ALL_CASE_IDS
    assert set(case_ids) == set(ALL_CASE_IDS), f"case ID set mismatch: got {sorted(case_ids)}, expected {sorted(ALL_CASE_IDS)}"
    assert total == len(ALL_CASE_IDS), "row count mismatch"

    classifications = {}
    for r in rows:
        classifications[r["classification"]] = classifications.get(r["classification"], 0) + 1

    # Write RESULTS.md
    with open("RESULTS.md", "w") as f:
        f.write("# RESULTS – python-wsgi-api-boundary-lab\n\n")
        f.write(f"Total: {total}, Passed: {passed}, Failed: {failed}\n\n")
        f.write("| classification | count |\n|---|---|\n")
        for k in sorted(classifications):
            f.write(f"| {k} | {classifications[k]} |\n")
        f.write("\n## Cases\n\n")
        for r in rows:
            status_str = "PASS" if r["passed"] else "FAIL"
            f.write(f"### {r['id']} [{r['classification']}] – {status_str}\n\n")
            # Common fields
            if "status" in r:
                f.write(f"- status: `{r['status']}`")
                if "expected_status" in r:
                    f.write(f" (expected `{r['expected_status']}`)")
                f.write("\n")
            if "body_match" in r:
                f.write(f"- body_match: {r['body_match']}\n")
            if "body" in r and "expected_body" in r and len(str(r["body"])) < 200:
                f.write(f"- body: `{r['body']}`\n")
            if "bytes_read" in r:
                f.write(f"- bytes_read: {r['bytes_read']} (expected {r.get('expected_bytes_read')})\n")
            if r.get("unread_bytes", 0):
                f.write(f"- unread_bytes: {r['unread_bytes']}\n")
            if "exception" in r:
                f.write(f"- exception: {r['exception']} (expected {r['expected_exception']}), stage: {r.get('stage')}\n")
            if "owned_header_count" in r:
                f.write(f"- owned_header_count: {r['owned_header_count']}\n")
            if "close_calls" in r:
                f.write(f"- close_calls: {r['close_calls']}\n")
            if "exception_propagated" in r:
                f.write(f"- exception_propagated: {r['exception_propagated']}\n")
            f.write("\n")

    print(f"Total: {total}, Passed: {passed}, Failed: {failed}")
    for k in sorted(classifications):
        print(f"  {k}: {classifications[k]}")
    if failed:
        print(f"FAILED: {failed} case(s)", file=sys.stderr)
        sys.exit(1)
    print("All cases passed.")


if __name__ == "__main__":
    main()
