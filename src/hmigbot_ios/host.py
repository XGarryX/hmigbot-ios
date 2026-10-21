"""Read-only host and provider capability negotiation.

Migration stages consume this profile instead of branching on the operating
system. Discovery never runs a build, connects to a device, or mutates a
project. Runtime and device capabilities remain unverified until a provider
records real evidence.
"""
from __future__ import annotations

import os
import platform as _platform
import shutil
import sys
from typing import Callable, Mapping

SCHEMA_VERSION = 1
AVAILABLE = "available"
PARTIAL = "partial"
UNAVAILABLE = "unavailable"
UNVERIFIED = "unverified"


def normalize_host_os(value: str | None) -> str:
    value = (value or "").strip().lower()
    if value in {"darwin", "macos", "mac", "osx"}:
        return "macos"
    if value in {"windows", "win32", "win"}:
        return "windows"
    if value in {"linux", "linux2"}:
        return "linux"
    return value or "unknown"


def _tool(name: str, *, aliases: tuple[str, ...] = (), lookup: Callable[[str], str | None] | None = None) -> dict:
    lookup = lookup or shutil.which
    for candidate in (name,) + aliases:
        path = lookup(candidate)
        if path:
            return {"status": AVAILABLE, "command": candidate, "path": path}
    return {"status": UNAVAILABLE, "command": name, "path": None}


def detect_host_profile(*, host_os: str | None = None, machine: str | None = None,
                        lookup: Callable[[str], str | None] | None = None,
                        environ: Mapping[str, str] | None = None) -> dict:
    """Detect the host and select source/target providers without mutation."""
    env = dict(os.environ if environ is None else environ)
    os_name = normalize_host_os(host_os or _platform.system())
    xcodebuild = _tool("xcodebuild", lookup=lookup)
    xcrun = _tool("xcrun", lookup=lookup)
    swift = _tool("swift", lookup=lookup)
    native_xcode = os_name == "macos" and xcodebuild["status"] == AVAILABLE and xcrun["status"] == AVAILABLE

    if native_xcode:
        source_provider, source_mode = "macos_xcode", "native"
        membership, compiler, ios_build, ios_runtime = AVAILABLE, AVAILABLE, AVAILABLE, UNVERIFIED
    elif os_name == "windows":
        source_provider, source_mode = "windows_static", "static"
        membership, compiler, ios_build, ios_runtime = PARTIAL, UNAVAILABLE, UNAVAILABLE, UNAVAILABLE
    elif os_name == "macos":
        source_provider, source_mode = "macos_static_fallback", "static_fallback"
        membership, compiler, ios_build, ios_runtime = PARTIAL, UNAVAILABLE, UNAVAILABLE, UNAVAILABLE
    else:
        source_provider, source_mode = "portable_static", "static"
        membership, compiler, ios_build, ios_runtime = PARTIAL, UNAVAILABLE, UNAVAILABLE, UNAVAILABLE

    hvigor = _tool("hvigorw", aliases=("hvigorw.bat",), lookup=lookup)
    node = _tool("node", lookup=lookup)
    ohpm = _tool("ohpm", lookup=lookup)
    hdc = _tool("hdc", lookup=lookup)
    harmony_build = AVAILABLE if hvigor["status"] == AVAILABLE and node["status"] == AVAILABLE else UNAVAILABLE
    cloud_allowed = env.get("HMIGBOT_ALLOW_CLOUD_PROVIDER", "1").lower() not in {"0", "false", "no"}

    return {
        "schema_version": SCHEMA_VERSION,
        "host": {"os": os_name, "arch": machine or _platform.machine(), "python": sys.version.split()[0]},
        "source": {"platform": "ios", "provider": source_provider, "mode": source_mode},
        "target": {"platform": "harmonyos", "provider": "local_harmony", "mode": "local"},
        "tools": {"xcodebuild": xcodebuild, "xcrun": xcrun, "swift": swift,
                  "hvigorw": hvigor, "node": node, "ohpm": ohpm, "hdc": hdc},
        "capabilities": {
            "ios.static_analysis": AVAILABLE,
            "ios.xcode_project_membership": membership,
            "ios.swift_compiler_context": compiler,
            "ios.build": ios_build,
            "ios.runtime": ios_runtime,
            "harmony.build": harmony_build,
            "harmony.runtime": UNVERIFIED,
            "harmony.device": UNVERIFIED if hdc["status"] == AVAILABLE else UNAVAILABLE,
            "cloud.macos_build": UNVERIFIED if cloud_allowed else UNAVAILABLE,
        },
        "selection": {
            "source_reason": ("macOS with xcodebuild and xcrun" if native_xcode else
                              "Windows static source provider" if os_name == "windows" else
                              "Apple tools unavailable; static fallback"),
            "cloud_provider_allowed": cloud_allowed,
            "evidence_policy": "availability is discovery only; execution requires provider evidence",
        },
    }


def provider_for(profile: Mapping, capability: str) -> str:
    source = profile.get("source") if isinstance(profile, Mapping) else None
    target = profile.get("target") if isinstance(profile, Mapping) else None
    if capability.startswith("ios."):
        return str(source.get("provider")) if isinstance(source, Mapping) else "unavailable"
    if capability.startswith("harmony."):
        return str(target.get("provider")) if isinstance(target, Mapping) else "unavailable"
    if capability.startswith("cloud."):
        return "cloud_macos"
    return "unavailable"


def validate_profile(profile: Mapping) -> None:
    if not isinstance(profile, Mapping) or profile.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Unsupported host profile schema")
    for section in ("host", "source", "target", "capabilities", "selection"):
        if not isinstance(profile.get(section), Mapping):
            raise ValueError("Host profile missing " + section)
    if profile["source"].get("platform") != "ios":
        raise ValueError("Host profile source platform must be ios")
    if profile["target"].get("platform") != "harmonyos":
        raise ValueError("Host profile target platform must be harmonyos")
    allowed = {AVAILABLE, PARTIAL, UNAVAILABLE, UNVERIFIED}
    if any(value not in allowed for value in profile["capabilities"].values()):
        raise ValueError("Invalid host capability status")
