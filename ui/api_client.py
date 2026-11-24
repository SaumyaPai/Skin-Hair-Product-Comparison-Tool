"""The ONLY way the screen talks to the app: plain web requests to the API.
The screen never calls Open Beauty Facts, Gemini or Groq itself."""
import os

import httpx

DEFAULT_URL = "http://localhost:8000"


class ApiProblem(Exception):
    """A friendly error to show the shopper. `message` always comes from the API's own plain text."""

    def __init__(self, message: str, code: str = "", status: int = 0):
        super().__init__(message)
        self.message, self.code, self.status = message, code, status


class ApiUnavailable(ApiProblem):
    pass


class ApiClient:
    def __init__(self, base_url: str = DEFAULT_URL, http: httpx.Client | None = None):
        self.http = http or httpx.Client(base_url=base_url, timeout=httpx.Timeout(120, connect=5))

    def _call(self, method: str, path: str, **kwargs) -> dict:
        try:
            resp = self.http.request(method, path, **kwargs)
        except httpx.TimeoutException:
            raise ApiProblem("This is taking too long. Please try again in a minute.", "TIMEOUT")
        except httpx.HTTPError:
            raise ApiUnavailable("The comparison service isn't running. Start it and refresh this page.",
                                 "API_UNAVAILABLE")
        try:
            body = resp.json()
        except ValueError:
            body = {}
        if resp.status_code >= 400:
            err = body.get("error", {}) if isinstance(body, dict) else {}
            raise ApiProblem(err.get("message") or "Something went wrong. Please try again.",
                             err.get("code", ""), resp.status_code)
        return body

    def options(self) -> dict:
        return self._call("GET", "/v1/meta/options")

    def lookup_barcode(self, barcode: str) -> dict:
        return self._call("GET", "/v1/products/lookup", params={"barcode": barcode})

    def search(self, query: str) -> dict:
        return self._call("GET", "/v1/products/lookup", params={"q": query})

    def extract(self, image_bytes: bytes, filename: str, mime: str, progress_id: str | None = None) -> dict:
        headers = {"X-Progress-Id": progress_id} if progress_id else None
        return self._call("POST", "/v1/products/extract", files={"image": (filename, image_bytes, mime)},
                          headers=headers)

    def extract_progress(self, progress_id: str) -> dict:
        """Which reader is working on the photo right now. Never raises: progress is only a nicety."""
        try:
            return self._call("GET", f"/v1/products/extract/progress/{progress_id}")
        except ApiProblem:
            return {}

    def compare(self, body: dict) -> dict:
        return self._call("POST", "/v1/compare", json=body)


def make_client() -> ApiClient:
    """Tests replace this function to point the screen at a fake API."""
    return ApiClient(os.getenv("API_URL", DEFAULT_URL))
