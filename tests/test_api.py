"""API routing and result checks without HTTP connections."""
from unittest.mock import AsyncMock, Mock

import pytest
import logging

from custom_components.econet_grant.api import EconetApi, EconetClient, AuthError


async def test_by_name_write_endpoint():
    client = Mock(spec=EconetClient)
    client.get_with_params.return_value = {
        "result": "OK", "paramName": "Circuit1ComfortTemp", "paramValue": 18.5,
    }
    assert await EconetApi(client).set_param("Circuit1ComfortTemp", 18.5) is True
    client.get_with_params.assert_awaited_once_with(
        "newParam", {"newParamName": "Circuit1ComfortTemp", "newParamValue": "18.5"},
    )


@pytest.mark.parametrize("response", [None, {"result": "ERROR"}])
async def test_write_rejection(response):
    client = Mock(spec=EconetClient)
    client.get_with_params.return_value = response
    assert await EconetApi(client).set_param("Circuit1ComfortTemp", 18.5) is False


async def test_authentication_error_is_not_retried():
    client = EconetClient("econet.invalid", "test", "test-only", Mock())
    client._throttled_get = AsyncMock(side_effect=AuthError("synthetic"))
    with pytest.raises(AuthError):
        await client.get("sysParams")
    client._throttled_get.assert_awaited_once()


async def test_write_name_mismatch(caplog):
    client = Mock(spec=EconetClient)
    client.get_with_params.return_value = {
        "result": "OK", "paramName": "OtherParameter", "paramValue": 18.5,
    }
    with caplog.at_level(logging.INFO):
        assert await EconetApi(client).set_param("Circuit1ComfortTemp", 18.5) is False
    assert "OtherParameter" in caplog.text
    assert "Circuit1ComfortTemp" in caplog.text
    assert any(record.levelno == logging.WARNING for record in caplog.records)
    assert "Successfully set" not in caplog.text


@pytest.mark.parametrize("returned", [19, "19", 18.500001, None, True, [], {}, "NaN", "Infinity"])
async def test_write_value_mismatch(returned, caplog):
    client = Mock(spec=EconetClient)
    client.get_with_params.return_value = {
        "result": "OK", "paramName": "Circuit1ComfortTemp", "paramValue": returned,
    }
    with caplog.at_level(logging.INFO):
        assert await EconetApi(client).set_param("Circuit1ComfortTemp", 18.5) is False
    assert "value mismatch" in caplog.text
    assert "18.5" in caplog.text
    assert not any(record.levelno == logging.INFO for record in caplog.records)


@pytest.mark.parametrize("requested,returned", [(18, 18.0), (18.5, "18.50"), (18, "18"), (0, "0.0")])
async def test_write_numeric_representations(requested, returned):
    client = Mock(spec=EconetClient)
    client.get_with_params.return_value = {
        "result": "OK", "paramName": "Circuit1ComfortTemp", "paramValue": returned,
    }
    assert await EconetApi(client).set_param("Circuit1ComfortTemp", requested) is True


@pytest.mark.parametrize("response", [[], "OK", 1, True, {}, {"result": None}])
async def test_malformed_write_response(response):
    client = Mock(spec=EconetClient)
    client.get_with_params.return_value = response
    assert await EconetApi(client).set_param("Circuit1ComfortTemp", 18.5) is False


@pytest.mark.parametrize("fields", [{}, {"paramName": "Circuit1ComfortTemp"}, {"paramValue": 18.5}])
async def test_missing_optional_fields_warn_but_succeed(fields, caplog):
    client = Mock(spec=EconetClient)
    client.get_with_params.return_value = {"result": "OK", **fields}
    with caplog.at_level(logging.INFO):
        assert await EconetApi(client).set_param("Circuit1ComfortTemp", 18.5) is True
    assert "missing" in caplog.text
    assert any(record.levelno == logging.WARNING for record in caplog.records)
    assert "Successfully set" not in caplog.text


async def test_success_logs_response_not_physical_confirmation(caplog):
    client = Mock(spec=EconetClient)
    client.get_with_params.return_value = {
        "result": "OK", "paramName": "Circuit1ComfortTemp", "paramValue": "18.50",
    }
    with caplog.at_level(logging.INFO):
        assert await EconetApi(client).set_param("Circuit1ComfortTemp", 18.5) is True
    assert "18.50" in caplog.text
    assert "Circuit1ComfortTemp" in caplog.text
    assert "not poll-confirmed" in caplog.text
    assert "Successfully set" not in caplog.text


@pytest.mark.parametrize("method", ["set_param_by_index", "set_param_by_key"])
async def test_legacy_helpers_do_not_compare_name_to_synthetic_label(method):
    client = Mock(spec=EconetClient)
    client.get_with_params.return_value = {
        "result": "OK", "paramName": "Circuit1ComfortTemp", "paramValue": 18.5,
    }
    assert await getattr(EconetApi(client), method)(42, 18.5) is True
