"""Conexão SQLite por thread, WAL, e o índice que a leitura consulta.

O arquivo em disco é o índice. Texto, cues e Opus ficam ao lado, em pastas,
para a biblioteca mudar de máquina sem regravar áudio.
https://sqlite.org/wal.html
https://docs.python.org/3/library/sqlite3.html
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from app.constantes import SCHEMA_DB, VOZ
from app.paths import absoluto, banco, garantir_pastas, raiz_dados, relativo

_SCHEMA = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")


def conectar() -> sqlite3.Connection:
    garantir_pastas()
    cx = sqlite3.connect(banco(), timeout=5.0, isolation_level=None)
    cx.row_factory = sqlite3.Row
    cx.execute("PRAGMA foreign_keys = ON")
    cx.execute("PRAGMA busy_timeout = 5000")
    cx.execute("PRAGMA journal_mode = WAL")
    cx.execute("PRAGMA synchronous = NORMAL")
    cx.execute("PRAGMA temp_store = MEMORY")
    cx.execute("PRAGMA cache_size = -64000")
    cx.execute("PRAGMA mmap_size = 268435456")
    migrar(cx)
    return cx


def migrar(cx: sqlite3.Connection) -> None:
    versao = int(cx.execute("PRAGMA user_version").fetchone()[0])
    if versao >= SCHEMA_DB:
        return
    if versao != 0:
        raise RuntimeError(f"banco numa versão que este aplicativo não migra: {versao}")
    cx.executescript(_SCHEMA)
    cx.execute(f"PRAGMA user_version = {SCHEMA_DB}")


def fechar(cx: sqlite3.Connection) -> None:
    try:
        cx.execute("PRAGMA optimize")
    finally:
        cx.close()


def _um(cx: sqlite3.Connection, sql: str, params: tuple | dict = ()) -> dict | None:
    linha = cx.execute(sql, params).fetchone()
    return dict(linha) if linha else None


def _varios(cx: sqlite3.Connection, sql: str, params: tuple | dict = ()) -> list[dict]:
    return [dict(linha) for linha in cx.execute(sql, params)]


def documento_por_hash(cx: sqlite3.Connection, sha: str) -> dict | None:
    return _um(cx, "SELECT * FROM documento WHERE pdf_sha256 = ?", (sha,))


def obter_documento(cx: sqlite3.Connection, doc_id: int) -> dict | None:
    return _um(cx, "SELECT * FROM documento WHERE id = ?", (doc_id,))


def listar_documentos(cx: sqlite3.Connection) -> list[dict]:
    return _varios(
        cx,
        """
        SELECT
          d.*,
          (SELECT COUNT(*) FROM pagina p WHERE p.documento_id = d.id AND p.lida = 1) AS lidas,
          (SELECT COUNT(*) FROM pagina p WHERE p.documento_id = d.id AND p.duracao_ms > 0) AS paginas_com_audio
        FROM documento d
        ORDER BY d.atualizado_em DESC, d.id DESC
        """,
    )


def criar_documento(
    cx: sqlite3.Connection,
    *,
    slug: str,
    titulo: str,
    sha: str,
    pdf_relpath: str,
    paginas: int,
) -> int:
    cx.execute("BEGIN IMMEDIATE")
    try:
        linha = cx.execute(
            """
            INSERT INTO documento (slug, titulo, pdf_sha256, pdf_relpath, paginas, voz, status)
            VALUES (?, ?, ?, ?, ?, ?, 'extraindo')
            RETURNING id
            """,
            (slug, titulo, sha, pdf_relpath, paginas, VOZ),
        ).fetchone()
        cx.execute("COMMIT")
    except Exception:
        cx.execute("ROLLBACK")
        raise
    return int(linha["id"])


def definir_status(cx: sqlite3.Connection, doc_id: int, status: str) -> None:
    cx.execute(
        """
        UPDATE documento
        SET status = ?, atualizado_em = datetime('now')
        WHERE id = ?
        """,
        (status, doc_id),
    )


def inserir_pagina(
    cx: sqlite3.Connection,
    *,
    doc_id: int,
    numero: int,
    largura: float,
    altura: float,
    texto_relpath: str,
    blocos_relpath: str,
    ocr: bool,
    blocos: list[dict],
) -> int:
    cx.execute("BEGIN IMMEDIATE")
    try:
        pagina = cx.execute(
            """
            INSERT INTO pagina (
              documento_id, numero, largura, altura, texto_relpath, blocos_relpath, ocr
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            (doc_id, numero, largura, altura, texto_relpath, blocos_relpath, int(ocr)),
        ).fetchone()
        pagina_id = int(pagina["id"])
        for bloco in blocos:
            cx.execute(
                """
                INSERT INTO bloco (
                  pagina_id, ordem, tipo, dublar, texto, imagem_relpath, bbox
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    pagina_id,
                    bloco["ordem"],
                    bloco["tipo"],
                    int(bloco["dublar"]),
                    bloco["texto"],
                    bloco.get("imagem_relpath"),
                    bloco.get("bbox"),
                ),
            )
        cx.execute("COMMIT")
    except Exception:
        cx.execute("ROLLBACK")
        raise
    return pagina_id


def paginas_do_documento(cx: sqlite3.Connection, doc_id: int) -> list[dict]:
    return _varios(
        cx,
        "SELECT * FROM pagina WHERE documento_id = ? ORDER BY numero",
        (doc_id,),
    )


def blocos_da_pagina(cx: sqlite3.Connection, pagina_id: int) -> list[dict]:
    return _varios(
        cx,
        "SELECT * FROM bloco WHERE pagina_id = ? ORDER BY ordem",
        (pagina_id,),
    )


def bloco_por_id(cx: sqlite3.Connection, bloco_id: int) -> dict | None:
    return _um(
        cx,
        """
        SELECT b.*, p.numero AS pagina_numero, p.documento_id
        FROM bloco b
        JOIN pagina p ON p.id = b.pagina_id
        WHERE b.id = ?
        """,
        (bloco_id,),
    )


def palavras_do_bloco(cx: sqlite3.Connection, bloco_id: int) -> list[dict]:
    return _varios(
        cx,
        """
        SELECT ordem, texto, inicio_ms, fim_ms
        FROM palavra
        WHERE bloco_id = ?
        ORDER BY ordem
        """,
        (bloco_id,),
    )


def paginas_com_audio_pendente(cx: sqlite3.Connection, doc_id: int) -> list[dict]:
    return _varios(
        cx,
        """
        SELECT p.id, p.numero
        FROM pagina p
        WHERE p.documento_id = ?
          AND EXISTS (
            SELECT 1 FROM bloco b
            WHERE b.pagina_id = p.id
              AND b.dublar = 1
              AND b.audio_relpath IS NULL
          )
        ORDER BY p.numero
        """,
        (doc_id,),
    )


def narracao_desde(cx: sqlite3.Connection, doc_id: int, pagina_inicial: int) -> list[dict]:
    """Trechos para ler em sequência: o que deve ser dublado e o que já tem áudio."""
    return _varios(
        cx,
        """
        SELECT b.*, p.numero AS pagina_numero
        FROM bloco b
        JOIN pagina p ON p.id = b.pagina_id
        WHERE p.documento_id = ?
          AND p.numero >= ?
          AND b.tipo != 'imagem'
          AND length(trim(b.texto)) > 0
          AND (b.dublar = 1 OR b.audio_relpath IS NOT NULL)
        ORDER BY p.numero, b.ordem
        """,
        (doc_id, pagina_inicial),
    )


def blocos_para_dublar(cx: sqlite3.Connection, pagina_id: int) -> list[dict]:
    return _varios(
        cx,
        """
        SELECT * FROM bloco
        WHERE pagina_id = ?
          AND dublar = 1
          AND audio_relpath IS NULL
        ORDER BY ordem
        """,
        (pagina_id,),
    )


def gravar_audio(
    cx: sqlite3.Connection,
    *,
    bloco_id: int,
    audio_relpath: str,
    cues_relpath: str,
    duracao_ms: int,
    palavras: list[dict],
) -> None:
    cx.execute("BEGIN IMMEDIATE")
    try:
        cx.execute("DELETE FROM palavra WHERE bloco_id = ?", (bloco_id,))
        cx.execute(
            """
            UPDATE bloco
            SET audio_relpath = ?, cues_relpath = ?, duracao_ms = ?, erro = NULL
            WHERE id = ?
            """,
            (audio_relpath, cues_relpath, duracao_ms, bloco_id),
        )
        cx.executemany(
            """
            INSERT INTO palavra (bloco_id, ordem, texto, inicio_ms, fim_ms)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (bloco_id, indice, item["texto"], item["inicio_ms"], item["fim_ms"])
                for indice, item in enumerate(palavras, start=1)
            ],
        )
        cx.execute("COMMIT")
    except Exception:
        cx.execute("ROLLBACK")
        raise


