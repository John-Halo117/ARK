"""Safe-mode codegen specification pipeline.

What: produces static plugin specs and validation results, but never shells out.
Why: missing tools can be proposed and tested in a sandbox before registration.
Where: optional tool system support outside SD-ARK core execution.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

MAX_SPEC_BYTES = 8192
MAX_PLUGIN_FILES = 8


@dataclass(frozen=True)
class PluginSpec:
    name: str
    capability: str
    files: dict[str, str] = field(default_factory=dict)

    def digest(self) -> str:
        payload = json.dumps(self.__dict__, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def generate_spec(name: str, capability: str, contract: dict[str, Any]) -> PluginSpec:
    raw = json.dumps(contract, sort_keys=True, default=str)
    if len(raw.encode("utf-8")) > MAX_SPEC_BYTES:
        raise ValueError(f"contract exceeds bound: {MAX_SPEC_BYTES}")
    safe_name = _safe_token(name)
    safe_capability = _safe_token(capability.replace(".", "_"))
    manifest = json.dumps({"name": safe_name, "capability": capability, "contract": contract}, sort_keys=True, indent=2)
    return PluginSpec(safe_name, capability, {f"{safe_capability}.plugin.json": manifest})


def validate_spec(spec: PluginSpec) -> dict[str, Any]:
    if not spec.name or not spec.capability:
        return _failure("PLUGIN_SPEC_INVALID", "plugin spec requires name and capability")
    if len(spec.files) > MAX_PLUGIN_FILES:
        return _failure("PLUGIN_SPEC_TOO_LARGE", "plugin spec has too many files")
    for path, content in spec.files.items():
        if "/" in path or "\\" in path or len(content.encode("utf-8")) > MAX_SPEC_BYTES:
            return _failure("PLUGIN_FILE_INVALID", "plugin files must be local bounded manifests")
    return {"status": "ok", "digest": spec.digest()}


def sandbox_run(spec: PluginSpec) -> dict[str, Any]:
    validation = validate_spec(spec)
    if validation["status"] != "ok":
        return validation
    return {"status": "ok", "registered": False, "digest": validation["digest"]}


def _safe_token(value: str) -> str:
    cleaned = "".join(ch for ch in value.lower()[:64] if ch.isalnum() or ch in {"-", "_"})
    return cleaned or "plugin"


def _failure(error_code: str, reason: str) -> dict[str, Any]:
    return {"status": "error", "error_code": error_code, "reason": reason, "context": {}, "recoverable": True}
