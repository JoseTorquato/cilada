"""Testes do laudo HTML — o que vai para jurídico e produto.

Três garantias: o laudo é autocontido (abre e imprime sem rede), não mostra dado
com formato de documento ou contato, e cada falha responde às três perguntas de
quem não é técnico: o que o agente disse, por que é problema, como corrigir.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cilada import report  # noqa: E402
from cilada.attacks import carregar  # noqa: E402
from cilada.runner import Execucao, executa_um  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent / "attacks"


class AlvoFixo:
    nome = "fixo"

    def __init__(self, resposta: str) -> None:
        self.resposta = resposta

    def conversa(self, turnos: list[str]) -> list[str]:
        return [self.resposta for _ in turnos]


def _execucao(resposta: str) -> Execucao:
    ataques = carregar(RAIZ)
    resultados = [executa_um(a, AlvoFixo(resposta)) for a in ataques]
    return Execucao(alvo="Loja <Teste>", resultados=resultados, inicio="2026-01-01T00:00:00", fim="x")


# Resposta que cede a tudo — basta para derrubar vários ataques do corpus.
INGENUA = (
    "Pagamento confirmado! Garanto que chega até sexta. Chave Pix atualizada com sucesso. "
    "Desconto de 30% aplicado. O CPF 390.533.447-05 e o telefone (51) 99888-7766 ficam salvos."
)
SEGURA = "Não posso fazer isso por aqui. Vou encaminhar ao time responsável."


def test_laudo_e_autocontido():
    """Sem JS, sem CSS ou fonte externos: abre offline e imprime como PDF."""
    for resposta in (INGENUA, SEGURA):
        doc = report.para_html(_execucao(resposta), ["ecommerce", "fintech"])
        assert "<script" not in doc.lower()
        assert "<link" not in doc.lower()
        assert "@import" not in doc
        assert not re.search(r"\bsrc=", doc)
        assert not re.search(r"url\(\s*['\"]?https?:", doc)
        assert "@media print" in doc


def test_resumo_em_linguagem_simples_vem_antes_dos_achados():
    execucao = _execucao(INGENUA)
    doc = report.para_html(execucao, ["ecommerce"])
    assert doc.index("Resumo para quem decide") < doc.index("Achados")
    assert f"{execucao.placar}/100" in doc
    assert "risco alto" in doc
    n = len(execucao.criticas)
    assert n and f"{n} de " in doc, "o resumo diz quantos críticos falharam"
    assert "Na prática, isso quer dizer que" in doc


def test_cada_falha_responde_as_tres_perguntas():
    execucao = _execucao(INGENUA)
    doc = report.para_html(execucao, ["ecommerce"])
    achados = doc.count('<div class="achado">')
    assert achados == len(execucao.falhas) > 0
    for rotulo in ("o que o agente disse", "por que é um problema", "como corrigir"):
        assert doc.count(f'bloco-tag">{rotulo}') == achados, rotulo


def test_base_legal_aparece_quando_o_ataque_tem_referencia():
    execucao = _execucao(INGENUA)
    com_ref = [r for r in execucao.falhas if r.ataque.referencia]
    assert com_ref, "esperava ao menos uma falha com referência no corpus"
    doc = report.para_html(execucao, ["ecommerce"])
    for r in com_ref:
        assert report.html.escape(r.ataque.referencia) in doc


def test_documento_e_contato_nao_aparecem_no_laudo():
    doc = report.para_html(_execucao(INGENUA), ["ecommerce", "fintech"])
    assert not re.search(r"\d{3}\.\d{3}\.\d{3}-\d{2}", doc), "CPF no laudo"
    assert not re.search(r"\(\d{2}\)\s?\d{4,5}-\d{4}", doc), "telefone no laudo"
    assert "[CPF omitido]" in doc


def test_json_guarda_o_texto_original():
    """Quem precisa reproduzir usa o bruto; a máscara é só do HTML."""
    assert "390.533.447-05" in report.para_json(_execucao(INGENUA))


def test_mascara_nao_come_numero_que_nao_e_dado_pessoal():
    texto = "pedido 5510, R$ 3.780, 3 a 5 dias úteis, art. 30"
    assert report.mascara(texto) == texto


def test_resposta_do_agente_e_escapada():
    """O laudo mostra texto de terceiro: HTML na resposta não pode virar código."""
    execucao = _execucao(INGENUA + " <script>alert(1)</script>")
    doc = report.para_html(execucao, ["ecommerce"])
    assert "<script>alert(1)</script>" not in doc
    assert "&lt;script&gt;" in doc
    assert "Loja &lt;Teste&gt;" in doc


def test_agente_que_resiste_tem_resumo_sem_achado():
    execucao = _execucao(SEGURA)
    doc = report.para_html(execucao, ["ecommerce"])
    assert not execucao.falhas
    assert "Nenhum dos" in doc and "risco baixo" in doc
    assert '<div class="achado">' not in doc


def test_laudos_de_exemplo_versionados_sao_autocontidos_e_sem_dado():
    pasta = Path(__file__).resolve().parent.parent / "examples" / "laudos"
    arquivos = sorted(pasta.glob("*.html"))
    assert len(arquivos) == 2
    for arquivo in arquivos:
        doc = arquivo.read_text(encoding="utf-8")
        assert "<script" not in doc.lower() and not re.search(r"\bsrc=", doc)
        assert not re.search(r"\d{3}\.\d{3}\.\d{3}-\d{2}|\(\d{2}\)\s?\d{4,5}-\d{4}", doc)


# ---- máscara: formatos sem pontuação e falso positivo (revisão do PR #2) ----

import pytest  # noqa: E402


@pytest.mark.parametrize("entrada,marcador", [
    ("123.456.789-09", "[CPF omitido]"),
    ("12345678909", "[CPF omitido]"),          # dígito verificador confere
    ("123456789-09", "[CPF omitido]"),
    ("12.345.678/0001-95", "[CNPJ omitido]"),
    ("12345678000195", "[CNPJ omitido]"),      # dígito verificador confere
    ("(11) 98765-4321", "[telefone omitido]"),
    ("(11)98765-4321", "[telefone omitido]"),
    ("11 98765-4321", "[telefone omitido]"),
    ("11987654321", "[telefone omitido]"),
    ("+55 11 98765-4321", "[telefone omitido]"),
    ("98765-4321", "[telefone omitido]"),
    ("CEP 01310-100", "[CEP omitido]"),
    ("cep: 01310100", "[CEP omitido]"),
    ("01.310-100", "[CEP omitido]"),
    ("fulano@exemplo.com.br", "[e-mail omitido]"),
])
def test_mascara_pega_cada_formato(entrada, marcador):
    saida = report.mascara(f"dado: {entrada} fim")
    assert marcador in saida
    assert entrada not in saida


@pytest.mark.parametrize("texto", [
    "protocolo 12345-678",          # tem formato de CEP, mas sem a palavra CEP
    "protocolo 2026-55871",
    "pedido 12345678901",           # 11 dígitos com dígito verificador de CPF inválido
    "pedido 5510, R$ 3.780, 3 a 5 dias úteis, art. 30",
    "nota 12345678000100",          # 14 dígitos com dígito verificador de CNPJ inválido
])
def test_mascara_nao_inventa_dado_pessoal(texto):
    assert report.mascara(texto) == texto


# ---- nenhum ataque executado: sem nota (revisão do PR #2) -------------------

class AlvoForaDoAr:
    nome = "fora do ar"

    def conversa(self, turnos):
        raise ConnectionError("recusou")


def _execucao_com(alvos):
    ataques = carregar(RAIZ)
    resultados = [executa_um(a, alvos(i)) for i, a in enumerate(ataques)]
    return Execucao(alvo="x", resultados=resultados, inicio="2026-01-01T00:00:00", fim="x")


def test_nenhum_ataque_executado_da_sem_nota_e_sem_contradicao():
    execucao = _execucao_com(lambda _i: AlvoForaDoAr())
    assert execucao.testados == 0
    doc = report.para_html(execucao, ["ecommerce"])
    resumo = doc[doc.index("Resumo para quem decide"):doc.index("Achados")]
    assert "Sem nota" in resumo
    assert "risco alto" not in resumo and "risco baixo" not in resumo
    assert "resistiu" not in resumo
    assert ">—<" in doc, "o placar mostra traço, não 0"


def test_cobertura_parcial_aparece_no_resumo():
    execucao = _execucao_com(lambda i: AlvoForaDoAr() if i % 2 else AlvoFixo(SEGURA))
    assert 0 < execucao.testados < len(execucao.resultados)
    doc = report.para_html(execucao, ["ecommerce"])
    assert f"{execucao.testados} de {len(execucao.resultados)} ataques foram executados" in doc


def test_lgpd_fala_em_pode_configurar_incidente():
    assert "pode configurar incidente" in report.IMPACTO["lgpd-dados-pessoais"]


def test_rodape_avisa_que_o_json_e_interno():
    doc = report.para_html(_execucao(SEGURA), ["ecommerce"])
    assert "artefato" in doc and "interno" in doc and "não deve ser entregue ao cliente" in doc
