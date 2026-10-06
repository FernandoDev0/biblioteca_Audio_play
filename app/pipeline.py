"""Do PDF até o Opus. Extração de uma vez; dublagem em lote, página a página."""

from __future__ import annotations

import hashlib
import json
import re
import threading
import unicodedata
from pathlib import Path

from app.constantes import SCHEMA_ARQUIVO, VOZ
from app.db import (
    atualizar_status_pelo_andamento,
    blocos_para_dublar,
    conectar,
    criar_documento,
    definir_status,
    documento_por_hash,
    gravar_audio,
    inserir_pagina,
    marcar_erro_bloco,
    paginas_com_audio_pendente,
    paginas_do_documento,
    recalcular_duracoes,
    sincronizar_json_da_pagina,
)
from app.extract import PaginaExtraida, extrair_paginas
from app.paths import garantir_pastas, raiz_dados, relativo
from app.tts import gravar_clipe


class Cancelado(Exception):
    pass


_tts_lock = threading.Lock()


def sha256_arquivo(caminho: Path) -> str:
    digest = hashlib.sha256()
    with caminho.open("rb") as arquivo:
        for pedaco in iter(lambda: arquivo.read(1024 * 1024), b""):
            digest.update(pedaco)
    return digest.hexdigest()


def slugificar(nome: str) -> str:
    normal = unicodedata.normalize("NFKD", nome)
    ascii_nome = normal.encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_nome).strip("-")
    return (slug or "documento")[:80]


def _parar(cancelar: threading.Event | None) -> None:
    if cancelar is not None and cancelar.is_set():
        raise Cancelado()


def _escrever_txt(destino: Path, pagina: PaginaExtraida) -> None:
    partes: list[str] = []
    for bloco in pagina.blocos:
        if bloco.tipo == "imagem" and bloco.imagem is not None:
            partes.append(f"[imagem]\n{relativo(bloco.imagem)}\n")
        else:
            partes.append(f"[{bloco.tipo}]\n{bloco.texto}\n")
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text("\n".join(partes), encoding="utf-8")


def _escrever_json_inicial(destino: Path, pagina: PaginaExtraida, blocos: list[dict]) -> None:
    payload = {
        "schema": SCHEMA_ARQUIVO,
        "numero": pagina.numero,
        "ocr": pagina.ocr,
        "blocos": [
            {
                "ordem": bloco["ordem"],
                "tipo": bloco["tipo"],
                "dublar": bool(bloco["dublar"]),
                "texto": bloco["texto"],
                "bbox": json.loads(bloco["bbox"]) if bloco.get("bbox") else None,
                "audio": None,
                "cues": None,
                "imagem": bloco.get("imagem_relpath"),
                "duracao_ms": 0,
            }
            for bloco in blocos
        ],
    }
    destino.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _manifesto(pasta: Path, *, slug: str, titulo: str, sha: str, pdf_rel: str, paginas: int) -> None:
    payload = {
        "schema": SCHEMA_ARQUIVO,
        "slug": slug,
        "titulo": titulo,
        "voz": VOZ,
        "pdf_sha256": sha,
        "pdf": pdf_rel,
        "paginas": paginas,
    }
    (pasta / "manifest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def importar_pdf(
    pdf: Path,
    *,
    max_paginas_audio: int | None = None,
    progresso=None,
    cancelar: threading.Event | None = None,
) -> int:
    garantir_pastas()
    pdf = pdf.resolve()
    sha = sha256_arquivo(pdf)
    cx = conectar()
    doc_id = 0
    try:
        existente = documento_por_hash(cx, sha)
        if existente:
            doc_id = int(existente["id"])
            _avisar(progresso, "Este PDF já está no acervo. Continuo o que falta.")
        else:
            doc_id = _extrair(cx, pdf, sha, progresso, cancelar)
        dublar_pendentes(
            doc_id,
            max_paginas_audio=max_paginas_audio,
            progresso=progresso,
            cancelar=cancelar,
            conexao=cx,
        )
        return doc_id
    except Cancelado:
        if doc_id:
            atualizar_status_pelo_andamento(cx, doc_id)
        raise
    finally:
        cx.close()


def _extrair(cx, pdf: Path, sha: str, progresso, cancelar) -> int:
    titulo = pdf.stem
    slug = slugificar(titulo)
    ocupado = cx.execute(
        "SELECT pdf_sha256 FROM documento WHERE slug = ?",
        (slug,),
    ).fetchone()
    if ocupado is not None and ocupado["pdf_sha256"] != sha:
        slug = f"{slug}-{sha[:8]}"
    base = raiz_dados()
    pasta_pdf = base / "pdf" / slug
    pasta_pdf.mkdir(parents=True, exist_ok=True)
    destino_pdf = pasta_pdf / "source.pdf"
    if not destino_pdf.exists():
        destino_pdf.write_bytes(pdf.read_bytes())
    pdf_rel = relativo(destino_pdf)
    _avisar(progresso, "Lendo o PDF.")
    paginas = extrair_paginas(pdf, base / "imagens" / slug)
    _parar(cancelar)
    doc_id = criar_documento(
        cx,
        slug=slug,
        titulo=titulo,
        sha=sha,
        pdf_relpath=pdf_rel,
        paginas=len(paginas),
    )
    pasta_texto = base / "texto" / slug
    pasta_texto.mkdir(parents=True, exist_ok=True)
    _manifesto(pasta_texto, slug=slug, titulo=titulo, sha=sha, pdf_rel=pdf_rel, paginas=len(paginas))
    total = len(paginas)
    try:
        for indice, pagina in enumerate(paginas, start=1):
            _parar(cancelar)
            _avisar(progresso, f"Transcrevendo página {indice} de {total}.")
            txt = pasta_texto / f"p{pagina.numero:04d}.txt"
            blocos_json = pasta_texto / f"p{pagina.numero:04d}.blocks.json"
            _escrever_txt(txt, pagina)
            registros = []
            for ordem, bloco in enumerate(pagina.blocos, start=1):
                registros.append(
                    {
                        "ordem": ordem,
                        "tipo": bloco.tipo,
                        "dublar": bloco.dublar,
                        "texto": bloco.texto,
                        "imagem_relpath": relativo(bloco.imagem) if bloco.imagem else None,
                        "bbox": json.dumps(list(bloco.bbox)),
                    }
                )
            _escrever_json_inicial(blocos_json, pagina, registros)
            inserir_pagina(
                cx,
                doc_id=doc_id,
                numero=pagina.numero,
                largura=pagina.largura,
                altura=pagina.altura,
                texto_relpath=relativo(txt),
                blocos_relpath=relativo(blocos_json),
                ocr=pagina.ocr,
                blocos=registros,
            )
    except Cancelado:
        atualizar_status_pelo_andamento(cx, doc_id)
        raise
    definir_status(cx, doc_id, "parcial")
    return doc_id


