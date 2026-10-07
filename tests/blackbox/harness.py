"""Utilitários comuns dos testes caixa-preta.

Nenhum teste importa módulos internos: todos invocam ``./app`` via
subprocesso, com stdin/stdout/stderr capturados.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = str(ROOT / "app")
FIXTURES = ROOT / "tests" / "fixtures"


def run(*args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    """Executa ``./app`` com os argumentos dados e captura tudo."""
    return subprocess.run(
        [APP, *args],
        input=stdin,
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        check=False,
    )


def json_out(proc: subprocess.CompletedProcess) -> dict:
    """Desserializa a única linha compacta de stdout."""
    assert proc.stdout.endswith("\n"), "stdout precisa terminar em \\n"
    body = proc.stdout.rstrip("\n")
    assert "\n" not in body, "modo --json deve emitir uma única linha"
    return json.loads(body)
