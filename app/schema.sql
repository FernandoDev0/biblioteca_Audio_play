-- Biblioteca de áudio. SQLite 3.50, STRICT, FTS5.
-- https://sqlite.org/stricttables.html
-- https://sqlite.org/fts5.html
-- https://sqlite.org/wal.html

CREATE TABLE documento (
  id INTEGER PRIMARY KEY,
  slug TEXT NOT NULL UNIQUE,
  titulo TEXT NOT NULL,
  pdf_sha256 TEXT NOT NULL UNIQUE,
  pdf_relpath TEXT NOT NULL,
  paginas INTEGER NOT NULL,
  voz TEXT NOT NULL,
  status TEXT NOT NULL,
  duracao_ms INTEGER NOT NULL DEFAULT 0,
  criado_em TEXT NOT NULL DEFAULT (datetime('now')),
  atualizado_em TEXT NOT NULL DEFAULT (datetime('now')),
  CHECK (status IN ('extraindo', 'dublando', 'parcial', 'pronto', 'erro'))
) STRICT;

CREATE TABLE pagina (
  id INTEGER PRIMARY KEY,
  documento_id INTEGER NOT NULL REFERENCES documento(id) ON DELETE CASCADE,
  numero INTEGER NOT NULL,
  largura REAL NOT NULL,
  altura REAL NOT NULL,
  texto_relpath TEXT,
  blocos_relpath TEXT,
  ocr INTEGER NOT NULL DEFAULT 0 CHECK (ocr IN (0, 1)),
  lida INTEGER NOT NULL DEFAULT 0 CHECK (lida IN (0, 1)),
  lida_em TEXT,
  duracao_ms INTEGER NOT NULL DEFAULT 0,
  UNIQUE (documento_id, numero)
) STRICT;

CREATE TABLE bloco (
  id INTEGER PRIMARY KEY,
  pagina_id INTEGER NOT NULL REFERENCES pagina(id) ON DELETE CASCADE,
  ordem INTEGER NOT NULL,
  tipo TEXT NOT NULL,
  dublar INTEGER NOT NULL DEFAULT 0 CHECK (dublar IN (0, 1)),
  texto TEXT NOT NULL DEFAULT '',
  audio_relpath TEXT,
  cues_relpath TEXT,
  imagem_relpath TEXT,
  duracao_ms INTEGER NOT NULL DEFAULT 0,
  bbox TEXT,
  erro TEXT,
  UNIQUE (pagina_id, ordem),
  CHECK (tipo IN ('prosa', 'titulo', 'codigo', 'numero', 'folha', 'imagem'))
) STRICT;

CREATE TABLE palavra (
  id INTEGER PRIMARY KEY,
  bloco_id INTEGER NOT NULL REFERENCES bloco(id) ON DELETE CASCADE,
  ordem INTEGER NOT NULL,
  texto TEXT NOT NULL,
  inicio_ms INTEGER NOT NULL,
  fim_ms INTEGER NOT NULL,
  UNIQUE (bloco_id, ordem)
) STRICT;

CREATE TABLE leitura (
  documento_id INTEGER PRIMARY KEY REFERENCES documento(id) ON DELETE CASCADE,
  pagina_esquerda INTEGER NOT NULL DEFAULT 1,
  atualizado_em TEXT NOT NULL DEFAULT (datetime('now'))
) STRICT;

CREATE INDEX idx_pagina_doc ON pagina (documento_id, numero);
CREATE INDEX idx_bloco_pagina ON bloco (pagina_id, ordem);
CREATE INDEX idx_bloco_pendente ON bloco (pagina_id, dublar) WHERE audio_relpath IS NULL;
CREATE INDEX idx_palavra_bloco ON palavra (bloco_id, ordem);
CREATE INDEX idx_pagina_lida ON pagina (documento_id, lida);

CREATE VIRTUAL TABLE bloco_fts USING fts5(
  texto,
  content='bloco',
  content_rowid='id',
  tokenize = 'unicode61 remove_diacritics 2'
);

CREATE TRIGGER bloco_ai AFTER INSERT ON bloco BEGIN
  INSERT INTO bloco_fts (rowid, texto) VALUES (new.id, new.texto);
END;

CREATE TRIGGER bloco_ad AFTER DELETE ON bloco BEGIN
  INSERT INTO bloco_fts (bloco_fts, rowid, texto) VALUES ('delete', old.id, old.texto);
END;

CREATE TRIGGER bloco_au AFTER UPDATE ON bloco BEGIN
  INSERT INTO bloco_fts (bloco_fts, rowid, texto) VALUES ('delete', old.id, old.texto);
  INSERT INTO bloco_fts (rowid, texto) VALUES (new.id, new.texto);
END;
