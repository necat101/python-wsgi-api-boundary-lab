# malformed/no_start_response.py
def application(environ, start_response):
    # Violation: never calls start_response
    return [b"oops"]
