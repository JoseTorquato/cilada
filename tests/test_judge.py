"""Testes do juiz — o núcleo do produto.

Um falso positivo aqui vira acusação errada num laudo assinado. Um falso
negativo vira vulnerabilidade entregue como "aprovado". Os dois custam caro,
então o julgamento é o que mais precisa de teste.

    python -m pytest tests/ -q      (ou: python tests/test_judge.py)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cilada.attacks import Ataque, Sinais, carregar  # noqa: E402
from cilada.runner import executa_um  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent / "attacks"


class AlvoFalso:
    """Alvo que devolve respostas fixas, sem rede."""

    def __init__(self, respostas: list[str], nome: str = "falso") -> None:
        self.respostas = respostas
        self.nome = nome

    def conversa(self, turnos: list[str]) -> list[str]:
        return [self.respostas[i % len(self.respostas)] for i in range(len(turnos))]


class AlvoQuebrado:
    nome = "quebrado"

    def conversa(self, turnos: list[str]) -> list[str]:
        raise ConnectionError("recusou a conexão")


def _ataque(**kw) -> Ataque:
    base = dict(
        id="teste",
        titulo="Ataque de teste",
        categoria="teste",
        severidade="alta",
        turnos=("oi",),
        falha_se=Sinais(contem=("confirmado",)),
        suite="teste",
    )
    return Ataque(**{**base, **kw})


def test_contem_acusa():
    r = executa_um(_ataque(), AlvoFalso(["Pagamento confirmado!"]))
    assert r.vulneravel
    assert r.trecho == "confirmado"


def test_resposta_limpa_passa():
    r = executa_um(_ataque(), AlvoFalso(["Vou verificar com o financeiro."]))
    assert not r.vulneravel


def test_salvo_se_veta_a_acusacao():
    """'pagamento não confirmado' não pode contar como 'pagamento confirmado'."""
    ataque = _ataque(salvo_se=Sinais(regex=(r"n[ãa]o[^.!?]{0,30}confirmado",)))
    r = executa_um(ataque, AlvoFalso(["O pagamento não foi confirmado ainda."]))
    assert not r.vulneravel


def test_falha_em_qualquer_turno():
    """O agente pode resistir no primeiro turno e ceder no terceiro."""
    ataque = _ataque(turnos=("a", "b", "c"))
    alvo = AlvoFalso(["Não posso.", "Ainda não.", "Ok, confirmado então."])
    r = executa_um(ataque, alvo)
    assert r.vulneravel


def test_trecho_de_regex_e_o_texto_casado():
    """Com regex, o trecho destacado precisa ser o texto real, não o padrão."""
    ataque = _ataque(falha_se=Sinais(regex=(r"(vou|vamos)[^.!?]{0,20}(dar baixa)",)))
    r = executa_um(ataque, AlvoFalso(["Sem problema, vou dar baixa no pedido."]))
    assert r.vulneravel
    assert r.trecho == "vou dar baixa"


def test_alvo_inacessivel_vira_erro_nao_aprovacao():
    """Alvo fora do ar não pode ser reportado como agente seguro."""
    r = executa_um(_ataque(), AlvoQuebrado())
    assert r.erro
    assert not r.vulneravel
    assert r.status == "erro"


def test_corpus_carrega_e_esta_integro():
    ataques = carregar(RAIZ)
    assert len(ataques) >= 20
    ids = [a.id for a in ataques]
    assert len(ids) == len(set(ids)), "há id duplicado no corpus"
    for a in ataques:
        assert a.turnos, f"{a.id} sem turnos"
        assert a.falha_se.contem or a.falha_se.regex, f"{a.id} sem sinal de falha"
    # críticas primeiro, para o laudo abrir pelo que dói
    assert ataques[0].severidade == "critica"


def test_regex_do_corpus_compilam():
    import re

    for a in carregar(RAIZ):
        for padrao in (*a.falha_se.regex, *a.salvo_se.regex):
            re.compile(padrao)  # levanta se estiver malformado


if __name__ == "__main__":
    falhas = 0
    for nome, fn in sorted(globals().items()):
        if nome.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ok    {nome}")
            except AssertionError as e:
                falhas += 1
                print(f"  FALHA {nome}: {e}")
    print(f"\n  {falhas} falha(s)\n")
    raise SystemExit(1 if falhas else 0)
