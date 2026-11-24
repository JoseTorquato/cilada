"""Amostra para revisão humana e medição dos juízes.

    cilada revisao exportar --resultado r.json [--resultado r2.json] [--n 30] [--semente 42] [--saida revisao]
    cilada revisao medir revisao.csv                       # depois de marcar a coluna rotulo_humano
    cilada revisao medir frases.jsonl [--juiz juiz.yaml]   # frases rotuladas, sem execução prévia

`exportar` lê os JSON de `cilada run --json` e gera:

- `<saida>.csv` e `<saida>.html` — o que o humano marca: a conversa, o critério
  do ataque e uma coluna `rotulo_humano` (cedeu | recusou). **Sem os vereditos
  dos juízes**, para não enviesar quem marca;
- `<saida>.gabarito.json` — os vereditos (regex, juiz LLM, combinado) por linha,
  que o `medir` lê depois.

Entram TODAS as divergências regex × LLM e todos os ambíguos, mais N respostas
sorteadas do resto com semente fixa (mesma semente, mesma amostra).

`medir` calcula, por juiz (regex, juiz LLM, combinado): concordância com o
humano, falsos negativos (humano: cedeu; juiz: não) e falsos positivos (humano:
recusou; juiz: cedeu), no total, por ataque e por severidade. Ambíguo e
"revisar" contam como "não acusou" — nunca como acusação — e são contados à
parte.

Formato de frases rotuladas (JSONL, uma por linha):

    {"ataque": "pix-agendado-cancelado", "resposta": "texto do agente", "rotulo": "cedeu"}

`rotulo` é `cedeu` ou `recusou`. Em vez de `resposta`, pode vir `respostas`
(lista, uma por turno do ataque). Com `resposta`, os turnos anteriores recebem
"Entendi." e a frase vai no último turno. Os campos extras são ignorados.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

from .attacks import carregar
from .report import _CSS, mascara
from .runner import executa_um

JUIZES = ("regex", "juiz_llm", "combinado")
ROTULOS = ("cedeu", "recusou")


def _raiz_padrao() -> Path:
    from .cli import RAIZ_PADRAO

    return RAIZ_PADRAO


def _ataques(raiz: Path | None = None) -> dict:
    return {a.id: a for a in carregar(raiz or _raiz_padrao())}


def _conversa(turnos: list[str], respostas: list[str]) -> str:
    partes = []
    for i, turno in enumerate(turnos):
        partes.append(f"cliente: {turno}")
        if i < len(respostas):
            partes.append(f"agente: {respostas[i]}")
    return mascara("\n".join(partes))


# ---- exportar ---------------------------------------------------------------

def _linhas_de(resultados_json: list[Path]) -> list[dict]:
    linhas = []
    for caminho in resultados_json:
        doc = json.loads(Path(caminho).read_text(encoding="utf-8"))
        for r in doc["resultados"]:
            if r.get("status") == "erro":
                continue
            juiz = r.get("juiz_llm") or {}
            linhas.append({
                "alvo": doc["alvo"],
                "ataque": r["id"],
                "severidade": r["severidade"],
                "conversa": _conversa(r.get("turnos", []), r.get("respostas", [])),
                "regex": r.get("regex") or ("cedeu" if r.get("status") == "falhou" else "passou"),
                "juiz_llm": juiz.get("veredito", ""),
                "combinado": r.get("status", ""),
                "revisar": bool(r.get("para_revisao")) or juiz.get("veredito") == "ambiguo",
            })
    return linhas


def exportar(resultados_json: list[Path], n: int, semente: int, saida: Path) -> dict:
    linhas = _linhas_de(resultados_json)
    obrigatorias = [l for l in linhas if l["revisar"]]
    resto = [l for l in linhas if not l["revisar"]]
    sorteadas = random.Random(semente).sample(resto, min(n, len(resto)))
    escolhidas = [(l, "divergencia ou ambiguo") for l in obrigatorias] + [(l, "amostra") for l in sorteadas]

    ataques = _ataques()
    gabarito = {}
    saida.parent.mkdir(parents=True, exist_ok=True)
    with open(f"{saida}.csv", "w", encoding="utf-8-sig", newline="") as arq:
        w = csv.writer(arq)
        w.writerow(["linha", "alvo", "ataque", "severidade", "conversa",
                    "criterio_cedeu", "criterio_recusou", "rotulo_humano", "observacao"])
        for i, (l, motivo) in enumerate(escolhidas, 1):
            crit = ataques[l["ataque"]].criterio_juiz if l["ataque"] in ataques else {}
            w.writerow([i, l["alvo"], l["ataque"], l["severidade"], l["conversa"],
                        crit.get("cedeu", ""), crit.get("recusou", ""), "", ""])
            gabarito[str(i)] = {k: l[k] for k in ("ataque", "severidade", "regex", "juiz_llm", "combinado")}
            gabarito[str(i)]["motivo"] = motivo
    Path(f"{saida}.gabarito.json").write_text(
        json.dumps({"semente": semente, "n_amostra": len(sorteadas), "linhas": gabarito},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    Path(f"{saida}.html").write_text(_html(escolhidas, ataques), encoding="utf-8")
    return {"total": len(escolhidas), "obrigatorias": len(obrigatorias), "amostra": len(sorteadas)}


def _html(escolhidas, ataques) -> str:
    blocos = []
    for i, (l, _motivo) in enumerate(escolhidas, 1):
        crit = ataques[l["ataque"]].criterio_juiz if l["ataque"] in ataques else {}
        blocos.append(
            f'<div class="achado"><h3>linha {i} · {html.escape(l["ataque"])}'
            f'<span class="sev {html.escape(l["severidade"])}">{html.escape(l["severidade"])}</span></h3>'
            f'<div class="id">alvo: {html.escape(l["alvo"])}</div>'
            f'<div class="bloco"><span class="bloco-tag">conversa</span>'
            f'<div class="citacao">{html.escape(l["conversa"])}</div></div>'
            f'<div class="bloco"><span class="bloco-tag">critério</span>'
            f'<p>Cedeu: {html.escape(crit.get("cedeu", ""))}<br>Recusou: {html.escape(crit.get("recusou", ""))}</p></div>'
            '<p class="nota">Marque no CSV, na linha correspondente: <strong>cedeu</strong> ou '
            '<strong>recusou</strong>. Deixe vazio se não der para decidir.</p></div>'
        )
    return f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><title>Cilada — revisão humana</title>
<style>{_CSS}</style></head><body><div class="wrap">
<p class="kicker">// revisão humana — os vereditos dos juízes ficam ocultos de propósito</p>
<h1>{len(escolhidas)} conversas para marcar</h1>
{''.join(blocos)}
</div></body></html>"""


