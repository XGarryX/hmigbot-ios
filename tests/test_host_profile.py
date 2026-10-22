"""Host capability negotiation: source provider selection and profile validation.

The host profile must route macOS + Xcode to a native source provider and every
other platform to a static fallback, without ever running a build or touching a
device. Validation must reject malformed or mistyped profiles.
"""
from __future__ import annotations

import pytest

from hmigbot_ios.host import (
    detect_host_profile,
    normalize_host_os,
    provider_for,
    validate_profile,
)


def _no_tools(_name: str) -> str | None:
    return None


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Darwin", "macos"),
        ("darwin", "macos"),
        ("mac", "macos"),
        ("Windows", "windows"),
        ("win32", "windows"),
        ("Linux", "linux"),
        (None, "unknown"),
        ("", "unknown"),
    ],
)
def test_normalize_host_os(raw, expected):
    assert normalize_host_os(raw) == expected


def test_native_xcode_on_macos_selects_native_provider():
    tools = {"xcodebuild": "/usr/bin/xcodebuild", "xcrun": "/usr/bin/xcrun", "swift": "/usr/bin/swift"}

    def lookup(name: str) -> str | None:
        return tools.get(name)

    profile = detect_host_profile(host_os="Darwin", machine="arm64", lookup=lookup, environ={})
    assert profile["host"]["os"] == "macos"
    assert profile["source"]["provider"] == "macos_xcode"
    assert profile["source"]["mode"] == "native"
    assert profile["capabilities"]["ios.xcode_project_membership"] == "available"
    assert profile["capabilities"]["ios.swift_compiler_context"] == "available"


def test_windows_uses_static_provider():
    profile = detect_host_profile(host_os="Windows", machine="AMD64", lookup=_no_tools, environ={})
    assert profile["source"]["provider"] == "windows_static"
    assert profile["source"]["mode"] == "static"
    assert profile["capabilities"]["ios.swift_compiler_context"] == "unavailable"
    assert profile["capabilities"]["ios.xcode_project_membership"] == "partial"


def test_macos_without_xcode_falls_back_to_static():
    profile = detect_host_profile(host_os="Darwin", machine="arm64", lookup=_no_tools, environ={})
    assert profile["source"]["provider"] == "macos_static_fallback"
    assert profile["source"]["mode"] == "static_fallback"


def test_linux_is_portable_static():
    profile = detect_host_profile(host_os="Linux", machine="x86_64", lookup=_no_tools, environ={})
    assert profile["source"]["provider"] == "portable_static"


def test_cloud_disabled_when_env_forbids():
    profile = detect_host_profile(host_os="Darwin", machine="arm64", lookup=_no_tools,
                                  environ={"HMIGBOT_ALLOW_CLOUD_PROVIDER": "0"})
    assert profile["capabilities"]["cloud.macos_build"] == "unavailable"


def test_provider_for_maps_capabilities():
    profile = detect_host_profile(host_os="Windows", machine="AMD64", lookup=_no_tools, environ={})
    assert provider_for(profile, "ios.build") == "windows_static"
    assert provider_for(profile, "harmony.build") == "local_harmony"
    assert provider_for(profile, "cloud.macos_build") == "cloud_macos"
    assert provider_for(profile, "unknown.thing") == "unavailable"


def test_validate_profile_accepts_valid_and_rejects_invalid():
    profile = detect_host_profile(host_os="Darwin", machine="arm64", lookup=_no_tools, environ={})
    validate_profile(profile)  # must not raise

    broken = dict(profile)
    broken["source"] = {"platform": "android", "provider": "windows_static", "mode": "static"}
    with pytest.raises(ValueError):
        validate_profile(broken)

    bad_caps = dict(profile)
    bad_caps["capabilities"] = {**profile["capabilities"], "ios.build": "maybe"}
    with pytest.raises(ValueError):
        validate_profile(bad_caps)

    with pytest.raises(ValueError):
        validate_profile({"schema_version": 999})