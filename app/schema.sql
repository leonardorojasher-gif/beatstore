-- Esquema de BeatStore (SQLite en el prototipo; el mismo modelo se migra a PostgreSQL)
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS usuarios (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre              TEXT NOT NULL,
    email               TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash       TEXT NOT NULL,
    rol                 TEXT NOT NULL CHECK (rol IN ('ARTISTA', 'PRODUCTOR')),
    intentos_fallidos   INTEGER NOT NULL DEFAULT 0,
    bloqueado_hasta     TEXT,
    acepta_terminos_en  TEXT NOT NULL,
    creado_en           TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS beats (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    titulo           TEXT NOT NULL,
    genero           TEXT NOT NULL,
    bpm              INTEGER NOT NULL CHECK (bpm BETWEEN 40 AND 250),
    tonalidad        TEXT NOT NULL,
    mood             TEXT NOT NULL,
    estado           TEXT NOT NULL DEFAULT 'PUBLICADO'
                     CHECK (estado IN ('PUBLICADO', 'OCULTO', 'VENDIDO_EXCLUSIVO')),
    archivo_master   TEXT NOT NULL,   -- WAV privado
    archivo_mp3      TEXT NOT NULL,   -- MP3 sin tag (licencia básica)
    archivo_stems    TEXT,            -- ZIP con pistas separadas (opcional)
    archivo_preview  TEXT NOT NULL,   -- MP3 con tag (público)
    creado_en        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tipos_licencia (
    codigo                  TEXT PRIMARY KEY,
    nombre                  TEXT NOT NULL,
    archivos                TEXT NOT NULL,
    limite_reproducciones   TEXT NOT NULL,
    monetizacion            TEXT NOT NULL,
    es_exclusiva            INTEGER NOT NULL DEFAULT 0,
    orden                   INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS licencias_beat (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    beat_id  INTEGER NOT NULL REFERENCES beats(id),
    tipo     TEXT NOT NULL REFERENCES tipos_licencia(codigo),
    precio   INTEGER NOT NULL CHECK (precio > 0),
    activa   INTEGER NOT NULL DEFAULT 1,
    UNIQUE (beat_id, tipo)
);

CREATE TABLE IF NOT EXISTS ordenes (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id           INTEGER NOT NULL REFERENCES usuarios(id),
    estado               TEXT NOT NULL DEFAULT 'PENDIENTE'
                         CHECK (estado IN ('PENDIENTE', 'PAGADA', 'RECHAZADA', 'ANULADA')),
    total                INTEGER NOT NULL CHECK (total > 0),
    token_pasarela       TEXT UNIQUE,
    codigo_autorizacion  TEXT,
    motivo               TEXT,
    creada_en            TEXT NOT NULL,
    pagada_en            TEXT
);

CREATE TABLE IF NOT EXISTS detalle_orden (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    orden_id           INTEGER NOT NULL REFERENCES ordenes(id),
    licencia_beat_id   INTEGER NOT NULL REFERENCES licencias_beat(id),
    beat_id            INTEGER NOT NULL REFERENCES beats(id),
    tipo               TEXT NOT NULL REFERENCES tipos_licencia(codigo),
    precio             INTEGER NOT NULL,
    contrato_archivo   TEXT,
    contrato_codigo    TEXT,
    contrato_sha256    TEXT
);

CREATE TABLE IF NOT EXISTS enlaces_descarga (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    detalle_id     INTEGER NOT NULL REFERENCES detalle_orden(id),
    token_hash     TEXT NOT NULL UNIQUE,   -- se guarda solo el hash del token
    expira_en      TEXT NOT NULL,
    descargas      INTEGER NOT NULL DEFAULT 0,
    max_descargas  INTEGER NOT NULL,
    creado_en      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS auditoria (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha       TEXT NOT NULL,
    usuario_id  INTEGER,
    evento      TEXT NOT NULL,
    detalle     TEXT,
    ip          TEXT
);

-- Bandeja de salida del adaptador de correo en modo "consola" (demo)
CREATE TABLE IF NOT EXISTS correos (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha         TEXT NOT NULL,
    destinatario  TEXT NOT NULL,
    asunto        TEXT NOT NULL,
    cuerpo        TEXT NOT NULL
);

-- Transacciones de la pasarela de pagos simulada (representa al sistema externo)
CREATE TABLE IF NOT EXISTS sandbox_transacciones (
    token        TEXT PRIMARY KEY,
    orden_id     INTEGER NOT NULL,
    monto        INTEGER NOT NULL,
    estado       TEXT NOT NULL DEFAULT 'INICIADA'
                 CHECK (estado IN ('INICIADA', 'AUTORIZADA', 'RECHAZADA', 'CONFIRMADA', 'ANULADA')),
    url_retorno  TEXT NOT NULL,
    creada_en    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_beats_estado ON beats(estado);
CREATE INDEX IF NOT EXISTS idx_ordenes_usuario ON ordenes(usuario_id);
CREATE INDEX IF NOT EXISTS idx_auditoria_fecha ON auditoria(fecha);

INSERT OR IGNORE INTO tipos_licencia VALUES
 ('BASICA',    'Básica',    'MP3 sin tag',                         '50.000 reproducciones',  'No monetiza en YouTube', 0, 1),
 ('PREMIUM',   'Premium',   'WAV sin tag',                         '500.000 reproducciones', 'Monetiza en YouTube',    0, 2),
 ('STEMS',     'Stems',     'WAV y pistas separadas (stems)',      'Ilimitadas',             'Monetiza en YouTube',    0, 3),
 ('EXCLUSIVA', 'Exclusiva', 'WAV, stems y derechos exclusivos',    'Ilimitadas',             'Monetiza en YouTube',    1, 4);
