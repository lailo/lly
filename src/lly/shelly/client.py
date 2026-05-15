"""Async JSON-RPC client for Shelly Gen2/Gen3 devices."""

from __future__ import annotations

from typing import Any, Self

import httpx


class ShellyError(Exception):
    """Raised on a Shelly RPC error envelope or transport failure."""

    def __init__(self, code: int | None, message: str) -> None:
        super().__init__(f"[{code}] {message}" if code is not None else message)
        self.code = code
        self.message = message


class ShellyClient:
    """Thin async wrapper around `POST http://<host>/rpc`."""

    def __init__(
        self,
        host: str,
        password: str | None = None,
        *,
        timeout: float = 4.0,
    ) -> None:
        self._host = host
        auth: httpx.Auth | None = (
            httpx.DigestAuth(username="admin", password=password) if password else None
        )
        self._client = httpx.AsyncClient(
            base_url=f"http://{host}",
            timeout=timeout,
            auth=auth,
        )

    @property
    def host(self) -> str:
        return self._host

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"id": 1, "method": method}
        if params:
            payload["params"] = params
        try:
            response = await self._client.post("/rpc", json=payload)
        except httpx.HTTPError as exc:
            # `str(exc)` is empty for several httpx exception classes
            # (ConnectTimeout, ReadTimeout, …) — fall back to the class name
            # so the log isn't a useless "transport: ".
            detail = str(exc) or type(exc).__name__
            raise ShellyError(None, f"transport: {detail}") from exc

        if response.status_code >= 400:
            raise ShellyError(
                response.status_code, f"http {response.status_code}: {response.text[:200]}"
            )

        try:
            body = response.json()
        except ValueError as exc:
            raise ShellyError(None, f"non-json response: {exc!s}") from exc

        if "error" in body and body["error"] is not None:
            err = body["error"]
            raise ShellyError(err.get("code"), err.get("message", "unknown shelly error"))

        result = body.get("result", {})
        if not isinstance(result, dict):
            return {"value": result}
        return result
