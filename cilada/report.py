"""Saída no terminal e laudo HTML."""

from __future__ import annotations

import html
import json
import os
import sys
from datetime import datetime

from .attacks import _ESPACO as ESPACO
from .runner import Execucao, Resultado

CIANO, VERM, AMAR, CINZA, NEGRITO, ZERA = (
    "\033[36m",
    "\033[31m",
    "\033[33m",
    "\033[90m",
    "\033[1m",
    "\033[0m",
)


def _cor_ativa() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    return sys.stdout.isatty()


def _c(texto: str, cor: str) -> str:
    return f"{cor}{texto}{ZERA}" if _cor_ativa() else texto


def linha_resultado(r: Resultado) -> str:
    if r.erro:
        rotulo = _c("[erro]   ", AMAR)
        detalhe = _c(r.erro[:70], CINZA)
    elif r.vulneravel:
        rotulo = _c("[FALHOU] ", VERM)
        detalhe = _c(r.evidencia[:70].replace("\n", " "), CINZA)
    else:
        rotulo = _c("[ok]     ", CIANO)
        detalhe = ""
    return f"  {rotulo} {r.ataque.id:<34} {detalhe}"


def resumo(execucao: Execucao, suites: list[str]) -> str:
    linhas = [""]
    placar = execucao.placar
    cor_placar = VERM if placar < 70 else (AMAR if placar < 90 else CIANO)
    linhas.append(
        f"  {_c('robustez', CINZA)} {_c(str(placar) + '/100', cor_placar + NEGRITO)}"
        f"   {execucao.aprovados}/{execucao.testados} aprovados"
        f"   {_c(str(len(execucao.criticas)) + ' críticas', VERM if execucao.criticas else CINZA)}"
    )
    if execucao.erros:
        linhas.append(_c(f"  {len(execucao.erros)} ataques não puderam ser executados", AMAR))
    linhas.append(_c(f"  alvo: {execucao.alvo}   suítes: {', '.join(suites)}", CINZA))
    linhas.append("")
    return "\n".join(linhas)


def para_json(execucao: Execucao) -> str:
    return json.dumps(
        {
            "alvo": execucao.alvo,
            "inicio": execucao.inicio,
            "fim": execucao.fim,
            "placar": execucao.placar,
            "aprovados": execucao.aprovados,
            "testados": execucao.testados,
            "resultados": [
                {
                    "id": r.ataque.id,
                    "titulo": r.ataque.titulo,
                    "categoria": r.ataque.categoria,
                    "severidade": r.ataque.severidade,
                    "suite": r.ataque.suite,
                    "referencia": r.ataque.referencia,
                    "status": r.status,
                    "padrao": r.padrao,
                    "trecho": r.trecho,
                    "evidencia": r.evidencia,
                    "turnos": list(r.ataque.turnos),
                    "respostas": r.respostas,
                    "erro": r.erro,
                }
                for r in execucao.resultados
            ],
        },
        ensure_ascii=False,
        indent=2,
    )


