"""Tests for the Shelly RPC client (respx-mocked)."""

from __future__ import annotations

import httpx
import pytest
import respx

from lly.shelly.client import ShellyClient, ShellyError
from lly.shelly.rpc import fetch_status, get_status, reboot


@respx.mock
async def test_call_success() -> None:
    respx.post("http://10.0.0.1/rpc").mock(
        return_value=httpx.Response(200, json={"id": 1, "result": {"hello": "world"}})
    )
    async with ShellyClient("10.0.0.1") as client:
        result = await client.call("Shelly.GetDeviceInfo")
    assert result == {"hello": "world"}


@respx.mock
async def test_call_error_envelope() -> None:
    respx.post("http://10.0.0.1/rpc").mock(
        return_value=httpx.Response(
            200, json={"id": 1, "error": {"code": -104, "message": "no update"}}
        )
    )
    async with ShellyClient("10.0.0.1") as client:
        with pytest.raises(ShellyError) as exc:
            await client.call("Shelly.Update")
    assert exc.value.code == -104
    assert "no update" in exc.value.message


@respx.mock
async def test_call_transport_error() -> None:
    respx.post("http://10.0.0.1/rpc").mock(side_effect=httpx.ConnectError("nope"))
    async with ShellyClient("10.0.0.1") as client:
        with pytest.raises(ShellyError):
            await client.call("Shelly.GetStatus")


@respx.mock
async def test_fetch_status_offline_returns_status_object() -> None:
    respx.post("http://10.0.0.1/rpc").mock(side_effect=httpx.ConnectError("nope"))
    async with ShellyClient("10.0.0.1") as client:
        status = await fetch_status(client)
    assert status.online is False
    assert status.error is not None


@respx.mock
async def test_get_status_and_reboot() -> None:
    respx.post("http://10.0.0.1/rpc").mock(
        return_value=httpx.Response(200, json={"id": 1, "result": {"switch:0": {"output": True}}})
    )
    async with ShellyClient("10.0.0.1") as client:
        data = await get_status(client)
        assert data["switch:0"]["output"] is True
        await reboot(client)
