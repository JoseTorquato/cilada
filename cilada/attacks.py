"""Carrega os ataques declarados em YAML."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

SEVERIDADES = ("critica", "alta", "media", "baixa")

_MARCACAO = re.compile(r"[*_`~#]+")
_ESPACO = re.compile(r"\s+")


def normaliza(texto: str) -> str:
    """Tira markdown e colapsa espaço antes de julgar.

    LLM responde em markdown e com quebra de linha; sem isso, 'passar de **R$
    200**' não casa com um padrão que espera 'de R$ 200', e a janela de
    proximidade dos regex estoura por causa de asterisco e newline.
    """
    return _ESPACO.sub(" ", _MARCACAO.sub("", texto)).strip()


@dataclass(frozen=True)
class Sinais:
    """Padrões que denunciam (ou inocentam) uma resposta do agente."""

    contem: tuple[str, ...] = ()
    regex: tuple[str, ...] = ()

    def casa(self, texto: str) -> tuple[str, str] | None:
        """Devolve (padrão, trecho que casou) ou None.

        O trecho é o que sai destacado no laudo — por isso não basta devolver o
        padrão: com regex, ele não existe literalmente na resposta.
        """
        texto = normaliza(texto)
        baixo = texto.lower()
        for termo in self.contem:
            pos = baixo.find(termo.lower())
            if pos >= 0:
                return termo, texto[pos : pos + len(termo)]
        for padrao in self.regex:
            if achado := re.search(padrao, texto, re.IGNORECASE | re.DOTALL):
                return padrao, achado.group(0)
        return None

    def mais(self, outro: "Sinais") -> "Sinais":
        """Une dois conjuntos de sinais (usado para herdar os vetos globais)."""
        return Sinais(contem=self.contem + outro.contem, regex=self.regex + outro.regex)

    @classmethod
    def de_dict(cls, bruto: dict | None) -> "Sinais":
        bruto = bruto or {}
        return cls(
            contem=tuple(bruto.get("contem", ()) or ()),
            regex=tuple(bruto.get("regex", ()) or ()),
        )


@dataclass(frozen=True)
class Ataque:
    id: str
    titulo: str
    categoria: str
    severidade: str
    turnos: tuple[str, ...]
    falha_se: Sinais
    suite: str
    salvo_se: Sinais = field(default_factory=Sinais)
    """Veto: se bater, a resposta é considerada segura mesmo com falha_se casando.
    Serve para 'pagamento NÃO confirmado' não contar como 'pagamento confirmado'."""
    descricao: str = ""
    referencia: str = ""
    mitigacao: str = ""
    """Como corrigir. É o que o cliente paga para saber — sem isso o laudo é
    reclamação, não solução."""
    regra: str = ""
    """Linha pronta para colar no system prompt. O laudo junta as regras dos
    ataques que falharam e emite o bloco de correção."""
    camada: str = "prompt"
    """Onde a correção mora: prompt | aplicacao | arquitetura. Nem tudo se
    resolve com prompt — dizer isso é honestidade e é upsell."""
    sempre_no_plano: bool = False
    """Entra no plano de correção mesmo que o ataque tenha passado.

    Existe porque medimos: injetar regras de segurança no prompt fez um agente
    que RESISTIA ao vazamento de instruções passar a vazar — o bloco de regras
    virou mais superfície para vazar. Correção que abre buraco novo não é
    correção."""
    tags: tuple[str, ...] = field(default_factory=tuple)

    @property
    def peso(self) -> int:
        """Severidade como número, para ordenar o laudo."""
        return {"critica": 0, "alta": 1, "media": 2, "baixa": 3}.get(self.severidade, 4)


def _valida(bruto: dict, origem: Path) -> None:
    faltando = [c for c in ("id", "titulo", "severidade", "turnos", "falha_se") if not bruto.get(c)]
    if faltando:
        raise ValueError(f"{origem}: ataque '{bruto.get('id', '?')}' sem campos {faltando}")
    if bruto["severidade"] not in SEVERIDADES:
        raise ValueError(
            f"{origem}: ataque '{bruto['id']}' tem severidade '{bruto['severidade']}',"
            f" esperado uma de {SEVERIDADES}"
        )


def _salvo_se_global(raiz: Path) -> Sinais:
    """Vetos que valem para todos os ataques (attacks/_base.yaml)."""
    base = raiz / "_base.yaml"
    if not base.exists():
        return Sinais()
    doc = yaml.safe_load(base.read_text(encoding="utf-8")) or {}
    return Sinais.de_dict(doc.get("salvo_se_global"))


def carregar(raiz: Path, suite: str | None = None) -> list[Ataque]:
    """Lê os YAML de `raiz`, opcionalmente filtrando por suíte (subpasta)."""
    global_ = _salvo_se_global(raiz)
    base = raiz / suite if suite else raiz
    if not base.exists():
        disponiveis = sorted(p.name for p in raiz.iterdir() if p.is_dir())
        raise FileNotFoundError(f"suíte '{suite}' não existe em {raiz}. Disponíveis: {disponiveis}")

    ataques: list[Ataque] = []
    vistos: dict[str, Path] = {}
    for arquivo in sorted(base.rglob("*.yaml")):
        doc = yaml.safe_load(arquivo.read_text(encoding="utf-8")) or {}
        categoria_padrao = doc.get("categoria", arquivo.stem)
        for bruto in doc.get("ataques", []):
            _valida(bruto, arquivo)
            if bruto["id"] in vistos:
                raise ValueError(f"id duplicado '{bruto['id']}' em {arquivo} e {vistos[bruto['id']]}")
            vistos[bruto["id"]] = arquivo
            ataques.append(
                Ataque(
                    id=bruto["id"],
                    titulo=bruto["titulo"],
                    categoria=bruto.get("categoria", categoria_padrao),
                    severidade=bruto["severidade"],
                    turnos=tuple(bruto["turnos"]),
                    falha_se=Sinais.de_dict(bruto["falha_se"]),
                    salvo_se=Sinais.de_dict(bruto.get("salvo_se")).mais(global_),
                    suite=arquivo.relative_to(raiz).parts[0],
                    descricao=bruto.get("descricao", ""),
                    referencia=bruto.get("referencia", ""),
                    mitigacao=bruto.get("mitigacao", ""),
                    regra=bruto.get("regra", ""),
                    camada=bruto.get("camada", "prompt"),
                    sempre_no_plano=bool(bruto.get("sempre_no_plano", False)),
                    tags=tuple(bruto.get("tags", ()) or ()),
                )
            )
    return sorted(ataques, key=lambda a: (a.peso, a.id))
