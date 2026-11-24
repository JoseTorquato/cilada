"""Compara execuções e emite a tabela — o artefato público da arena.

    python -m cilada.compara resultado-a.json resultado-b.json [--html arena.html]

Lê os JSON gerados por `cilada run --json` e mostra, ataque a ataque, quem
resistiu e quem caiu. É o que vira post e, depois, o leaderboard.
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path

from .report import _CSS


def carrega(caminhos: list[str]) -> list[dict]:
    execucoes = []
    for c in caminhos:
        dados = json.loads(Path(c).read_text(encoding="utf-8"))
        dados["_arquivo"] = Path(c).name
        execucoes.append(dados)
    return execucoes


def _ordena(ataques: dict[str, dict]) -> list[dict]:
    peso = {"critica": 0, "alta": 1, "media": 2, "baixa": 3}
    return sorted(ataques.values(), key=lambda a: (peso.get(a["severidade"], 4), a["id"]))


def _indice(execucoes: list[dict]) -> tuple[list[dict], dict[str, dict[str, str]]]:
    """Devolve (ataques em ordem, {id do ataque: {alvo: status}})."""
    ataques: dict[str, dict] = {}
    matriz: dict[str, dict[str, str]] = {}
    for ex in execucoes:
        for r in ex["resultados"]:
            ataques.setdefault(r["id"], {"id": r["id"], "titulo": r["titulo"], "severidade": r["severidade"], "suite": r["suite"]})
            matriz.setdefault(r["id"], {})[ex["alvo"]] = r["status"]
    return _ordena(ataques), matriz


def _nota(ex: dict) -> str:
    """Nota com a situação: JSON antigo (sem o campo) é nota definitiva."""
    situacao = ex.get("situacao_da_nota", "definitiva")
    if situacao == "sem nota":
        return "sem nota"
    return f"{ex['placar']}/100" + (" (provisória)" if situacao == "provisoria" else "")


def _classe(ex: dict) -> str:
    placar = ex.get("placar")
    if placar is None:  # sem nota
        return ""
    if placar < 70:
        return "mau"
    return "bom" if placar >= 90 and _nota(ex).endswith("/100") else ""


def markdown(execucoes: list[dict]) -> str:
    ordenados, matriz = _indice(execucoes)
    alvos = [ex["alvo"] for ex in execucoes]

    linhas = ["| ataque | sev. | " + " | ".join(alvos) + " |"]
    linhas.append("|---|---|" + "---|" * len(alvos))
    for a in ordenados:
        celulas = []
        for alvo in alvos:
            st = matriz[a["id"]].get(alvo, "—")
            celulas.append({"ok": "resistiu", "falhou": "**CAIU**", "erro": "erro", "revisar": "revisar"}.get(st, st))
        linhas.append(f"| `{a['id']}` | {a['severidade']} | " + " | ".join(celulas) + " |")

    linhas.append("")
    linhas.append("| | " + " | ".join(alvos) + " |")
    linhas.append("|---|" + "---|" * len(alvos))
    linhas.append("| **robustez** | " + " | ".join(f"**{_nota(ex)}**" for ex in execucoes) + " |")
    linhas.append("| aprovados | " + " | ".join(f"{ex['aprovados']}/{ex['testados']}" for ex in execucoes) + " |")
    linhas.append(
        "| falhas críticas | "
        + " | ".join(
            str(sum(1 for r in ex["resultados"] if r["status"] == "falhou" and r["severidade"] == "critica"))
            for ex in execucoes
        )
        + " |"
    )
    return "\n".join(linhas)


def para_html(execucoes: list[dict]) -> str:
    ordenados, matriz = _indice(execucoes)
    alvos = [ex["alvo"] for ex in execucoes]

    cabecalho = "".join(f"<th>{html.escape(a)}</th>" for a in alvos)
    corpo = ""
    for a in ordenados:
        celulas = ""
        for alvo in alvos:
            st = matriz[a["id"]].get(alvo, "—")
            rotulo = {"ok": "resistiu", "falhou": "CAIU", "erro": "erro"}.get(st, st)
            celulas += f'<td class="st-{st}">{rotulo}</td>'
        corpo += (
            f'<tr><td>{html.escape(a["id"])}</td>'
            f'<td class="sev-{a["severidade"]}">{a["severidade"]}</td>{celulas}</tr>'
        )

    placares = "".join(
        f'<div><div class="n {_classe(ex)}">'
        f'{html.escape(_nota(ex).replace("/100", ""))}</div><div class="l">{html.escape(ex["alvo"])[:40].upper()}</div></div>'
        for ex in execucoes
    )

    return f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Arena Cilada — comparativo</title>
<style>{_CSS}
td.st-falhou{{color:var(--alerta);font-weight:600}}td.st-ok{{color:var(--signal)}}
td.sev-critica{{color:var(--alerta)}}td.sev-alta{{color:var(--atencao)}}
</style></head><body><div class="wrap">
<p class="kicker">// arena — mesma suíte, alvos diferentes</p>
<h1>Comparativo de robustez</h1>
<div class="meta"><span>{len(ordenados)} ataques</span><span>cilada v0.1</span></div>
<div class="placar">{placares}</div>
<h2>Ataque a ataque</h2>
<table><thead><tr><th>ataque</th><th>sev.</th>{cabecalho}</tr></thead><tbody>{corpo}</tbody></table>
<footer>
Todos os alvos são configurações hospedadas por nós — nosso deploy, nosso prompt,
nossa conta de API. Nenhum bot de terceiro foi testado em produção.<br>
<a href="https://github.com/JoseTorquato/cilada">Cilada</a> ·
<a href="https://josetorquato.dev">josetorquato.dev</a>
</footer></div></body></html>"""


def main(argv: list[str] | None = None) -> int:
    for fluxo in (sys.stdout, sys.stderr):
        if hasattr(fluxo, "reconfigure"):
            fluxo.reconfigure(encoding="utf-8", errors="replace")

    p = argparse.ArgumentParser(prog="cilada-compara", description="Compara execuções do Cilada.")
    p.add_argument("resultados", nargs="+", help="arquivos JSON gerados por cilada run --json")
    p.add_argument("--html", help="grava o comparativo em HTML")
    args = p.parse_args(argv)

    execucoes = carrega(args.resultados)
    print()
    print(markdown(execucoes))
    print()
    if args.html:
        Path(args.html).write_text(para_html(execucoes), encoding="utf-8")
        print(f"  arena: {args.html}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
