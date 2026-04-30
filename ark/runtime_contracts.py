"""Canonical runtime contract registry for ARK Python services.

Runtime constraints:
- Schema file load bounded to 128 KiB.
- Payload validation is O(F) in declared fields with local-only state.
- No hidden global mutable state beyond the immutable cached registry.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ark.security import validate_payload

_MAX_SCHEMA_BYTES = 131_072
_SUPPORTED_FIELD_TYPES = frozenset({"bool", "dict", "float", "int", "list", "null", "str"})
_SCHEMA_PATH = Path(__file__).resolve().parents[1] / "internal" / "contracts" / "runtime_schemas_v1.json"


@dataclass(frozen=True)
class ContractFailure:
    status: str
    error_code: str
    reason: str
    context: dict[str, Any]
    recoverable: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "error_code": self.error_code,
            "reason": self.reason,
            "context": self.context,
            "recoverable": self.recoverable,
        }


class ContractValidationError(ValueError):
    def __init__(self, error_code: str, reason: str, context: dict[str, Any], recoverable: bool = True):
        super().__init__(reason)
        self.failure = ContractFailure(
            status="error",
            error_code=error_code,
            reason=reason,
            context=context,
            recoverable=recoverable,
        )


@dataclass(frozen=True)
class ContractSpec:
    name: str
    required: tuple[str, ...]
    optional: tuple[str, ...]
    field_types: dict[str, tuple[str, ...]]
    allow_additional_fields: bool = False


@dataclass(frozen=True)
class RuntimeContractRegistry:
    version: str
    schema_path: str
    contracts: dict[str, ContractSpec]

    def materialize_payload(self, contract_name: str, values: dict[str, Any]) -> dict[str, Any]:
        spec = self.contracts.get(contract_name)
        if spec is None:
            raise ContractValidationError(
                "RUNTIME_CONTRACT_NOT_FOUND",
                f"unknown runtime contract: {contract_name}",
                {"contract_name": contract_name},
                recoverable=False,
            )
        if not isinstance(values, dict):
            raise ContractValidationError(
                "RUNTIME_CONTRACT_INVALID_PAYLOAD",
                f"payload for {contract_name} must be an object",
                {"contract_name": contract_name, "actual_type": type(values).__name__},
            )
        missing = [name for name in spec.required if name not in values]
        if missing:
            raise ContractValidationError(
                "RUNTIME_CONTRACT_MISSING_FIELD",
                f"missing required fields for {contract_name}: {', '.join(missing)}",
                {"contract_name": contract_name, "missing": missing},
            )
        allowed_fields = set(spec.required) | set(spec.optional)
        unexpected = sorted(set(values) - allowed_fields)
        if unexpected and not spec.allow_additional_fields:
            raise ContractValidationError(
                "RUNTIME_CONTRACT_UNEXPECTED_FIELD",
                f"unexpected fields for {contract_name}: {', '.join(unexpected)}",
                {"contract_name": contract_name, "unexpected": unexpected},
            )
        payload: dict[str, Any] = {}
        for field_name in spec.required + spec.optional:
            if field_name in values:
                field_value = values[field_name]
                field_types = spec.field_types.get(field_name, ())
                if field_types and not _matches_types(field_value, field_types):
                    raise ContractValidationError(
                        "RUNTIME_CONTRACT_INVALID_TYPE",
                        f"field {field_name!r} in {contract_name} has invalid type",
                        {
                            "contract_name": contract_name,
                            "field": field_name,
                            "allowed_types": list(field_types),
                            "actual_type": type(field_value).__name__,
                        },
                    )
                payload[field_name] = field_value
        if spec.allow_additional_fields:
            for field_name, field_value in values.items():
                if field_name not in payload:
                    payload[field_name] = field_value
        return validate_payload(payload)

    def health(self) -> dict[str, Any]:
        return {
            "name": "runtime_contract_registry",
            "ok": True,
            "version": self.version,
            "contracts": len(self.contracts),
            "schema_path": self.schema_path,
        }


def runtime_contract_registry() -> RuntimeContractRegistry:
    return _REGISTRY


def _load_registry(path: Path) -> RuntimeContractRegistry:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ContractValidationError(
            "RUNTIME_SCHEMA_LOAD_FAILED",
            f"failed to read runtime contract schema: {exc}",
            {"schema_path": str(path)},
            recoverable=False,
        ) from exc
    encoded = raw.encode("utf-8")
    if len(encoded) > _MAX_SCHEMA_BYTES:
        raise ContractValidationError(
            "RUNTIME_SCHEMA_TOO_LARGE",
            "runtime contract schema exceeds configured size budget",
            {"schema_path": str(path), "bytes": len(encoded), "max_bytes": _MAX_SCHEMA_BYTES},
            recoverable=False,
        )
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ContractValidationError(
            "RUNTIME_SCHEMA_INVALID_JSON",
            f"invalid runtime contract schema json: {exc}",
            {"schema_path": str(path)},
            recoverable=False,
        ) from exc
    version = document.get("version")
    contracts_doc = document.get("contracts")
    if not isinstance(version, str) or not isinstance(contracts_doc, dict):
        raise ContractValidationError(
            "RUNTIME_SCHEMA_INVALID_ROOT",
            "runtime contract schema root is invalid",
            {"schema_path": str(path)},
            recoverable=False,
        )
    contracts: dict[str, ContractSpec] = {}
    for name, spec_doc in contracts_doc.items():
        contracts[name] = _parse_contract_spec(name, spec_doc)
    return RuntimeContractRegistry(version=version, schema_path=str(path), contracts=contracts)


def _parse_contract_spec(name: str, spec_doc: Any) -> ContractSpec:
    if not isinstance(spec_doc, dict):
        raise ContractValidationError(
            "RUNTIME_SCHEMA_INVALID_CONTRACT",
            f"contract {name} must be an object",
            {"contract_name": name},
            recoverable=False,
        )
    required = _parse_string_list(name, spec_doc.get("required", []), "required")
    optional = _parse_string_list(name, spec_doc.get("optional", []), "optional")
    field_types_doc = spec_doc.get("field_types", {})
    if not isinstance(field_types_doc, dict):
        raise ContractValidationError(
            "RUNTIME_SCHEMA_INVALID_TYPES",
            f"contract {name} field_types must be an object",
            {"contract_name": name},
            recoverable=False,
        )
    field_types: dict[str, tuple[str, ...]] = {}
    for field_name, type_names_doc in field_types_doc.items():
        type_names = _parse_string_list(name, type_names_doc, f"field_types.{field_name}")
        invalid_types = [type_name for type_name in type_names if type_name not in _SUPPORTED_FIELD_TYPES]
        if invalid_types:
            raise ContractValidationError(
                "RUNTIME_SCHEMA_UNSUPPORTED_TYPE",
                f"contract {name} field {field_name} declares unsupported types",
                {"contract_name": name, "field": field_name, "invalid_types": invalid_types},
                recoverable=False,
            )
        field_types[field_name] = tuple(type_names)
    declared_fields = set(required) | set(optional)
    allow_additional_fields = bool(spec_doc.get("allow_additional_fields", False))
    if declared_fields != set(field_types):
        if not allow_additional_fields or declared_fields:
            raise ContractValidationError(
                "RUNTIME_SCHEMA_FIELD_MISMATCH",
                f"contract {name} required/optional fields must match field_types keys",
                {
                    "contract_name": name,
                    "declared_fields": sorted(declared_fields),
                    "typed_fields": sorted(field_types),
                },
                recoverable=False,
            )
    return ContractSpec(
        name=name,
        required=tuple(required),
        optional=tuple(optional),
        field_types=field_types,
        allow_additional_fields=allow_additional_fields,
    )


def _parse_string_list(contract_name: str, value: Any, field_name: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ContractValidationError(
            "RUNTIME_SCHEMA_INVALID_LIST",
            f"contract {contract_name} field {field_name} must be a string list",
            {"contract_name": contract_name, "field": field_name},
            recoverable=False,
        )
    return value


def _matches_types(value: Any, allowed_types: tuple[str, ...]) -> bool:
    return any(_matches_type(value, type_name) for type_name in allowed_types)


def _matches_type(value: Any, type_name: str) -> bool:
    if type_name == "null":
        return value is None
    if type_name == "bool":
        return isinstance(value, bool)
    if type_name == "dict":
        return isinstance(value, dict)
    if type_name == "list":
        return isinstance(value, list)
    if type_name == "str":
        return isinstance(value, str)
    if type_name == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    if type_name == "float":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return False


_REGISTRY = _load_registry(_SCHEMA_PATH)