def marcar_erro_bloco(cx: sqlite3.Connection, bloco_id: int, erro: str) -> None:
    cx.execute("UPDATE bloco SET erro = ? WHERE id = ?", (erro[:500], bloco_id))


def recalcular_duracoes(cx: sqlite3.Connection, pagina_id: int) -> None:
    cx.execute("BEGIN IMMEDIATE")
    try:
        cx.execute(
            """
            UPDATE pagina
            SET duracao_ms = (
              SELECT COALESCE(SUM(duracao_ms), 0) FROM bloco WHERE pagina_id = pagina.id
            )
            WHERE id = ?
            """,
            (pagina_id,),
        )
        doc = cx.execute(
            "SELECT documento_id FROM pagina WHERE id = ?",
            (pagina_id,),
        ).fetchone()
        cx.execute(
            """
            UPDATE documento
            SET duracao_ms = (
              SELECT COALESCE(SUM(duracao_ms), 0) FROM pagina WHERE documento_id = documento.id
            ),
            atualizado_em = datetime('now')
            WHERE id = ?
            """,
            (int(doc["documento_id"]),),
        )
        cx.execute("COMMIT")
    except Exception:
        cx.execute("ROLLBACK")
        raise


def atualizar_status_pelo_andamento(cx: sqlite3.Connection, doc_id: int) -> str:
    faltam = cx.execute(
        """
        SELECT COUNT(*) AS n
        FROM bloco b
        JOIN pagina p ON p.id = b.pagina_id
        WHERE p.documento_id = ? AND b.dublar = 1 AND b.audio_relpath IS NULL
        """,
        (doc_id,),
    ).fetchone()["n"]
    status = "pronto" if int(faltam) == 0 else "parcial"
    definir_status(cx, doc_id, status)
    return status


