import unittest

from app.classify import classificar, fatiar_prosa, indentar_codigo, juntar_prosa
from app.ui.sintaxe import detectar_linguagem
from app.ui.texto import mapear


class ClassificarTeste(unittest.TestCase):
    def test_prosa_entra_na_dublagem(self) -> None:
        tipo, dublar = classificar(
            "Um teste de unidade testa uma única unidade do nosso sistema."
        )
        self.assertEqual(tipo, "prosa")
        self.assertTrue(dublar)

    def test_codigo_fica_mudo(self) -> None:
        tipo, dublar = classificar(
            "public class MaiorEMenor {\nprivate Produto menor;\n}",
            code=True,
        )
        self.assertEqual(tipo, "codigo")
        self.assertFalse(dublar)

    def test_numero_solto_fica_mudo(self) -> None:
        tipo, dublar = classificar("6")
        self.assertEqual(tipo, "numero")
        self.assertFalse(dublar)

    def test_titulo_com_numero_e_lido(self) -> None:
        tipo, dublar = classificar(
            "2.2 Preciso mesmo escrevê-los?",
            tamanho=16,
            negrito=True,
        )
        self.assertEqual(tipo, "titulo")
        self.assertTrue(dublar)

    def test_url_fica_muda(self) -> None:
        _tipo, dublar = classificar("https://casadocodigo.com.br")
        self.assertFalse(dublar)

    def test_hifen_de_quebra_de_linha(self) -> None:
        texto = juntar_prosa(
            [
                "com as incontaveis conversas de corredor sobre o assunto. Isso com certeza enrique-",
                "ceu muito o texto, e o mesmo vale para o Rafael Fer-",
                "reira no fim da dedicatória.",
            ]
        )
        self.assertIn("enriqueceu", texto)
        self.assertIn("Ferreira", texto)

    def test_indentacao_sai_da_margem(self) -> None:
        texto = indentar_codigo(
            [
                ("public class A {", 57.8),
                ("private int x;", 78.7),
                ("return x;", 99.7),
                ("}", 57.8),
            ]
        )
        self.assertIn("\n    private int x;", texto)
        self.assertIn("\n        return x;", texto)
        self.assertTrue(texto.startswith("public class A {"))

    def test_reconhece_java(self) -> None:
        self.assertEqual(
            detectar_linguagem("public class MaiorEMenor {\n    private int x;\n}"),
            "Java",
        )

    def test_marca_a_palavra_certa(self) -> None:
        texto = "Agradecimentos ao leitor."
        mapas = mapear(
            texto,
            [{"texto": "Agradecimentos"}, {"texto": "ao"}, {"texto": "leitor."}],
        )
        self.assertEqual(mapas[0], (0, len("Agradecimentos")))
        self.assertEqual(mapas[2][0], texto.index("leitor"))

    def test_fatiar_respeita_frase(self) -> None:
        texto = "Primeira frase longa o bastante. " * 40
        fatias = fatiar_prosa(texto, limite=200)
        self.assertGreater(len(fatias), 1)
        self.assertTrue(all(len(fatia) <= 220 for fatia in fatias))


if __name__ == "__main__":
    unittest.main()