# ---- medir --------------------------------------------------------------------

def _acusou(juiz: str, valor: str) -> bool:
    if juiz == "regex":
        return valor == "cedeu"
    if juiz == "juiz_llm":
        return valor == "cedeu"
    return valor == "falhou"


def _abstencao(juiz: str, valor: str) -> bool:
    return (juiz == "juiz_llm" and valor in ("ambiguo", "")) or (juiz == "combinado" and valor == "revisar")


def metricas(linhas: list[dict]) -> dict:
    """linhas: {ataque, severidade, rotulo, regex, juiz_llm, combinado}."""
    def conta(subset):
        out = {}
        for j in JUIZES:
            if j == "juiz_llm" and all(not l.get("juiz_llm") for l in subset):
                out[j] = None  # rodou sem juiz LLM
                continue
            fn = sum(1 for l in subset if l["rotulo"] == "cedeu" and not _acusou(j, l[j]))
            fp = sum(1 for l in subset if l["rotulo"] == "recusou" and _acusou(j, l[j]))
            ab = sum(1 for l in subset if _abstencao(j, l[j]))
            out[j] = {"n": len(subset), "acertos": len(subset) - fn - fp,
                      "falsos_negativos": fn, "falsos_positivos": fp, "ambiguos": ab}
        return out

    por_ataque, por_sev = defaultdict(list), defaultdict(list)
    for l in linhas:
        por_ataque[l["ataque"]].append(l)
        por_sev[l["severidade"]].append(l)
    return {
        "total": conta(linhas),
        "cedeu_humano": sum(1 for l in linhas if l["rotulo"] == "cedeu"),
        "recusou_humano": sum(1 for l in linhas if l["rotulo"] == "recusou"),
        "por_severidade": {k: conta(v) for k, v in sorted(por_sev.items())},
        "por_ataque": {k: conta(v) for k, v in sorted(por_ataque.items())},
    }


def _linhas_do_csv(caminho: Path, gabarito: Path) -> tuple[list[dict], int]:
    gab = json.loads(gabarito.read_text(encoding="utf-8"))["linhas"]
    linhas, sem_rotulo = [], 0
    with open(caminho, encoding="utf-8-sig", newline="") as arq:
        for row in csv.DictReader(arq):
            rotulo = (row.get("rotulo_humano") or "").strip().lower()
            if rotulo not in ROTULOS:
                sem_rotulo += 1
                continue
            g = gab[str(row["linha"]).strip()]
            linhas.append({"ataque": g["ataque"], "severidade": g["severidade"], "rotulo": rotulo,
                           "regex": g["regex"], "juiz_llm": g["juiz_llm"], "combinado": g["combinado"]})
    return linhas, sem_rotulo


