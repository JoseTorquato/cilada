"""Linha de comando do Cilada."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from . import __version__, arena, report
from .attacks import carregar
from .runner import executa
from .targets import AlvoHTTP, de_config

_AQUI = Path(__file__).resolve().parent
# instalado, os ataques vêm dentro do pacote; no repo clonado, ficam na raiz
RAIZ_PADRAO = _AQUI / "attacks" if (_AQUI / "attacks").is_dir() else _AQUI.parent / "attacks"


def _monta_alvo(args):
    if args.config:
        cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8")) or {}
        alvo = cfg["alvo"]
        # trocar só o modelo mantendo o mesmo system prompt é o que torna a
        # comparação da arena honesta — uma config, vários alvos
        if args.modelo:
            alvo = {**alvo, "modelo": args.modelo, "nome": args.nome or args.modelo}
        elif args.nome:
            alvo = {**alvo, "nome": args.nome}
        return de_config(alvo)
    if args.target:
        return AlvoHTTP(url=args.target, nome=args.nome or args.target, campo_resposta=args.campo)
    raise SystemExit("informe --target URL ou --config arquivo.yaml")


def _arena(args, ataques, suites) -> int:
    if not args.lista:
        raise SystemExit("arena: informe --lista arquivo.yaml")
    try:
        planos = arena.carrega_lista(Path(args.lista))
    except (ValueError, KeyError) as erro:
        print(f"  lista da arena inválida: {erro}", file=sys.stderr)
        return 2
    print(arena.plano_texto(planos, ataques))
    if args.seco:
        print("  --seco: nada foi executado.\n")
        return 0
    try:
        execucoes = arena.roda(
            planos, ataques, suites, Path(args.saida), args.paralelo,
            permitir_remoto=args.permitir_remoto,
            ao_terminar=lambda r: print(report.linha_resultado(r)),
        )
    except PermissionError as erro:
        print(f"  {erro}\n", file=sys.stderr)
        return 2
    for ex in execucoes:
        print(report.resumo(ex, suites))
    print(f"  comparativo: {Path(args.saida) / 'arena.html'}\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    # console do Windows costuma abrir em cp1252 e picotar os acentos do laudo
    for fluxo in (sys.stdout, sys.stderr):
        if hasattr(fluxo, "reconfigure"):
            fluxo.reconfigure(encoding="utf-8", errors="replace")

    p = argparse.ArgumentParser(
        prog="cilada",
        description="Suíte adversarial em português brasileiro para agentes de IA.",
    )
    p.add_argument(
        "comando",
        choices=["run", "list", "arena"],
        help="run: ataca um alvo. list: lista ataques. arena: vários alvos e o comparativo.",
    )
    p.add_argument("--target", help="URL do endpoint do agente (POST JSON)")
    p.add_argument("--config", help="arquivo de configuração com o bloco alvo:")
    p.add_argument("--nome", help="nome do alvo no laudo")
    p.add_argument("--modelo", help="sobrescreve o modelo da config (mesmo prompt, outro alvo)")
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
    p.add_argument("--lista", help="arena: arquivo com base: e alvos:")
    p.add_argument("--seco", action="store_true", help="arena: mostra o plano e as chamadas, sem executar")
    p.add_argument("--saida", default="arena", help="arena: pasta dos JSON e do comparativo (padrão: arena/)")
    p.add_argument(
        "--permitir-remoto",
        action="store_true",
        help="arena: permite alvo fora de localhost (API paga custa por chamada)",
    )
    p.add_argument("--version", action="version", version=f"cilada {__version__}")
    args = p.parse_args(argv)

    raiz = Path(args.attacks)
    suites = args.suite or [d.name for d in sorted(raiz.iterdir()) if d.is_dir()]
    ataques = [a for s in suites for a in carregar(raiz, s)]
    if not ataques:
        print("nenhum ataque encontrado", file=sys.stderr)
        return 2

    if args.comando == "arena":
        return _arena(args, ataques, suites)

    if args.comando == "list":
        for a in ataques:
            print(f"  {a.severidade:<8} {a.id:<34} {a.titulo}")
        print(f"\n  {len(ataques)} ataques em {len(suites)} suíte(s): {', '.join(suites)}\n")
        return 0

    try:
        alvo = _monta_alvo(args)
    except (ValueError, KeyError) as erro:
        # mensagem curta, sem traceback: as mensagens de config nunca trazem valores
        print(f"  config do alvo inválida: {erro}", file=sys.stderr)
        return 2
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
