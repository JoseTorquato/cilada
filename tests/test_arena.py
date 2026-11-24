"""Testes da arena — só com alvos falsos locais.

Os alvos são o bot-cobaia em threads, em portas livres de 127.0.0.1. Nenhum
teste toca modelo em nuvem: a trava de alvo remoto é testada sem rede, porque
ela recusa antes de qualquer conexão.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from cilada import arena, cli  # noqa: E402
from cilada.attacks import carregar  # noqa: E402

_spec = importlib.util.spec_from_file_location("bot_cobaia", RAIZ / "examples" / "bot_cobaia.py")
bot_cobaia = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bot_cobaia)

ATAQUES = carregar(RAIZ / "attacks")


class Contador:
    n = 0


@pytest.fixture
def bots():
    """Dois bot-cobaia locais (ingênuo e blindado) que contam as chamadas."""
    servidores, contador = [], Contador()
    for modo in ("ingenuo", "blindado"):
        base = bot_cobaia.cria_handler(modo)

        class Handler(base):
            def do_POST(self):  # noqa: N802
                contador.n += 1
                super().do_POST()

        srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        servidores.append(srv)
    yield [f"http://127.0.0.1:{s.server_address[1]}/chat" for s in servidores], contador
    for s in servidores:
        s.shutdown()


def _lista(tmp_path: Path, urls: list[str], **extra) -> Path:
    doc = {
        "base": {"tipo": "http", "campo_resposta": "resposta"},
        "alvos": [{"nome": "ingenuo", "url": urls[0]}, {"nome": "blindado", "url": urls[1]}],
        **extra,
    }
    caminho = tmp_path / "lista.yaml"
    caminho.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    return caminho


def test_seco_mostra_o_plano_e_nao_chama_ninguem(bots, tmp_path, capsys):
    urls, contador = bots
    lista = _lista(tmp_path, urls)
    assert cli.main(["arena", "--lista", str(lista), "--seco", "--saida", str(tmp_path / "out")]) == 0
    saida = capsys.readouterr().out
    por_alvo = sum(len(a.turnos) for a in ATAQUES)
    assert f"{por_alvo} chamadas por alvo" in saida
    assert f"total: {por_alvo * 2} chamadas ({por_alvo} × 2 alvos)" in saida
    assert "nada foi executado" in saida
    assert contador.n == 0, "o --seco não pode fazer nenhuma chamada"
    assert not (tmp_path / "out").exists()


def test_arena_roda_todos_e_gera_o_comparativo(bots, tmp_path):
    urls, contador = bots
    lista = _lista(tmp_path, urls)
    out = tmp_path / "out"
    assert cli.main(["arena", "--lista", str(lista), "--saida", str(out)]) == 0
    assert contador.n == 2 * sum(len(a.turnos) for a in ATAQUES)
    ingenuo = json.loads((out / "ingenuo.json").read_text(encoding="utf-8"))
    blindado = json.loads((out / "blindado.json").read_text(encoding="utf-8"))
    assert ingenuo["placar"] == 0 and blindado["placar"] == 100
    html = (out / "arena.html").read_text(encoding="utf-8")
    assert "ingenuo" in html and "blindado" in html and "CAIU" in html
    assert "| **robustez** | **0/100** | **100/100** |" in (out / "arena.md").read_text(encoding="utf-8")


def test_alvo_remoto_e_barrado_sem_permissao(tmp_path, capsys):
    lista = tmp_path / "lista.yaml"
    lista.write_text(yaml.safe_dump({
        "base": {"tipo": "openai", "system": "s", "base_url": "https://api.exemplo.invalid/v1",
                 "api_key_env": "NAO_EXISTE"},
        "alvos": [{"modelo": "modelo-a"}, {"modelo": "modelo-b"}],
    }), encoding="utf-8")
    assert cli.main(["arena", "--lista", str(lista), "--saida", str(tmp_path / "out")]) == 2
    erro = capsys.readouterr()
    assert "REMOTO" in erro.out and "--permitir-remoto" in erro.err
    assert not (tmp_path / "out").exists()


def test_seco_de_lista_remota_funciona_e_avisa(tmp_path, capsys):
    """Ver o custo de uma lista em nuvem não pode exigir chave nem rede."""
    lista = tmp_path / "lista.yaml"
    lista.write_text(yaml.safe_dump({
        "base": {"tipo": "openai", "system": "s", "base_url": "https://api.exemplo.invalid/v1",
                 "api_key_env": "NAO_EXISTE"},
        "alvos": [{"modelo": "a"}, {"modelo": "b"}, {"modelo": "c"}],
    }), encoding="utf-8")
    assert cli.main(["arena", "--lista", str(lista), "--seco"]) == 0
    saida = capsys.readouterr().out
    por_alvo = sum(len(a.turnos) for a in ATAQUES)
    assert f"{por_alvo * 3} delas em alvo remoto" in saida


def test_config_base_e_sobrescrita_por_alvo(tmp_path):
    cfg = tmp_path / "base.yaml"
    cfg.write_text(yaml.safe_dump({"alvo": {"tipo": "openai", "system": "prompt comum",
                                            "base_url": "http://localhost:11434/v1",
                                            "modelo": "padrao"}}), encoding="utf-8")
    lista = tmp_path / "lista.yaml"
    lista.write_text(yaml.safe_dump({"config": "base.yaml",
                                     "alvos": [{"modelo": "m1"}, {"modelo": "m2", "nome": "Dois"}]}),
                     encoding="utf-8")
    planos = arena.carrega_lista(lista)
    assert [p.nome for p in planos] == ["m1", "Dois"]
    assert all(p.cfg["system"] == "prompt comum" and not p.remoto for p in planos)
    assert planos[1].cfg["modelo"] == "m2"


@pytest.mark.parametrize("doc,mensagem", [
    ({"alvos": []}, "não tem `alvos:`"),
    ({"base": {"tipo": "http"}, "alvos": [{"url": "http://127.0.0.1:1/a", "nome": "x"},
                                         {"url": "http://127.0.0.1:1/b", "nome": "x"}]}, "repetido"),
    ({"alvos": ["so-um-texto"]}, "precisa ser um bloco"),
])
def test_lista_invalida_falha_antes_de_executar(tmp_path, doc, mensagem):
    lista = tmp_path / "lista.yaml"
    lista.write_text(yaml.safe_dump(doc), encoding="utf-8")
    with pytest.raises(ValueError, match=mensagem):
        arena.carrega_lista(lista)


def test_exemplo_versionado_e_local():
    planos = arena.carrega_lista(RAIZ / "examples" / "arena-local.yaml")
    assert len(planos) == 2 and not any(p.remoto for p in planos)


# ---- contornos da trava de remoto (revisão do PR #3) ----------------------
#
# A trava lia base_url||url do dict, mas cada tipo de alvo usa um campo só.
# Os testes bloqueiam o socket e contam tentativas: tem de dar zero.

@pytest.fixture
def sem_rede(monkeypatch):
    import socket

    tentativas = []

    def bloqueado(*a, **_k):
        tentativas.append(a)
        raise OSError("rede bloqueada no teste")

    monkeypatch.setattr(socket.socket, "connect", bloqueado)
    monkeypatch.setattr(socket, "create_connection", bloqueado)
    return tentativas


@pytest.mark.parametrize("base,alvos", [
    # (a) openai com `url` local e sem base_url: o alvo usa o padrão da OpenAI
    ({"tipo": "openai", "system": "s", "api_key_env": "NAO_EXISTE"},
     [{"modelo": "m", "url": "http://127.0.0.1:11434/v1"}]),
    # (b) http com `url` remota e `base_url` local: o alvo usa a url
    ({"tipo": "http", "base_url": "http://localhost:9/v1"},
     [{"nome": "x", "url": "https://api.example.invalid/chat"}]),
])
def test_contorno_por_campo_errado_e_barrado_sem_conexao(tmp_path, capsys, sem_rede, base, alvos):
    """Barrado de um jeito ou de outro: campo recusado no carregamento, ou alvo
    classificado como remoto. O que não pode é rodar."""
    lista = tmp_path / "lista.yaml"
    lista.write_text(yaml.safe_dump({"base": base, "alvos": alvos}), encoding="utf-8")
    try:
        planos = arena.carrega_lista(lista)
    except ValueError:
        planos = None  # config com campo que o tipo não usa é recusada
    if planos is not None:
        assert all(p.remoto for p in planos), [(p.nome, p.endereco) for p in planos]
    assert cli.main(["arena", "--lista", str(lista), "--saida", str(tmp_path / "out")]) == 2
    saida = capsys.readouterr()
    assert "REMOTO" in saida.out or "inválida" in saida.err
    assert sem_rede == [], "a trava tem de recusar antes de qualquer conexão"
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("endereco", ["", "nao-e-url", "http://", "http://[::1"])
def test_endereco_ilegivel_conta_como_remoto(endereco):
    assert arena._remoto(endereco)


def test_alvo_de_tipo_desconhecido_nao_tem_endereco():
    class Estranho:
        nome = "x"

    assert arena.endereco_do_alvo(Estranho()) == ""
    assert arena._remoto(arena.endereco_do_alvo(Estranho()))


def test_roda_reconfere_no_objeto_mesmo_com_plano_adulterado(tmp_path, sem_rede):
    """Se alguém montar um PlanoAlvo dizendo 'local', o objeto construído manda."""
    plano = arena.PlanoAlvo(nome="x", cfg={"tipo": "http", "url": "https://api.example.invalid/c"},
                            endereco="http://127.0.0.1/c", remoto=False)
    with pytest.raises(PermissionError):
        arena.roda([plano], ATAQUES[:1], ["ecommerce"], tmp_path / "out")
    assert sem_rede == []


def test_lista_invalida_pela_cli_sai_com_codigo_2_sem_traceback(tmp_path, capsys):
    lista = tmp_path / "lista.yaml"
    lista.write_text(yaml.safe_dump({"alvos": []}), encoding="utf-8")
    assert cli.main(["arena", "--lista", str(lista), "--seco"]) == 2
    assert "inválida" in capsys.readouterr().err
