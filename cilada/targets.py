"""Adapters de alvo: como o Cilada conversa com o agente sob teste."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Protocol

import httpx


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
                r = cliente.post(self.url, json=corpo, headers=headers)
                r.raise_for_status()
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
    api_key_env: str = "OPENAI_API_KEY"
    nome: str = ""
    temperature: float = 0.0
    timeout: float = 60.0

    def __post_init__(self) -> None:
        self.nome = self.nome or self.modelo

    def conversa(self, turnos: list[str]) -> list[str]:
        chave = os.environ.get(self.api_key_env, "")
        if not chave:
            raise RuntimeError(f"variável de ambiente {self.api_key_env} não definida")
        mensagens: list[dict[str, str]] = [{"role": "system", "content": self.system}]
        respostas: list[str] = []
        with httpx.Client(timeout=self.timeout) as cliente:
            for turno in turnos:
                mensagens.append({"role": "user", "content": turno})
                r = cliente.post(
                    f"{self.base_url.rstrip('/')}/chat/completions",
                    headers={"Authorization": f"Bearer {chave}"},
                    json={
                        "model": self.modelo,
                        "messages": mensagens,
                        "temperature": self.temperature,
                    },
                )
                r.raise_for_status()
                texto = _busca_caminho(r.json(), "choices.0.message.content")
                mensagens.append({"role": "assistant", "content": texto})
                respostas.append(texto)
        return respostas


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
            api_key_env=cfg.get("api_key_env", "OPENAI_API_KEY"),
            nome=cfg.get("nome", ""),
        )
    raise ValueError(f"tipo de alvo desconhecido: {tipo}")
