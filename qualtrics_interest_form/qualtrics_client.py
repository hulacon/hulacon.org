"""Thin wrapper around the Qualtrics Survey-Definition API.

Reads the API token from ~/Dropbox/admin/api_keys/qualtrics.txt.
Never logs, prints, or includes the token in exceptions.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional
import requests


TOKEN_PATH = Path.home() / "Dropbox" / "admin" / "api_keys" / "qualtrics.txt"

# Qualtrics exposes the same API under the bare datacenter host and under the
# brand-specific host. We try the bare datacenter first and fall back on auth/
# routing errors. (Verified empirically on first request.)
PRIMARY_BASE = "https://yul1.qualtrics.com/API/v3"
FALLBACK_BASE = "https://oregon.yul1.qualtrics.com/API/v3"


class QualtricsError(RuntimeError):
    """Raised for non-2xx responses. Message comes from the Qualtrics error
    body when present, otherwise the HTTP status. The API token is never
    included."""


def _load_token() -> str:
    token = TOKEN_PATH.read_text().strip()
    if not token:
        raise RuntimeError(f"Token file at {TOKEN_PATH} is empty")
    return token


class QualtricsClient:
    def __init__(self, base_url: Optional[str] = None) -> None:
        self._token = _load_token()
        self._session = requests.Session()
        self._session.headers.update({
            "X-API-TOKEN": self._token,
            "Content-Type": "application/json",
        })
        # If caller pins a base_url, skip the probe.
        self.base_url: Optional[str] = base_url
        self._probed = base_url is not None

    # ---------- low-level ----------

    def _ensure_base(self) -> str:
        if self.base_url:
            return self.base_url
        # Probe: try primary, fall back on 401/403/404.
        for candidate in (PRIMARY_BASE, FALLBACK_BASE):
            try:
                r = self._session.get(f"{candidate}/whoami", timeout=15)
            except requests.RequestException:
                continue
            if r.status_code == 200:
                self.base_url = candidate
                self._probed = True
                return candidate
            if r.status_code in (401, 403, 404) and candidate != FALLBACK_BASE:
                continue
            # Some other error — surface it.
            self._raise_for_response(r)
        raise QualtricsError("Could not reach Qualtrics API on either base URL")

    def _request(self, method: str, path: str, **kwargs: Any) -> dict:
        base = self._ensure_base()
        url = f"{base}{path}"
        r = self._session.request(method, url, timeout=30, **kwargs)
        if not r.ok:
            self._raise_for_response(r)
        if r.status_code == 204 or not r.content:
            return {}
        return r.json()

    @staticmethod
    def _raise_for_response(r: requests.Response) -> None:
        msg = f"HTTP {r.status_code}"
        # Show the raw body in full — Qualtrics' meta.error.errorMessage is
        # often a useless "The request was invalid." but the body sometimes
        # includes hints (or proves nothing else was returned).
        text = r.text.strip()
        try:
            body = r.json()
            err = (body.get("meta") or {}).get("error") or {}
            api_msg = err.get("errorMessage") or err.get("errorCode")
            if api_msg:
                msg = f"{msg}: {api_msg}"
        except ValueError:
            pass
        if text:
            msg = f"{msg} | raw: {text[:2000]}"
        raise QualtricsError(msg)

    # ---------- high-level endpoints ----------

    def whoami(self) -> dict:
        return self._request("GET", "/whoami").get("result", {})

    def list_surveys(self) -> list[dict]:
        """Return all surveys, following nextPage tokens."""
        out: list[dict] = []
        path = "/surveys"
        while path:
            body = self._request("GET", path)
            result = body.get("result", {}) or {}
            out.extend(result.get("elements", []) or [])
            next_page = result.get("nextPage")
            if not next_page:
                break
            # nextPage is a full URL; strip the base.
            base = self.base_url or ""
            path = next_page[len(base):] if next_page.startswith(base) else next_page
        return out

    def get_survey_definition(self, survey_id: str) -> dict:
        return self._request("GET", f"/survey-definitions/{survey_id}").get("result", {})

    def create_survey(self, name: str, language: str = "EN", project_category: str = "CORE") -> dict:
        payload = {"SurveyName": name, "Language": language, "ProjectCategory": project_category}
        return self._request("POST", "/survey-definitions", json=payload).get("result", {})

    def delete_survey(self, survey_id: str) -> dict:
        return self._request("DELETE", f"/survey-definitions/{survey_id}")

    # /surveys/{id} (note: surveys endpoint, not survey-definitions) handles
    # the isActive flag and exposes the rendered question/choice shapes.
    def get_survey_meta(self, survey_id: str) -> dict:
        return self._request("GET", f"/surveys/{survey_id}").get("result", {})

    def activate_survey(self, survey_id: str) -> dict:
        return self._request("PUT", f"/surveys/{survey_id}", json={"isActive": True})

    def deactivate_survey(self, survey_id: str) -> dict:
        return self._request("PUT", f"/surveys/{survey_id}", json={"isActive": False})

    def anonymous_link(self, survey_id: str) -> str:
        # Brand subdomain is required for the public form URL.
        return f"https://oregon.yul1.qualtrics.com/jfe/form/{survey_id}"

    # ---- questions ----

    def create_question(self, survey_id: str, payload: dict, block_id: Optional[str] = None) -> dict:
        path = f"/survey-definitions/{survey_id}/questions"
        if block_id:
            path = f"{path}?blockId={block_id}"
        return self._request("POST", path, json=payload).get("result", {})

    def update_question(self, survey_id: str, question_id: str, payload: dict) -> dict:
        return self._request("PUT", f"/survey-definitions/{survey_id}/questions/{question_id}", json=payload).get("result", {})

    def delete_question(self, survey_id: str, question_id: str) -> dict:
        return self._request("DELETE", f"/survey-definitions/{survey_id}/questions/{question_id}")

    # ---- blocks ----

    def create_block(self, survey_id: str, payload: dict) -> dict:
        return self._request("POST", f"/survey-definitions/{survey_id}/blocks", json=payload).get("result", {})

    def update_block(self, survey_id: str, block_id: str, payload: dict) -> dict:
        return self._request("PUT", f"/survey-definitions/{survey_id}/blocks/{block_id}", json=payload).get("result", {})

    def delete_block(self, survey_id: str, block_id: str) -> dict:
        return self._request("DELETE", f"/survey-definitions/{survey_id}/blocks/{block_id}")

    # ---- flow ----

    def get_flow(self, survey_id: str) -> dict:
        return self._request("GET", f"/survey-definitions/{survey_id}/flow").get("result", {})

    def update_flow(self, survey_id: str, payload: dict) -> dict:
        return self._request("PUT", f"/survey-definitions/{survey_id}/flow", json=payload).get("result", {})