class _UltimoTurno:
    nome = "frases"

    def __init__(self, respostas: list[str]) -> None:
        self.respostas = respostas

    def conversa(self, turnos: list[str]) -> list[str]:
        return self.respostas


def _linhas_do_jsonl(caminho: Path, juiz=None, raiz: Path | None = None) -> tuple[list[dict], int]:
    ataques = _ataques(raiz)
    linhas, invalidas = [], 0
    for numero, bruta in enumerate(Path(caminho).read_text(encoding="utf-8").splitlines(), 1):
        if not bruta.strip():
            continue
        item = json.loads(bruta)
        ataque = ataques.get(item.get("ataque"))
        rotulo = str(item.get("rotulo", "")).lower()
        if ataque is None or rotulo not in ROTULOS:
            invalidas += 1
            continue
        if "respostas" in item:
            respostas = list(item["respostas"])
        else:
            respostas = ["Entendi."] * (len(ataque.turnos) - 1) + [item["resposta"]]
        r = executa_um(ataque, _UltimoTurno(respostas))
        if juiz is not None:
            r.juiz = juiz.julga(ataque, respostas)
        linhas.append({"ataque": ataque.id, "severidade": ataque.severidade, "rotulo": rotulo,
                       "regex": "cedeu" if r.vulneravel else "passou",
                       "juiz_llm": r.veredito_llm, "combinado": r.status})
    return linhas, invalidas


def _texto(m: dict, descartadas: int) -> str:
    def linha(nome, d):
        if d is None:
            return f"  {nome:<11} (não rodou)"
        pct = 100 * d["acertos"] / d["n"] if d["n"] else 0
        return (f"  {nome:<11} concordância {d['acertos']}/{d['n']} ({pct:.0f}%)"
                f" · FN {d['falsos_negativos']} · FP {d['falsos_positivos']} · ambíguos {d['ambiguos']}")

    out = [f"\n  {m['cedeu_humano']} cessões e {m['recusou_humano']} recusas segundo o humano"
           f" ({descartadas} sem rótulo, ignoradas)\n", "  total"]
    out += [linha(j, m["total"][j]) for j in JUIZES]
    for titulo, grupo in (("por severidade", m["por_severidade"]), ("por ataque", m["por_ataque"])):
        out.append(f"\n  {titulo}")
        for chave, d in grupo.items():
            out.append(f"   {chave}")
            out += ["  " + linha(j, d[j]) for j in JUIZES]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="cilada revisao", description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="acao", required=True)
    e = sub.add_parser("exportar", help="gera CSV + HTML para revisão humana")
    e.add_argument("--resultado", action="append", required=True, help="JSON de cilada run --json (repetível)")
    e.add_argument("--n", type=int, default=30, help="respostas sorteadas além das divergências (padrão 30)")
    e.add_argument("--semente", type=int, default=42)
    e.add_argument("--saida", default="revisao", help="prefixo dos arquivos (padrão: revisao)")
    m = sub.add_parser("medir", help="mede os juízes contra rótulos humanos")
    m.add_argument("arquivo", help="CSV marcado (de exportar) ou JSONL de frases rotuladas")
    m.add_argument("--gabarito", help="gabarito do CSV (padrão: <arquivo sem .csv>.gabarito.json)")
    m.add_argument("--juiz", help="JSONL: YAML com bloco juiz: para julgar as frases também pelo LLM")
    m.add_argument("--permitir-remoto", action="store_true")
    m.add_argument("--json", dest="saida_json", help="grava as métricas em JSON")
    args = p.parse_args(argv)

    if args.acao == "exportar":
        info = exportar([Path(x) for x in args.resultado], args.n, args.semente, Path(args.saida))
        print(f"\n  {info['total']} linhas ({info['obrigatorias']} divergências/ambíguos + "
              f"{info['amostra']} sorteadas, semente {args.semente})")
        print(f"  marcar: {args.saida}.csv (ou ler em {args.saida}.html)")
        print(f"  gabarito, não abrir antes de marcar: {args.saida}.gabarito.json\n")
        return 0

    arquivo = Path(args.arquivo)
    if arquivo.suffix == ".jsonl":
        juiz = None
        if args.juiz:
            from . import juiz as juiz_mod

            juiz = juiz_mod.carrega(Path(args.juiz))
            if juiz.remoto and not args.permitir_remoto:
                print("  o juiz é remoto; use --permitir-remoto", file=sys.stderr)
                return 2
        linhas, descartadas = _linhas_do_jsonl(arquivo, juiz)
    else:
        gabarito = Path(args.gabarito) if args.gabarito else arquivo.with_name(arquivo.stem + ".gabarito.json")
        linhas, descartadas = _linhas_do_csv(arquivo, gabarito)
    resultado = metricas(linhas)
    print(_texto(resultado, descartadas))
    if args.saida_json:
        Path(args.saida_json).write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0
