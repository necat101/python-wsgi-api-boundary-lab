# malformed/bad_headers.py
def application(environ, start_response):
    # Violation: header value is not a native string
    start_response("200 OK", [("Content-Type", 12345)])
    return [b"hi"]
