# Biblioteca

Sistema de tratamento de arquivo para áudio. Um PDF entra, o texto é organizado, e o que carrega a ideia do livro sai em voz, para ouvir como um audiolivro sem perder a essência.

A página continua inteira na tela. A voz fica com a prosa e os títulos. Código, número solto, endereço, marcação de página e figura permanecem visíveis para consulta, no lugar em que estavam no documento.

A voz é a Francisca, neural, em português (`pt-BR-FranciscaNeural`). Cada trecho vira um clipe Opus, com a marca de tempo de cada palavra. Enquanto o áudio toca, a palavra da vez acende em âmbar.

## O que a tratativa preserva

O PDF não é lido de ponta a ponta como um bloco único. Cada página vira trechos, e cada trecho recebe um papel:

| Na página | No áudio |
| --- | --- |
| Prosa | Entra. Frases longas são cortadas em trechos de leitura, sem partir uma frase no meio. |
| Título | Entra. |
| Código | Fica na tela, com a indentação lida da margem do PDF, guias de indentação, cores de sintaxe e um botão Copiar. |
| Número solto, figura, ISBN, URL, e-mail | Ficam na tela. |
| Marcação de folha e rodapé | Ficam na tela, ou saem quando não dizem nada. |
| Imagem | Fica na tela. |

Hífen de quebra de linha é recolocado na palavra. Página em duas colunas é lida da coluna esquerda para a direita. Página que é só foto continua visível; a transcrição dessa foto pede o Tesseract instalado.

O mesmo PDF, reconhecido pelo hash, não é importado de novo. O lote segue do que ainda falta.

## As três telas

**Estúdio.** O PDF entra por arrastar ou por *Tratar PDF*. A extração do texto acontece de uma vez. A dublagem segue página a página e pode parar e continuar depois. Um livro grande fica em lote.

**Acervo.** Lista os documentos pelo nome do PDF, com páginas, quantas já têm áudio, quantas foram concluídas e a duração.

**Leitura.** Mostra duas páginas lado a lado.

- *Ouvir tudo* narra da página aberta até o fim do documento. O clipe que já existe toca na hora. O que falta é gerado em ordem, sem cortar a frase que já está no ar. *Parar leitura* corta o som e a fila.
- *Ler* toca só as duas páginas abertas.
- Um clique num trecho toca aquele trecho. Se ainda não houver áudio e a máquina tiver folga de memória, a voz daquele trecho é gerada na hora.
- A busca acha um trecho no livro e abre a página.
- O volume e a página em que você parou ficam guardados. Página ouvida até o fim é marcada como concluída.

## Como o arquivo fica guardado

Tudo que pertence à biblioteca fica em `biblioteca/`:

```
biblioteca/
  pdf/        cópia do PDF, uma pasta por documento
  texto/      página em .txt e em .blocks.json
  audio/      clipe .opus e marcas de palavra em .cues.json
  imagens/    figuras e páginas que são foto
  banco/      biblioteca.db
  cache/      modelo do alinhamento, quando usado
```

O banco é SQLite. Guarda documento, página, trecho, palavra com início e fim em milissegundos, e a página em que a leitura parou. A busca usa o texto dos trechos.

A voz chega em MP3 e é convertida para Opus mono. A marca de cada palavra vem da própria narração. Se essa marca não vier, o tempo é estimado pelo tamanho das palavras. O alinhamento fino por reconhecimento de fala só entra num trecho avulso, e só quando há memória de sobra. O livro inteiro segue sempre em lote.

## Como abrir

Dois cliques em `abrir.bat`. O atalho sobe a janela com o Python do projeto:

```powershell
.\.venv\Scripts\python.exe -m app
```

Na primeira instalação, com o Python do Windows:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -U pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Para ouvir, o VLC precisa estar instalado (o padrão é `C:\Program Files\VideoLAN\VLC`). A narração da Francisca usa a rede. Sem o Tesseract, página que é só foto permanece visível e sem transcrição.

A pasta dos dados pode sair do projeto com a variável `BIBLIOTECA_DADOS`. A pasta do VLC pode sair do padrão com `VLC_DIR`.
