"""Adapters de alvo: como o Cilada conversa com o agente sob teste."""

from __future__ import annotations

import json
import os
import random
import re
import time
from dataclasses import dataclass, field
from typing import Protocol

import httpx

TENTATIVAS = 5


def _post_com_retry(cliente: httpx.Client, url: str, **kw) -> httpx.Response:
    """POST que aguenta 429 e 5xx — endpoint de cliente sempre limita taxa.

    Respeita o Retry-After quando vem; senão, backoff exponencial com jitter.
    Sem isso, uma rajada de 429 vira "13 ataques não executados" e o laudo
    fica com buraco no meio.
    """
    for tentativa in range(TENTATIVAS):
        resposta = cliente.post(url, **kw)
        if resposta.status_code < 400 or resposta.status_code not in (429, 500, 502, 503, 504):
            resposta.raise_for_status()
            return resposta
        if tentativa == TENTATIVAS - 1:
            resposta.raise_for_status()
        cabecalho = resposta.headers.get("retry-after")
        espera = float(cabecalho) if cabecalho and cabecalho.replace(".", "", 1).isdigit() else 0
        time.sleep(max(espera, 2**tentativa) + random.uniform(0, 0.5))
    raise RuntimeError("inalcançável")


class Alvo(Protocol):
    nome: str

    def conversa(self, turnos: list[str]) -> list[str]:
        """Envia os turnos em sequência e devolve as respostas do agente."""


def _resolve_env(valor: str) -> str:
    """Expande ${VAR} para não deixar credencial escrita em arquivo de config."""
    return re.sub(r"\$\{(\w+)\}", lambda m: os.environ.get(m.group(1), ""), valor)


def _busca_caminho(dados: object, caminho: str) -> str:
    """Extrai um valor de JSON aninhado via caminho tipo 'choices.0.message.content'."""
    atual = dados
    for parte in caminho.split("."):
        if isinstance(atual, list):
            atual = atual[int(parte)]
        elif isinstance(atual, dict):
            atual = atual.get(parte)
        else:
            return ""
        if atual is None:
            return ""
    return atual if isinstance(atual, str) else json.dumps(atual, ensure_ascii=False)


@dataclass
class AlvoHTTP:
    """Endpoint HTTP genérico que recebe uma mensagem e devolve texto.

    O corpo é um template JSON onde {mensagem} e {sessao} são substituídos.
    """

    url: str
    nome: str = "http"
    corpo: dict | None = None
    campo_resposta: str = "resposta"
    headers: dict[str, str] | None = None
    timeout: float = 60.0

    def conversa(self, turnos: list[str]) -> list[str]:
        respostas: list[str] = []
        sessao = f"cilada-{abs(hash(tuple(turnos))) % 10**8}"
        headers = {k: _resolve_env(v) for k, v in (self.headers or {}).items()}
        with httpx.Client(timeout=self.timeout) as cliente:
            for turno in turnos:
                molde = json.dumps(self.corpo or {"mensagem": "{mensagem}", "sessao": "{sessao}"})
                corpo = json.loads(
                    molde.replace("{mensagem}", json.dumps(turno)[1:-1]).replace("{sessao}", sessao)
                )
                r = _post_com_retry(cliente, self.url, json=corpo, headers=headers)
                respostas.append(_busca_caminho(r.json(), self.campo_resposta))
        return respostas


