# middleware/lab_header.py
class LabHeaderMiddleware:
    """WSGI middleware that adds/owns one deterministic header.

    Policy:
    - Preserve every non-owned response header.
    - Replace any preexisting case-insensitive X-Lab-Middleware entry
      with exactly one canonical ("X-Lab-Middleware", "applied") pair.
    - Otherwise append it once.
    - Forward status/body unchanged.
    - Forward iterator close().
    - Propagate exceptions (do not swallow).
    """
    OWNED_HEADER = "X-Lab-Middleware"
    OWNED_VALUE = "applied"

    def __init__(self, application):
        self.application = application

    def __call__(self, environ, start_response):
        captured = {}

        def mw_start_response(status, response_headers, exc_info=None):
            # Strip any existing owned header (case-insensitive)
            filtered = [
                (k, v)
                for (k, v) in response_headers
                if k.lower() != self.OWNED_HEADER.lower()
            ]
            filtered.append((self.OWNED_HEADER, self.OWNED_VALUE))
            captured["status"] = status
            captured["headers"] = filtered
            # Forward exc_info correctly
            return start_response(status, filtered, exc_info)

        app_iter = self.application(environ, mw_start_response)

        class WrappingIterator:
            def __init__(self, inner):
                self._inner = iter(inner)
                self._inner_obj = inner

            def __iter__(self):
                return self

            def __next__(self):
                return next(self._inner)

        wrapped = WrappingIterator(app_iter)

        # Forward close() only if inner has it
        close_fn = getattr(app_iter, "close", None)
        if close_fn is not None:
            def do_close():
                close_fn()
            wrapped.close = do_close

        return wrapped
