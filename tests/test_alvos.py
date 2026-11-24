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
    with pytest.raises(ValueError, match="não parece nome de variável") as erro:
        de_config({"tipo": "openai", "modelo": "m", "api_key_env": "sk-proj-abc123-xyz"})
    assert "sk-proj" not in str(erro.value)


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


# ---- vazamento de chave (revisão do PR #1) ---------------------------------
#
# Chave com cara de identificador (gsk_…, AIza…, hf_…, AKIA…) passava como
# "nome de variável" e era ecoada no erro, que ia para o terminal e o laudo.

CHAVES_FALSAS = [
    "gsk_FAKEFAKEfake1234567890abcdefXYZ",
    "AIzaSyFAKEFAKE_fake-1234567890abc",
    "hf_FAKEfakeFAKEfake123456",
    "xai_FAKEfake123456789",
    "AKIAFAKEFAKE12345678",
    "ABCDEF0123456789ABCDEF0123456789",
]


@pytest.mark.parametrize("chave", CHAVES_FALSAS)
def test_chave_com_cara_de_nome_e_recusada_sem_eco(chave):
    with pytest.raises(ValueError) as erro:
        de_config({"tipo": "openai", "modelo": "m", "api_key_env": chave})
    assert chave not in str(erro.value)


@pytest.mark.parametrize("nome", ["OPENAI_API_KEY", "GROQ_API_KEY", "HF_TOKEN", "MINHA_CHAVE_2"])
def test_nomes_legitimos_continuam_aceitos(nome):
    assert de_config({"tipo": "openai", "modelo": "m", "api_key_env": nome}).api_key_env == nome


def test_repr_do_alvo_nao_mostra_api_key_env():
    alvo = de_config({"tipo": "openai", "modelo": "m", "api_key_env": "MINHA_CHAVE_SECRETA"})
    assert "MINHA_CHAVE_SECRETA" not in repr(alvo)


def test_variavel_ausente_nao_e_ecoada_no_erro(monkeypatch):
    monkeypatch.delenv("NOME_QUE_NAO_DEVE_APARECER", raising=False)
    alvo = de_config({"tipo": "openai", "modelo": "m", "api_key_env": "NOME_QUE_NAO_DEVE_APARECER"})
    with pytest.raises(RuntimeError) as erro:
        alvo.conversa(["oi"])
    assert "NOME_QUE_NAO_DEVE_APARECER" not in str(erro.value)


@pytest.mark.parametrize("campo", ["apikey", "api-key", "openai_api_key", "secret", "bearer",
                                   "segredo", "temperatura_secreta", "url"])
def test_campo_desconhecido_no_alvo_openai_e_recusado(campo):
    with pytest.raises(ValueError, match="não aceita") as erro:
        de_config({"tipo": "openai", "modelo": "m", "sem_chave": True, campo: "VALOR-SECRETO-123"})
    assert "VALOR-SECRETO-123" not in str(erro.value)


def test_campo_desconhecido_no_alvo_http_e_recusado():
    with pytest.raises(ValueError, match="não aceita"):
        de_config({"tipo": "http", "url": "http://127.0.0.1/c", "api_key": "VALOR-SECRETO-123"})


@pytest.mark.parametrize("headers,aceito", [
    ({"Authorization": "Bearer ${MINHA_CHAVE}"}, True),
    ({"X-Api-Key": "${MINHA_CHAVE}"}, True),
    ({"Content-Type": "application/json"}, True),
    ({"Authorization": "Bearer sk-literal-123"}, False),
    ({"X-Api-Key": "literal123"}, False),
    ({"Cookie": "sessao=abc"}, False),
])
def test_header_com_credencial_precisa_vir_de_variavel(headers, aceito):
    cfg = {"tipo": "http", "url": "http://127.0.0.1/c", "headers": headers}
    if aceito:
        de_config(cfg)
    else:
        with pytest.raises(ValueError) as erro:
            de_config(cfg)
        assert not any(v in str(erro.value) for v in headers.values())


def test_sem_chave_remoto_so_avisa(capsys):
    alvo = de_config({"tipo": "openai", "modelo": "m", "sem_chave": True,
                      "base_url": "https://api.exemplo.invalid/v1"})
    assert alvo.api_key_env is None
    assert "aviso" in capsys.readouterr().err


@pytest.mark.parametrize("chave", CHAVES_FALSAS)
def test_chave_falsa_nao_aparece_em_saida_nenhuma(tmp_path, capsys, chave):
    """Ponta a ponta: config com a chave no lugar do nome, pela CLI.

    Procura a chave no stdout, no stderr, no JSON e no HTML: zero ocorrências.
    Nada chega a conectar — a config é recusada antes.
    """
    from cilada import cli

    cfg = tmp_path / "alvo.yaml"
    cfg.write_text(yaml.safe_dump({"alvo": {"tipo": "openai", "modelo": "m",
                                            "base_url": "http://127.0.0.1:9/v1",
                                            "api_key_env": chave}}), encoding="utf-8")
    js, ht = tmp_path / "r.json", tmp_path / "r.html"
    codigo = cli.main(["run", "--config", str(cfg), "--json", str(js), "--html", str(ht),
                       "--suite", "ecommerce"])
    saida = capsys.readouterr()
    assert codigo == 2
    textos = [saida.out, saida.err] + [p.read_text(encoding="utf-8") for p in (js, ht) if p.exists()]
    assert sum(t.count(chave) for t in textos) == 0