@dataclass
class AlvoOpenAI:
    """Qualquer API compatível com /chat/completions (OpenAI, Groq, Together, Ollama...).

    Serve para testar modelo + system prompt isoladamente — é o que alimenta a arena
    pública, já que o alvo é uma configuração nossa, não o bot de terceiro.
    """

    modelo: str
    system: str
    base_url: str = "https://api.openai.com/v1"
    api_key_env: str | None = "OPENAI_API_KEY"
    """Nome da variável de ambiente com a chave. None = o alvo não exige chave
    (Ollama local, servidor de teste). A chave em si nunca vem da config."""
    nome: str = ""
    temperature: float = 0.0
    timeout: float = 60.0
    transporte: httpx.BaseTransport | None = field(default=None, repr=False)
    """Só para teste: permite um servidor falso sem rede."""

    def __post_init__(self) -> None:
        self.nome = self.nome or self.modelo
        if self.api_key_env is not None and not _NOME_DE_VARIAVEL.fullmatch(self.api_key_env):
            raise ValueError(
                "api_key_env precisa ser o NOME de uma variável de ambiente (ex.: "
                "OPENAI_API_KEY), não a chave. Nunca escreva a chave no arquivo de config."
            )

    def _cabecalhos(self) -> dict[str, str]:
        if self.api_key_env is None:
            return {}
        chave = os.environ.get(self.api_key_env, "")
        if not chave:
            raise RuntimeError(
                f"variável de ambiente {self.api_key_env} não definida. Se o alvo não "
                "exige chave (ex.: Ollama local), use `sem_chave: true` na config."
            )
        return {"Authorization": f"Bearer {chave}"}

    def conversa(self, turnos: list[str]) -> list[str]:
        cabecalhos = self._cabecalhos()
        mensagens: list[dict[str, str]] = [{"role": "system", "content": self.system}]
        respostas: list[str] = []
        with httpx.Client(timeout=self.timeout, transport=self.transporte) as cliente:
            for turno in turnos:
                mensagens.append({"role": "user", "content": turno})
                r = _post_com_retry(
                    cliente,
                    f"{self.base_url.rstrip('/')}/chat/completions",
                    headers=cabecalhos,
                    json={
                        "model": self.modelo,
                        "messages": mensagens,
                        "temperature": self.temperature,
                    },
                )
                texto = _busca_caminho(r.json(), "choices.0.message.content")
                mensagens.append({"role": "assistant", "content": texto})
                respostas.append(texto)
        return respostas


_NOME_DE_VARIAVEL = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

# Campos que só existiriam para carregar uma chave literal no YAML. Config vai
# para repositório, para print de tela e para issue — chave nela é chave vazada.
_CHAVE_LITERAL = ("api_key", "chave", "token", "key", "authorization", "senha")


def _chave_do_alvo(cfg: dict) -> str | None:
    """Decide de onde vem a chave do alvo openai, recusando chave literal."""
    literais = sorted(c for c in cfg if c.lower() in _CHAVE_LITERAL)
    if literais:
        raise ValueError(
            f"a config do alvo tem {literais}: a chave nunca vai no YAML. Use "
            "`api_key_env: NOME_DA_VARIAVEL` e defina a variável no ambiente."
        )
    sem_chave = cfg.get("sem_chave", False)
    if not isinstance(sem_chave, bool):
        raise ValueError("sem_chave precisa ser true ou false")
    if sem_chave:
        if "api_key_env" in cfg:
            raise ValueError("use `sem_chave: true` ou `api_key_env`, não os dois")
        return None
    return cfg.get("api_key_env", "OPENAI_API_KEY")


def de_config(cfg: dict) -> Alvo:
    """Constrói o alvo a partir do bloco `alvo:` do cilada.yaml."""
    tipo = cfg.get("tipo", "http")
    if tipo == "http":
        return AlvoHTTP(
            url=cfg["url"],
            nome=cfg.get("nome", "http"),
            corpo=cfg.get("corpo"),
            campo_resposta=cfg.get("campo_resposta", "resposta"),
            headers=cfg.get("headers"),
        )
    if tipo == "openai":
        return AlvoOpenAI(
            modelo=cfg["modelo"],
            system=cfg.get("system", ""),
            base_url=cfg.get("base_url", "https://api.openai.com/v1"),
            api_key_env=_chave_do_alvo(cfg),
            nome=cfg.get("nome", ""),
        )
    raise ValueError(f"tipo de alvo desconhecido: {tipo}")