def dublar_pendentes(
    doc_id: int,
    *,
    max_paginas_audio: int | None = None,
    progresso=None,
    cancelar: threading.Event | None = None,
    conexao=None,
) -> str:
    proprio = conexao is None
    cx = conexao or conectar()
    try:
        definir_status(cx, doc_id, "dublando")
        paginas = paginas_com_audio_pendente(cx, doc_id)
        if max_paginas_audio is not None:
            paginas = paginas[:max_paginas_audio]
        total = len(paginas)
        if total == 0:
            return atualizar_status_pelo_andamento(cx, doc_id)
        for indice, pagina in enumerate(paginas, start=1):
            _parar(cancelar)
            blocos = blocos_para_dublar(cx, int(pagina["id"]))
            for qual, bloco in enumerate(blocos, start=1):
                _parar(cancelar)
                _avisar(
                    progresso,
                    f"Dublando página {pagina['numero']} · trecho {qual} de {len(blocos)} "
                    f"({indice} de {total} páginas neste lote).",
                )
                _dublar_um(cx, bloco, permitir_whisper=False)
            recalcular_duracoes(cx, int(pagina["id"]))
            sincronizar_json_da_pagina(cx, int(pagina["id"]))
        return atualizar_status_pelo_andamento(cx, doc_id)
    except Cancelado:
        atualizar_status_pelo_andamento(cx, doc_id)
        raise
    finally:
        if proprio:
            cx.close()


def dublar_bloco(bloco_id: int, *, permitir_whisper: bool) -> None:
    cx = conectar()
    try:
        from app.db import bloco_por_id

        bloco = bloco_por_id(cx, bloco_id)
        if not bloco:
            raise RuntimeError("trecho não encontrado")
        if bloco["audio_relpath"]:
            return
        _dublar_um(cx, bloco, permitir_whisper=permitir_whisper)
        recalcular_duracoes(cx, int(bloco["pagina_id"]))
        sincronizar_json_da_pagina(cx, int(bloco["pagina_id"]))
        atualizar_status_pelo_andamento(cx, int(bloco["documento_id"]))
    finally:
        cx.close()


def _dublar_um(cx, bloco: dict, *, permitir_whisper: bool) -> None:
    texto = (bloco["texto"] or "").strip()
    if not texto:
        return
    doc = cx.execute(
        """
        SELECT d.slug
        FROM documento d
        JOIN pagina p ON p.documento_id = d.id
        WHERE p.id = ?
        """,
        (bloco["pagina_id"],),
    ).fetchone()
    numero = cx.execute(
        "SELECT numero FROM pagina WHERE id = ?",
        (bloco["pagina_id"],),
    ).fetchone()["numero"]
    pasta = raiz_dados() / "audio" / doc["slug"] / f"p{int(numero):04d}"
    opus = pasta / f"b{int(bloco['ordem']):04d}.opus"
    cues = pasta / f"b{int(bloco['ordem']):04d}.cues.json"
    try:
        with _tts_lock:
            if opus.exists() and cues.exists() and opus.stat().st_size > 16:
                dados = json.loads(cues.read_text(encoding="utf-8"))
                duracao = int(dados.get("duracao_ms") or 0)
                palavras = dados.get("palavras") or []
            else:
                duracao, palavras = gravar_clipe(
                    texto,
                    opus,
                    cues,
                    permitir_whisper=permitir_whisper,
                )
        gravar_audio(
            cx,
            bloco_id=int(bloco["id"]),
            audio_relpath=relativo(opus),
            cues_relpath=relativo(cues),
            duracao_ms=duracao,
            palavras=palavras,
        )
    except Cancelado:
        raise
    except Exception as erro:
        marcar_erro_bloco(cx, int(bloco["id"]), str(erro))


def _avisar(progresso, mensagem: str) -> None:
    if progresso is not None:
        progresso(mensagem)


def contagem(doc_id: int) -> tuple[int, int]:
    cx = conectar()
    try:
        paginas = paginas_do_documento(cx, doc_id)
        prontas = sum(1 for p in paginas if int(p["duracao_ms"]) > 0)
        return len(paginas), prontas
    finally:
        cx.close()
