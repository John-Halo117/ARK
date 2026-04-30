"""Linux Forge launcher asset checks."""

from __future__ import annotations

from pathlib import Path
import subprocess


def test_linux_desktop_assets_exist(project_root: Path) -> None:
    repo_root = project_root.parent

    expected = [
        repo_root / "forge-app",
        repo_root / "Forge App.sh",
        repo_root / "install-forge-arch.sh",
        repo_root / "packaging" / "linux" / "forge-app.desktop.in",
        repo_root / "packaging" / "linux" / "forge-app.svg",
    ]

    for path in expected:
        assert path.is_file(), f"missing Linux Forge asset: {path.name}"

    desktop_template = (
        repo_root / "packaging" / "linux" / "forge-app.desktop.in"
    ).read_text(encoding="utf-8")
    installer = (repo_root / "install-forge-arch.sh").read_text(encoding="utf-8")

    assert "Exec=__BIN__/forge-app" in desktop_template
    assert "No systemd service was created." in installer


def test_linux_shell_scripts_parse(project_root: Path) -> None:
    repo_root = project_root.parent

    for rel in ["forge-app", "Forge App.sh", "install-forge-arch.sh"]:
        result = subprocess.run(
            ["bash", "-n", str(repo_root / rel)],
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
