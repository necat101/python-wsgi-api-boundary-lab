# malformed/returns_str.py
def application(environ, start_response):
    start_response("200 OK", [("Content-Type", "text/plain")])
    # Violation: returns str instead of bytes
    return ["hello"]