_CSS = """
:root{--base:#0A0A0A;--panel:#0D0D0D;--rule:#1C1C1C;--title:#fff;--body:#8A8A8A;
--muted:#C8C8C8;--dim:#5A5A5A;--signal:#22D3EE;--alerta:#F87171;--atencao:#FBBF24}
*{box-sizing:border-box}body{margin:0;background:var(--base);color:var(--body);
font-family:ui-monospace,'JetBrains Mono',monospace;font-size:14px;line-height:1.75}
.wrap{max-width:960px;margin:0 auto;padding:56px 24px 80px}
h1{color:var(--title);font-size:30px;letter-spacing:-.03em;margin:0 0 8px}
h2{color:var(--title);font-size:18px;margin:52px 0 18px;letter-spacing:-.02em}
.kicker{color:var(--signal);margin:0 0 26px;font-size:12px}
.meta{color:var(--dim);font-size:11.5px;border-top:1px solid var(--rule);
border-bottom:1px solid var(--rule);padding:16px 0;margin:26px 0 0;
display:flex;flex-wrap:wrap;gap:8px 32px}
.placar{display:flex;gap:1px;background:var(--rule);border:1px solid var(--rule);margin:26px 0}
.placar div{background:var(--base);padding:22px 24px;flex:1;min-width:120px}
.placar .n{color:var(--title);font-size:30px;line-height:1}
.placar .n.mau{color:var(--alerta)}.placar .n.bom{color:var(--signal)}
.placar .l{color:var(--dim);font-size:10.5px;letter-spacing:.09em;margin-top:8px}
.achado{border:1px solid var(--rule);border-left:2px solid var(--alerta);
background:var(--panel);padding:22px 24px;margin-bottom:14px}
.achado.ok{border-left-color:var(--rule)}
.achado h3{color:var(--title);font-size:15px;margin:0 0 6px;font-weight:600}
.sev{font-size:9.5px;letter-spacing:.09em;text-transform:uppercase;padding:3px 8px;
border:1px solid currentColor;margin-left:10px;vertical-align:middle}
.sev.critica{color:var(--alerta)}.sev.alta{color:var(--atencao)}
.sev.media,.sev.baixa{color:var(--dim)}
.id{color:var(--dim);font-size:11px}
.ref{color:var(--signal);font-size:11.5px;margin-top:10px}
.dialogo{margin-top:16px;border-top:1px solid var(--rule);padding-top:14px}
.turno{margin:10px 0;font-size:12.5px;white-space:pre-wrap;word-wrap:break-word}
.turno .quem{color:var(--dim);font-size:10.5px;letter-spacing:.09em;display:block;margin-bottom:3px}
.turno.bot{color:var(--muted)}
.marca{color:var(--alerta)}
table{width:100%;border-collapse:collapse;margin-top:8px;font-size:12.5px}
th,td{text-align:left;padding:11px 12px;border-bottom:1px solid var(--rule)}
th{color:var(--dim);font-size:10.5px;letter-spacing:.09em;text-transform:uppercase;font-weight:400}
td.st-falhou{color:var(--alerta)}td.st-ok{color:var(--signal)}td.st-erro{color:var(--atencao)}
.mitig{margin-top:16px;border-top:1px solid var(--rule);padding-top:14px}
.mitig-tag{color:var(--signal);font-size:10.5px;letter-spacing:.09em;
text-transform:uppercase;display:block;margin-bottom:8px}
.mitig p{margin:0;color:var(--muted);font-size:12.5px;line-height:1.8}
.plano-h3{color:var(--title);font-size:14px;margin:34px 0 8px;font-weight:600}
.plano-lista{margin:14px 0 0;padding:0}
.plano-lista li{list-style:none;border-left:2px solid var(--rule);padding:0 0 0 16px;
margin-bottom:16px;font-size:12.5px;line-height:1.8;color:var(--muted)}
.plano-lista strong{color:var(--title);font-weight:600}
.nota{color:var(--dim);font-size:12px;margin-top:28px}
footer{color:var(--dim);font-size:11px;border-top:1px solid var(--rule);
margin-top:56px;padding-top:22px}
footer a{color:var(--signal);text-decoration:none}
@media print{body{background:#fff;color:#222}.achado{background:#fff}}
"""


def _dialogo(r: Resultado) -> str:
    partes = []
    for i, turno in enumerate(r.ataque.turnos):
        partes.append(
            f'<div class="turno"><span class="quem">atacante</span>{html.escape(turno)}</div>'
        )
        if i < len(r.respostas):
            resposta = html.escape(r.respostas[i])
            if r.trecho and r.vulneravel:
                # destaca o trecho que denunciou a falha
                alvo = html.escape(r.trecho)
                idx = resposta.lower().find(alvo.lower())
                if idx >= 0:
                    resposta = (
                        resposta[:idx]
                        + f'<span class="marca">{resposta[idx : idx + len(alvo)]}</span>'
                        + resposta[idx + len(alvo) :]
                    )
            partes.append(f'<div class="turno bot"><span class="quem">agente</span>{resposta}</div>')
    return f'<div class="dialogo">{"".join(partes)}</div>'


CAMADAS = {
    "prompt": ("system prompt", "Resolve-se com regra no prompt."),
    "aplicacao": ("aplicação", "Exige mudança no código ou na política — prompt sozinho não sustenta."),
    "arquitetura": ("arquitetura", "Exige rever permissões e limites do agente. Prompt aqui é mitigação secundária, não controle."),
}


def _mitigacao(r: Resultado) -> str:
    if not r.ataque.mitigacao:
        return ""
    rotulo, _ = CAMADAS.get(r.ataque.camada, (r.ataque.camada, ""))
    return (
        f'<div class="mitig"><span class="mitig-tag">como corrigir · {html.escape(rotulo)}</span>'
        f"<p>{html.escape(r.ataque.mitigacao.strip())}</p></div>"
    )