def pendentes_na_pagina(cx: sqlite3.Connection, pagina_id: int) -> int:
    return int(
        cx.execute(
            """
            SELECT COUNT(*) AS n FROM bloco
            WHERE pagina_id = ? AND dublar = 1 AND audio_relpath IS NULL
            """,
            (pagina_id,),
        ).fetchone()["n"]
    )


def marcar_pagina_lida(cx: sqlite3.Connection, doc_id: int, numero: int) -> None:
    cx.execute(
        """
        UPDATE pagina
        SET lida = 1, lida_em = datetime('now')
        WHERE documento_id = ? AND numero = ? AND lida = 0
        """,
        (doc_id, numero),
    )


def salvar_spread(cx: sqlite3.Connection, doc_id: int, pagina_esquerda: int) -> None:
    cx.execute(
        """
        INSERT INTO leitura (documento_id, pagina_esquerda, atualizado_em)
        VALUES (?, ?, datetime('now'))
        ON CONFLICT (documento_id) DO UPDATE SET
          pagina_esquerda = excluded.pagina_esquerda,
          atualizado_em = excluded.atualizado_em
        """,
        (doc_id, pagina_esquerda),
    )


def ler_spread(cx: sqlite3.Connection, doc_id: int) -> int:
    linha = cx.execute(
        "SELECT pagina_esquerda FROM leitura WHERE documento_id = ?",
        (doc_id,),
    ).fetchone()
    if not linha:
        return 1
    return max(1, int(linha["pagina_esquerda"]))


def expectativa(cx: sqlite3.Connection, doc_id: int) -> dict:
    return _um(
        cx,
        """
        SELECT
          (SELECT COUNT(*) FROM pagina WHERE documento_id = :id) AS paginas,
          (SELECT COUNT(*) FROM pagina WHERE documento_id = :id AND lida = 1) AS lidas,
          (SELECT COALESCE(SUM(duracao_ms), 0) FROM pagina WHERE documento_id = :id) AS duracao_ms,
          (
            SELECT COALESCE(SUM(b.duracao_ms), 0)
            FROM bloco b
            JOIN pagina p ON p.id = b.pagina_id
            WHERE p.documento_id = :id AND p.lida = 0 AND b.audio_relpath IS NOT NULL
          ) AS restante_ms,
          (
            SELECT COUNT(*)
            FROM bloco b
            JOIN pagina p ON p.id = b.pagina_id
            WHERE p.documento_id = :id AND b.dublar = 1 AND b.audio_relpath IS NULL
          ) AS faltam
        """,
        {"id": doc_id},
    ) or {}


def buscar(cx: sqlite3.Connection, doc_id: int, consulta: str) -> dict | None:
    frase = consulta.replace('"', " ").strip()
    if not frase:
        return None
    try:
        return _um(
            cx,
            """
            SELECT p.numero AS pagina_numero, b.id AS bloco_id
            FROM bloco_fts f
            JOIN bloco b ON b.id = f.rowid
            JOIN pagina p ON p.id = b.pagina_id
            WHERE bloco_fts MATCH :q AND p.documento_id = :id
            ORDER BY p.numero, b.ordem
            LIMIT 1
            """,
            {"q": f'"{frase}"', "id": doc_id},
        )
    except sqlite3.OperationalError:
        return None


