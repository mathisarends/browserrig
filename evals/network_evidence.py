"""Readable request evidence for diagnosis, without replacing upstream scoring."""

import html
import json
import re
from email import policy
from email.parser import BytesParser
from pathlib import Path
from urllib.parse import parse_qs

from pydantic import BaseModel, Field, JsonValue


class NetworkRequest(BaseModel):
    method: str
    url: str
    fields: dict[str, JsonValue] = Field(default_factory=dict)


class PayloadDifference(BaseModel):
    field: str
    expected: JsonValue
    actual: JsonValue


class DocumentVisit(BaseModel):
    time: str
    method: str
    url: str
    status: int
    title: str = ""


def documents(workspace: Path) -> list[DocumentVisit]:
    path = workspace / "network.har"
    if not path.is_file():
        return []
    visits = []
    for entry in json.loads(path.read_bytes())["log"]["entries"]:
        if entry.get("_resourceType") != "document":
            continue
        response = entry["response"]
        text = response.get("content", {}).get("text", "")
        title = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
        visits.append(
            DocumentVisit(
                time=entry.get("startedDateTime", ""),
                method=entry["request"]["method"],
                url=entry["request"]["url"],
                status=response["status"],
                title=html.unescape(title.group(1).strip()) if title else "",
            )
        )
    return visits


def requests(workspace: Path) -> list[NetworkRequest]:
    path = workspace / "network.har"
    if not path.is_file():
        return []
    config = json.loads((workspace / "environment.json").read_bytes())
    mappings = {
        url.rstrip("/"): placeholder.lower()
        for placeholder, environment in config["environments"].items()
        for url in environment["urls"]
    }
    har = json.loads(path.read_bytes())
    evidence = []
    for entry in har["log"]["entries"]:
        request = entry["request"]
        if request["method"] in {"GET", "HEAD", "OPTIONS"}:
            continue
        fields = _fields(request.get("postData", {}))
        fields = {key: _derender(value, mappings) for key, value in fields.items()}
        evidence.append(
            NetworkRequest(
                method=request["method"],
                url=request["url"],
                fields=redact(fields),
            )
        )
    return evidence


def differences(grade: dict, recorded: list[NetworkRequest]) -> list[PayloadDifference]:
    """Compare literal form fields; regexes/alternatives remain upstream's concern."""
    result = []
    for evaluator in grade.get("evaluators_results", []):
        if (
            evaluator.get("evaluator_name") != "NetworkEventEvaluator"
            or evaluator["status"] == "success"
        ):
            continue
        expected = (evaluator.get("expected") or {}).get("post_data") or {}
        expected = {
            key: value
            for key, value in expected.items()
            if not isinstance(value, (dict, list)) and not _special(value)
        }
        if not expected:
            continue
        actual = evaluator.get("actual_normalized") or []
        candidates = [
            item.get("post_data") or {} for item in actual if isinstance(item, dict)
        ]
        if not candidates:
            candidates = [
                item.fields for item in recorded if expected.keys() & item.fields.keys()
            ]
        if not candidates:
            continue
        closest = max(
            candidates,
            key=lambda fields, wanted=expected: sum(
                _equal(value, fields.get(key)) for key, value in wanted.items()
            ),
        )
        result.extend(
            PayloadDifference(field=key, expected=value, actual=closest.get(key))
            for key, value in expected.items()
            if not _equal(value, closest.get(key))
        )
    return result


def redact(value):
    if isinstance(value, list):
        return [redact(item) for item in value]
    if not isinstance(value, dict):
        return value
    return {
        key: "[redacted]" if _secret(key) else redact(item)
        for key, item in value.items()
    }


def _derender(value: JsonValue, mappings: dict[str, str]) -> JsonValue:
    if not isinstance(value, str):
        return value
    for url, placeholder in sorted(mappings.items(), key=lambda item: -len(item[0])):
        value = value.replace(url, placeholder)
    return value


def _secret(key: str) -> bool:
    return any(
        part in key.lower()
        for part in ("token", "password", "cookie", "authorization", "form_key")
    )


def _special(value) -> bool:
    return isinstance(value, str) and value.startswith("^") and value.endswith("$")


def _equal(expected, actual) -> bool:
    if isinstance(expected, str) and isinstance(actual, str):
        return expected.casefold() == actual.casefold()
    return expected == actual


def _fields(data: dict) -> dict:
    params = {
        item["name"]: item.get("value", "")
        for item in data.get("params", [])
        if "fileName" not in item
    }
    if params:
        return params
    text = data.get("text", "")
    mime = data.get("mimeType", "")
    if "application/x-www-form-urlencoded" in mime:
        return {
            key: values[0]
            for key, values in parse_qs(text, keep_blank_values=True).items()
        }
    if "application/json" in mime:
        value = json.loads(text or "null")
        return value if isinstance(value, dict) else {}
    if "multipart/form-data" not in mime or not text:
        return {}
    message = BytesParser(policy=policy.default).parsebytes(
        f"Content-Type: {mime}\r\nMIME-Version: 1.0\r\n\r\n{text}".encode()
    )
    fields = {}
    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition")
        payload = part.get_payload(decode=True)
        if name and part.get_filename() is None and isinstance(payload, bytes):
            fields[name] = payload.decode("utf-8", errors="replace")
    return fields
