#!/usr/bin/env python3
"""Small offline JSON Schema validator for the keywords used by P0 schemas."""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


class OfflineSchemaValidator:
    def __init__(self, schema_root: Path):
        self.schema_root = schema_root.resolve()
        self.cache: dict[Path, dict[str, Any]] = {}

    def load(self, path: Path) -> dict[str, Any]:
        path = path.resolve()
        if path not in self.cache:
            self.cache[path] = json.loads(path.read_text(encoding="utf-8"))
        return self.cache[path]

    def resolve_ref(self, ref: str, current: Path) -> tuple[dict[str, Any], Path]:
        file_part, _, fragment = ref.partition("#")
        target_path = (current.parent / file_part).resolve() if file_part else current.resolve()
        if self.schema_root not in target_path.parents and target_path != self.schema_root:
            raise ValueError(f"schema reference escapes root: {ref}")
        target: Any = self.load(target_path)
        if fragment:
            for token in fragment.lstrip("/").split("/"):
                target = target[token.replace("~1", "/").replace("~0", "~")]
        return target, target_path

    def validate(self, value: Any, schema_path: Path) -> list[str]:
        errors: list[str] = []
        self._walk(value, self.load(schema_path), schema_path.resolve(), "$", errors)
        return errors

    @staticmethod
    def _type_ok(value: Any, expected: str) -> bool:
        return {
            "null": value is None, "object": isinstance(value, dict), "array": isinstance(value, list),
            "string": isinstance(value, str), "boolean": isinstance(value, bool),
            "integer": isinstance(value, int) and not isinstance(value, bool),
            "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        }.get(expected, True)

    def _walk(self, value: Any, schema: dict[str, Any], current: Path, loc: str, errors: list[str]) -> None:
        if "$ref" in schema:
            target, target_path = self.resolve_ref(schema["$ref"], current)
            self._walk(value, target, target_path, loc, errors)
            return
        if "oneOf" in schema:
            matches = 0
            for option in schema["oneOf"]:
                option_errors: list[str] = []
                self._walk(value, option, current, loc, option_errors)
                if not option_errors:
                    matches += 1
            if matches != 1:
                errors.append(f"{loc}: expected exactly one oneOf schema match, got {matches}")
        if "anyOf" in schema:
            matches = 0
            for option in schema["anyOf"]:
                option_errors: list[str] = []
                self._walk(value, option, current, loc, option_errors)
                if not option_errors:
                    matches += 1
            if not matches:
                errors.append(f"{loc}: expected at least one anyOf schema match")
        if "not" in schema:
            forbidden_errors: list[str] = []
            self._walk(value, schema["not"], current, loc, forbidden_errors)
            if not forbidden_errors:
                errors.append(f"{loc}: value matches forbidden schema")
        for part in schema.get("allOf", []):
            self._walk(value, part, current, loc, errors)
        if "if" in schema:
            probe: list[str] = []
            self._walk(value, schema["if"], current, loc, probe)
            if not probe and "then" in schema:
                self._walk(value, schema["then"], current, loc, errors)
            elif probe and "else" in schema:
                self._walk(value, schema["else"], current, loc, errors)
        if "const" in schema and value != schema["const"]:
            errors.append(f"{loc}: expected constant {schema['const']!r}")
        if "enum" in schema and value not in schema["enum"]:
            errors.append(f"{loc}: value {value!r} not in enum")
        expected = schema.get("type")
        if expected:
            choices = expected if isinstance(expected, list) else [expected]
            if not any(self._type_ok(value, choice) for choice in choices):
                errors.append(f"{loc}: expected type {choices}, got {type(value).__name__}")
                return
        if isinstance(value, str):
            if len(value) < schema.get("minLength", 0):
                errors.append(f"{loc}: string shorter than minLength")
            if schema.get("pattern") and not re.search(schema["pattern"], value):
                errors.append(f"{loc}: string does not match pattern")
            fmt = schema.get("format")
            try:
                if fmt == "date": date.fromisoformat(value)
                elif fmt == "date-time": datetime.fromisoformat(value.replace("Z", "+00:00"))
                elif fmt == "uri" and not urlparse(value).scheme: raise ValueError
            except ValueError:
                errors.append(f"{loc}: invalid {fmt}")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if "minimum" in schema and value < schema["minimum"]: errors.append(f"{loc}: below minimum")
            if "maximum" in schema and value > schema["maximum"]: errors.append(f"{loc}: above maximum")
        if isinstance(value, list):
            if len(value) < schema.get("minItems", 0): errors.append(f"{loc}: fewer than minItems")
            if schema.get("uniqueItems"):
                serial = [json.dumps(item, ensure_ascii=False, sort_keys=True) for item in value]
                if len(serial) != len(set(serial)): errors.append(f"{loc}: duplicate array items")
            if isinstance(schema.get("items"), dict):
                for index, item in enumerate(value): self._walk(item, schema["items"], current, f"{loc}[{index}]", errors)
            if isinstance(schema.get("contains"), dict):
                if not any(not (item_errors := self._validation_errors(item, schema["contains"], current, f"{loc}[{index}]")) for index, item in enumerate(value)):
                    errors.append(f"{loc}: array has no item matching contains schema")
        if isinstance(value, dict):
            if isinstance(schema.get("propertyNames"), dict):
                for key in value:
                    self._walk(key, schema["propertyNames"], current, f"{loc}.<property:{key}>", errors)
            for required in schema.get("required", []):
                if required not in value: errors.append(f"{loc}: missing required property {required}")
            properties = schema.get("properties", {})
            for key, item in value.items():
                if key in properties:
                    self._walk(item, properties[key], current, f"{loc}.{key}", errors)
                elif schema.get("additionalProperties") is False:
                    errors.append(f"{loc}: unexpected property {key}")
                elif isinstance(schema.get("additionalProperties"), dict):
                    self._walk(item, schema["additionalProperties"], current, f"{loc}.{key}", errors)

    def _validation_errors(self, value: Any, schema: dict[str, Any], current: Path, loc: str) -> list[str]:
        errors: list[str] = []
        self._walk(value, schema, current, loc, errors)
        return errors