def sincronizar_json_da_pagina(cx: sqlite3.Connection, pagina_id: int) -> None:
    pagina = _um(cx, "SELECT * FROM pagina WHERE id = ?", (pagina_id,))
    if not pagina or not pagina["blocos_relpath"]:
        return
    destino = absoluto(pagina["blocos_relpath"])
    if destino is None:
        return
    blocos = []
    for bloco in blocos_da_pagina(cx, pagina_id):
        blocos.append(
            {
                "ordem": bloco["ordem"],
                "tipo": bloco["tipo"],
                "dublar": bool(bloco["dublar"]),
                "texto": bloco["texto"],
                "bbox": json.loads(bloco["bbox"]) if bloco["bbox"] else None,
                "audio": bloco["audio_relpath"],
                "cues": bloco["cues_relpath"],
                "imagem": bloco["imagem_relpath"],
                "duracao_ms": bloco["duracao_ms"],
            }
        )
    payload = {
        "schema": 1,
        "numero": pagina["numero"],
        "ocr": bool(pagina["ocr"]),
        "blocos": blocos,
    }
    destino.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def reconstruir_se_vazio(cx: sqlite3.Connection) -> int:
    """Se o banco sumiu e as pastas continuam, recria o índice a partir dos JSON."""
    existe = cx.execute("SELECT COUNT(*) AS n FROM documento").fetchone()["n"]
    if int(existe):
        return 0
    texto_raiz = raiz_dados() / "texto"
    if not texto_raiz.exists():
        return 0
    criados = 0
    for manifesto_path in sorted(texto_raiz.glob("*/manifest.json")):
        manifesto = json.loads(manifesto_path.read_text(encoding="utf-8"))
        if int(manifesto.get("schema", 0)) != 1:
            continue
        doc_id = int(
            cx.execute(
                """
                INSERT INTO documento (
                  slug, titulo, pdf_sha256, pdf_relpath, paginas, voz, status
                ) VALUES (?, ?, ?, ?, ?, ?, 'parcial')
                RETURNING id
                """,
                (
                    manifesto["slug"],
                    manifesto["titulo"],
                    manifesto["pdf_sha256"],
                    manifesto["pdf"],
                    int(manifesto["paginas"]),
                    manifesto.get("voz") or VOZ,
                ),
            ).fetchone()["id"]
        )
        for arquivo in sorted(manifesto_path.parent.glob("p*.blocks.json")):
            pagina_json = json.loads(arquivo.read_text(encoding="utf-8"))
            numero = int(pagina_json["numero"])
            txt = manifesto_path.parent / f"p{numero:04d}.txt"
            pagina_id = int(
                cx.execute(
                    """
                    INSERT INTO pagina (
                      documento_id, numero, largura, altura, texto_relpath, blocos_relpath, ocr
                    ) VALUES (?, ?, 0, 0, ?, ?, ?)
                    RETURNING id
                    """,
                    (
                        doc_id,
                        numero,
                        relativo(txt) if txt.exists() else None,
                        relativo(arquivo),
                        int(bool(pagina_json.get("ocr"))),
                    ),
                ).fetchone()["id"]
            )
            for bloco in pagina_json.get("blocos", []):
                bloco_id = int(
                    cx.execute(
                        """
                        INSERT INTO bloco (
                          pagina_id, ordem, tipo, dublar, texto, audio_relpath,
                          cues_relpath, imagem_relpath, duracao_ms, bbox
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        RETURNING id
                        """,
                        (
                            pagina_id,
                            int(bloco["ordem"]),
                            bloco["tipo"],
                            int(bool(bloco.get("dublar"))),
                            bloco.get("texto") or "",
                            bloco.get("audio"),
                            bloco.get("cues"),
                            bloco.get("imagem"),
                            int(bloco.get("duracao_ms") or 0),
                            json.dumps(bloco["bbox"]) if bloco.get("bbox") else None,
                        ),
                    ).fetchone()["id"]
                )
                cues = bloco.get("cues")
                if not cues:
                    continue
                caminho = absoluto(cues)
                if caminho is None or not caminho.exists():
                    continue
                dados = json.loads(caminho.read_text(encoding="utf-8"))
                palavras = dados.get("palavras") or []
                cx.executemany(
                    """
                    INSERT INTO palavra (bloco_id, ordem, texto, inicio_ms, fim_ms)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    [
                        (bloco_id, i, item["texto"], item["inicio_ms"], item["fim_ms"])
                        for i, item in enumerate(palavras, start=1)
                    ],
                )
            recalcular_duracoes(cx, pagina_id)
        atualizar_status_pelo_andamento(cx, doc_id)
        criados += 1
    return criados
