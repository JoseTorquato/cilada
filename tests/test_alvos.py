"""Testes do alvo compatível com OpenAI, contra um servidor falso local.

Nada aqui sai da máquina: o servidor é um httpx.MockTransport que responde como
/chat/completions. Regra do projeto: o Cilada não roda contra modelo pago ou em
nuvem nos testes.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cilada.targets import AlvoOpenAI, de_config  # noqa: E402

EXEMPLOS = Path(__file__).resolve().parent.parent / "examples"


class ServidorFalso:
    """Imita /v1/chat/completions e guarda o que recebeu."""

    def __init__(self, exige_chave: str | None = None) -> None:
        self.exige_chave = exige_chave
        self.pedidos: list[httpx.Request] = []

    def __call__(self, pedido: httpx.Request) -> httpx.Response:
        self.pedidos.append(pedido)
        if not pedido.url.path.endswith("/chat/completions"):
            return httpx.Response(404)
        if self.exige_chave and pedido.headers.get("authorization") != f"Bearer {self.exige_chave}":
            return httpx.Response(401, json={"error": "sem chave"})
        corpo = json.loads(pedido.content)
        ultimo = corpo["messages"][-1]["content"]
        return httpx.Response(200, json={"choices": [{"message": {"content": f"eco: {ultimo}"}}]})

    @property
    def transporte(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)


def _alvo(cfg: dict, servidor: ServidorFalso) -> AlvoOpenAI:
    alvo = de_config({"tipo": "openai", "modelo": "falso", "base_url": "http://local.test/v1", **cfg})
    alvo.transporte = servidor.transporte
    return alvo


def test_sem_chave_conversa_sem_cabecalho_de_autorizacao(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    servidor = ServidorFalso()
    alvo = _alvo({"sem_chave": True, "system": "s"}, servidor)
    assert alvo.conversa(["oi", "tudo bem?"]) == ["eco: oi", "eco: tudo bem?"]
    assert all("authorization" not in p.headers for p in servidor.pedidos)
    # o histórico vai inteiro a cada turno, como numa conversa de verdade
    assert len(json.loads(servidor.pedidos[1].content)["messages"]) == 4


def test_com_chave_usa_a_variavel_de_ambiente(monkeypatch):
    monkeypatch.setenv("CHAVE_DE_TESTE", "segredo-falso")
    servidor = ServidorFalso(exige_chave="segredo-falso")
    alvo = _alvo({"api_key_env": "CHAVE_DE_TESTE"}, servidor)
    assert alvo.conversa(["oi"]) == ["eco: oi"]


def test_variavel_vazia_continua_erro_claro(monkeypatch):
    monkeypatch.delenv("CHAVE_DE_TESTE", raising=False)
    alvo = _alvo({"api_key_env": "CHAVE_DE_TESTE"}, ServidorFalso())
    with pytest.raises(RuntimeError, match="sem_chave: true"):
        alvo.conversa(["oi"])


def test_sem_api_key_env_mantem_o_padrao_openai(monkeypatch):
    """Compatibilidade: config antiga sem api_key_env continua exigindo OPENAI_API_KEY."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    alvo = _alvo({}, ServidorFalso())
    assert alvo.api_key_env == "OPENAI_API_KEY"
    with pytest.raises(RuntimeError):
        alvo.conversa(["oi"])


@pytest.mark.parametrize("campo", ["api_key", "chave", "token", "Authorization", "senha"])
def test_chave_literal_na_config_e_recusada(campo):
    with pytest.raises(ValueError, match="nunca vai no YAML"):
        de_config({"tipo": "openai", "modelo": "m", campo: "sk-qualquer"})


def test_chave_colada_em_api_key_env_e_recusada():
    """Erro comum: colar a chave no lugar do nome da variável."""
    with pytest.raises(ValueError, match="NOME de uma variável"):
        de_config({"tipo": "openai", "modelo": "m", "api_key_env": "sk-proj-abc123-xyz"})


def test_sem_chave_e_api_key_env_juntos_e_recusado():
    with pytest.raises(ValueError, match="não os dois"):
        de_config({"tipo": "openai", "modelo": "m", "sem_chave": True, "api_key_env": "X"})


def test_sem_chave_precisa_ser_booleano():
    with pytest.raises(ValueError, match="true ou false"):
        de_config({"tipo": "openai", "modelo": "m", "sem_chave": "sim"})


@pytest.mark.parametrize("arquivo,sem_chave", [
    ("alvo-ollama-local.yaml", True),
    ("alvo-api-nuvem.yaml", False),
])
def test_exemplos_de_config_carregam_sem_chave_literal(arquivo, sem_chave):
    texto = (EXEMPLOS / arquivo).read_text(encoding="utf-8")
    alvo = de_config(yaml.safe_load(texto)["alvo"])
    assert (alvo.api_key_env is None) is sem_chave
    assert "sk-" not in texto and "Bearer" not in texto
