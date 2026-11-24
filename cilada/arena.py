"""Arena: a mesma suíte contra vários alvos, numa execução só.

    cilada arena --lista examples/arena-local.yaml --seco      # só mostra o plano
    cilada arena --lista examples/arena-local.yaml --saida arena/

O arquivo de lista tem um alvo base (o system prompt comum) e a lista de alvos,
cada um sobrescrevendo o que muda — em geral só o modelo:

    base:                      # opcional; ou `config: caminho.yaml` com bloco alvo:
      tipo: openai
      base_url: http://localhost:11434/v1
      sem_chave: true
      system: |
        Você é o assistente da Loja Exemplo...
    alvos:
      - modelo: qwen3:8b
      - modelo: gemma3:4b
        nome: Gemma 3 4B

Alvo remoto (qualquer coisa fora de localhost) só roda com --permitir-remoto:
cada turno de cada ataque é uma chamada, e em API paga isso é dinheiro. O --seco
mostra quantas chamadas seriam feitas antes de qualquer uma acontecer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import yaml

from . import compara, report
from .attacks import Ataque
from .runner import Execucao, executa
from .targets import AlvoHTTP, AlvoOpenAI, de_config

_LOCAIS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


@dataclass
class PlanoAlvo:
    nome: str
    cfg: dict
    endereco: str
    remoto: bool


def endereco_do_alvo(alvo: object) -> str:
    """O endereço que o alvo construído vai de fato usar — não o que a config diz.

    Ler do dict abria brecha: `url` num alvo openai (que só usa base_url) ou
    `base_url` num alvo http (que só usa url) faziam o plano dizer "local"
    enquanto a conexão ia para a nuvem. Tipo desconhecido devolve "" e é
    tratado como remoto.
    """
    if isinstance(alvo, AlvoHTTP):
        return alvo.url
    if isinstance(alvo, AlvoOpenAI):
        return alvo.base_url
    return ""


def _remoto(endereco: str) -> bool:
    """Falha fechada: endereço vazio ou sem host legível conta como remoto."""
    try:
        host = urlparse(endereco).hostname or ""
    except ValueError:
        return True
    return not host or host.lower() not in _LOCAIS


def carrega_lista(caminho: Path) -> list[PlanoAlvo]:
    """Lê o arquivo de lista e devolve um alvo já mesclado por entrada."""
    doc = yaml.safe_load(caminho.read_text(encoding="utf-8")) or {}
    base: dict = {}
    if "config" in doc:
        cfg_path = (caminho.parent / doc["config"]).resolve()
        if not cfg_path.is_file():
            cfg_path = Path(doc["config"]).resolve()
        base = (yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}).get("alvo", {})
    base = {**base, **(doc.get("base") or {})}

    entradas = doc.get("alvos") or []
    if not entradas:
        raise ValueError(f"{caminho}: a lista não tem `alvos:`")

    planos: list[PlanoAlvo] = []
    vistos: set[str] = set()
    for i, entrada in enumerate(entradas, 1):
        if not isinstance(entrada, dict):
            raise ValueError(f"{caminho}: alvo {i} precisa ser um bloco (ex.: `- modelo: x`)")
        cfg = {**base, **entrada}
        nome = cfg.get("nome") or cfg.get("modelo") or cfg.get("url")
        if not nome:
            raise ValueError(f"{caminho}: alvo {i} sem nome, modelo ou url")
        cfg["nome"] = nome
        if nome in vistos:
            raise ValueError(f"{caminho}: nome de alvo repetido '{nome}' — o comparativo os confundiria")
        vistos.add(nome)
        alvo = de_config(cfg)  # valida a config agora, não no meio da execução
        endereco = endereco_do_alvo(alvo)
        planos.append(PlanoAlvo(nome=nome, cfg=cfg, endereco=endereco, remoto=_remoto(endereco)))
    return planos


def chamadas_por_alvo(ataques: list[Ataque]) -> int:
    """Uma chamada por turno de cada ataque. Retentativa por 429/5xx não entra."""
    return sum(len(a.turnos) for a in ataques)


def plano_texto(planos: list[PlanoAlvo], ataques: list[Ataque]) -> str:
    por_alvo = chamadas_por_alvo(ataques)
    linhas = ["", f"  arena · {len(planos)} alvo(s) · {len(ataques)} ataques · {por_alvo} chamadas por alvo", ""]
    for p in planos:
        onde = "REMOTO" if p.remoto else "local"
        linhas.append(f"  {onde:<6}  {p.nome:<34} {p.endereco or '(endereço desconhecido)'}  ({por_alvo} chamadas)")
    remotos = sum(1 for p in planos if p.remoto)
    linhas += [
        "",
        f"  total: {por_alvo * len(planos)} chamadas ({por_alvo} × {len(planos)} alvos)"
        + (f", {por_alvo * remotos} delas em alvo remoto" if remotos else ""),
        "  retentativas por limite de taxa (429/5xx) podem somar chamadas a isso.",
        "",
    ]
    return "\n".join(linhas)


def _arquivo(nome: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", nome.lower()).strip("-") or "alvo"


def roda(
    planos: list[PlanoAlvo],
    ataques: list[Ataque],
    suites: list[str],
    saida: Path,
    paralelo: int = 4,
    permitir_remoto: bool = False,
    ao_terminar=None,
) -> list[Execucao]:
    remotos = [p.nome for p in planos if p.remoto]
    if remotos and not permitir_remoto:
        raise PermissionError(
            f"alvos remotos na lista: {remotos}. Cada turno é uma chamada (veja --seco); "
            "para rodar mesmo assim, use --permitir-remoto."
        )
    saida.mkdir(parents=True, exist_ok=True)
    execucoes: list[Execucao] = []
    jsons: list[str] = []
    for p in planos:
        alvo = de_config(p.cfg)
        # reconfere no objeto que vai rodar: o plano e a execução não podem divergir
        if _remoto(endereco_do_alvo(alvo)) and not permitir_remoto:
            raise PermissionError(f"alvo {p.nome!r} é remoto; use --permitir-remoto")
        execucao = executa(ataques, alvo, paralelo, ao_terminar=ao_terminar)
        execucoes.append(execucao)
        destino = saida / f"{_arquivo(p.nome)}.json"
        destino.write_text(report.para_json(execucao), encoding="utf-8")
        jsons.append(str(destino))
    comparadas = compara.carrega(jsons)
    (saida / "arena.md").write_text(compara.markdown(comparadas) + "\n", encoding="utf-8")
    (saida / "arena.html").write_text(compara.para_html(comparadas), encoding="utf-8")
    return execucoes
