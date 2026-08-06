"""Linha de comando do Cilada."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from . import __version__, report
from .attacks import carregar
from .runner import executa
from .targets import AlvoHTTP, de_config

_AQUI = Path(__file__).resolve().parent
# instalado, os ataques vêm dentro do pacote; no repo clonado, ficam na raiz
RAIZ_PADRAO = _AQUI / "attacks" if (_AQUI / "attacks").is_dir() else _AQUI.parent / "attacks"


def _monta_alvo(args):
    if args.config:
        cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8")) or {}
        return de_config(cfg["alvo"])
    if args.target:
        return AlvoHTTP(url=args.target, nome=args.nome or args.target, campo_resposta=args.campo)
    raise SystemExit("informe --target URL ou --config arquivo.yaml")


def main(argv: list[str] | None = None) -> int:
    # console do Windows costuma abrir em cp1252 e picotar os acentos do laudo
    for fluxo in (sys.stdout, sys.stderr):
        if hasattr(fluxo, "reconfigure"):
            fluxo.reconfigure(encoding="utf-8", errors="replace")

    p = argparse.ArgumentParser(
        prog="cilada",
        description="Suíte adversarial em português brasileiro para agentes de IA.",
    )
    p.add_argument("comando", choices=["run", "list"], help="run: ataca um alvo. list: lista ataques.")
    p.add_argument("--target", help="URL do endpoint do agente (POST JSON)")
    p.add_argument("--config", help="arquivo de configuração com o bloco alvo:")
    p.add_argument("--nome", help="nome do alvo no laudo")
    p.add_argument("--campo", default="resposta", help="caminho do texto na resposta JSON")
    p.add_argument("--suite", action="append", help="suíte a rodar (repetível). Padrão: todas")
    p.add_argument("--attacks", default=str(RAIZ_PADRAO), help="pasta com os YAML de ataque")
    p.add_argument("--json", dest="saida_json", help="grava o resultado bruto em JSON")
    p.add_argument("--html", dest="saida_html", help="grava o laudo HTML")
    p.add_argument("--paralelo", type=int, default=4, help="ataques simultâneos (padrão 4)")
    p.add_argument(
        "--falhar-em",
        choices=["nunca", "critica", "qualquer"],
        default="critica",
        help="quando sair com código 1 — use em CI (padrão: critica)",
    )
    p.add_argument("--version", action="version", version=f"cilada {__version__}")
    args = p.parse_args(argv)

    raiz = Path(args.attacks)
    suites = args.suite or [d.name for d in sorted(raiz.iterdir()) if d.is_dir()]
    ataques = [a for s in suites for a in carregar(raiz, s)]
    if not ataques:
        print("nenhum ataque encontrado", file=sys.stderr)
        return 2

    if args.comando == "list":
        for a in ataques:
            print(f"  {a.severidade:<8} {a.id:<34} {a.titulo}")
        print(f"\n  {len(ataques)} ataques em {len(suites)} suíte(s): {', '.join(suites)}\n")
        return 0

    alvo = _monta_alvo(args)
    print(f"\n  cilada v{__version__} · {len(ataques)} ataques · pt-BR\n")
    execucao = executa(ataques, alvo, args.paralelo, ao_terminar=lambda r: print(report.linha_resultado(r)))
    print(report.resumo(execucao, suites))

    if args.saida_json:
        Path(args.saida_json).write_text(report.para_json(execucao), encoding="utf-8")
        print(f"  json:  {args.saida_json}")
    if args.saida_html:
        Path(args.saida_html).write_text(report.para_html(execucao, suites), encoding="utf-8")
        print(f"  laudo: {args.saida_html}")
    if args.saida_json or args.saida_html:
        print()

    if args.falhar_em == "qualquer" and execucao.falhas:
        return 1
    if args.falhar_em == "critica" and execucao.criticas:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
