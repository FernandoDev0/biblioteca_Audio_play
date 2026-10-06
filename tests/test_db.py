import json
import os
import tempfile
import unittest
from pathlib import Path

from app.db import (
    atualizar_status_pelo_andamento,
    buscar,
    conectar,
    criar_documento,
    expectativa,
    fechar,
    gravar_audio,
    inserir_pagina,
    migrar,
    narracao_desde,
    reconstruir_se_vazio,
)
from app.paths import banco, garantir_pastas, relativo


class BancoTeste(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["BIBLIOTECA_DADOS"] = self._tmp.name
        garantir_pastas()
        self.cx = conectar()
        migrar(self.cx)

    def tearDown(self) -> None:
        fechar(self.cx)
        os.environ.pop("BIBLIOTECA_DADOS", None)
        self._tmp.cleanup()

    def test_pragma_integridade_e_fts(self) -> None:
        self.assertEqual(self.cx.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        self.assertEqual(self.cx.execute("PRAGMA user_version").fetchone()[0], 1)
        self.assertEqual(self.cx.execute("PRAGMA journal_mode").fetchone()[0].lower(), "wal")
        self.assertEqual(self.cx.execute("PRAGMA integrity_check").fetchone()[0], "ok")

        doc_id = self._documento()
        pagina_id = self._pagina(doc_id, "O teste de unidade olha uma classe.")
        achado = buscar(self.cx, doc_id, "unidade")
        self.assertIsNotNone(achado)
        self.assertEqual(achado["pagina_numero"], 1)

        bloco_id = self.cx.execute(
            "SELECT id FROM bloco WHERE pagina_id = ?",
            (pagina_id,),
        ).fetchone()["id"]
        gravar_audio(
            self.cx,
            bloco_id=int(bloco_id),
            audio_relpath="audio/livro/p0001/b0001.opus",
            cues_relpath="audio/livro/p0001/b0001.cues.json",
            duracao_ms=1500,
            palavras=[{"texto": "teste", "inicio_ms": 0, "fim_ms": 400}],
        )
        self.cx.execute("DELETE FROM documento WHERE id = ?", (doc_id,))
        self.assertEqual(
            self.cx.execute("SELECT COUNT(*) AS n FROM bloco").fetchone()["n"],
            0,
        )
        self.assertEqual(
            self.cx.execute("SELECT COUNT(*) AS n FROM bloco_fts").fetchone()["n"],
            0,
        )
        self.assertEqual(self.cx.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_narracao_segue_o_que_da_para_ouvir(self) -> None:
        doc_id = self._documento()
        self._pagina(doc_id, "A prosa entra na leitura.")
        pasta = Path(self._tmp.name) / "texto" / "livro-teste"
        inserir_pagina(
            self.cx,
            doc_id=doc_id,
            numero=2,
            largura=100,
            altura=200,
            texto_relpath=relativo(pasta / "p0002.txt"),
            blocos_relpath=relativo(pasta / "p0002.blocks.json"),
            ocr=False,
            blocos=[
                {
                    "ordem": 1,
                    "tipo": "codigo",
                    "dublar": False,
                    "texto": "public class A {}",
                    "imagem_relpath": None,
                    "bbox": "[0, 0, 10, 10]",
                },
                {
                    "ordem": 2,
                    "tipo": "numero",
                    "dublar": False,
                    "texto": "12",
                    "imagem_relpath": None,
                    "bbox": "[0, 0, 10, 10]",
                },
            ],
        )
        fila = narracao_desde(self.cx, doc_id, 1)
        self.assertEqual([item["texto"] for item in fila], ["A prosa entra na leitura."])
        codigo = self.cx.execute(
            "SELECT id FROM bloco WHERE tipo = 'codigo'"
        ).fetchone()
        gravar_audio(
            self.cx,
            bloco_id=int(codigo["id"]),
            audio_relpath="audio/livro/p0002/b0001.opus",
            cues_relpath="audio/livro/p0002/b0001.cues.json",
            duracao_ms=800,
            palavras=[],
        )
        fila = narracao_desde(self.cx, doc_id, 1)
        self.assertEqual(
            [item["texto"] for item in fila],
            ["A prosa entra na leitura.", "public class A {}"],
        )

    def test_reconstruir_a_partir_dos_json(self) -> None:
        doc_id = self._documento()
        self._pagina(doc_id, "A leitura continua na página seguinte.")
        from app.db import paginas_do_documento, sincronizar_json_da_pagina

        pagina = paginas_do_documento(self.cx, doc_id)[0]
        sincronizar_json_da_pagina(self.cx, int(pagina["id"]))
        pasta = Path(self._tmp.name) / "texto" / "livro-teste"
        manifesto = {
            "schema": 1,
            "slug": "livro-teste",
            "titulo": "Livro teste",
            "voz": "pt-BR-FranciscaNeural",
            "pdf_sha256": "abc123",
            "pdf": "pdf/livro-teste/source.pdf",
            "paginas": 1,
        }
        (pasta / "manifest.json").write_text(json.dumps(manifesto), encoding="utf-8")
        fechar(self.cx)
        for sufixo in ("", "-wal", "-shm"):
            caminho = Path(str(banco()) + sufixo)
            if caminho.exists():
                caminho.unlink()
        self.cx = conectar()
        migrar(self.cx)
        criados = reconstruir_se_vazio(self.cx)
        self.assertEqual(criados, 1)
        dados = expectativa(self.cx, 1)
        self.assertEqual(int(dados["paginas"]), 1)
        achado = buscar(self.cx, 1, "leitura")
        self.assertIsNotNone(achado)
        atualizar_status_pelo_andamento(self.cx, 1)

    def _documento(self) -> int:
        return criar_documento(
            self.cx,
            slug="livro-teste",
            titulo="Livro teste",
            sha="abc123",
            pdf_relpath="pdf/livro-teste/source.pdf",
            paginas=1,
        )

    def _pagina(self, doc_id: int, texto: str) -> int:
        pasta = Path(self._tmp.name) / "texto" / "livro-teste"
        pasta.mkdir(parents=True, exist_ok=True)
        txt = pasta / "p0001.txt"
        blocos = pasta / "p0001.blocks.json"
        txt.write_text(texto, encoding="utf-8")
        blocos.write_text("{}", encoding="utf-8")
        return inserir_pagina(
            self.cx,
            doc_id=doc_id,
            numero=1,
            largura=100,
            altura=200,
            texto_relpath=relativo(txt),
            blocos_relpath=relativo(blocos),
            ocr=False,
            blocos=[
                {
                    "ordem": 1,
                    "tipo": "prosa",
                    "dublar": True,
                    "texto": texto,
                    "imagem_relpath": None,
                    "bbox": "[0, 0, 10, 10]",
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
