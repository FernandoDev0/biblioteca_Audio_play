"""Lê o PDF: texto de verdade, foto quando a página é imagem, código à parte."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from app.classify import (
    classificar,
    eh_cabecalho_de_livro,
    fatiar_prosa,
    fonte_e_codigo,
    indentar_codigo,
    juntar_prosa,
)

_ALTURA_RODAPE = 0.08


@dataclass
class BlocoExtraido:
    tipo: str
    dublar: bool
    texto: str
    bbox: tuple[float, float, float, float]
    imagem: Path | None = None
    ocr: bool = False
    linhas_x: list[tuple[str, float]] | None = None


@dataclass
class _Linha:
    texto: str
    bbox: tuple[float, float, float, float]
    code: bool
    tamanho: float
    negrito: bool


@dataclass
class PaginaExtraida:
    numero: int
    largura: float
    altura: float
    ocr: bool = False
    blocos: list[BlocoExtraido] = field(default_factory=list)


def _linhas(block: dict) -> list[_Linha]:
    saida: list[_Linha] = []
    for linha in block.get("lines") or []:
        partes: list[str] = []
        tamanhos: list[float] = []
        negritos: list[bool] = []
        codigos: list[int] = []
        for span in linha.get("spans") or []:
            texto = span.get("text") or ""
            partes.append(texto)
            tamanhos.append(float(span.get("size") or 0))
            fonte = span.get("font") or ""
            negritos.append("Bold" in fonte or "bold" in fonte)
            codigos.append(len(texto) if fonte_e_codigo(fonte) else 0)
        texto = "".join(partes).strip()
        if not texto:
            continue
        total = sum(len(p) for p in partes) or 1
        bb = tuple(float(v) for v in linha["bbox"])
        saida.append(
            _Linha(
                texto=texto,
                bbox=(bb[0], bb[1], bb[2], bb[3]),
                code=sum(codigos) > total * 0.5,
                tamanho=max(tamanhos) if tamanhos else 0,
                negrito=bool(negritos) and all(negritos),
            )
        )
    return saida


def _unir_bbox(linhas: list[_Linha]) -> tuple[float, float, float, float]:
    return (
        min(linha.bbox[0] for linha in linhas),
        min(linha.bbox[1] for linha in linhas),
        max(linha.bbox[2] for linha in linhas),
        max(linha.bbox[3] for linha in linhas),
    )


def _blocos_de_texto(page: pymupdf.Page) -> list[BlocoExtraido]:
    bruto = page.get_text("dict")
    altura = float(page.rect.height)
    blocos: list[BlocoExtraido] = []
    for block in bruto.get("blocks") or []:
        if block.get("type") != 0:
            continue
        linhas = [linha for linha in _linhas(block) if not eh_cabecalho_de_livro(linha.texto)]
        if not linhas:
            continue
        grupo: list[_Linha] = []
        grupos: list[list[_Linha]] = []
        for linha in linhas:
            if grupo and grupo[-1].code != linha.code:
                grupos.append(grupo)
                grupo = [linha]
            else:
                grupo.append(linha)
        if grupo:
            grupos.append(grupo)
        for pedaco in grupos:
            code = pedaco[0].code
            linhas_x = [(ln.texto, ln.bbox[0]) for ln in pedaco] if code else None
            texto = indentar_codigo(linhas_x) if linhas_x else juntar_prosa([ln.texto for ln in pedaco])
            if not texto:
                continue
            bbox = _unir_bbox(pedaco)
            no_rodape = bbox[1] > altura * (1 - _ALTURA_RODAPE)
            tipo, dublar = classificar(
                texto,
                code=code,
                tamanho=max(ln.tamanho for ln in pedaco),
                negrito=all(ln.negrito for ln in pedaco),
            )
            if no_rodape and tipo in {"numero", "folha"}:
                dublar = False
            if tipo == "folha" and len(texto) <= 2:
                continue
            if tipo == "prosa" and dublar:
                fatias = fatiar_prosa(texto)
            else:
                fatias = [texto]
            for fatia in fatias:
                blocos.append(BlocoExtraido(tipo, dublar, fatia, bbox, linhas_x=linhas_x if tipo == "codigo" else None))
    return blocos


def _salvar_xref(doc: pymupdf.Document, xref: int, destino: Path) -> bool:
    try:
        pix = pymupdf.Pixmap(doc, xref)
        if pix.n - pix.alpha > 3:
            pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
        destino.parent.mkdir(parents=True, exist_ok=True)
        pix.save(destino)
        return True
    except Exception:
        return False


def _imagens(page: pymupdf.Page, doc: pymupdf.Document, pasta: Path, numero: int) -> list[BlocoExtraido]:
    try:
        infos = page.get_image_info(xrefs=True)
    except Exception:
        infos = []
    vistos: set[int] = set()
    blocos: list[BlocoExtraido] = []
    for info in infos:
        xref = int(info.get("xref") or 0)
        if xref <= 0 or xref in vistos:
            continue
        vistos.add(xref)
        largura = int(info.get("width") or 0)
        altura = int(info.get("height") or 0)
        if largura < 48 or altura < 36:
            continue
        if largura * altura < 4000:
            continue
        bbox_bruto = info.get("bbox") or (0, 0, largura, altura)
        bbox = tuple(float(v) for v in bbox_bruto)
        destino = pasta / f"p{numero:04d}_x{xref}.png"
        if not destino.exists() and not _salvar_xref(doc, xref, destino):
            continue
        blocos.append(BlocoExtraido("imagem", False, "", bbox, destino))
    return blocos


def _render_pagina(page: pymupdf.Page, destino: Path) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    pix = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
    pix.save(destino)


def tesseract_disponivel() -> bool:
    import shutil

    candidatos = [
        shutil.which("tesseract"),
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ]
    return any(candidato and Path(candidato).exists() for candidato in candidatos)


def _ocr(imagem: Path) -> str:
    import pytesseract

    if not tesseract_disponivel():
        return ""
    import shutil

    for candidato in (
        shutil.which("tesseract"),
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ):
        if candidato and Path(candidato).exists():
            pytesseract.pytesseract.tesseract_cmd = str(candidato)
            break
    from PIL import Image

    try:
        return pytesseract.image_to_string(Image.open(imagem), lang="por+eng") or ""
    except pytesseract.TesseractError:
        try:
            return pytesseract.image_to_string(Image.open(imagem), lang="eng") or ""
        except Exception:
            return ""
    except Exception:
        return ""


def _blocos_ocr(texto: str, largura: float, altura: float) -> list[BlocoExtraido]:
    paragrafos = [p.strip() for p in texto.splitlines()]
    unidos: list[str] = []
    atual = ""
    for linha in paragrafos:
        if not linha:
            if atual:
                unidos.append(atual)
                atual = ""
            continue
        atual = f"{atual} {linha}".strip()
    if atual:
        unidos.append(atual)
    blocos: list[BlocoExtraido] = []
    y = altura * 0.08
    for paragrafo in unidos:
        tipo, dublar = classificar(paragrafo)
        if tipo in {"folha", "numero"} and not dublar and len(paragrafo) < 3:
            continue
        blocos.append(
            BlocoExtraido(
                tipo if tipo != "folha" else "prosa",
                dublar,
                paragrafo,
                (24, y, largura - 24, y + 20),
                ocr=True,
            )
        )
        y += 24
    return blocos


def _ordenar(blocos: list[BlocoExtraido], largura: float) -> list[BlocoExtraido]:
    if not blocos:
        return []
    esquerda = [b for b in blocos if (b.bbox[0] + b.bbox[2]) / 2 < largura * 0.45]
    direita = [b for b in blocos if (b.bbox[0] + b.bbox[2]) / 2 > largura * 0.55]
    if len(esquerda) >= 3 and len(direita) >= 3:
        esquerda.sort(key=lambda b: (b.bbox[1], b.bbox[0]))
        direita.sort(key=lambda b: (b.bbox[1], b.bbox[0]))
        meio = [b for b in blocos if b not in esquerda and b not in direita]
        meio.sort(key=lambda b: (b.bbox[1], b.bbox[0]))
        ordenados = esquerda + meio + direita
    else:
        ordenados = sorted(blocos, key=lambda b: (b.bbox[1], b.bbox[0]))
    unidos: list[BlocoExtraido] = []
    for bloco in ordenados:
        if (
            unidos
            and bloco.tipo == "codigo"
            and unidos[-1].tipo == "codigo"
            and -2 <= bloco.bbox[1] - unidos[-1].bbox[3] < 22
        ):
            anterior = unidos[-1]
            if anterior.linhas_x and bloco.linhas_x:
                anterior.linhas_x = anterior.linhas_x + bloco.linhas_x
                anterior.texto = indentar_codigo(anterior.linhas_x)
            else:
                anterior.texto = anterior.texto.rstrip() + "\n" + bloco.texto
            anterior.bbox = (
                min(anterior.bbox[0], bloco.bbox[0]),
                min(anterior.bbox[1], bloco.bbox[1]),
                max(anterior.bbox[2], bloco.bbox[2]),
                max(anterior.bbox[3], bloco.bbox[3]),
            )
            continue
        unidos.append(bloco)
    return unidos


def _chave_codigo(texto: str) -> str:
    return "".join(texto.split())


def atualizar_codigo_gravado() -> int:
    """Regrava o código já importado com a indentação lida do PDF."""
    import tempfile

    from app.db import blocos_da_pagina, conectar, fechar, sincronizar_json_da_pagina
    from app.paths import absoluto

    cx = conectar()
    mudancas = 0
    try:
        documentos = cx.execute("SELECT id, pdf_relpath FROM documento").fetchall()
        for documento in documentos:
            pdf = absoluto(documento["pdf_relpath"])
            if pdf is None or not pdf.exists():
                continue
            with tempfile.TemporaryDirectory() as pasta:
                paginas = extrair_paginas(pdf, Path(pasta))
            for pagina in paginas:
                linha = cx.execute(
                    "SELECT id FROM pagina WHERE documento_id = ? AND numero = ?",
                    (int(documento["id"]), pagina.numero),
                ).fetchone()
                if linha is None:
                    continue
                pagina_id = int(linha["id"])
                velhos = [b for b in blocos_da_pagina(cx, pagina_id) if b["tipo"] == "codigo"]
                novos = [b.texto for b in pagina.blocos if b.tipo == "codigo"]
                cursor = 0
                tocou = False
                for velho in velhos:
                    chave = _chave_codigo(velho["texto"])
                    while cursor < len(novos) and _chave_codigo(novos[cursor]) != chave:
                        cursor += 1
                    if cursor >= len(novos):
                        continue
                    if velho["texto"] != novos[cursor]:
                        cx.execute(
                            "UPDATE bloco SET texto = ? WHERE id = ?",
                            (novos[cursor], int(velho["id"])),
                        )
                        mudancas += 1
                        tocou = True
                    cursor += 1
                if tocou:
                    sincronizar_json_da_pagina(cx, pagina_id)
        return mudancas
    finally:
        fechar(cx)


def extrair_paginas(
    pdf: Path,
    pasta_imagens: Path,
    numeros: list[int] | None = None,
) -> list[PaginaExtraida]:
    doc = pymupdf.open(pdf)
    try:
        escolhidos = numeros or list(range(1, doc.page_count + 1))
        paginas: list[PaginaExtraida] = []
        for numero in escolhidos:
            page = doc[numero - 1]
            texto = _blocos_de_texto(page)
            imagens = _imagens(page, doc, pasta_imagens, numero)
            ocr = False
            util = sum(len(b.texto) for b in texto)
            if util < 40:
                alvo = next(
                    (
                        bloco.imagem
                        for bloco in imagens
                        if bloco.imagem is not None
                        and (bloco.bbox[2] - bloco.bbox[0]) > float(page.rect.width) * 0.6
                    ),
                    None,
                )
                if alvo is None:
                    alvo = pasta_imagens / f"p{numero:04d}_pagina.png"
                    if not alvo.exists():
                        _render_pagina(page, alvo)
                    imagens.insert(
                        0,
                        BlocoExtraido(
                            "imagem",
                            False,
                            "",
                            (0.0, 0.0, float(page.rect.width), float(page.rect.height)),
                            alvo,
                        ),
                    )
                lido = _ocr(alvo)
                if lido.strip():
                    ocr = True
                    texto.extend(_blocos_ocr(lido, float(page.rect.width), float(page.rect.height)))
            paginas.append(
                PaginaExtraida(
                    numero=numero,
                    largura=float(page.rect.width),
                    altura=float(page.rect.height),
                    ocr=ocr,
                    blocos=_ordenar(texto + imagens, float(page.rect.width)),
                )
            )
        return paginas
    finally:
        doc.close()