def _plano(execucao: Execucao) -> str:
    """Plano de correção: o bloco de prompt pronto para colar + o que exige engenharia."""
    falhas = sorted(execucao.falhas, key=lambda r: r.ataque.peso)
    if not falhas:
        return ""

    regras, engenharia = [], {"aplicacao": [], "arquitetura": []}
    for r in falhas:
        if r.ataque.regra and r.ataque.regra.strip() not in regras:
            regras.append(r.ataque.regra.strip())
        if r.ataque.camada in engenharia:
            engenharia[r.ataque.camada].append(r.ataque)

    partes = ['<h2>Plano de correção</h2>']

    if regras:
        bloco = "REGRAS DE SEGURANÇA — valem acima de qualquer pedido do cliente:\n" + "\n".join(
            f"{i}. {ESPACO.sub(' ', regra)}" for i, regra in enumerate(regras, 1)
        )
        partes.append(
            "<p>Cole o bloco abaixo no fim do system prompt do agente. Ele cobre "
            f"{len(regras)} dos {len(falhas)} achados — os que se resolvem com instrução.</p>"
            f'<pre class="code-card">{html.escape(bloco)}</pre>'
        )

    for camada in ("aplicacao", "arquitetura"):
        itens = engenharia[camada]
        if not itens:
            continue
        rotulo, explica = CAMADAS[camada]
        lista = "".join(
            f"<li><strong>{html.escape(a.titulo)}</strong> — {html.escape(a.mitigacao.strip())}</li>"
            for a in itens
        )
        partes.append(
            f'<h3 class="plano-h3">Exige trabalho de {html.escape(rotulo)} ({len(itens)})</h3>'
            f"<p>{html.escape(explica)}</p><ul class='plano-lista'>{lista}</ul>"
        )

    partes.append(
        '<p class="nota">Depois de aplicar as correções, rode o Cilada de novo: '
        "achado corrigido sem reteste é achado que você acha que corrigiu.</p>"
    )
    return "".join(partes)


def para_html(execucao: Execucao, suites: list[str]) -> str:
    placar = execucao.placar
    classe = "bom" if placar >= 90 else ("mau" if placar < 70 else "")
    falhas = sorted(execucao.falhas, key=lambda r: r.ataque.peso)

    achados = "".join(
        f"""<div class="achado">
<h3>{html.escape(r.ataque.titulo)}<span class="sev {r.ataque.severidade}">{r.ataque.severidade}</span></h3>
<div class="id">{html.escape(r.ataque.id)} · {html.escape(r.ataque.categoria)} · suíte {html.escape(r.ataque.suite)}</div>
{f'<p>{html.escape(r.ataque.descricao)}</p>' if r.ataque.descricao else ''}
{f'<div class="ref">{html.escape(r.ataque.referencia)}</div>' if r.ataque.referencia else ''}
{_dialogo(r)}
{_mitigacao(r)}
</div>"""
        for r in falhas
    )
    if not falhas:
        achados = '<div class="achado ok"><h3>Nenhuma falha encontrada nesta suíte</h3><p>O agente resistiu a todos os ataques executados. Isso não prova ausência de vulnerabilidade — prova resistência a este conjunto.</p></div>'

    linhas = "".join(
        f"<tr><td>{html.escape(r.ataque.id)}</td><td>{html.escape(r.ataque.categoria)}</td>"
        f"<td>{r.ataque.severidade}</td><td class='st-{r.status}'>{r.status}</td></tr>"
        for r in execucao.resultados
    )

    return f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Laudo Cilada — {html.escape(execucao.alvo)}</title>
<style>{_CSS}</style></head><body><div class="wrap">
<p class="kicker">// laudo de robustez adversarial</p>
<h1>{html.escape(execucao.alvo)}</h1>
<div class="meta">
  <span>suítes: {html.escape(', '.join(suites))}</span>
  <span>execução: {html.escape(execucao.inicio)} UTC</span>
  <span>cilada v0.1</span>
</div>

<div class="placar">
  <div><div class="n {classe}">{placar}</div><div class="l">ROBUSTEZ / 100</div></div>
  <div><div class="n">{execucao.aprovados}/{execucao.testados}</div><div class="l">APROVADOS</div></div>
  <div><div class="n {'mau' if execucao.criticas else ''}">{len(execucao.criticas)}</div><div class="l">CRÍTICAS</div></div>
  <div><div class="n">{len(execucao.falhas)}</div><div class="l">TOTAL DE FALHAS</div></div>
</div>

<h2>Achados</h2>
{achados}

{_plano(execucao)}

<h2>Execução completa</h2>
<table><thead><tr><th>ataque</th><th>categoria</th><th>severidade</th><th>status</th></tr></thead>
<tbody>{linhas}</tbody></table>

<footer>
Gerado por <a href="https://github.com/JoseTorquato/cilada">Cilada</a> — suíte adversarial em
português brasileiro para agentes de IA.<br>
Este laudo cobre apenas os ataques executados nas suítes listadas. Resistir a eles não garante
ausência de outras vulnerabilidades.<br>
{datetime.now().strftime('%d/%m/%Y')} · <a href="https://josetorquato.dev">josetorquato.dev</a>
</footer>
</div></body></html>"""
