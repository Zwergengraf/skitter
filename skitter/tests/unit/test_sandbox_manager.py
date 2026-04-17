from __future__ import annotations

from skitter.tools.sandbox_manager import _docker_dns_label


def test_docker_dns_label_keeps_short_names_readable() -> None:
    assert _docker_dns_label("skitter-sandbox-user-1-default") == "skitter-sandbox-user-1-default"


def test_docker_dns_label_normalizes_dns_unsafe_characters() -> None:
    assert _docker_dns_label("Skitter_Sandbox/User 1/Profile") == "skitter-sandbox-user-1-profile"
    assert _docker_dns_label("Skitter-Über-Profil") == "skitter-ber-profil"


def test_docker_dns_label_truncates_long_names_with_stable_hash_suffix() -> None:
    raw = "skitter-sandbox-559027e9-27aa-4cc0-9738-716c469cc6d0-" + "profile-" * 20
    label = _docker_dns_label(raw)

    assert len(label) <= 63
    assert label == _docker_dns_label(raw)
    assert label.startswith("skitter-sandbox-")
    assert label.rsplit("-", 1)[-1].isalnum()
