-- Esquema de la base de datos (solo estructura, sin contenido)
-- Se genera a partir de archivo_iigm.db

CREATE TABLE IF NOT EXISTS articulos (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            titulo      TEXT NOT NULL,
            contenido   TEXT NOT NULL,
            fecha_pub   TEXT NOT NULL
        );

CREATE TABLE IF NOT EXISTS articulos_fotografias (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            articulo_id   INTEGER NOT NULL REFERENCES articulos(id)   ON DELETE CASCADE,
            fotografia_id INTEGER NOT NULL REFERENCES fotografias(id) ON DELETE CASCADE,
            UNIQUE(articulo_id, fotografia_id)
        );

CREATE TABLE IF NOT EXISTS bibliografia (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            titulo      TEXT NOT NULL,
            tipo        TEXT,
            autor       TEXT,
            pais        TEXT,
            enlace      TEXT,
            idioma      TEXT,
            descripcion TEXT,
            fiabilidad  INTEGER DEFAULT 3,
            fecha_alta  TEXT NOT NULL
        );

CREATE TABLE IF NOT EXISTS fotografias (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            titulo      TEXT NOT NULL,
            fecha_foto  TEXT,
            ubicacion   TEXT,
            pais        TEXT,
            frente      TEXT,
            descripcion TEXT,
            fuente      TEXT,
            etiquetas   TEXT,
            archivo     TEXT,
            fecha_alta  TEXT NOT NULL
        , lat REAL, lon REAL, orden INTEGER, orden_manual INTEGER DEFAULT 0);

CREATE TABLE IF NOT EXISTS fotografias_personas (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            fotografia_id INTEGER NOT NULL REFERENCES fotografias(id) ON DELETE CASCADE,
            persona_id    INTEGER NOT NULL REFERENCES personas(id)    ON DELETE CASCADE,
            UNIQUE(fotografia_id, persona_id)
        );

CREATE TABLE IF NOT EXISTS investigacion (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            titulo      TEXT NOT NULL,
            categoria   TEXT,
            autor       TEXT,
            fecha_doc   TEXT,
            descripcion TEXT,
            archivo     TEXT,
            fecha_alta  TEXT NOT NULL
        );

CREATE TABLE IF NOT EXISTS mapa_puntos (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre      TEXT NOT NULL,
            descripcion TEXT,
            lat         REAL NOT NULL,
            lon         REAL NOT NULL,
            color       TEXT DEFAULT '#8b3a2a',
            fotos_ids   TEXT DEFAULT ''
        );

CREATE TABLE IF NOT EXISTS personas (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre       TEXT NOT NULL,
            rango        TEXT,
            unidad       TEXT,
            nacionalidad TEXT,
            fecha_nac    TEXT,
            fecha_fall   TEXT,
            biografia    TEXT,
            foto_perfil  TEXT,
            fecha_alta   TEXT NOT NULL
        );

CREATE TABLE IF NOT EXISTS videos (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            titulo      TEXT NOT NULL,
            fecha_video TEXT,
            ubicacion   TEXT,
            pais        TEXT,
            frente      TEXT,
            descripcion TEXT,
            fuente      TEXT,
            etiquetas   TEXT,
            archivo     TEXT,
            duracion    TEXT,
            fecha_alta  TEXT NOT NULL
        );
