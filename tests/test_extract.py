import tempfile
import unittest
from pathlib import Path

from app.classify import sem_acento
from app.extract import extrair_paginas
from app.paths import RAIZ_PROJETO

PDF = RAIZ_PROJETO / "Test-Driven Development - Teste e Design no Mundo Real - Autor (Casa do Código).pdf"


class ExtrairTeste(unittest.TestCase):
    def test_separa_prosa_codigo_e_capa(self) -> None:
        if not PDF.exists():
            self.skipTest("PDF de trabalho ausente")
        with tempfile.TemporaryDirectory() as pasta:
            paginas = extrair_paginas(PDF, Path(pasta), [1, 2, 17])
        por_numero = {pagina.numero: pagina for pagina in paginas}

        capa = por_numero[1]
        self.assertTrue(any(bloco.tipo == "imagem" for bloco in capa.blocos))

        agradecimento = por_numero[2]
        prosa = [bloco.texto for bloco in agradecimento.blocos if bloco.dublar]
        self.assertTrue(prosa)
        junto = "\n".join(prosa)
        self.assertIn("enriqueceu", junto)
        self.assertIn("Ferreira", junto)
        self.assertFalse(
            any(sem_acento(bloco.texto) == "casa do codigo" for bloco in agradecimento.blocos)
        )

        codigo = por_numero[17]
        fontes = [bloco for bloco in codigo.blocos if bloco.tipo == "codigo"]
        self.assertTrue(fontes)
        self.assertTrue(any("MaiorEMenor" in bloco.texto for bloco in fontes))
        self.assertTrue(any("\n    private Produto menor;" in bloco.texto for bloco in fontes))
        self.assertTrue(all(not bloco.dublar for bloco in fontes))
        self.assertTrue(all(not bloco.dublar for bloco in codigo.blocos if bloco.tipo == "numero"))
        self.assertFalse(any(sem_acento(bloco.texto) == "casa do codigo" for bloco in codigo.blocos))


if __name__ == "__main__":
    unittest.main()
