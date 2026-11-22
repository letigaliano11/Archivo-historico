"""
ARCHIVO HISTÓRICO - LSFG
Instalación previa:
    pip install flask pillow
"""

import argparse
from flask import Flask, render_template_string, request, redirect, url_for, jsonify, send_from_directory, session, abort, send_file, Response
import sqlite3
import re
import os
import io
import zipfile
from datetime import datetime
from werkzeug.utils import secure_filename
from collections import defaultdict
import json
import hmac

parser = argparse.ArgumentParser()
parser.add_argument("--host", action="store_true", help="Escucha en 0.0.0.0 (acceso en red)")
args, _ = parser.parse_known_args()
HOST = "0.0.0.0" if args.host else "127.0.0.1"

app = Flask(__name__)

UPLOAD_FOLDER  = "fotos_archivo"
import sys

if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

UPLOAD_FOLDER  = os.path.join(BASE_DIR, "fotos_archivo")
VIDEOS_FOLDER  = os.path.join(BASE_DIR, "videos_archivo")
PDFS_FOLDER    = os.path.join(BASE_DIR, "pdfs_archivo")
ALLOWED_IMAGES = {"png", "jpg", "jpeg", "gif", "webp", "tif", "tiff"}
ALLOWED_VIDEOS = {"mp4", "webm", "mov", "avi", "mkv", "m4v"}
ALLOWED_PDF    = {"pdf"}
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["VIDEOS_FOLDER"] = VIDEOS_FOLDER
app.config["PDFS_FOLDER"]   = PDFS_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024  # 500 MB para vídeos

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(VIDEOS_FOLDER, exist_ok=True)
os.makedirs(PDFS_FOLDER, exist_ok=True)
os.makedirs(os.path.join(BASE_DIR, "personas_archivo"), exist_ok=True)
app.config["PERSONAS_FOLDER"] = os.path.join(BASE_DIR, "personas_archivo")

def _cargar_config():
    # Lee config_local.json (junto a este archivo). No se sube a GitHub.
    ruta = os.path.join(BASE_DIR, "config_local.json")
    try:
        with open(ruta, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}

_CONFIG = _cargar_config()
app.secret_key = _CONFIG.get("secret_key") or os.urandom(32)
CONTRASENA_ACCESO = str(_CONFIG.get("contrasena_acceso") or "")
ADMINS = {str(a) for a in _CONFIG.get("admins", [])}

def usuario_activo():
    return session.get("usuario")

def es_admin():
    u = usuario_activo()
    return u is not None and u.get("rol") == "admin"

def login_requerido(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not usuario_activo():
            return redirect(url_for("login", next=request.path))
        return f(*args, **kwargs)
    return decorated

def solo_admin(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not es_admin():
            abort(403)
        return f(*args, **kwargs)
    return decorated
def get_db():
    db = sqlite3.connect(os.path.join(BASE_DIR, "archivo_iigm.db"))
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db

def init_db():
    db = get_db()
    # Fotografías
    db.execute("""
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
            fecha_alta  TEXT NOT NULL,
            lat         REAL,
            lon         REAL,
            orden_manual INTEGER DEFAULT 0
        )
    """)
    cols = [row[1] for row in db.execute("PRAGMA table_info(fotografias)").fetchall()]
    if "lat"          not in cols: db.execute("ALTER TABLE fotografias ADD COLUMN lat REAL")
    if "lon"          not in cols: db.execute("ALTER TABLE fotografias ADD COLUMN lon REAL")
    if "orden_manual" not in cols: db.execute("ALTER TABLE fotografias ADD COLUMN orden_manual INTEGER DEFAULT 0")
    if "identificador" not in cols: db.execute("ALTER TABLE fotografias ADD COLUMN identificador TEXT")
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_fotografias_identificador ON fotografias(identificador) WHERE identificador IS NOT NULL")

    db.execute("""
        CREATE TABLE IF NOT EXISTS articulos (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            titulo      TEXT NOT NULL,
            contenido   TEXT NOT NULL,
            fecha_pub   TEXT NOT NULL
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS articulos_fotografias (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            articulo_id   INTEGER NOT NULL REFERENCES articulos(id)   ON DELETE CASCADE,
            fotografia_id INTEGER NOT NULL REFERENCES fotografias(id) ON DELETE CASCADE,
            UNIQUE(articulo_id, fotografia_id)
        )
    """)

    db.execute("""
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
        )
    """)
    
    db.execute("""
        CREATE TABLE IF NOT EXISTS investigacion (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            titulo       TEXT NOT NULL,
            categoria    TEXT,
            autor        TEXT,
            fecha_doc    TEXT,
            descripcion  TEXT,
            archivo      TEXT,
            tipo_archivo TEXT DEFAULT 'pdf',
            periodico    TEXT,
            pagina       TEXT,
            fecha_alta   TEXT NOT NULL
        )
    """)
    cols_inv = [row[1] for row in db.execute("PRAGMA table_info(investigacion)").fetchall()]
    if "tipo_archivo" not in cols_inv: db.execute("ALTER TABLE investigacion ADD COLUMN tipo_archivo TEXT DEFAULT 'pdf'")
    if "periodico"    not in cols_inv: db.execute("ALTER TABLE investigacion ADD COLUMN periodico TEXT")
    if "pagina"       not in cols_inv: db.execute("ALTER TABLE investigacion ADD COLUMN pagina TEXT")
    
    db.execute("""
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
        )
    """)
    
    db.execute("""
        CREATE TABLE IF NOT EXISTS fotografias_personas (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            fotografia_id INTEGER NOT NULL REFERENCES fotografias(id) ON DELETE CASCADE,
            persona_id    INTEGER NOT NULL REFERENCES personas(id)    ON DELETE CASCADE,
            UNIQUE(fotografia_id, persona_id)
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS fotografias_investigacion (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            fotografia_id     INTEGER NOT NULL REFERENCES fotografias(id)     ON DELETE CASCADE,
            investigacion_id  INTEGER NOT NULL REFERENCES investigacion(id)   ON DELETE CASCADE,
            UNIQUE(fotografia_id, investigacion_id)
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS hitos_persona (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            persona_id   INTEGER NOT NULL REFERENCES personas(id) ON DELETE CASCADE,
            tipo         TEXT NOT NULL DEFAULT 'ascenso',
            titulo       TEXT NOT NULL,
            fecha        TEXT,
            detalle      TEXT,
            orden_manual INTEGER DEFAULT 0,
            fecha_alta   TEXT NOT NULL
        )
    """)

    db.execute("""
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
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS afirmaciones (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            entidad_tipo TEXT NOT NULL,
            entidad_id   INTEGER NOT NULL,
            campo        TEXT NOT NULL,
            certeza      TEXT NOT NULL DEFAULT 'probable',
            fuente_id    INTEGER REFERENCES bibliografia(id) ON DELETE SET NULL,
            notas        TEXT,
            fecha_alta   TEXT NOT NULL,
            UNIQUE(entidad_tipo, entidad_id, campo)
        )
    """)

    db.commit()
    db.close()

NIVELES_CERTEZA = {
    "confirmado":    {"label": "✔ Confirmado",    "color": "#3d6b2a"},
    "probable":      {"label": "◐ Probable",      "color": "#8a7a2a"},
    "dudoso":        {"label": "❓ Dudoso",        "color": "#b5651d"},
    "especulativo":  {"label": "✳ Especulativo",  "color": "#8b3a2a"},
}

def obtener_afirmaciones(entidad_tipo, entidad_id):
    """Devuelve un dict {campo: afirmación-con-fuente} para una entidad dada."""
    db = get_db()
    filas = db.execute("""
        SELECT a.*, b.titulo AS fuente_titulo, b.autor AS fuente_autor
        FROM afirmaciones a LEFT JOIN bibliografia b ON b.id = a.fuente_id
        WHERE a.entidad_tipo=? AND a.entidad_id=?
    """, (entidad_tipo, entidad_id)).fetchall()
    db.close()
    return {f["campo"]: dict(f) for f in filas}

def allowed_image(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_IMAGES

def allowed_video(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_VIDEOS

def allowed_pdf(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_PDF

def allowed_investigacion(filename):
    """Para el apartado de Investigación: admite PDF o imágenes (p. ej. fotos de periódicos)."""
    if "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[1].lower()
    return ext in ALLOWED_PDF or ext in ALLOWED_IMAGES

def tipo_investigacion(filename):
    ext = filename.rsplit(".", 1)[1].lower() if "." in filename else ""
    return "imagen" if ext in ALLOWED_IMAGES else "pdf"

def obtener_mapa_historias(db):
    """Devuelve {fotografia_id: articulo_id} con la primera entrada del Diario
    que documenta cada fotografía (si existe alguna)."""
    rows = db.execute("""
        SELECT fotografia_id, MIN(articulo_id) as articulo_id
        FROM articulos_fotografias
        GROUP BY fotografia_id
    """).fetchall()
    return {r["fotografia_id"]: r["articulo_id"] for r in rows}
# ══════════════════════════════════════════════════════════════════════════════
# ESTILOS CSS GLOBALES
# ══════════════════════════════════════════════════════════════════════════════
CSS_BASE = """
<link href="https://fonts.googleapis.com/css2?family=Merriweather:ital,wght@0,300;0,400;0,700;1,400&family=Playfair+Display:wght@400;600;700&family=Source+Sans+3:wght@300;400;500;600&display=swap" rel="stylesheet">
<style>
:root {
  --sepia:#f5efe0; --paper:#faf7f0; --ink:#1a1410;
  --brown:#6b4c2a; --rust:#8b3a2a; --tan:#c9a97a;
  --muted:#7a6a58; --border:#d4c4a8; --card:#ffffff;
  --shadow:0 2px 12px rgba(26,20,16,.08);
}
*{box-sizing:border-box;margin:0;padding:0;}
body{font-family:'Source Sans 3',sans-serif;background:var(--paper);color:var(--ink);min-height:100vh;}

header{background:var(--ink);color:var(--sepia);padding:1rem 1.5rem;display:flex;align-items:center;
       justify-content:flex-end;gap:1rem;flex-wrap:wrap;position:sticky;top:0;z-index:100;}
header > div:first-child{margin-right:auto;}
header h1{font-family:'Playfair Display',serif;font-size:clamp(1rem,4vw,1.4rem);letter-spacing:.03em;font-weight:600;}
header small{display:block;font-size:.75rem;color:var(--tan);font-weight:300;}
.header-right{display:flex;align-items:center;gap:.6rem;flex-wrap:wrap;}

.btn{display:inline-flex;align-items:center;gap:.3rem;padding:.32rem .7rem;border-radius:4px;font-size:.75rem;
     font-family:inherit;cursor:pointer;border:none;font-weight:500;text-decoration:none;
     transition:opacity .15s,transform .1s;white-space:nowrap;}
.btn:active{transform:scale(.97);}
.btn-primary  {background:var(--rust);color:#fff;}
.btn-secondary{background:transparent;color:var(--ink);border:1px solid var(--brown);}
.btn-sm       {padding:.25rem .55rem;font-size:.72rem;}
.btn:hover    {opacity:.85;}
.btn-edit-pro {background:transparent;color:var(--ink);border:1px solid var(--brown);font-weight:600;}
.btn-edit-pro:hover{background:rgba(107,76,42,.1);}
.btn-download {background:rgba(74,107,58,.12);color:#3d6b2a;border:1px solid rgba(74,107,58,.5);font-weight:600;}
.btn-download:hover{background:rgba(74,107,58,.22);}

.nav-link{color:var(--tan);font-size:.74rem;text-decoration:none;border:1px solid rgba(201,169,122,.4);
          padding:3px 8px;border-radius:4px;transition:border-color .2s,color .2s;}
.nav-link:hover{color:var(--sepia);border-color:var(--tan);}
.nav-link.active{background:rgba(201,169,122,.15);color:var(--sepia);border-color:var(--tan);}

.rol-badge{font-size:.7rem;padding:2px 8px;border-radius:99px;font-weight:600;letter-spacing:.04em;}
.rol-admin {background:rgba(139,58,42,.25);color:#e8b090;border:1px solid rgba(139,58,42,.4);}
.rol-lector{background:rgba(201,169,122,.15);color:var(--tan);border:1px solid rgba(201,169,122,.3);}

.overlay{display:none;position:fixed;inset:0;background:rgba(10,8,6,.85);z-index:200;
         align-items:center;justify-content:center;padding:1rem;}
.overlay.open{display:flex;}
.modal{background:var(--card);border-radius:8px;width:100%;max-width:680px;max-height:90vh;
       overflow-y:auto;display:flex;flex-direction:column;}
.modal-header{padding:1.1rem 1.5rem;border-bottom:1px solid var(--border);display:flex;align-items:center;
              justify-content:space-between;background:var(--ink);color:var(--sepia);
              border-radius:8px 8px 0 0;position:sticky;top:0;z-index:10;}
.modal-header h2{font-family:'Playfair Display',serif;font-size:1.1rem;}
.modal-body{padding:1.5rem;display:flex;flex-direction:column;gap:1.1rem;}
.modal-footer{padding:1rem 1.5rem;border-top:1px solid var(--border);display:flex;justify-content:flex-end;
              gap:.75rem;background:var(--sepia);border-radius:0 0 8px 8px;flex-wrap:wrap;}

.form-grid{display:grid;grid-template-columns:1fr 1fr;gap:.9rem;}
@media(max-width:520px){.form-grid{grid-template-columns:1fr;}}
.form-group{display:flex;flex-direction:column;gap:.35rem;}
.form-group.span2{grid-column:1/-1;}
label{font-size:.82rem;font-weight:600;color:var(--brown);text-transform:uppercase;letter-spacing:.05em;}
input[type=text],input[type=date],input[type=number],select,textarea{
  padding:.55rem .75rem;border:1px solid var(--border);border-radius:4px;
  font-family:inherit;font-size:.875rem;background:var(--paper);color:var(--ink);width:100%;}
input:focus,select:focus,textarea:focus{outline:none;border-color:var(--brown);
  box-shadow:0 0 0 2px rgba(107,76,42,.15);}
textarea{resize:vertical;min-height:90px;}

.toast{position:fixed;bottom:1.5rem;right:1.5rem;background:var(--ink);color:var(--sepia);
       padding:.75rem 1.25rem;border-radius:6px;font-size:.875rem;z-index:300;
       transform:translateY(100px);opacity:0;transition:transform .3s,opacity .3s;}
.toast.show{transform:translateY(0);opacity:1;}
</style>
"""

def header_usuario():
    u = usuario_activo()
    if not u:
        return ""
    rol_class = "rol-admin" if u["rol"] == "admin" else "rol-lector"
    rol_texto  = "Admin" if u["rol"] == "admin" else "Lector"
    return f"""
    <span class="rol-badge {rol_class}">{rol_texto}</span>
    <span style="font-size:.78rem;color:var(--tan);max-width:160px;overflow:hidden;
                 text-overflow:ellipsis;white-space:nowrap;">{u['correo']}</span>
    <a href="/logout" class="nav-link" style="font-size:.75rem;">Salir</a>
    """

NAV_LINKS = """
<a href="/" class="nav-link {g}">🖼 Galería</a>
<a href="/fotos" class="nav-link {f}">📸 Fotos</a>
<a href="/videos" class="nav-link {v}">🎬 Vídeos</a>
<a href="/linea-temporal" class="nav-link {t}">📅 Cronología</a>
<a href="/mapa" class="nav-link {m}">🗺 Mapa</a>
<a href="/blog" class="nav-link {b}">✍️ Diario</a>
<a href="/investigacion" class="nav-link {inv}">📄 Investigación</a>
<a href="/personas" class="nav-link {per}">🧑‍✈️ Personas</a>
<a href="/bibliografia" class="nav-link {bib}">📚 Bibliografía</a>
<a href="/descargas" class="nav-link {desc}">⬇️ Descargas</a>
"""

def nav(active=""):
    return NAV_LINKS.format(
        g="active" if active=="galeria" else "",
        f="active" if active=="fotos" else "",
        v="active" if active=="videos" else "",
        t="active" if active=="timeline" else "",
        m="active" if active=="mapa" else "",
        b="active" if active=="blog" else "",
        inv="active" if active=="investigacion" else "",
        per="active" if active=="personas" else "",
        bib="active" if active=="bibliografia" else "",
        desc="active" if active=="descargas" else "",
    )

MODAL_DETALLE_HTML = """
<div class="overlay" id="modal-detalle">
  <div class="modal">
    <div class="modal-header">
      <h2 id="detalle-titulo">—</h2>
      <button class="btn btn-secondary btn-sm" onclick="cerrarModal('modal-detalle')"
              style="color:var(--sepia);border-color:var(--sepia);">✕ Cerrar</button>
    </div>
    <div class="modal-body" id="detalle-body"></div>
    <div class="modal-footer">
      <button class="btn btn-secondary" onclick="cerrarModal('modal-detalle')">Cerrar</button>
      <button class="btn btn-download" id="btn-descargar-detalle">⬇️ Descargar foto</button>
      <button class="btn btn-secondary" id="btn-qr-detalle">🔗 Ver QR</button>
      <button class="btn btn-edit-pro" id="btn-editar-detalle"
              style="display:{{ 'inline-flex' if admin else 'none' }}">✏️ Editar Ficha</button>
    </div>
  </div>
</div>
"""

SCRIPT_DETALLE = """
function verDetalle(id) {
  fetch('/foto-detalle/' + id).then(r => r.json()).then(f => {
    document.getElementById('detalle-titulo').textContent = f.titulo;
    document.getElementById('btn-editar-detalle').onclick = () => { cerrarModal('modal-detalle'); editarFoto(id); };
    document.getElementById('btn-qr-detalle').onclick = () => { window.open('/ficha/'+id,'_blank'); };
    document.getElementById('btn-descargar-detalle').onclick = () => { window.location.href = '/descargar-foto/'+id; };
    document.getElementById('btn-descargar-detalle').style.display = f.archivo ? '' : 'none';
    let html = f.archivo ? `<img src="/foto/${f.archivo}" class="detail-img">` : '';
    html += '<div style="display:grid;grid-template-columns:1fr 1fr;gap:.85rem;margin-top:1rem;">';
    [['📅 Fecha',f.fecha_foto],['📍 Ubicación',f.ubicacion],['🏳 País',f.pais],
     ['⚔️ Frente',f.frente],['📚 Fuente',f.fuente],['🏷 Etiquetas',f.etiquetas],
     ['🌐 GPS',(f.lat&&f.lon)?`${f.lat}, ${f.lon}`:null]]
      .forEach(([lbl,val])=>{if(val)html+=`<div class="detail-field">
        <div class="lbl">${lbl}</div><div class="val">${val}</div></div>`;});
    html += '</div>';
    if(f.descripcion) html += `<div class="detail-field" style="margin-top:1rem;padding-top:1rem;border-top:1px solid var(--border);">
      <div class="lbl" style="margin-bottom:5px;">📝 Descripción / Notas</div>
      <div class="val" style="white-space:pre-wrap;line-height:1.6;">${f.descripcion}</div></div>`;
    if(f.personas && f.personas.length){
      html += '<div class="detail-field" style="margin-top:1rem;padding-top:1rem;border-top:1px solid var(--border);">'
            + '<div class="lbl" style="margin-bottom:8px;">🧑‍✈️ Personas identificadas</div>'
            + '<div style="display:flex;flex-wrap:wrap;gap:.4rem;">';
      f.personas.forEach(p => {
        html += `<a href="/persona/${p.id}" class="tag" style="text-decoration:none;">🧑 ${p.nombre}</a>`;
      });
      html += '</div></div>';
    }
    if(f.articulos && f.articulos.length){
      html += '<div class="detail-field" style="margin-top:1rem;padding-top:1rem;border-top:1px solid var(--border);">'
            + '<div class="lbl" style="margin-bottom:8px;">📖 Historia relacionada</div>'
            + '<div style="display:flex;flex-direction:column;gap:.4rem;">';
      f.articulos.forEach(a => {
        html += `<a href="/blog?abrir=${a.id}" class="btn btn-sm btn-secondary" style="justify-content:flex-start;">📖 ${a.titulo}</a>`;
      });
      html += '</div></div>';
    }
    if(f.documentos && f.documentos.length){
      html += '<div class="detail-field" style="margin-top:1rem;padding-top:1rem;border-top:1px solid var(--border);">'
            + '<div class="lbl" style="margin-bottom:8px;">📄 Documentos de investigación relacionados</div>'
            + '<div style="display:flex;flex-direction:column;gap:.4rem;">';
      f.documentos.forEach(d => {
        const icono = d.tipo_archivo === 'imagen' ? '🗞' : '📄';
        if(d.archivo){
          html += `<a href="/pdf/${d.archivo}" target="_blank" class="btn btn-sm btn-secondary" style="justify-content:flex-start;">${icono} ${d.titulo}</a>`;
        } else {
          html += `<a href="/investigacion" class="btn btn-sm btn-secondary" style="justify-content:flex-start;">${icono} ${d.titulo}</a>`;
        }
      });
      html += '</div></div>';
    }
    document.getElementById('detalle-body').innerHTML = html;
    abrirModal('modal-detalle');
  });
}
"""
# ══════════════════════════════════════════════════════════════════════════════
# LOGIN PAGE
# ══════════════════════════════════════════════════════════════════════════════
HTML_LOGIN = """
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Acceso · Archivo Histórico IIGM</title>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@400;600;700&family=Source+Sans+3:wght@300;400;500&display=swap" rel="stylesheet">
<style>
*{box-sizing:border-box;margin:0;padding:0;}
body{font-family:'Source Sans 3',sans-serif;background:#0e0c08;
     display:flex;align-items:center;justify-content:center;min-height:100vh;padding:1rem;}
.login-box{background:#1a1410;border:1px solid #3a2e1a;border-radius:10px;padding:2.5rem 2rem;
           width:100%;max-width:400px;box-shadow:0 8px 40px rgba(0,0,0,.6);}
.login-logo{text-align:center;margin-bottom:2rem;}
.login-logo h1{font-family:'Playfair Display',serif;font-size:1.5rem;color:#c9a97a;
               letter-spacing:.04em;font-weight:600;line-height:1.3;}
.login-logo small{display:block;font-size:.75rem;color:#7a6a58;margin-top:.3rem;}
.login-logo .emblema{font-size:2.5rem;display:block;margin-bottom:.75rem;}
.form-group{margin-bottom:1.1rem;}
label{display:block;font-size:.78rem;font-weight:600;color:#c9a97a;
      text-transform:uppercase;letter-spacing:.06em;margin-bottom:.4rem;}
input[type=email],input[type=password]{width:100%;padding:.65rem .85rem;background:#0e0c08;
  border:1px solid #3a2e1a;border-radius:5px;font-family:inherit;font-size:.9rem;
  color:#e8dfc8;transition:border-color .2s;}
input:focus{outline:none;border-color:#c9a97a;box-shadow:0 0 0 2px rgba(201,169,122,.15);}
input::placeholder{color:#4a3e30;}
.btn-login{width:100%;padding:.75rem;margin-top:.5rem;background:#8b3a2a;color:#fff;border:none;
           border-radius:5px;font-family:inherit;font-size:.95rem;font-weight:600;cursor:pointer;
           letter-spacing:.03em;transition:background .2s;}
.btn-login:hover{background:#a04535;}
.error-msg{background:rgba(139,58,42,.2);border:1px solid #8b3a2a;border-radius:5px;
           padding:.65rem .85rem;font-size:.82rem;color:#e8a090;margin-bottom:1rem;}
.hint{font-size:.72rem;color:#4a3e30;text-align:center;margin-top:1.25rem;line-height:1.5;}
</style>
</head>
<body>
<div class="login-box">
  <div class="login-logo">
    <span class="emblema">🎖</span>
    <h1>Archivo Histórico<br>Erwin Rommel</h1>
    <small>Segunda Guerra Mundial · Colección privada</small>
  </div>
  {% if error %}<div class="error-msg">⚠️ {{ error }}</div>{% endif %}
  <form method="post" action="/login">
    <input type="hidden" name="next" value="{{ next }}">
    <div class="form-group">
      <label for="correo">Correo electrónico</label>
      <input type="email" id="correo" name="correo" required placeholder="tu@correo.com"
             autocomplete="email" value="{{ correo_previo }}">
    </div>
    <div class="form-group">
      <label for="contrasena">Contraseña de acceso</label>
      <input type="password" id="contrasena" name="contrasena" required
             placeholder="••••••••" autocomplete="current-password">
    </div>
    <button type="submit" class="btn-login">Entrar al archivo →</button>
  </form>
  <p class="hint">Archivo de acceso restringido.<br>Si no tienes contraseña, contacta con el administrador.</p>
</div>
</body>
</html>
"""
# ══════════════════════════════════════════════════════════════════════════════
# GALERÍA
# ══════════════════════════════════════════════════════════════════════════════
HTML = """
<!DOCTYPE html><html lang="es"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Archivo Histórico · IIGM</title>
""" + CSS_BASE + """
<style>
.search-bar{display:flex;gap:10px;padding:1.5rem;background:var(--sepia);border-bottom:1px solid var(--border);align-items:center;flex-wrap:wrap;}
.search-bar input,.search-bar select{flex:1;min-width:150px;padding:10px;border:1px solid var(--border);border-radius:4px;background:#fff;}
.gallery{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:20px;padding:20px;}
.foto-card{background:var(--card);border:1px solid var(--border);border-radius:8px;overflow:hidden;
           box-shadow:var(--shadow);cursor:pointer;transition:transform .15s,box-shadow .15s;display:flex;flex-direction:column;}
.foto-card:hover{transform:translateY(-5px);box-shadow:0 6px 20px rgba(26,20,16,.14);}
.foto-img{width:100%;aspect-ratio:4/3;object-fit:cover;background:var(--sepia);display:flex;align-items:center;
          justify-content:center;color:var(--tan);font-size:3rem;overflow:hidden;}
.foto-img img{width:100%;height:100%;object-fit:cover;display:block;}
.foto-body{padding:1rem;flex:1;display:flex;flex-direction:column;gap:.4rem;}
.foto-title{font-family:'Playfair Display',serif;font-size:1.1rem;font-weight:600;line-height:1.3;}
.foto-meta{font-size:.78rem;color:var(--muted);display:flex;flex-wrap:wrap;gap:.6rem;}
.foto-desc{font-size:.85rem;color:var(--muted);line-height:1.5;margin-top:.4rem;flex:1;
           display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;}
.tag-list{display:flex;flex-wrap:wrap;gap:.3rem;margin-top:.5rem;}
.tag{font-size:.7rem;padding:.15rem .5rem;border-radius:99px;background:var(--sepia);color:var(--brown);border:1px solid var(--border);}
.foto-footer{padding:.8rem 1rem;border-top:1px solid var(--border);display:flex;gap:.5rem;background:var(--paper);flex-wrap:wrap;}
.empty{text-align:center;padding:4rem 2rem;color:var(--muted);grid-column:1/-1;}
.upload-zone{border:2px dashed var(--border);border-radius:6px;padding:1.5rem;text-align:center;cursor:pointer;transition:border-color .2s;color:var(--muted);font-size:.875rem;}
.upload-zone:hover{border-color:var(--brown);background:var(--sepia);}
#preview-img{max-width:100%;max-height:180px;border-radius:4px;display:none;margin:.75rem auto 0;object-fit:contain;}
.detail-img{width:100%;max-height:400px;object-fit:contain;background:var(--sepia);border-radius:4px;}
.detail-field{display:flex;flex-direction:column;gap:.2rem;}
.detail-field .lbl{font-size:.75rem;font-weight:600;color:var(--tan);text-transform:uppercase;letter-spacing:.05em;}
.detail-field .val{font-size:.95rem;color:var(--ink);}
/* ── MODO ORDENAR (galería) ── */
.modo-orden .foto-card{cursor:grab;user-select:none;}
.modo-orden .foto-card:active{cursor:grabbing;}
.modo-orden .foto-card.dragging{opacity:.35;outline:2px dashed var(--brown);}
.modo-orden .foto-card.drag-over{outline:3px solid var(--brown);outline-offset:-2px;}
.orden-bar{position:fixed;bottom:1.5rem;left:50%;transform:translateX(-50%);
           background:var(--ink);color:var(--sepia);padding:.85rem 1.5rem;border-radius:8px;
           z-index:200;display:none;align-items:center;gap:1rem;
           box-shadow:0 4px 24px rgba(0,0,0,.4);border:1px solid #3a2e1a;white-space:nowrap;}
.orden-bar.visible{display:flex;}
</style>
</head><body>

<header>
  <div><h1>Archivo Histórico · Erwin Rommel</h1><small>{{ total }} fotografías catalogadas</small></div>
  <div class="header-right">
    {{ nav | safe }}
    {% if admin %}
    <button class="btn btn-primary" onclick="abrirNueva()">+ Añadir foto</button>
    <button class="btn" id="btn-toggle-orden" onclick="toggleOrden()"
            style="background:rgba(107,76,42,.15);color:var(--brown);border:1px solid var(--brown);
                   font-weight:600;letter-spacing:.02em;">⇅ Ordenar</button>
    {% endif %}
    <a href="/descargas" class="btn btn-download">⬇️ Descargar todo</a>
    {{ header_usuario | safe }}
  </div>
</header>

<form class="search-bar" method="get" action="/">
  <input type="text" name="q" placeholder="Buscar por título, lugar, descripción…" value="{{ q }}">
  <select name="frente"><option value="">— Todos los frentes —</option>
    {% for f in frentes %}<option value="{{ f }}" {{ 'selected' if f==frente_sel }}>{{ f }}</option>{% endfor %}
  </select>
  <select name="pais"><option value="">— Todos los países —</option>
    {% for p in paises %}<option value="{{ p }}" {{ 'selected' if p==pais_sel }}>{{ p }}</option>{% endfor %}
  </select>
  <button type="submit" class="btn btn-primary">Buscar</button>
  <a href="/" class="btn btn-secondary">Limpiar</a>
</form>

<div class="gallery" id="foto-grid">
  {% if fotos %}
    {% for f in fotos %}
    <div class="foto-card"
         onclick="verDetalle({{ f.id }})"
         data-id="{{ f.id }}"
         data-fecha="{{ f.fecha_foto or '' }}">
      <div class="foto-img">{% if f.archivo %}<img src="/foto/{{ f.archivo }}" alt="{{ f.titulo }}">{% else %}📷{% endif %}</div>
      <div class="foto-body">
        <div class="foto-title">{{ f.titulo }}</div>
        <div class="foto-meta">
          {% if f.fecha_foto %}<span>📅 {{ f.fecha_foto }}</span>{% endif %}
          {% if f.ubicacion %}<span>📍 {{ f.ubicacion }}</span>{% endif %}
          {% if f.pais %}<span>🏳 {{ f.pais }}</span>{% endif %}
        </div>
        {% if f.descripcion %}<div class="foto-desc">{{ f.descripcion }}</div>{% endif %}
        {% if f.etiquetas %}
        <div class="tag-list">
          {% for t in f.etiquetas.split(',') %}{% if t.strip() %}<span class="tag">{{ t.strip() }}</span>{% endif %}{% endfor %}
        </div>
        {% endif %}
      </div>
      <div class="foto-footer" onclick="event.stopPropagation()">
        {% if admin %}
        <button class="btn btn-sm btn-edit-pro" onclick="editarFoto({{ f.id }})">✏️ Editar</button>
        <button class="btn btn-sm" style="background:var(--rust);color:#fff;"
                onclick="confirmarBorrar({{ f.id }},'{{ f.titulo|replace("'","\\'")|safe }}')">🗑 Borrar</button>
        {% endif %}
        {% if f.archivo %}
        <a href="/descargar-foto/{{ f.id }}" class="btn btn-sm btn-download">⬇️ Descargar</a>
        {% endif %}
        {% if f.id in historia_map %}
        <a href="/blog?abrir={{ historia_map[f.id] }}" class="btn btn-sm"
           style="background:#4a3f7a;color:#fff;">📖 Ver historia</a>
        {% endif %}
        <a href="/ficha/{{ f.id }}" target="_blank" class="btn btn-sm btn-secondary">🔗 QR</a>
      </div>
    </div>
    {% endfor %}
  {% else %}
  <div class="empty"><div style="font-size:3rem;margin-bottom:1rem">📂</div><h3>No hay fotografías todavía</h3></div>
  {% endif %}
</div>

{% if admin %}
<div class="orden-bar" id="orden-bar">
  <span style="font-size:.82rem;">Arrastra fotos del <strong>mismo día</strong> para reordenarlas</span>
  <button class="btn btn-primary btn-sm" onclick="guardarOrden()">💾 Guardar orden</button>
  <button class="btn btn-secondary btn-sm" onclick="cancelarOrden()">✕ Cancelar</button>
</div>
{% endif %}

{% if admin %}
<!-- MODAL AÑADIR/EDITAR -->
<div class="overlay" id="modal-form">
  <div class="modal">
    <div class="modal-header"><h2 id="modal-title">Nueva fotografía</h2>
      <button class="btn btn-secondary btn-sm" onclick="cerrarModal('modal-form')"
              style="color:var(--sepia);border-color:var(--sepia);">✕ Cerrar</button></div>
    <div class="modal-body">
      <form id="form-foto" enctype="multipart/form-data" method="post" action="/guardar">
        <input type="hidden" name="id" id="foto-id">
        <div class="form-grid">
          <div class="form-group span2"><label>Título *</label><input type="text" id="titulo" name="titulo" required></div>
          <div class="form-group"><label>Fecha</label><input type="date" id="fecha_foto" name="fecha_foto"></div>
          <div class="form-group"><label>Frente / Campaña</label>
            <input type="text" id="frente" name="frente" list="frentes-list">
            <datalist id="frentes-list">{% for f in frentes %}<option value="{{ f }}">{% endfor %}</datalist>
          </div>
          <div class="form-group"><label>Ubicación</label><input type="text" id="ubicacion" name="ubicacion"></div>
          <div class="form-group"><label>País</label>
            <input type="text" id="pais" name="pais" list="paises-list">
            <datalist id="paises-list">{% for p in paises %}<option value="{{ p }}">{% endfor %}</datalist>
          </div>
          <div class="form-group"><label>Fuente / Procedencia</label><input type="text" id="fuente" name="fuente"></div>
          <div class="form-group"><label>Etiquetas (separadas por comas)</label><input type="text" id="etiquetas" name="etiquetas"></div>
          <div class="form-group"><label>Latitud (GPS)</label><input type="number" id="lat" name="lat" step="0.000001"></div>
          <div class="form-group"><label>Longitud (GPS)</label><input type="number" id="lon" name="lon" step="0.000001"></div>
          <div class="form-group span2"><label>📝 Descripción / Notas</label><textarea id="descripcion" name="descripcion"></textarea></div>
          <div class="form-group span2">
  <label>Fotografía</label>
  <div class="upload-zone" id="upload-zone" onclick="document.getElementById('archivo').click()">
    <span id="upload-text" style="font-size:1.2rem">📸 Pulsa para seleccionar una foto</span>
  </div>
  <input type="file" id="archivo" name="archivo" accept="image/*" style="display:none" onchange="previsualizarImagen(this)">
  <img id="preview-img" alt="Vista previa">
</div>
          <div class="form-group span2">
            <label>🧑‍✈️ Personas que aparecen</label>
            <div style="border:1px solid var(--border);border-radius:4px;max-height:150px;overflow-y:auto;padding:8px;background:var(--paper);">
              {% for p in personas %}
              <label style="display:flex;align-items:center;gap:8px;padding:4px 0;font-size:.85rem;cursor:pointer;">
                <input type="checkbox" name="personas_ids" value="{{ p.id }}" class="persona-cb">
                {{ p.nombre }}{% if p.rango %} <small style="color:var(--muted)">({{ p.rango }})</small>{% endif %}
              </label>
              {% endfor %}
              {% if not personas %}<p style="font-size:.8rem;color:var(--muted)">No hay personas registradas. Añádelas desde la sección Personas.</p>{% endif %}
            </div>
          </div>
          <div class="form-group span2">
            <label>📄 Documentos de investigación relacionados</label>
            <div style="border:1px solid var(--border);border-radius:4px;max-height:150px;overflow-y:auto;padding:8px;background:var(--paper);">
              {% for d in documentos %}
              <label style="display:flex;align-items:center;gap:8px;padding:4px 0;font-size:.85rem;cursor:pointer;">
                <input type="checkbox" name="investigacion_ids" value="{{ d.id }}" class="inv-cb">
                {{ d.titulo }}{% if d.categoria %} <small style="color:var(--muted)">({{ d.categoria }})</small>{% endif %}
              </label>
              {% endfor %}
              {% if not documentos %}<p style="font-size:.8rem;color:var(--muted)">No hay documentos registrados. Añádelos desde la sección Investigación.</p>{% endif %}
            </div>
          </div>
        </div>
      </form>
    </div>
    <div class="modal-footer">
      <button class="btn btn-secondary" onclick="cerrarModal('modal-form')">Cancelar</button>
      <button class="btn btn-primary" onclick="document.getElementById('form-foto').submit()">💾 Guardar</button>
    </div>
  </div>
</div>
{% endif %}

""" + MODAL_DETALLE_HTML + """

<div class="toast" id="toast"></div>

<script>
const ADMIN = {{ 'true' if admin else 'false' }};
function abrirModal(id){document.getElementById(id).classList.add('open');}
function cerrarModal(id){document.getElementById(id).classList.remove('open');}
document.querySelectorAll('.overlay').forEach(o=>o.addEventListener('click',e=>{if(e.target===o)o.classList.remove('open');}));

{% if admin %}
function abrirNueva(){
  document.getElementById('modal-title').textContent='Nueva fotografía';
  document.getElementById('form-foto').reset();
  document.getElementById('foto-id').value='';
  document.getElementById('preview-img').style.display='none';
  document.getElementById('upload-text').innerHTML='📸 Pulsa para seleccionar una foto';
  document.querySelectorAll('.persona-cb').forEach(cb=>cb.checked=false);
  document.querySelectorAll('.inv-cb').forEach(cb=>cb.checked=false);
  abrirModal('modal-form');
}
function previsualizarImagen(input){
  if(!input.files[0])return;
  const reader=new FileReader();
  reader.onload=e=>{document.getElementById('preview-img').src=e.target.result;
    document.getElementById('preview-img').style.display='block';
    document.getElementById('upload-text').textContent='📎 '+input.files[0].name;};
  reader.readAsDataURL(input.files[0]);
}
function editarFoto(id){
  fetch('/foto-detalle/'+id).then(r=>r.json()).then(f=>{
    document.getElementById('modal-title').textContent='Editar fotografía';
    document.getElementById('foto-id').value=f.id;
    ['titulo','fecha_foto','frente','ubicacion','pais','fuente','etiquetas','descripcion','lat','lon']
      .forEach(k=>{if(document.getElementById(k))document.getElementById(k).value=f[k]||'';});
    if(f.archivo){document.getElementById('preview-img').src='/foto/'+f.archivo;
      document.getElementById('preview-img').style.display='block';
      document.getElementById('upload-text').textContent='📎 Archivo subido';}
    else{document.getElementById('preview-img').style.display='none';
      document.getElementById('upload-text').innerHTML='📸 Pulsa para seleccionar una foto';}
    document.querySelectorAll('.persona-cb').forEach(cb=>{
      cb.checked = (f.personas_ids||[]).includes(parseInt(cb.value));
    });
    document.querySelectorAll('.inv-cb').forEach(cb=>{
      cb.checked = (f.investigacion_ids||[]).includes(parseInt(cb.value));
    });
    abrirModal('modal-form');
  });
}
function confirmarBorrar(id,titulo){
  if(confirm('¿Seguro que quieres borrar «'+titulo+'»?'))
    fetch('/borrar/'+id,{method:'POST'}).then(()=>location.reload());
}
{% else %}
function abrirNueva(){}
function editarFoto(){}
function confirmarBorrar(){}
{% endif %}

/* ── TOAST ── */
function mostrarToast(msg, dur=2800){
  const t=document.getElementById('toast');
  t.textContent=msg; t.classList.add('show');
  clearTimeout(t._timer);
  t._timer=setTimeout(()=>t.classList.remove('show'), dur);
}

/* ── MODO ORDENAR (galería) ── */
{% if admin %}
let modoOrden = false;
let dragSrc   = null;
let ordenOriginal = [];

function toggleOrden(){
  modoOrden = true;
  ordenOriginal = [...document.querySelectorAll('.foto-card')].map(el => ({
    id: el.dataset.id, fecha: el.dataset.fecha, el: el
  }));
  activarOrden();
}

function activarOrden(){
  document.getElementById('foto-grid').classList.add('modo-orden');
  document.getElementById('btn-toggle-orden').style.display = 'none';
  document.getElementById('orden-bar').classList.add('visible');
  document.querySelectorAll('.foto-card').forEach(el => {
    el.setAttribute('draggable', 'true');
    el.addEventListener('dragstart',  onDragStart);
    el.addEventListener('dragover',   onDragOver);
    el.addEventListener('dragleave',  onDragLeave);
    el.addEventListener('drop',       onDrop);
    el.addEventListener('dragend',    onDragEnd);
    el._clickOriginal = el.onclick;
    el.onclick = null;
  });
  mostrarToast('Modo orden activado — arrastra fotos del mismo día');
}

function desactivarOrden(){
  document.getElementById('foto-grid').classList.remove('modo-orden');
  document.getElementById('btn-toggle-orden').style.display = '';
  document.getElementById('orden-bar').classList.remove('visible');
  document.querySelectorAll('.foto-card').forEach(el => {
    el.removeAttribute('draggable');
    el.removeEventListener('dragstart',  onDragStart);
    el.removeEventListener('dragover',   onDragOver);
    el.removeEventListener('dragleave',  onDragLeave);
    el.removeEventListener('drop',       onDrop);
    el.removeEventListener('dragend',    onDragEnd);
    if(el._clickOriginal) el.onclick = el._clickOriginal;
  });
  modoOrden = false;
}

function cancelarOrden(){
  const grid = document.getElementById('foto-grid');
  ordenOriginal.forEach(item => grid.appendChild(item.el));
  desactivarOrden();
  mostrarToast('Orden cancelado');
}

function onDragStart(e){
  dragSrc = this;
  this.classList.add('dragging');
  e.dataTransfer.effectAllowed = 'move';
  e.dataTransfer.setData('text/plain', this.dataset.id);
}
function onDragOver(e){
  e.preventDefault();
  e.dataTransfer.dropEffect = 'move';
  if(this !== dragSrc) this.classList.add('drag-over');
}
function onDragLeave(){ this.classList.remove('drag-over'); }
function onDrop(e){
  e.stopPropagation();
  this.classList.remove('drag-over');
  if(!dragSrc || this === dragSrc) return;
  if(this.dataset.fecha !== dragSrc.dataset.fecha){
    mostrarToast('⚠️ Solo puedes reordenar fotos del mismo día');
    return;
  }
  const grid  = document.getElementById('foto-grid');
  const cards = [...grid.querySelectorAll('.foto-card')];
  const si    = cards.indexOf(dragSrc);
  const di    = cards.indexOf(this);
  if(si < di) this.after(dragSrc);
  else        this.before(dragSrc);
}
function onDragEnd(){
  document.querySelectorAll('.foto-card').forEach(el =>
    el.classList.remove('dragging','drag-over'));
  dragSrc = null;
}

function guardarOrden(){
  const items = [...document.querySelectorAll('.foto-card')].map((el, i) => ({
    id: parseInt(el.dataset.id), orden: i
  }));
  fetch('/guardar-orden', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(items)
  })
  .then(r => r.json())
  .then(d => {
    if(d.ok){ desactivarOrden(); mostrarToast('✅ Orden guardado correctamente'); }
    else mostrarToast('⚠️ Error al guardar el orden');
  })
  .catch(() => mostrarToast('⚠️ Error de conexión'));
}
{% endif %}
""" + SCRIPT_DETALLE + """
</script>
</body></html>
"""
# ══════════════════════════════════════════════════════════════════════════════
# FOTOS (cuadrícula pura) — con drag & drop para ordenar
# ══════════════════════════════════════════════════════════════════════════════
HTML_FOTOS = """
<!DOCTYPE html><html lang="es"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Fotos · IIGM</title>
""" + CSS_BASE + """
<style>
body{background:#0e0c08;}
.foto-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(220px,100%),1fr));gap:4px;padding:4px;}
.foto-pura{position:relative;aspect-ratio:1/1;overflow:hidden;cursor:pointer;background:#1a1408;}
.foto-pura img{width:100%;height:100%;object-fit:cover;display:block;transition:transform .3s,opacity .2s;}
.foto-pura:hover img{transform:scale(1.04);opacity:.88;}
.foto-pura .sin-imagen{width:100%;height:100%;display:flex;align-items:center;justify-content:center;font-size:2.5rem;color:#3a3020;}
.foto-pura .hover-label{position:absolute;bottom:0;left:0;right:0;background:linear-gradient(transparent,rgba(10,8,4,.85));
  color:#e8dfc8;font-size:.72rem;padding:.5rem .6rem .4rem;transform:translateY(100%);
  transition:transform .2s;pointer-events:none;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.foto-pura:hover .hover-label{transform:translateY(0);}
.foto-pura .descarga-mini{position:absolute;top:6px;right:6px;width:30px;height:30px;border-radius:50%;
  background:rgba(10,8,4,.72);color:#e8dfc8;display:flex;align-items:center;justify-content:center;
  font-size:.95rem;text-decoration:none;opacity:0;transition:opacity .2s,background .2s;z-index:4;}
.foto-pura:hover .descarga-mini{opacity:1;}
.foto-pura .descarga-mini:hover{background:rgba(74,107,58,.85);}
.foto-pura .historia-mini{position:absolute;top:6px;left:6px;width:30px;height:30px;border-radius:50%;
  background:rgba(74,63,122,.85);color:#fff;display:flex;align-items:center;justify-content:center;
  font-size:.9rem;text-decoration:none;z-index:5;}
.foto-pura .historia-mini:hover{background:rgba(94,80,155,.95);}
.modo-orden .historia-mini{display:none;}
.detail-img{width:100%;max-height:400px;object-fit:contain;background:var(--sepia);border-radius:4px;}
.detail-field{display:flex;flex-direction:column;gap:.2rem;}
.detail-field .lbl{font-size:.75rem;font-weight:600;color:var(--tan);text-transform:uppercase;letter-spacing:.05em;}
.detail-field .val{font-size:.95rem;color:var(--ink);}

/* ── MODO ORDENAR ── */
.modo-orden .foto-pura{cursor:grab;}
.modo-orden .foto-pura:active{cursor:grabbing;}
.modo-orden .foto-pura.dragging{opacity:.35;outline:2px dashed #c9a97a;}
.modo-orden .foto-pura.drag-over{outline:3px solid #c9a97a;outline-offset:-2px;}
/* Etiqueta de fecha flotante en modo orden */
.fecha-badge{position:absolute;top:6px;left:6px;background:rgba(26,20,8,.82);color:#c9a97a;
             font-size:.65rem;padding:2px 7px;border-radius:99px;letter-spacing:.04em;
             pointer-events:none;display:none;z-index:4;}
.modo-orden .fecha-badge{display:block;}
.modo-orden .descarga-mini{display:none;}
/* Barra flotante guardar orden */
.orden-bar{position:fixed;bottom:1.5rem;left:50%;transform:translateX(-50%);
           background:#1a1410;color:#e8dfc8;padding:.85rem 1.5rem;border-radius:8px;
           z-index:200;display:none;align-items:center;gap:1rem;
           box-shadow:0 4px 24px rgba(0,0,0,.7);border:1px solid #3a2e1a;white-space:nowrap;}
.orden-bar.visible{display:flex;}
</style>
</head><body>
<header>
  <div><h1>Archivo Histórico · Erwin Rommel</h1><small>{{ total }} fotografías catalogadas</small></div>
  <div class="header-right">
    {{ nav | safe }}
    {% if admin %}
    <button class="btn" id="btn-toggle-orden" onclick="toggleOrden()"
            style="background:rgba(201,169,122,.18);color:#f0dfa8;border:1px solid rgba(201,169,122,.7);
                   font-weight:600;letter-spacing:.02em;">⇅ Ordenar fotos</button>
    {% endif %}
    <a href="/descargas" class="btn btn-download">⬇️ Descargar todo</a>
    {{ header_usuario | safe }}
  </div>
</header>

<div class="foto-grid" id="foto-grid">
  {% if fotos %}
    {% for f in fotos %}
    <div class="foto-pura"
         onclick="verDetalle({{ f.id }})"
         data-id="{{ f.id }}"
         data-fecha="{{ f.fecha_foto or '' }}">
      {% if f.archivo %}<img src="/foto/{{ f.archivo }}" alt="{{ f.titulo }}" loading="lazy">
      {% else %}<div class="sin-imagen">📷</div>{% endif %}
      <div class="hover-label">{{ f.titulo }}{% if f.fecha_foto %} · {{ f.fecha_foto }}{% endif %}</div>
      <div class="fecha-badge">{{ f.fecha_foto or 'Sin fecha' }}</div>
      {% if f.id in historia_map %}
      <a href="/blog?abrir={{ historia_map[f.id] }}" class="historia-mini" title="Ver historia detrás de esta foto"
         onclick="event.stopPropagation()">📖</a>
      {% endif %}
      {% if f.archivo %}
      <a href="/descargar-foto/{{ f.id }}" class="descarga-mini" title="Descargar"
         onclick="event.stopPropagation()">⬇️</a>
      {% endif %}
    </div>
    {% endfor %}
  {% else %}
    <div style="grid-column:1/-1;text-align:center;padding:5rem;color:#3a3020;font-size:1.1rem">Aún no hay fotografías.</div>
  {% endif %}
</div>

{% if admin %}
<div class="orden-bar" id="orden-bar">
  <span style="font-size:.82rem;">Arrastra fotos del <strong>mismo día</strong> para reordenarlas</span>
  <button class="btn btn-primary btn-sm" onclick="guardarOrden()">💾 Guardar orden</button>
  <button class="btn btn-secondary btn-sm"
          style="color:#e8dfc8;border-color:rgba(232,223,200,.3);"
          onclick="cancelarOrden()">✕ Cancelar</button>
</div>
{% endif %}

""" + MODAL_DETALLE_HTML + """

<div class="toast" id="toast"></div>

<script>
function abrirModal(id){document.getElementById(id).classList.add('open');}
function cerrarModal(id){document.getElementById(id).classList.remove('open');}
document.querySelectorAll('.overlay').forEach(o=>o.addEventListener('click',e=>{if(e.target===o)o.classList.remove('open');}));
function editarFoto(id){window.location.href='/?editar='+id;}

/* ── TOAST ── */
function mostrarToast(msg, dur=2800){
  const t=document.getElementById('toast');
  t.textContent=msg; t.classList.add('show');
  clearTimeout(t._timer);
  t._timer=setTimeout(()=>t.classList.remove('show'), dur);
}

/* ── MODO ORDENAR ── */
{% if admin %}
const ADMIN = true;
let modoOrden = false;
let dragSrc   = null;
let ordenOriginal = []; // snapshot para cancelar

function toggleOrden(){
  modoOrden = true;
  // Guardar snapshot del orden actual por si se cancela
  ordenOriginal = [...document.querySelectorAll('.foto-pura')].map(el => ({
    id: el.dataset.id, fecha: el.dataset.fecha, el: el
  }));
  activarOrden();
}

function activarOrden(){
  document.getElementById('foto-grid').classList.add('modo-orden');
  document.getElementById('btn-toggle-orden').style.display = 'none';
  document.getElementById('orden-bar').classList.add('visible');

  document.querySelectorAll('.foto-pura').forEach(el => {
    el.setAttribute('draggable', 'true');
    el.addEventListener('dragstart',  onDragStart);
    el.addEventListener('dragover',   onDragOver);
    el.addEventListener('dragleave',  onDragLeave);
    el.addEventListener('drop',       onDrop);
    el.addEventListener('dragend',    onDragEnd);
    // En modo orden, click no abre detalle
    el._clickOriginal = el.onclick;
    el.onclick = null;
  });
  mostrarToast('Modo orden activado — arrastra fotos del mismo día');
}

function desactivarOrden(){
  document.getElementById('foto-grid').classList.remove('modo-orden');
  document.getElementById('btn-toggle-orden').style.display = '';
  document.getElementById('orden-bar').classList.remove('visible');

  document.querySelectorAll('.foto-pura').forEach(el => {
    el.removeAttribute('draggable');
    el.removeEventListener('dragstart',  onDragStart);
    el.removeEventListener('dragover',   onDragOver);
    el.removeEventListener('dragleave',  onDragLeave);
    el.removeEventListener('drop',       onDrop);
    el.removeEventListener('dragend',    onDragEnd);
    if(el._clickOriginal) el.onclick = el._clickOriginal;
  });
  modoOrden = false;
}

function cancelarOrden(){
  // Restaurar el orden original en el DOM sin recargar página
  const grid = document.getElementById('foto-grid');
  ordenOriginal.forEach(item => grid.appendChild(item.el));
  desactivarOrden();
  mostrarToast('Orden cancelado');
}

function onDragStart(e){
  dragSrc = this;
  this.classList.add('dragging');
  e.dataTransfer.effectAllowed = 'move';
  e.dataTransfer.setData('text/plain', this.dataset.id);
}
function onDragOver(e){
  e.preventDefault();
  e.dataTransfer.dropEffect = 'move';
  if(this !== dragSrc) this.classList.add('drag-over');
}
function onDragLeave(e){
  this.classList.remove('drag-over');
}
function onDrop(e){
  e.stopPropagation();
  this.classList.remove('drag-over');
  if(!dragSrc || this === dragSrc) return;

  // Solo permite reordenar dentro del mismo grupo de fecha
  if(this.dataset.fecha !== dragSrc.dataset.fecha){
    mostrarToast('⚠️ Solo puedes reordenar fotos del mismo día');
    return;
  }

  // Insertar en el DOM en la posición correcta
  const grid  = document.getElementById('foto-grid');
  const cards = [...grid.querySelectorAll('.foto-pura')];
  const si    = cards.indexOf(dragSrc);
  const di    = cards.indexOf(this);
  if(si < di) this.after(dragSrc);
  else        this.before(dragSrc);
}
function onDragEnd(){
  document.querySelectorAll('.foto-pura').forEach(el => {
    el.classList.remove('dragging','drag-over');
  });
  dragSrc = null;
}

function guardarOrden(){
  // Asigna índice a TODAS las fotos visibles para preservar el orden relativo
  const items = [...document.querySelectorAll('.foto-pura')].map((el, i) => ({
    id:    parseInt(el.dataset.id),
    orden: i
  }));

  fetch('/guardar-orden', {
    method:  'POST',
    headers: {'Content-Type': 'application/json'},
    body:    JSON.stringify(items)
  })
  .then(r => r.json())
  .then(d => {
    if(d.ok){
      desactivarOrden();
      mostrarToast('✅ Orden guardado correctamente');
    } else {
      mostrarToast('⚠️ Error al guardar el orden');
    }
  })
  .catch(() => mostrarToast('⚠️ Error de conexión'));
}
{% else %}
const ADMIN = false;
{% endif %}

""" + SCRIPT_DETALLE + """
</script>
</body></html>
"""
# ══════════════════════════════════════════════════════════════════════════════
# VÍDEOS
# ══════════════════════════════════════════════════════════════════════════════
HTML_VIDEOS = """
<!DOCTYPE html><html lang="es"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Vídeos · IIGM</title>
""" + CSS_BASE + """
<style>
.search-bar{display:flex;gap:10px;padding:1.5rem;background:var(--sepia);
            border-bottom:1px solid var(--border);align-items:center;flex-wrap:wrap;}
.search-bar input,.search-bar select{flex:1;min-width:150px;padding:10px;
  border:1px solid var(--border);border-radius:4px;background:#fff;}
.video-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:20px;padding:20px;}
.video-card{background:var(--card);border:1px solid var(--border);border-radius:8px;overflow:hidden;
            box-shadow:var(--shadow);display:flex;flex-direction:column;}
.video-thumb{width:100%;aspect-ratio:16/9;background:#111;position:relative;cursor:pointer;overflow:hidden;}
.video-thumb video{width:100%;height:100%;object-fit:cover;display:block;}
.video-thumb .play-overlay{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;
  background:rgba(0,0,0,.35);transition:background .2s;}
.video-thumb:hover .play-overlay{background:rgba(0,0,0,.15);}
.play-btn{width:60px;height:60px;background:rgba(201,169,122,.9);border-radius:50%;
          display:flex;align-items:center;justify-content:center;font-size:1.5rem;
          transition:transform .2s;}
.video-thumb:hover .play-btn{transform:scale(1.1);}
.video-body{padding:1rem;flex:1;display:flex;flex-direction:column;gap:.4rem;}
.video-title{font-family:'Playfair Display',serif;font-size:1.1rem;font-weight:600;line-height:1.3;}
.video-meta{font-size:.78rem;color:var(--muted);display:flex;flex-wrap:wrap;gap:.6rem;}
.video-desc{font-size:.85rem;color:var(--muted);line-height:1.5;margin-top:.4rem;
            display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;}
.video-footer{padding:.8rem 1rem;border-top:1px solid var(--border);display:flex;gap:.5rem;
              background:var(--paper);flex-wrap:wrap;}
.tag{font-size:.7rem;padding:.15rem .5rem;border-radius:99px;background:var(--sepia);
     color:var(--brown);border:1px solid var(--border);}
.upload-zone{border:2px dashed var(--border);border-radius:6px;padding:1.5rem;text-align:center;
             cursor:pointer;transition:border-color .2s;color:var(--muted);font-size:.875rem;}
.upload-zone:hover{border-color:var(--brown);background:var(--sepia);}
.empty{text-align:center;padding:4rem 2rem;color:var(--muted);grid-column:1/-1;}
.video-player-wrap{width:100%;background:#000;border-radius:4px;overflow:hidden;}
.video-player-wrap video{width:100%;max-height:450px;display:block;}
.detail-field{display:flex;flex-direction:column;gap:.2rem;}
.detail-field .lbl{font-size:.75rem;font-weight:600;color:var(--tan);text-transform:uppercase;letter-spacing:.05em;}
.detail-field .val{font-size:.95rem;color:var(--ink);}
</style>
</head><body>

<header>
  <div><h1>Vídeos · Erwin Rommel</h1><small>{{ total }} vídeos archivados</small></div>
  <div class="header-right">
    {{ nav | safe }}
    {% if admin %}<button class="btn btn-primary" onclick="abrirNuevoVideo()">+ Añadir vídeo</button>{% endif %}
    <a href="/descargas" class="btn btn-download">⬇️ Descargar todo</a>
    {{ header_usuario | safe }}
  </div>
</header>

<form class="search-bar" method="get" action="/videos">
  <input type="text" name="q" placeholder="Buscar por título, lugar, descripción…" value="{{ q }}">
  <select name="frente"><option value="">— Todos los frentes —</option>
    {% for f in frentes %}<option value="{{ f }}" {{ 'selected' if f==frente_sel }}>{{ f }}</option>{% endfor %}
  </select>
  <button type="submit" class="btn btn-primary">Buscar</button>
  <a href="/videos" class="btn btn-secondary">Limpiar</a>
</form>

<div class="video-grid">
  {% if videos %}
    {% for v in videos %}
    <div class="video-card">
      <div class="video-thumb" onclick="reproducirVideo({{ v.id }})">
        {% if v.archivo %}
        <video src="/video/{{ v.archivo }}" preload="metadata" muted></video>
        {% else %}
        <div style="width:100%;height:100%;background:#1a1410;display:flex;align-items:center;justify-content:center;font-size:3rem;">🎬</div>
        {% endif %}
        <div class="play-overlay"><div class="play-btn">▶</div></div>
      </div>
      <div class="video-body">
        <div class="video-title">{{ v.titulo }}</div>
        <div class="video-meta">
          {% if v.fecha_video %}<span>📅 {{ v.fecha_video }}</span>{% endif %}
          {% if v.ubicacion %}<span>📍 {{ v.ubicacion }}</span>{% endif %}
          {% if v.duracion %}<span>⏱ {{ v.duracion }}</span>{% endif %}
        </div>
        {% if v.descripcion %}<div class="video-desc">{{ v.descripcion }}</div>{% endif %}
        {% if v.etiquetas %}
        <div style="display:flex;flex-wrap:wrap;gap:.3rem;margin-top:.5rem;">
          {% for t in v.etiquetas.split(',') %}{% if t.strip() %}<span class="tag">{{ t.strip() }}</span>{% endif %}{% endfor %}
        </div>
        {% endif %}
      </div>
      <div class="video-footer">
        {% if admin %}
        <button class="btn btn-sm btn-edit-pro" onclick="editarVideo({{ v.id }})">✏️ Editar</button>
        <button class="btn btn-sm" style="background:var(--rust);color:#fff;"
                onclick="confirmarBorrarVideo({{ v.id }},'{{ v.titulo|replace("'","\\'")|safe }}')">🗑 Borrar</button>
        {% endif %}
        {% if v.archivo %}
        <a href="/descargar-video/{{ v.id }}" class="btn btn-sm btn-download">⬇️ Descargar</a>
        {% endif %}
        <button class="btn btn-sm btn-secondary" onclick="reproducirVideo({{ v.id }})">▶ Reproducir</button>
      </div>
    </div>
    {% endfor %}
  {% else %}
  <div class="empty"><div style="font-size:3rem;margin-bottom:1rem">🎬</div><h3>No hay vídeos todavía</h3>
    {% if admin %}<p style="margin-top:.5rem;font-size:.9rem">Pulsa "+ Añadir vídeo" para subir el primero.</p>{% endif %}
  </div>
  {% endif %}
</div>

<!-- MODAL REPRODUCTOR -->
<div class="overlay" id="modal-video-player">
  <div class="modal" style="max-width:780px;">
    <div class="modal-header">
      <h2 id="vp-titulo">—</h2>
      <button class="btn btn-secondary btn-sm" onclick="cerrarReproductor()"
              style="color:var(--sepia);border-color:var(--sepia);">✕ Cerrar</button>
    </div>
    <div class="modal-body" style="padding:1rem;">
      <div class="video-player-wrap">
        <video id="vp-video" controls controlsList="nodownload">
          <source id="vp-source" src="" type="video/mp4">
          Tu navegador no soporta este formato de vídeo.
        </video>
      </div>
      <div id="vp-info" style="display:grid;grid-template-columns:1fr 1fr;gap:.85rem;margin-top:1rem;"></div>
    </div>
    <div class="modal-footer">
      <button class="btn btn-secondary" onclick="cerrarReproductor()">Cerrar</button>
      <a class="btn btn-download" id="vp-descargar" href="#">⬇️ Descargar vídeo</a>
    </div>
  </div>
</div>

{% if admin %}
<!-- MODAL AÑADIR/EDITAR VÍDEO -->
<div class="overlay" id="modal-video-form">
  <div class="modal">
    <div class="modal-header"><h2 id="video-modal-title">Nuevo vídeo</h2>
      <button class="btn btn-secondary btn-sm" onclick="cerrarModal('modal-video-form')"
              style="color:var(--sepia);border-color:var(--sepia);">✕ Cerrar</button></div>
    <div class="modal-body">
      <form id="form-video" enctype="multipart/form-data" method="post" action="/guardar-video">
        <input type="hidden" name="id" id="video-id">
        <div class="form-grid">
          <div class="form-group span2"><label>Título *</label><input type="text" id="v-titulo" name="titulo" required></div>
          <div class="form-group"><label>Fecha</label><input type="date" id="v-fecha" name="fecha_video"></div>
          <div class="form-group"><label>Frente / Campaña</label>
            <input type="text" id="v-frente" name="frente" list="v-frentes-list">
            <datalist id="v-frentes-list">{% for f in frentes %}<option value="{{ f }}">{% endfor %}</datalist>
          </div>
          <div class="form-group"><label>Ubicación</label><input type="text" id="v-ubicacion" name="ubicacion"></div>
          <div class="form-group"><label>País</label><input type="text" id="v-pais" name="pais"></div>
          <div class="form-group"><label>Fuente / Procedencia</label><input type="text" id="v-fuente" name="fuente"></div>
          <div class="form-group"><label>Duración (ej: 3:42)</label><input type="text" id="v-duracion" name="duracion" placeholder="mm:ss"></div>
          <div class="form-group span2"><label>Etiquetas (separadas por comas)</label><input type="text" id="v-etiquetas" name="etiquetas"></div>
          <div class="form-group span2"><label>📝 Descripción / Notas</label><textarea id="v-descripcion" name="descripcion"></textarea></div>
          <div class="form-group span2">
            <label>Archivo de vídeo (MP4, WebM, MOV, AVI, MKV)</label>
            <div class="upload-zone" id="v-upload-zone" onclick="document.getElementById('v-archivo').click()">
              <span id="v-upload-text" style="font-size:1.2rem">🎬 Pulsa para seleccionar un vídeo</span>
            </div>
            <input type="file" id="v-archivo" name="archivo" accept="video/*" style="display:none"
                   onchange="document.getElementById('v-upload-text').textContent='📎 '+this.files[0].name">
          </div>
        </div>
      </form>
    </div>
    <div class="modal-footer">
      <button class="btn btn-secondary" onclick="cerrarModal('modal-video-form')">Cancelar</button>
      <button class="btn btn-primary" onclick="document.getElementById('form-video').submit()">💾 Guardar</button>
    </div>
  </div>
</div>
{% endif %}

<script>
function abrirModal(id){document.getElementById(id).classList.add('open');}
function cerrarModal(id){document.getElementById(id).classList.remove('open');}
document.querySelectorAll('.overlay').forEach(o=>o.addEventListener('click',e=>{
  if(e.target===o){
    if(o.id==='modal-video-player') cerrarReproductor();
    else o.classList.remove('open');
  }
}));

function reproducirVideo(id){
  fetch('/video-detalle/'+id).then(r=>r.json()).then(v=>{
    document.getElementById('vp-titulo').textContent=v.titulo;
    const video=document.getElementById('vp-video');
    document.getElementById('vp-source').src='/video/'+v.archivo;
    document.getElementById('vp-descargar').href='/descargar-video/'+v.id;
    video.load();
    let info='';
    [['📅 Fecha',v.fecha_video],['📍 Ubicación',v.ubicacion],['🏳 País',v.pais],
     ['⚔️ Frente',v.frente],['⏱ Duración',v.duracion],['📚 Fuente',v.fuente]]
      .forEach(([l,val])=>{if(val)info+=`<div class="detail-field">
        <div class="lbl">${l}</div><div class="val">${val}</div></div>`;});
    if(v.descripcion) info+=`<div class="detail-field" style="grid-column:1/-1">
      <div class="lbl">📝 Descripción</div>
      <div class="val" style="white-space:pre-wrap">${v.descripcion}</div></div>`;
    document.getElementById('vp-info').innerHTML=info;
    abrirModal('modal-video-player');
    setTimeout(()=>video.play(),300);
  });
}
function cerrarReproductor(){
  document.getElementById('vp-video').pause();
  document.getElementById('modal-video-player').classList.remove('open');
}

{% if admin %}
function abrirNuevoVideo(){
  document.getElementById('video-modal-title').textContent='Nuevo vídeo';
  document.getElementById('form-video').reset();
  document.getElementById('video-id').value='';
  document.getElementById('v-upload-text').textContent='🎬 Pulsa para seleccionar un vídeo';
  abrirModal('modal-video-form');
}
function editarVideo(id){
  fetch('/video-detalle/'+id).then(r=>r.json()).then(v=>{
    document.getElementById('video-modal-title').textContent='Editar vídeo';
    document.getElementById('video-id').value=v.id;
    [['v-titulo','titulo'],['v-fecha','fecha_video'],['v-frente','frente'],
     ['v-ubicacion','ubicacion'],['v-pais','pais'],['v-fuente','fuente'],
     ['v-duracion','duracion'],['v-etiquetas','etiquetas'],['v-descripcion','descripcion']]
      .forEach(([elId,key])=>{const el=document.getElementById(elId);if(el)el.value=v[key]||'';});
    if(v.archivo) document.getElementById('v-upload-text').textContent='📎 '+v.archivo+' (subido)';
    abrirModal('modal-video-form');
  });
}
function confirmarBorrarVideo(id,titulo){
  if(confirm('¿Seguro que quieres borrar «'+titulo+'»?'))
    fetch('/borrar-video/'+id,{method:'POST'}).then(()=>location.reload());
}
{% endif %}
</script>
</body></html>
"""
# ══════════════════════════════════════════════════════════════════════════════
# FICHA DE FOTOGRAFÍA + QR
# ══════════════════════════════════════════════════════════════════════════════
HTML_FICHA = """
<!DOCTYPE html><html lang="es"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{{ foto.titulo }} · Archivo Rommel</title>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@400;600;700&family=Source+Sans+3:wght@300;400;500;600&display=swap" rel="stylesheet">
<script src="https://cdnjs.cloudflare.com/ajax/libs/qrcodejs/1.0.0/qrcode.min.js"></script>
<style>
:root{--sepia:#f5efe0;--paper:#faf7f0;--ink:#1a1410;--brown:#6b4c2a;--rust:#8b3a2a;
      --tan:#c9a97a;--muted:#7a6a58;--border:#d4c4a8;}
*{box-sizing:border-box;margin:0;padding:0;}
body{font-family:'Source Sans 3',sans-serif;background:var(--paper);color:var(--ink);
     min-height:100vh;padding:0;}
.ficha-header{background:var(--ink);color:var(--sepia);padding:1.2rem 1.5rem;
              display:flex;align-items:center;justify-content:space-between;gap:1rem;flex-wrap:wrap;}
.ficha-header h1{font-family:'Playfair Display',serif;font-size:clamp(.95rem,3vw,1.3rem);
                 letter-spacing:.03em;line-height:1.3;}
.ficha-header small{display:block;font-size:.72rem;color:var(--tan);margin-top:.2rem;}
.back-btn{color:var(--tan);font-size:.82rem;text-decoration:none;
          border:1px solid rgba(201,169,122,.4);padding:4px 12px;border-radius:4px;white-space:nowrap;}
.back-btn:hover{color:var(--sepia);border-color:var(--tan);}
.ficha-wrap{max-width:900px;margin:0 auto;padding:2rem 1.5rem;}
.ficha-grid{display:grid;grid-template-columns:1fr 1fr;gap:2rem;align-items:start;}
@media(max-width:640px){.ficha-grid{grid-template-columns:1fr;}}
.foto-grande{width:100%;border-radius:8px;border:1px solid var(--border);
             object-fit:contain;max-height:500px;background:var(--sepia);}
.sin-foto{width:100%;aspect-ratio:4/3;background:var(--sepia);border-radius:8px;
          display:flex;align-items:center;justify-content:center;font-size:4rem;
          border:1px solid var(--border);}
.ficha-meta{display:flex;flex-direction:column;gap:1.2rem;}
.ficha-id{font-family:'Playfair Display',serif;font-size:.8rem;color:var(--muted);
          letter-spacing:.1em;text-transform:uppercase;margin-bottom:.5rem;}
.ficha-titulo{font-family:'Playfair Display',serif;font-size:1.6rem;line-height:1.3;
              color:var(--ink);margin-bottom:.25rem;}
.campo-lista{display:flex;flex-direction:column;gap:.65rem;}
.campo{display:flex;flex-direction:column;gap:.2rem;padding:.6rem .8rem;
       background:#fff;border:1px solid var(--border);border-radius:6px;}
.campo .lbl{font-size:.7rem;font-weight:600;color:var(--tan);text-transform:uppercase;letter-spacing:.06em;}
.campo .val{font-size:.95rem;color:var(--ink);line-height:1.5;}
.tag-list{display:flex;flex-wrap:wrap;gap:.3rem;margin-top:.3rem;}
.tag{font-size:.72rem;padding:.15rem .55rem;border-radius:99px;background:var(--sepia);
     color:var(--brown);border:1px solid var(--border);}
.descripcion-box{background:#fff;border:1px solid var(--border);border-radius:6px;
                 padding:1rem 1.1rem;margin-top:1.5rem;}
.descripcion-box h3{font-family:'Playfair Display',serif;font-size:1rem;color:var(--brown);margin-bottom:.6rem;}
.descripcion-box p{font-size:.95rem;line-height:1.7;white-space:pre-wrap;color:var(--ink);}
.descarga-box{margin-top:1.5rem;padding:1.25rem;background:#fff;border:1px solid var(--border);
              border-radius:8px;display:flex;flex-direction:column;align-items:center;gap:.6rem;text-align:center;}
.descarga-box h3{font-family:'Playfair Display',serif;font-size:1rem;color:var(--brown);}
.btn-descargar-grande{background:#3d6b2a;color:#fff;border:none;padding:.7rem 1.6rem;border-radius:4px;
           font-family:inherit;font-size:.9rem;font-weight:600;cursor:pointer;text-decoration:none;
           display:inline-flex;align-items:center;gap:.5rem;}
.btn-descargar-grande:hover{opacity:.85;}
.qr-section{margin-top:1.5rem;padding:1.5rem;background:#fff;border:1px solid var(--border);
            border-radius:8px;display:flex;flex-direction:column;align-items:center;gap:1rem;}
.qr-section h3{font-family:'Playfair Display',serif;font-size:1.1rem;color:var(--brown);}
.qr-section p{font-size:.8rem;color:var(--muted);text-align:center;max-width:300px;line-height:1.5;}
#qr-canvas{border:1px solid var(--border);border-radius:4px;padding:8px;background:#fff;}
.btn-print{background:var(--rust);color:#fff;border:none;padding:.65rem 1.5rem;border-radius:4px;
           font-family:inherit;font-size:.9rem;font-weight:600;cursor:pointer;margin-top:.5rem;}
.btn-print:hover{opacity:.85;}
.id-manual-wrap{width:100%;max-width:320px;display:flex;flex-direction:column;align-items:center;gap:.4rem;margin-top:.25rem;}
.id-manual-wrap label{font-size:.72rem;font-weight:600;color:var(--brown);text-transform:uppercase;letter-spacing:.06em;align-self:flex-start;}
.id-manual-input-row{display:flex;align-items:center;gap:.5rem;width:100%;}
.id-manual-input{font-family:'Source Sans 3',monospace,sans-serif;font-size:1.05rem;font-weight:600;
  letter-spacing:.12em;text-align:center;padding:.5rem .75rem;border:2px dashed var(--border);
  border-radius:6px;background:var(--paper);color:var(--ink);width:100%;text-transform:uppercase;}
.id-manual-input:focus{outline:none;border-color:var(--brown);border-style:solid;
  box-shadow:0 0 0 2px rgba(107,76,42,.15);}
.id-manual-input.valido{border-color:#5a8a5a;border-style:solid;background:#f0f7f0;}
.id-manual-input.invalido{border-color:var(--rust);border-style:solid;background:#fdf5f3;}
.id-manual-hint{font-size:.68rem;color:var(--muted);align-self:flex-start;}
.certeza-badge{display:inline-flex;align-items:center;gap:.25rem;font-size:.66rem;font-weight:600;
  padding:.12rem .55rem;border-radius:99px;color:#fff;margin-left:.5rem;cursor:pointer;white-space:nowrap;
  vertical-align:middle;}
.certeza-detalle{display:none;font-size:.78rem;color:var(--muted);margin-top:.4rem;padding:.5rem .65rem;
  background:var(--sepia);border-radius:4px;border:1px dashed var(--border);line-height:1.5;}
.certeza-detalle.show{display:block;}
.certeza-edit{display:none;margin-top:.55rem;padding:.65rem;background:var(--sepia);border-radius:6px;
  border:1px solid var(--border);gap:.4rem;flex-direction:column;}
.certeza-edit.show{display:flex;}
.certeza-edit label{font-size:.68rem;font-weight:600;color:var(--brown);text-transform:uppercase;letter-spacing:.05em;}
.certeza-edit select,.certeza-edit textarea{font-family:inherit;font-size:.82rem;padding:.35rem .5rem;
  border:1px solid var(--border);border-radius:4px;background:#fff;color:var(--ink);}
.certeza-edit textarea{resize:vertical;min-height:55px;}
.certeza-edit-btns{display:flex;gap:.5rem;margin-top:.15rem;}
.btn-certeza-guardar{background:#3d6b2a;color:#fff;border:none;padding:.35rem .9rem;border-radius:4px;
  font-size:.78rem;font-weight:600;cursor:pointer;}
.btn-certeza-cancelar{background:transparent;color:var(--muted);border:1px solid var(--border);
  padding:.35rem .9rem;border-radius:4px;font-size:.78rem;cursor:pointer;}
.btn-editar-certeza{font-size:.68rem;color:var(--brown);text-decoration:underline;cursor:pointer;
  margin-left:.45rem;background:none;border:none;padding:0;}
.sin-certeza{font-size:.68rem;color:var(--muted);font-style:italic;margin-left:.5rem;cursor:pointer;
  background:none;border:none;text-decoration:underline;padding:0;}
.etiqueta-print{display:none;}
@media print{
  body *{display:none !important;}
  .etiqueta-print{
    display:flex !important;
    flex-direction:column;align-items:center;justify-content:center;
    width:6cm;padding:.6cm;border:1px solid #888;border-radius:4px;
    font-family:'Source Sans 3',sans-serif;page-break-inside:avoid;margin:0 auto;
  }
  .etiqueta-print .et-titulo{font-size:9pt;font-weight:700;text-align:center;margin-bottom:4pt;line-height:1.3;}
  .etiqueta-print .et-meta{font-size:7pt;color:#555;text-align:center;margin-bottom:6pt;line-height:1.4;}
  .etiqueta-print #qr-print{display:block !important;}
  .etiqueta-print .et-id{font-size:7pt;color:#888;margin-top:4pt;letter-spacing:.05em;}
  .etiqueta-print .et-id-manual{font-size:9pt;font-weight:700;color:#222;margin-top:5pt;
    letter-spacing:.1em;border:1px solid #bbb;border-radius:3px;padding:2pt 6pt;background:#f9f9f9;}
}
</style>
</head><body>

{% macro campo_certeza(campo_key, label, valor) %}
{% set af = afirmaciones.get(campo_key) %}
<div class="campo">
  <div class="lbl">{{ label }}</div>
  <div class="val">
    {{ valor }}
    {% if af %}
    <span class="certeza-badge" style="background:{{ niveles_certeza[af.certeza].color }}"
          onclick="toggleDetalleCerteza('{{ campo_key }}')">{{ niveles_certeza[af.certeza].label }}</span>
    {% if admin %}<button type="button" class="btn-editar-certeza" onclick="abrirEdicionCerteza('{{ campo_key }}')">editar</button>{% endif %}
    <div class="certeza-detalle" id="detalle-{{ campo_key }}">
      {% if af.fuente_titulo %}<strong>Fuente:</strong> {{ af.fuente_titulo }}{% if af.fuente_autor %} ({{ af.fuente_autor }}){% endif %}<br>{% endif %}
      {% if af.notas %}{{ af.notas }}{% endif %}
      {% if not af.fuente_titulo and not af.notas %}<em>Sin fuente ni notas adicionales.</em>{% endif %}
    </div>
    {% elif admin %}
    <button type="button" class="sin-certeza" onclick="abrirEdicionCerteza('{{ campo_key }}')">+ añadir certeza / fuente</button>
    {% endif %}
  </div>
  {% if admin %}
  <div class="certeza-edit" id="edit-{{ campo_key }}">
    <label>Nivel de certeza</label>
    <select id="certeza-sel-{{ campo_key }}">
      {% for k, v in niveles_certeza.items() %}
      <option value="{{ k }}" {% if af and af.certeza==k %}selected{% endif %}>{{ v.label }}</option>
      {% endfor %}
    </select>
    <label>Fuente</label>
    <select id="fuente-sel-{{ campo_key }}">
      <option value="">— sin fuente vinculada —</option>
      {% for f in fuentes %}
      <option value="{{ f.id }}" {% if af and af.fuente_id==f.id %}selected{% endif %}>{{ f.titulo }}{% if f.autor %} — {{ f.autor }}{% endif %}</option>
      {% endfor %}
    </select>
    <label>Notas / razonamiento</label>
    <textarea id="notas-{{ campo_key }}" placeholder="¿Por qué se cree esto? ¿Hay fuentes que lo contradicen?">{{ af.notas if af else '' }}</textarea>
    <div class="certeza-edit-btns">
      <button type="button" class="btn-certeza-guardar" onclick="guardarCerteza('{{ campo_key }}')">Guardar</button>
      <button type="button" class="btn-certeza-cancelar" onclick="cerrarEdicionCerteza('{{ campo_key }}')">Cancelar</button>
    </div>
  </div>
  {% endif %}
</div>
{% endmacro %}

<div class="ficha-header">
  <div>
    <h1>Archivo Histórico · Erwin Rommel</h1>
    <small>Segunda Guerra Mundial · Colección privada</small>
  </div>
  <a href="/" class="back-btn">← Volver al archivo</a>
</div>

<div class="ficha-wrap">
  <div class="ficha-grid">
    <div>
      {% if foto.archivo %}
      <img src="/foto/{{ foto.archivo }}" class="foto-grande" alt="{{ foto.titulo }}">
      {% else %}
      <div class="sin-foto">📷</div>
      {% endif %}
    </div>
    <div class="ficha-meta">
      <div>
        <div class="ficha-id">{% if foto.identificador %}{{ foto.identificador }}{% else %}Ficha nº {{ foto.id }}{% endif %}</div>
        <div class="ficha-titulo">{{ foto.titulo }}</div>
      </div>
      <div class="campo-lista">
        {% if foto.fecha_foto %}
        {{ campo_certeza('fecha_foto', '📅 Fecha', foto.fecha_foto) }}
        {% endif %}
        {% if foto.frente %}
        <div class="campo"><div class="lbl">⚔️ Frente / Campaña</div><div class="val">{{ foto.frente }}</div></div>
        {% endif %}
        {% if foto.ubicacion %}
        {{ campo_certeza('ubicacion', '📍 Ubicación', foto.ubicacion) }}
        {% endif %}
        {% if foto.pais %}
        <div class="campo"><div class="lbl">🏳 País</div><div class="val">{{ foto.pais }}</div></div>
        {% endif %}
        {% if foto.fuente %}
        <div class="campo"><div class="lbl">📚 Fuente / Procedencia</div><div class="val">{{ foto.fuente }}</div></div>
        {% endif %}
        {% if foto.lat and foto.lon %}
        <div class="campo"><div class="lbl">🌐 Coordenadas GPS</div><div class="val">{{ foto.lat }}, {{ foto.lon }}</div></div>
        {% endif %}
        {% if foto.etiquetas %}
        <div class="campo">
          <div class="lbl">🏷 Etiquetas</div>
          <div class="tag-list">
            {% for t in foto.etiquetas.split(',') %}{% if t.strip() %}<span class="tag">{{ t.strip() }}</span>{% endif %}{% endfor %}
          </div>
        </div>
        {% endif %}
      </div>
    </div>
  </div>

  {% if foto.descripcion %}
  <div class="descripcion-box">
    <h3>📝 Descripción / Notas</h3>
    <p>{{ foto.descripcion }}</p>
  </div>
  {% endif %}

  {% if foto.archivo %}
  <div class="descarga-box">
    <h3>⬇️ Descargar esta fotografía</h3>
    <a href="/descargar-foto/{{ foto.id }}" class="btn-descargar-grande">⬇️ Descargar foto en alta calidad</a>
  </div>
  {% endif %}

  <div class="qr-section">
    <h3>🔧 Apartado técnico</h3>
    <p>Código QR de acceso directo a esta ficha desde el archivo físico, y el identificador asignado a esta fotografía.</p>
    <div id="qr-canvas"></div>
    <p style="font-size:.75rem;color:var(--muted);word-break:break-all;text-align:center;">{{ ficha_url }}</p>

    <div class="id-manual-wrap">
      <label for="id-manual">Identificador de la foto</label>
      {% if admin %}
      <div class="id-manual-input-row">
        <input type="text" id="id-manual" class="id-manual-input"
               placeholder="XXX-000000-00" maxlength="13"
               value="{{ foto.identificador or '' }}"
               oninput="formatearIdManual(this)"
               title="Formato: 3 siglas – 6 números – 2 números">
        <button type="button" class="btn-print" id="btn-guardar-id" style="display:none;" onclick="guardarIdentificador()">Guardar</button>
      </div>
      <div class="id-manual-hint">Formato: 3 letras · 6 dígitos · 2 dígitos &nbsp;(ej. ROM-194200-01)</div>
      <div id="id-manual-msg" style="font-size:.72rem;margin-top:.3rem;"></div>
      {% else %}
        {% if foto.identificador %}
        <div class="id-manual-input-row"><strong>{{ foto.identificador }}</strong></div>
        {% else %}
        <div class="id-manual-hint">Sin identificador asignado todavía.</div>
        {% endif %}
      {% endif %}
    </div>

    <button class="btn-print" onclick="window.print()">🖨️ Imprimir etiqueta QR</button>
    <p style="font-size:.72rem;color:var(--muted);">La etiqueta impresa es de 6×6 cm aprox. — ideal para el dorso de la foto física.</p>
  </div>
</div>

<div class="etiqueta-print">
  <div class="et-titulo">{{ foto.titulo }}</div>
  <div class="et-meta">
    {% if foto.fecha_foto %}{{ foto.fecha_foto }}{% endif %}
    {% if foto.frente %} · {{ foto.frente }}{% endif %}
    {% if foto.ubicacion %}<br>{{ foto.ubicacion }}{% endif %}
  </div>
  <div id="qr-print"></div>
  <div class="et-id">Archivo Rommel · Ficha #{{ foto.id }}</div>
  <div class="et-id-manual" id="et-id-manual-print" style="display:none;"></div>
</div>

<script>
const FICHA_URL = {{ ficha_url | tojson }};
new QRCode(document.getElementById('qr-canvas'), {
  text: FICHA_URL, width: 200, height: 200,
  colorDark: '#1a1410', colorLight: '#ffffff',
  correctLevel: QRCode.CorrectLevel.M
});
new QRCode(document.getElementById('qr-print'), {
  text: FICHA_URL, width: 140, height: 140,
  colorDark: '#000000', colorLight: '#ffffff',
  correctLevel: QRCode.CorrectLevel.M
});

let idManualGuardado = {{ (foto.identificador or '') | tojson }};

function aplicarIdManual(valor) {
  const input = document.getElementById('id-manual');
  const patron = /^[A-Z]{3}-[0-9]{6}-[0-9]{2}$/;
  const valido = patron.test(valor);
  if (input) {
    input.value = valor;
    input.classList.toggle('valido', valido);
    input.classList.toggle('invalido', valor.length > 0 && !valido);
  }
  const printEl = document.getElementById('et-id-manual-print');
  if (printEl) {
    if (valido) {
      printEl.textContent = valor;
      printEl.style.display = '';
    } else {
      printEl.style.display = 'none';
    }
  }
}

function formatearIdManual(input) {
  // Guardar posición del cursor antes de reformatear
  const selStart = input.selectionStart;
  const anteriorLen = input.value.length;

  // Separar en bloques: 3 letras, 6 dígitos, 2 dígitos
  let raw = input.value.replace(/[^A-Za-z0-9]/g, '').toUpperCase();
  let result = '';
  if (raw.length > 0)  result += raw.slice(0, 3);
  if (raw.length > 3)  result += '-' + raw.slice(3, 9);
  if (raw.length > 9)  result += '-' + raw.slice(9, 11);

  aplicarIdManual(result);

  // Restaurar cursor ajustando por los guiones añadidos
  const diff = result.length - anteriorLen;
  const nuevaPos = Math.max(0, selStart + diff);
  input.setSelectionRange(nuevaPos, nuevaPos);

  // Mostrar el botón "Guardar" solo si el valor cambió y es válido (o está vacío, para poder borrarlo)
  const btn = document.getElementById('btn-guardar-id');
  const msg = document.getElementById('id-manual-msg');
  if (btn) {
    const patron = /^[A-Z]{3}-[0-9]{6}-[0-9]{2}$/;
    const valido = result === '' || patron.test(result);
    btn.style.display = (result !== idManualGuardado && valido) ? '' : 'none';
  }
  if (msg) msg.textContent = '';
}

async function guardarIdentificador() {
  const input = document.getElementById('id-manual');
  const btn   = document.getElementById('btn-guardar-id');
  const msg   = document.getElementById('id-manual-msg');
  const valor = input.value.trim();
  try {
    const resp = await fetch('/guardar-identificador/{{ foto.id }}', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({identificador: valor})
    });
    const data = await resp.json();
    if (data.ok) {
      idManualGuardado = data.identificador || '';
      if (btn) btn.style.display = 'none';
      if (msg) { msg.style.color = '#2e7d32'; msg.textContent = '✔ Guardado'; }
      setTimeout(() => { if (msg && msg.textContent === '✔ Guardado') msg.textContent = ''; }, 2500);
    } else {
      if (msg) { msg.style.color = '#b3261e'; msg.textContent = data.error || 'No se pudo guardar.'; }
    }
  } catch (e) {
    if (msg) { msg.style.color = '#b3261e'; msg.textContent = 'Error de conexión.'; }
  }
}

// Cargar identificador guardado al abrir la página (viene ya de la base de datos)
window.addEventListener('DOMContentLoaded', () => {
  if (idManualGuardado) aplicarIdManual(idManualGuardado);
});

// ── Certeza / fuente de cada dato histórico ──────────────────────────────
function toggleDetalleCerteza(campo) {
  const el = document.getElementById('detalle-' + campo);
  if (el) el.classList.toggle('show');
}
function abrirEdicionCerteza(campo) {
  const el = document.getElementById('edit-' + campo);
  if (el) el.classList.add('show');
}
function cerrarEdicionCerteza(campo) {
  const el = document.getElementById('edit-' + campo);
  if (el) el.classList.remove('show');
}
async function guardarCerteza(campo) {
  const certeza  = document.getElementById('certeza-sel-' + campo).value;
  const fuenteId = document.getElementById('fuente-sel-' + campo).value;
  const notas    = document.getElementById('notas-' + campo).value;
  try {
    const resp = await fetch('/guardar-afirmacion', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        entidad_tipo: 'fotografia',
        entidad_id: {{ foto.id }},
        campo: campo,
        certeza: certeza,
        fuente_id: fuenteId ? parseInt(fuenteId) : null,
        notas: notas
      })
    });
    const data = await resp.json();
    if (data.ok) {
      location.reload();
    } else {
      alert('No se ha podido guardar. Inténtalo de nuevo.');
    }
  } catch (e) {
    alert('Error de conexión al guardar.');
  }
}
</script>
</body></html>
"""
# ══════════════════════════════════════════════════════════════════════════════
# ETIQUETAS
# ══════════════════════════════════════════════════════════════════════════════
HTML_QR_ETIQUETAS = """
<!DOCTYPE html><html lang="es"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Etiquetas QR · Archivo Rommel</title>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@400;600&family=Source+Sans+3:wght@400;600&display=swap" rel="stylesheet">
<script src="https://cdnjs.cloudflare.com/ajax/libs/qrcodejs/1.0.0/qrcode.min.js"></script>
<style>
:root{--sepia:#f5efe0;--paper:#faf7f0;--ink:#1a1410;--brown:#6b4c2a;--rust:#8b3a2a;--tan:#c9a97a;--border:#d4c4a8;}
*{box-sizing:border-box;margin:0;padding:0;}
body{font-family:'Source Sans 3',sans-serif;background:var(--paper);color:var(--ink);}
.top-bar{background:var(--ink);color:var(--sepia);padding:1rem 1.5rem;
         display:flex;align-items:center;justify-content:space-between;gap:1rem;flex-wrap:wrap;}
.top-bar h1{font-family:'Playfair Display',serif;font-size:1.2rem;}
.btn-print-all{background:var(--rust);color:#fff;border:none;padding:.6rem 1.4rem;border-radius:4px;
               font-family:inherit;font-size:.9rem;font-weight:600;cursor:pointer;}
.info-bar{padding:.75rem 1.5rem;background:var(--sepia);border-bottom:1px solid var(--border);
          font-size:.82rem;color:var(--muted);}
.etiquetas-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));
                gap:1.5rem;padding:1.5rem;}
.etiqueta{border:1px dashed var(--border);border-radius:6px;padding:1rem;text-align:center;
          display:flex;flex-direction:column;align-items:center;gap:.5rem;background:#fff;}
.et-titulo{font-family:'Playfair Display',serif;font-size:.9rem;font-weight:600;line-height:1.3;color:var(--ink);}
.et-meta{font-size:.7rem;color:var(--muted);line-height:1.4;}
.et-id{font-size:.65rem;color:#aaa;letter-spacing:.05em;margin-top:.2rem;}
@media print{
  .top-bar,.info-bar{display:none!important;}
  body{background:#fff;}
  .etiquetas-grid{display:grid;grid-template-columns:repeat(3,6cm);gap:.5cm;
                  padding:.5cm;justify-content:start;}
  .etiqueta{border:1px solid #999;border-radius:3px;padding:.5cm;page-break-inside:avoid;
            width:6cm;height:auto;}
  .et-titulo{font-size:8pt;}
  .et-meta{font-size:6pt;}
  .et-id{font-size:6pt;}
}
</style>
</head><body>
<div class="top-bar">
  <div>
    <h1>🏷 Etiquetas QR — Colección Completa</h1>
    <small style="font-size:.75rem;color:var(--tan);">{{ fotos|length }} fotografías catalogadas</small>
  </div>
  <button class="btn-print-all" onclick="window.print()">🖨️ Imprimir todas</button>
</div>
<div class="info-bar">
  Imprime esta página para obtener las etiquetas QR de toda la colección. Recórtalas y pégalas en el dorso de cada fotografía física.
</div>
<div class="etiquetas-grid" id="grid"></div>
<script>
const BASE = {{ base_url | tojson }};
const fotos = {{ fotos_json | safe }};
fotos.forEach(f => {
  const url = BASE + '/ficha/' + f.id;
  const qrContainer = document.createElement('div');
  const titleDiv = document.createElement('div');
  titleDiv.className = 'et-titulo';
  titleDiv.textContent = f.titulo;
  const metaDiv = document.createElement('div');
  metaDiv.className = 'et-meta';
  metaDiv.textContent = [f.fecha_foto, f.frente, f.ubicacion].filter(Boolean).join(' · ');
  const idDiv = document.createElement('div');
  idDiv.className = 'et-id';
  idDiv.textContent = 'Archivo Rommel · #' + f.id;
  const wrapper = document.createElement('div');
  wrapper.className = 'etiqueta';
  wrapper.appendChild(titleDiv);
  wrapper.appendChild(metaDiv);
  wrapper.appendChild(qrContainer);
  wrapper.appendChild(idDiv);
  document.getElementById('grid').appendChild(wrapper);
  new QRCode(qrContainer, {
    text: url, width: 120, height: 120,
    colorDark: '#000000', colorLight: '#ffffff',
    correctLevel: QRCode.CorrectLevel.M
  });
});
</script>
</body></html>
"""
# ══════════════════════════════════════════════════════════════════════════════
# LÍNEA TEMPORAL
# ══════════════════════════════════════════════════════════════════════════════
HTML_TIMELINE = """
<!DOCTYPE html><html lang="es"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Línea Temporal · IIGM</title>
""" + CSS_BASE + """
<style>
body{background:#111008;color:#e8dfc8;}
.tl-hero{padding:2.5rem 1.5rem 1.5rem;text-align:center;background:linear-gradient(to bottom,#1a1208,#111008);border-bottom:1px solid #2e2510;}
.tl-hero h2{font-family:'Playfair Display',serif;font-size:clamp(1.5rem,5vw,2.2rem);color:var(--tan);letter-spacing:.06em;margin-bottom:.4rem;}
.tl-wrap{max-width:900px;margin:0 auto;padding:2rem 1rem 4rem;position:relative;}
.tl-wrap::before{content:'';position:absolute;left:50%;top:0;bottom:0;width:2px;
  background:linear-gradient(to bottom,transparent,var(--brown) 5%,var(--brown) 95%,transparent);transform:translateX(-50%);}
.tl-item{display:flex;justify-content:flex-end;padding-right:calc(50% + 30px);margin-bottom:2.5rem;position:relative;}
.tl-item.right{justify-content:flex-start;padding-right:0;padding-left:calc(50% + 30px);}
.tl-item::after{content:'';position:absolute;top:20px;left:50%;width:16px;height:16px;
  background:var(--rust);border:3px solid var(--tan);border-radius:50%;transform:translateX(-50%);z-index:3;}
.tl-card{background:#1e1608;border:1px solid #3a2e1a;border-radius:8px;padding:1.5rem;width:100%;max-width:450px;}
.tl-fecha{font-family:'Playfair Display',serif;font-size:1.4rem;color:var(--tan);margin-bottom:1rem;border-bottom:1px solid #3a2e1a;padding-bottom:.5rem;}
.tl-fotos-grid{display:flex;flex-wrap:wrap;gap:10px;}
.tl-foto-wrap{text-align:center;width:calc(50% - 5px);}
.tl-foto-wrap img{width:100%;height:100px;object-fit:cover;border-radius:4px;border:1px solid #3a2e1a;cursor:pointer;transition:.2s;}
.tl-foto-wrap img:hover{border-color:var(--tan);transform:scale(1.05);}
@media(max-width:768px){
  .tl-wrap::before{left:28px;}
  .tl-item,.tl-item.right{padding:0 0 0 60px;justify-content:flex-start;}
  .tl-item::after{left:28px;transform:none;}
  .tl-card{max-width:100%;}
}
</style>
</head><body>
<header>
  <div><h1>Línea Temporal</h1><small>Cronología agrupada por fechas</small></div>
  <div class="header-right">
    {{ nav | safe }}
    {{ header_usuario | safe }}
  </div>
</header>
<div class="tl-hero"><h2>Cronología de la Campaña</h2>
  <p>Fotografías agrupadas automáticamente por momentos históricos</p></div>
<div class="tl-wrap">
  {% if not eventos %}
  <div style="text-align:center;padding:5rem 2rem;color:var(--muted);position:relative;z-index:5;">
    <h3>Sin fechas documentadas todavía</h3></div>
  {% else %}
    {% set ns = namespace(lado=0) %}
    {% for ev in eventos %}
    <div class="tl-item {{ 'right' if ns.lado==1 else '' }}">
      <div class="tl-card">
        <div class="tl-fecha">📅 {{ ev.fecha }}</div>
        <div class="tl-fotos-grid">
          {% for f in ev.fotos %}
          <div class="tl-foto-wrap" onclick="window.location='/?q={{ f.titulo|urlencode }}'">
            {% if f.archivo %}<img src="/foto/{{ f.archivo }}" title="{{ f.titulo }}">
            {% else %}<div style="height:100px;background:#111;display:flex;align-items:center;justify-content:center">📷</div>{% endif %}
            <div style="font-size:.75rem;color:var(--muted);margin-top:4px;">{{ f.titulo }}</div>
          </div>
          {% endfor %}
        </div>
      </div>
    </div>
    {% set ns.lado = 1 - ns.lado %}
    {% endfor %}
  {% endif %}
</div>
</body></html>
"""
# ══════════════════════════════════════════════════════════════════════════════
# MAPA
# ══════════════════════════════════════════════════════════════════════════════
HTML_MAPA = """
<!DOCTYPE html><html lang="es"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Mapa Interactivo · IIGM</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
""" + CSS_BASE + """
<style>
body{display:flex;flex-direction:column;height:100vh;overflow:hidden;}
.map-layout{display:flex;flex:1;overflow:hidden;}
#map{flex:1;}
.map-sidebar{width:320px;background:var(--paper);border-left:1px solid var(--border);display:flex;flex-direction:column;overflow-y:auto;}
.sidebar-header{padding:.85rem 1rem;background:var(--ink);color:var(--sepia);font-family:'Playfair Display',serif;font-size:.95rem;}
.punto-card{background:var(--card);border:1px solid var(--border);border-radius:6px;padding:.75rem;margin:.5rem;cursor:pointer;transition:border-color .2s;}
.punto-card:hover{border-color:var(--brown);}
.popup-foto-thumb{width:52px;height:42px;object-fit:cover;border-radius:3px;margin:2px;border:1px solid #444;}
.leaflet-popup-content-wrapper{background:var(--ink);color:var(--sepia);border-radius:6px;}
.leaflet-popup-tip{background:var(--ink);}

/* ── Barra de línea temporal ── */
.time-bar{position:absolute;bottom:0;left:0;right:320px;background:rgba(26,20,16,.92);
          color:var(--sepia);padding:.9rem 1.5rem;display:flex;align-items:center;gap:1rem;
          z-index:500;flex-wrap:wrap;}
.time-bar .fecha-actual{font-family:'Playfair Display',serif;font-size:1.05rem;color:var(--tan);
          min-width:110px;text-align:center;}
.time-bar input[type=range]{flex:1;min-width:150px;accent-color:var(--rust);}
.time-btn{background:var(--rust);color:#fff;border:none;border-radius:50%;width:36px;height:36px;
          cursor:pointer;font-size:1rem;display:flex;align-items:center;justify-content:center;flex-shrink:0;}
.time-btn:hover{opacity:.85;}
@media(max-width:768px){.time-bar{right:0;}}
.punto-oculto{opacity:.12 !important;}
</style>
</head><body>
<header>
  <div><h1>Mapa Interactivo</h1><small>{{ n_fotos }} fotos geolocalizadas</small></div>
  <div class="header-right">
    {{ nav | safe }}
    {{ header_usuario | safe }}
  </div>
</header>
<div class="map-layout">
  <div id="map">
    {% if fechas_disponibles %}
    <div class="time-bar">
      <button class="time-btn" id="btn-play" onclick="togglePlay()">▶</button>
      <div class="fecha-actual" id="fecha-actual">—</div>
      <input type="range" id="time-slider" min="0" max="{{ fechas_disponibles|length }}" value="{{ fechas_disponibles|length }}"
             oninput="actualizarSlider(this.value)">
      <span style="font-size:.72rem;color:var(--tan);">Arrastra para ver la evolución de la campaña en el tiempo</span>
    </div>
    {% endif %}
  </div>
  <div class="map-sidebar">
    <div class="sidebar-header">📍 Agrupaciones Automáticas</div>
    <div style="padding:10px;font-size:.8rem;color:var(--muted);border-bottom:1px solid var(--border);">Agrupaciones por coordenadas GPS compartidas.</div>
    <div id="sidebar-body"></div>
  </div>
</div>
<script>
const map=L.map('map').setView([45,10],4);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{attribution:'© OpenStreetMap',maxZoom:19}).addTo(map);
const puntos={{ puntos|tojson|safe }};
const fechasDisponibles={{ fechas_disponibles|tojson|safe }};
const sb=document.getElementById('sidebar-body');
const marcadores=[];

puntos.forEach(p=>{
  const marker=L.circleMarker([p.lat,p.lon],{radius:8,fillColor:'#8b3a2a',color:'#fff',weight:2,fillOpacity:.9}).addTo(map);
  let fotosHtml=p.fotos.map(f=>f.archivo?`<img src='/foto/${f.archivo}' class='popup-foto-thumb'>`:'<div class="popup-foto-thumb" style="background:#333;display:inline-flex;align-items:center;justify-content:center">📷</div>').join('');
  marker.bindPopup(`<div style="font-family:'Playfair Display';font-size:1.1rem;color:var(--tan)">${p.nombre}</div>
    <div style="font-size:.8rem;color:#bbb;margin-bottom:8px">${p.fotos.length} fotografías${p.fecha_min?(' · desde '+p.fecha_min):''}</div>
    <div style="display:flex;flex-wrap:wrap;max-width:200px">${fotosHtml}</div>`);
  const card=document.createElement('div');
  card.className='punto-card';
  card.onclick=()=>map.flyTo([p.lat,p.lon],10);
  card.innerHTML=`<div style='font-weight:600;color:var(--ink)'>${p.nombre}</div>
    <div style='font-size:.75rem;color:var(--muted)'>${p.lat}, ${p.lon}</div>
    <div style='font-size:.8rem;color:var(--rust);margin-top:5px;font-weight:600'>${p.fotos.length} fotos${p.fecha_min?(' · '+p.fecha_min):''}</div>`;
  sb.appendChild(card);
  marcadores.push({marker, card, fecha_min:p.fecha_min});
});

let reproduciendo=false, timer=null;

function actualizarSlider(valor){
  valor = parseInt(valor);
  const fechaLimite = valor >= fechasDisponibles.length ? null : fechasDisponibles[valor];
  document.getElementById('fecha-actual').textContent = fechaLimite ? fechaLimite : 'Toda la campaña';
  marcadores.forEach(m=>{
    const visible = !m.fecha_min || fechaLimite === null || m.fecha_min <= fechaLimite;
    m.marker.setStyle({fillOpacity: visible ? .9 : .08, opacity: visible ? 1 : .08});
    m.card.classList.toggle('punto-oculto', !visible);
  });
}

function togglePlay(){
  const btn = document.getElementById('btn-play');
  const slider = document.getElementById('time-slider');
  if(reproduciendo){
    clearInterval(timer); reproduciendo=false; btn.textContent='▶'; return;
  }
  reproduciendo=true; btn.textContent='⏸';
  if(parseInt(slider.value) >= fechasDisponibles.length) slider.value = 0;
  timer = setInterval(()=>{
    let v = parseInt(slider.value) + 1;
    if(v > fechasDisponibles.length){ clearInterval(timer); reproduciendo=false; btn.textContent='▶'; return; }
    slider.value = v;
    actualizarSlider(v);
  }, 900);
}

{% if fechas_disponibles %}
actualizarSlider(document.getElementById('time-slider').value);
{% endif %}
</script>
</body></html>
"""
# ══════════════════════════════════════════════════════════════════════════════
# BLOG 
# ══════════════════════════════════════════════════════════════════════════════
HTML_BLOG = """
<!DOCTYPE html><html><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Diario de Investigación · IIGM</title>
<link href="https://cdnjs.cloudflare.com/ajax/libs/quill/1.3.7/quill.snow.min.css" rel="stylesheet">
""" + CSS_BASE + """
<style>
.foto-selector{border:1px solid var(--border);border-radius:4px;max-height:200px;overflow-y:auto;
               padding:10px;background:var(--paper);margin-bottom:15px;}
.foto-item{display:flex;align-items:center;gap:10px;padding:5px;border-bottom:1px solid #eee;font-size:.85rem;cursor:pointer;}
.foto-item:hover{background:#fff;}
.foto-item img{width:40px;height:30px;object-fit:cover;border-radius:2px;}
.articulo-contenido{
  font-family:'Merriweather',serif;line-height:1.85;font-size:1.05rem;color:#2c241e;
}
.articulo-contenido p{margin-bottom:1em;}
.articulo-contenido h1,.articulo-contenido h2,.articulo-contenido h3{
  font-family:'Playfair Display',serif;color:var(--brown);margin:1.4em 0 .5em;line-height:1.3;}
.articulo-contenido h1{font-size:1.5rem;}
.articulo-contenido h2{font-size:1.25rem;}
.articulo-contenido h3{font-size:1.1rem;}
.articulo-contenido strong{font-weight:700;color:var(--ink);}
.articulo-contenido em{font-style:italic;}
.articulo-contenido u{text-decoration:underline;}
.articulo-contenido ul,.articulo-contenido ol{padding-left:1.6em;margin-bottom:1em;}
.articulo-contenido li{margin-bottom:.3em;}
.articulo-contenido blockquote{
  border-left:3px solid var(--tan);margin:1em 0;padding:.5em 1em;
  color:var(--muted);font-style:italic;background:var(--sepia);border-radius:0 4px 4px 0;}
.articulo-card{padding:30px;}
.articulo-card h2{font-family:'Playfair Display',serif;font-size:1.6rem;margin-bottom:10px;color:var(--rust);}

/* ── Archivo desplegable por año ── */
.year-archive{max-width:850px;margin:1.5rem auto;background:#fff;border:1px solid var(--border);
              border-radius:8px;box-shadow:var(--shadow);overflow:hidden;}
.year-archive summary{cursor:pointer;list-style:none;padding:1rem 1.5rem;background:var(--sepia);
              display:flex;align-items:center;justify-content:space-between;gap:1rem;}
.year-archive summary::-webkit-details-marker{display:none;}
.year-archive summary span:first-child{font-family:'Playfair Display',serif;font-size:1.3rem;
              color:var(--brown);font-weight:700;}
.year-archive summary::after{content:'▸';font-size:.9rem;color:var(--muted);margin-left:auto;
              transition:transform .2s;}
.year-archive[open] summary::after{transform:rotate(90deg);}
.year-count{font-size:.78rem;color:var(--muted);background:var(--paper);border:1px solid var(--border);
              border-radius:99px;padding:.2rem .7rem;white-space:nowrap;}
.year-body{padding:14px;background:var(--paper);display:flex;flex-direction:column;gap:10px;}

/* ── Cada entrada: solo título hasta que se abre ── */
.entrada-archivo{background:#fff;border:1px solid var(--border);border-radius:6px;overflow:hidden;}
.entrada-archivo summary{cursor:pointer;list-style:none;padding:.85rem 1.1rem;
              display:flex;align-items:center;justify-content:space-between;gap:1rem;
              background:#fff;transition:background .15s;}
.entrada-archivo summary:hover{background:var(--sepia);}
.entrada-archivo summary::-webkit-details-marker{display:none;}
.entrada-titulo-wrap{display:flex;flex-direction:column;gap:2px;min-width:0;}
.entrada-titulo{font-family:'Playfair Display',serif;font-size:1.05rem;color:var(--ink);
              font-weight:600;line-height:1.3;}
.entrada-fecha{font-size:.72rem;color:var(--rust);font-weight:700;text-transform:uppercase;
              letter-spacing:.03em;white-space:nowrap;}
.entrada-archivo summary::after{content:'▸';font-size:.8rem;color:var(--muted);flex-shrink:0;
              transition:transform .2s;}
.entrada-archivo[open] summary::after{transform:rotate(90deg);}
.entrada-archivo .articulo-card{border-top:1px solid var(--border);}

.quill-wrap{border:1px solid var(--border);border-radius:4px;overflow:hidden;margin-bottom:15px;}
.ql-toolbar{background:var(--sepia);border:none !important;border-bottom:1px solid var(--border) !important;}
.ql-container{border:none !important;font-family:'Merriweather',serif;font-size:.95rem;min-height:220px;}
.ql-editor{min-height:220px;color:var(--ink);line-height:1.8;}
.ql-editor p{margin-bottom:.6em;}
#blog-contenido{display:none;}

/* ── Leyenda del identificador físico ── */
.id-leyenda{max-width:850px;margin:20px auto 0;background:#fff;border:1px solid var(--border);
            border-radius:8px;box-shadow:var(--shadow);overflow:hidden;}
.id-leyenda summary{cursor:pointer;padding:1rem 1.25rem;font-family:'Playfair Display',serif;
            font-size:1.05rem;color:var(--brown);font-weight:600;list-style:none;
            display:flex;align-items:center;justify-content:space-between;gap:.5rem;
            background:var(--sepia);}
.id-leyenda summary::-webkit-details-marker{display:none;}
.id-leyenda summary .chev{font-size:.8rem;color:var(--muted);transition:transform .2s;}
.id-leyenda[open] summary .chev{transform:rotate(90deg);}
.id-leyenda-body{padding:1.1rem 1.25rem 1.4rem;}
.id-leyenda-ejemplo{display:flex;justify-content:center;margin-bottom:1.1rem;}
.id-leyenda-ejemplo .codigo{font-family:'Source Sans 3',monospace,sans-serif;font-size:1.15rem;
            font-weight:700;letter-spacing:.1em;color:var(--ink);background:var(--paper);
            border:2px dashed var(--border);border-radius:6px;padding:.5rem 1.1rem;}
.id-leyenda-partes{display:grid;grid-template-columns:repeat(3,1fr);gap:.85rem;}
@media(max-width:640px){.id-leyenda-partes{grid-template-columns:1fr;}}
.id-parte{background:var(--paper);border:1px solid var(--border);border-radius:6px;padding:.8rem .9rem;}
.id-parte .id-tag{display:inline-block;font-family:monospace;font-weight:700;font-size:.85rem;
            padding:1px 8px;border-radius:99px;margin-bottom:.45rem;}
.id-parte.p1 .id-tag{background:rgba(139,58,42,.15);color:var(--rust);}
.id-parte.p2 .id-tag{background:rgba(107,76,42,.15);color:var(--brown);}
.id-parte.p3 .id-tag{background:rgba(74,107,58,.15);color:#3d6b2a;}
.id-parte h4{font-size:.82rem;color:var(--ink);margin-bottom:.3rem;}
.id-parte p{font-size:.78rem;color:var(--muted);line-height:1.5;}
</style>
</head><body>
<header>
  <div><h1>Diario de Investigación Histórica</h1></div>
  <div class="header-right">
    {{ nav | safe }}
    {% if admin %}<button class="btn btn-primary" onclick="abrirNuevoBlog()">+ Nueva Entrada</button>{% endif %}
    {{ header_usuario | safe }}
  </div>
</header>

<details class="id-leyenda">
  <summary>🏷 ¿Cómo se lee el identificador físico de cada foto? <span class="chev">▸</span></summary>
  <div class="id-leyenda-body">
    <div class="id-leyenda-ejemplo">
      <span class="codigo">ROM&nbsp;-&nbsp;150642&nbsp;-&nbsp;01</span>
    </div>
    <div class="id-leyenda-partes">
      <div class="id-parte p1">
        <span class="id-tag">ROM</span>
        <h4>Siglas del evento</h4>
        <p>3 letras que identifican el evento o campaña al que pertenece la fotografía.</p>
      </div>
      <div class="id-parte p2">
        <span class="id-tag">150642</span>
        <h4>Fecha (DDMMAA)</h4>
        <p>Día, mes y año en que se tomó la fotografía. En el ejemplo: 15/06/1942.</p>
      </div>
      <div class="id-parte p3">
        <span class="id-tag">01</span>
        <h4>Nº dentro del lote</h4>
        <p>Posición de esta foto entre todas las que se tomaron en ese mismo momento (01, 02, 03…).</p>
      </div>
    </div>
  </div>
</details>

<div style="padding:20px;">
  {% if archivo_anios %}
    {% for grupo in archivo_anios %}
    <details class="year-archive" {{ 'open' if loop.first else '' }}>
      <summary>
        <span>📅 {{ grupo.anio }}</span>
        <span class="year-count">{{ grupo.articulos|length }} entrada{{ 's' if grupo.articulos|length != 1 else '' }}</span>
      </summary>
      <div class="year-body">
        {% for art in grupo.articulos %}
        <details class="entrada-archivo" data-id="{{ art.id }}">
          <summary>
            <div class="entrada-titulo-wrap">
              <span class="entrada-titulo">{{ art.titulo }}</span>
              {% if art.fecha_historica %}<span class="entrada-fecha">⚔️ {{ art.fecha_historica }}</span>{% endif %}
            </div>
          </summary>
          <div class="articulo-card">
            <div style="display:flex;justify-content:space-between;align-items:start;margin-bottom:20px;">
              <div>
                <small style="color:var(--muted);font-size:.75rem;">Entrada creada el {{ art.fecha_pub }}</small>
              </div>
              {% if admin %}
              <div style="display:flex;gap:10px;">
                <button class="btn btn-secondary btn-sm"
                  onclick='abrirEditarBlog({{ art.id }},{{ art.titulo|tojson|safe }},{{ art.contenido|tojson|safe }},{{ art.fotos_ids|tojson|safe }})'>
                  ✏️ Editar</button>
                <form action="/borrar-blog/{{ art.id }}" method="post">
                  <button class="btn btn-sm" style="color:var(--rust);border:1px solid var(--rust);font-size:.7rem;">🗑 Borrar</button>
                </form>
              </div>
              {% endif %}
            </div>
            <div class="articulo-contenido">{{ art.contenido | safe }}</div>
            <div style="margin-top:30px;display:flex;gap:10px;flex-wrap:wrap;border-top:1px solid var(--border);padding-top:20px;">
              {% for f in art.fotos %}
              <div style="text-align:center;">
                {% if f.archivo %}
                  <img src="/foto/{{ f.archivo }}" style="width:120px;height:90px;object-fit:cover;border-radius:4px;border:1px solid var(--tan);">
                {% else %}
                  <div style="width:120px;height:90px;background:var(--sepia);display:flex;align-items:center;justify-content:center;border-radius:4px;border:1px solid var(--tan)">📷</div>
                {% endif %}
                <div style="font-size:.6rem;color:var(--muted);max-width:120px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ f.titulo }}</div>
                {% if f.fecha_foto %}<div style="font-size:.6rem;color:var(--tan)">{{ f.fecha_foto }}</div>{% endif %}
              </div>
              {% endfor %}
            </div>
          </div>
        </details>
        {% endfor %}
      </div>
    </details>
    {% endfor %}
  {% else %}
    <p style="text-align:center;color:var(--muted);padding:3rem;">Todavía no hay entradas en el diario.</p>
  {% endif %}
</div>

{% if admin %}
<div class="overlay" id="modal-blog">
  <div class="modal" style="max-width:780px;">
    <div class="modal-header"><h2 id="blog-modal-title">Entrada en el Diario</h2>
      <button class="btn btn-secondary btn-sm" onclick="cerrarModal('modal-blog')"
              style="color:var(--sepia);border-color:var(--sepia);">✕ Cerrar</button></div>
    <div class="modal-body">
      <form id="form-blog" method="post" action="/guardar-blog">
        <input type="hidden" name="id" id="blog-id">
        <label>Título del Hallazgo</label>
        <input type="text" name="titulo_blog" id="blog-titulo" required style="margin-bottom:15px;">
        <label>📝 Cuerpo del Artículo</label>
        <div class="quill-wrap">
          <div id="quill-editor"></div>
        </div>
        <textarea name="contenido_blog" id="blog-contenido"></textarea>
        <label>📷 Vincular Imágenes de la Colección</label>
        <p style="font-size:.78rem;color:var(--muted);margin-bottom:8px;">La entrada se ordenará por la fecha más antigua de las fotos seleccionadas.</p>
        <div class="foto-selector">
          {% for f in todas_fotos %}
          <label class="foto-item">
            <input type="checkbox" name="fotos_ids" value="{{ f.id }}" class="blog-foto-cb">
            {% if f.archivo %}<img src="/foto/{{ f.archivo }}">
            {% else %}<div style="width:40px;height:30px;background:var(--border);display:flex;align-items:center;justify-content:center">📷</div>{% endif %}
            <span>{{ f.titulo }} <small>({{ f.fecha_foto or 'S.F.' }})</small></span>
          </label>
          {% endfor %}
        </div>
      </form>
    </div>
    <div class="modal-footer">
      <button class="btn btn-secondary" onclick="cerrarModal('modal-blog')">Cancelar</button>
      <button class="btn btn-primary" onclick="guardarBlog()">💾 Guardar Entrada</button>
    </div>
  </div>
</div>
{% endif %}

<script src="https://cdnjs.cloudflare.com/ajax/libs/quill/1.3.7/quill.min.js"></script>
<script>
function abrirModal(id){document.getElementById(id).classList.add('open');}
function cerrarModal(id){document.getElementById(id).classList.remove('open');}

const ABRIR_ID = {{ abrir_id | tojson }};
window.addEventListener('DOMContentLoaded', () => {
  if(!ABRIR_ID) return;
  const target = document.querySelector('.entrada-archivo[data-id="' + ABRIR_ID + '"]');
  if(!target) return;
  target.open = true;
  const yearParent = target.closest('.year-archive');
  if(yearParent) yearParent.open = true;
  setTimeout(() => {
    target.scrollIntoView({behavior:'smooth', block:'start'});
    target.style.outline = '3px solid var(--rust)';
    target.style.outlineOffset = '2px';
    setTimeout(() => { target.style.outline = ''; target.style.outlineOffset = ''; }, 2500);
  }, 250);
});

{% if admin %}
const quill = new Quill('#quill-editor', {
  theme: 'snow',
  placeholder: 'Escribe aquí la entrada del diario…',
  modules: {
    toolbar: [
      [{ header: [2, 3, false] }],
      ['bold', 'italic', 'underline', 'strike'],
      [{ color: [] }],
      [{ list: 'ordered' }, { list: 'bullet' }],
      ['blockquote'],
      ['clean']
    ]
  }
});

function guardarBlog(){
  document.getElementById('blog-contenido').value = quill.root.innerHTML;
  const titulo = document.getElementById('blog-titulo').value.trim();
  if(!titulo){ alert('El título es obligatorio.'); return; }
  if(quill.getText().trim().length < 2){ alert('El contenido no puede estar vacío.'); return; }
  document.getElementById('form-blog').submit();
}

function abrirNuevoBlog(){
  document.getElementById('blog-modal-title').textContent = 'Nueva Entrada en el Diario';
  document.getElementById('blog-id').value = '';
  document.getElementById('blog-titulo').value = '';
  quill.root.innerHTML = '';
  document.querySelectorAll('.blog-foto-cb').forEach(cb => cb.checked = false);
  abrirModal('modal-blog');
}

function abrirEditarBlog(id, titulo, contenido, fotosIds){
  document.getElementById('blog-modal-title').textContent = 'Editar Entrada del Diario';
  document.getElementById('blog-id').value = id;
  document.getElementById('blog-titulo').value = titulo;
  quill.root.innerHTML = contenido;
  document.querySelectorAll('.blog-foto-cb').forEach(cb => {
    cb.checked = fotosIds.includes(parseInt(cb.value));
  });
  abrirModal('modal-blog');
}
{% endif %}
</script>
</body></html>
"""
# ══════════════════════════════════════════════════════════════════════════════
# DESCARGAS 
# ══════════════════════════════════════════════════════════════════════════════
HTML_DESCARGAS = """
<!DOCTYPE html><html lang="es"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Descargas · Archivo Rommel</title>
""" + CSS_BASE + """
<style>
.desc-hero{padding:2.5rem 1.5rem 1.5rem;background:var(--sepia);border-bottom:1px solid var(--border);text-align:center;}
.desc-hero h2{font-family:'Playfair Display',serif;font-size:1.8rem;color:var(--brown);margin-bottom:.5rem;}
.desc-hero p{font-size:.92rem;color:var(--muted);max-width:600px;margin:0 auto;line-height:1.6;}
.desc-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:1.5rem;
           padding:2rem;max-width:1000px;margin:0 auto;}
.desc-card{background:var(--card);border:1px solid var(--border);border-radius:10px;
           padding:2rem 1.5rem;text-align:center;box-shadow:var(--shadow);
           display:flex;flex-direction:column;align-items:center;gap:.8rem;}
.desc-icon{font-size:3rem;}
.desc-card h3{font-family:'Playfair Display',serif;font-size:1.2rem;color:var(--ink);}
.desc-card p{font-size:.85rem;color:var(--muted);line-height:1.5;}
.desc-card .cuenta{font-size:.78rem;color:var(--tan);font-weight:600;}
.btn-desc-grande{background:#3d6b2a;color:#fff;border:none;padding:.75rem 1.6rem;border-radius:6px;
           font-family:inherit;font-size:.92rem;font-weight:600;cursor:pointer;text-decoration:none;
           display:inline-flex;align-items:center;gap:.5rem;margin-top:.5rem;width:100%;justify-content:center;}
.btn-desc-grande:hover{opacity:.85;}
.desc-nota{max-width:1000px;margin:0 auto 2rem;padding:0 2rem;font-size:.8rem;color:var(--muted);
           text-align:center;line-height:1.6;}
</style>
</head><body>
<header>
  <div><h1>Centro de Descargas</h1><small>Lleva la colección contigo</small></div>
  <div class="header-right">
    {{ nav | safe }}
    {{ header_usuario | safe }}
  </div>
</header>

<div class="desc-hero">
  <h2>⬇️ Descarga la colección</h2>
  <p>Aquí puedes descargar las fotografías y vídeos del archivo, ya sea de uno en uno desde sus fichas,
     o la colección completa en un único archivo ZIP listo para guardar.</p>
</div>

<div class="desc-grid">
  <div class="desc-card">
    <div class="desc-icon">📸</div>
    <h3>Todas las fotografías</h3>
    <p>Descarga un ZIP con todas las fotos originales en su máxima calidad.</p>
    <div class="cuenta">{{ total_fotos }} fotografías</div>
    <a href="/descargar-zip/fotos" class="btn-desc-grande">⬇️ Descargar fotos (ZIP)</a>
  </div>

  <div class="desc-card">
    <div class="desc-icon">🎬</div>
    <h3>Todos los vídeos</h3>
    <p>Descarga un ZIP con todos los vídeos archivados.</p>
    <div class="cuenta">{{ total_videos }} vídeos</div>
    <a href="/descargar-zip/videos" class="btn-desc-grande">⬇️ Descargar vídeos (ZIP)</a>
  </div>

  <div class="desc-card">
    <div class="desc-icon">🗂</div>
    <h3>Colección completa</h3>
    <p>Descarga fotos y vídeos juntos en un único archivo ZIP.</p>
    <div class="cuenta">{{ total_fotos }} fotos · {{ total_videos }} vídeos</div>
    <a href="/descargar-zip/todo" class="btn-desc-grande">⬇️ Descargar todo (ZIP)</a>
  </div>
</div>

<p class="desc-nota">
  Los nombres de los archivos dentro del ZIP incluyen el título de cada fotografía o vídeo para que sea fácil identificarlos.
  Si la colección es muy grande, la descarga puede tardar unos segundos en prepararse.
</p>
</body></html>
"""
# ══════════════════════════════════════════════════════════════════════════════
# RUTAS: LOGIN / LOGOUT
# ══════════════════════════════════════════════════════════════════════════════
@app.route("/login", methods=["GET", "POST"])
def login():
    if usuario_activo():
        return redirect(url_for("index"))
    error = ""
    correo_previo = ""
    next_url = request.args.get("next") or request.form.get("next") or "/"
    if request.method == "POST":
        correo     = request.form.get("correo", "").strip().lower()
        contrasena = request.form.get("contrasena", "").strip()
        correo_previo = correo
        if not CONTRASENA_ACCESO:
            error = "No hay contraseña configurada. Crea config_local.json (ver README)."
        elif not hmac.compare_digest(contrasena.encode("utf-8"), CONTRASENA_ACCESO.encode("utf-8")):
            error = "Contraseña incorrecta."
        elif not correo:
            error = "Introduce tu correo electrónico."
        else:
            rol = "admin" if correo in {a.lower() for a in ADMINS} else "lector"
            session["usuario"] = {"correo": correo, "rol": rol}
            session.permanent = False
            if not next_url.startswith("/"):
                next_url = "/"
            return redirect(next_url)
    return render_template_string(HTML_LOGIN, error=error,
                                  correo_previo=correo_previo, next=next_url)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))
# ══════════════════════════════════════════════════════════════════════════════
# RUTAS: GALERÍA
# ══════════════════════════════════════════════════════════════════════════════
@app.route("/")
@login_requerido
def index():
    db = get_db()
    personas = db.execute("SELECT id,nombre,rango FROM personas ORDER BY nombre").fetchall()
    documentos = db.execute("SELECT id,titulo,categoria FROM investigacion ORDER BY titulo").fetchall()
    q = request.args.get("q","").strip()
    frente_sel = request.args.get("frente","").strip()
    pais_sel   = request.args.get("pais","").strip()
    query  = "SELECT * FROM fotografias WHERE 1=1"
    params = []
    if q:
        query  += " AND (titulo LIKE ? OR descripcion LIKE ? OR ubicacion LIKE ? OR etiquetas LIKE ? OR fuente LIKE ?)"
        params += [f"%{q}%"] * 5
    if frente_sel:
        query += " AND frente=?"; params.append(frente_sel)
    if pais_sel:
        query += " AND pais=?";   params.append(pais_sel)
    query += " ORDER BY fecha_foto DESC, COALESCE(orden_manual,0) ASC, id DESC"
    fotos   = db.execute(query, params).fetchall()
    total   = db.execute("SELECT COUNT(*) FROM fotografias").fetchone()[0]
    frentes = [r[0] for r in db.execute("SELECT DISTINCT frente FROM fotografias WHERE frente IS NOT NULL AND frente!='' ORDER BY frente").fetchall()]
    paises  = [r[0] for r in db.execute("SELECT DISTINCT pais  FROM fotografias WHERE pais  IS NOT NULL AND pais !='' ORDER BY pais").fetchall()]
    historia_map = obtener_mapa_historias(db)
    db.close()
    return render_template_string(HTML, fotos=fotos, total=total, q=q,
        frentes=frentes, paises=paises, frente_sel=frente_sel, pais_sel=pais_sel,
        historia_map=historia_map, personas=personas, documentos=documentos,
        admin=es_admin(), header_usuario=header_usuario(), nav=nav("galeria"))

@app.route("/fotos")
@login_requerido
def solo_fotos():
    db    = get_db()
    fotos = db.execute("SELECT id,titulo,archivo,fecha_foto FROM fotografias ORDER BY fecha_foto DESC, COALESCE(orden_manual,0) ASC, id DESC").fetchall()
    total = db.execute("SELECT COUNT(*) FROM fotografias").fetchone()[0]
    historia_map = obtener_mapa_historias(db)
    db.close()
    return render_template_string(HTML_FOTOS, fotos=fotos, total=total,
        historia_map=historia_map,
        admin=es_admin(), header_usuario=header_usuario(), nav=nav("fotos"))

@app.route("/guardar", methods=["POST"])
@login_requerido
@solo_admin
def guardar():
    f  = request.form
    db = get_db()
    lat = float(f.get("lat","").strip()) if f.get("lat","").strip() else None
    lon = float(f.get("lon","").strip()) if f.get("lon","").strip() else None
    archivo = None
    if "archivo" in request.files:
        file = request.files["archivo"]
        if file.filename and allowed_image(file.filename):
            archivo = secure_filename(file.filename)
            file.save(os.path.join(app.config["UPLOAD_FOLDER"], archivo))
    if f.get("id"):
        foto_id = f["id"]
        if archivo:
            db.execute("UPDATE fotografias SET titulo=?,fecha_foto=?,ubicacion=?,pais=?,frente=?,descripcion=?,fuente=?,etiquetas=?,lat=?,lon=?,archivo=? WHERE id=?",
                       (f["titulo"],f["fecha_foto"],f["ubicacion"],f.get("pais"),f.get("frente"),f["descripcion"],f.get("fuente"),f.get("etiquetas"),lat,lon,archivo,foto_id))
        else:
            db.execute("UPDATE fotografias SET titulo=?,fecha_foto=?,ubicacion=?,pais=?,frente=?,descripcion=?,fuente=?,etiquetas=?,lat=?,lon=? WHERE id=?",
                       (f["titulo"],f["fecha_foto"],f["ubicacion"],f.get("pais"),f.get("frente"),f["descripcion"],f.get("fuente"),f.get("etiquetas"),lat,lon,foto_id))
    else:
        cur = db.execute("INSERT INTO fotografias (titulo,fecha_foto,ubicacion,pais,frente,descripcion,fuente,etiquetas,lat,lon,archivo,fecha_alta) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                   (f["titulo"],f["fecha_foto"],f["ubicacion"],f.get("pais"),f.get("frente"),f["descripcion"],f.get("fuente"),f.get("etiquetas"),lat,lon,archivo,datetime.now().strftime("%Y-%m-%d")))
        foto_id = cur.lastrowid
    db.execute("DELETE FROM fotografias_personas WHERE fotografia_id=?", (foto_id,))
    for pid in request.form.getlist("personas_ids"):
        db.execute("INSERT OR IGNORE INTO fotografias_personas (fotografia_id,persona_id) VALUES (?,?)", (foto_id, pid))
    db.execute("DELETE FROM fotografias_investigacion WHERE fotografia_id=?", (foto_id,))
    for did in request.form.getlist("investigacion_ids"):
        db.execute("INSERT OR IGNORE INTO fotografias_investigacion (fotografia_id,investigacion_id) VALUES (?,?)", (foto_id, did))
    db.commit(); db.close()
    return redirect(url_for("index"))

@app.route("/foto/<filename>")
@login_requerido
def servir_foto(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)

@app.route("/foto-detalle/<int:id>")
@login_requerido
def foto_detalle(id):
    db   = get_db()
    foto = db.execute("SELECT * FROM fotografias WHERE id=?", (id,)).fetchone()
    articulos = db.execute("""
        SELECT a.id, a.titulo FROM articulos a
        JOIN articulos_fotografias af ON af.articulo_id = a.id
        WHERE af.fotografia_id = ?
    """, (id,)).fetchall()
    personas = db.execute("""
        SELECT p.id, p.nombre FROM personas p
        JOIN fotografias_personas fp ON fp.persona_id = p.id
        WHERE fp.fotografia_id = ?
    """, (id,)).fetchall()
    documentos = db.execute("""
        SELECT i.id, i.titulo, i.archivo, i.tipo_archivo FROM investigacion i
        JOIN fotografias_investigacion fi ON fi.investigacion_id = i.id
        WHERE fi.fotografia_id = ?
    """, (id,)).fetchall()
    db.close()
    data = dict(foto)
    data["articulos"] = [dict(a) for a in articulos]
    data["personas"] = [dict(p) for p in personas]
    data["personas_ids"] = [p["id"] for p in personas]
    data["documentos"] = [dict(d) for d in documentos]
    data["investigacion_ids"] = [d["id"] for d in documentos]
    return jsonify(data)

@app.route("/borrar/<int:id>", methods=["POST"])
@login_requerido
@solo_admin
def borrar(id):
    db   = get_db()
    foto = db.execute("SELECT archivo FROM fotografias WHERE id=?", (id,)).fetchone()
    if foto and foto["archivo"]:
        ruta = os.path.join(app.config["UPLOAD_FOLDER"], foto["archivo"])
        if os.path.exists(ruta): os.remove(ruta)
    db.execute("DELETE FROM fotografias WHERE id=?", (id,))
    db.commit(); db.close()
    return jsonify({"ok": True})

@app.route("/guardar-orden", methods=["POST"])
@login_requerido
@solo_admin
def guardar_orden():
    """Recibe [{id: X, orden: N}, ...] y actualiza orden_manual solo para esas fotos."""
    data = request.get_json()
    if not data or not isinstance(data, list):
        return jsonify({"ok": False}), 400
    db = get_db()
    for item in data:
        db.execute("UPDATE fotografias SET orden_manual=? WHERE id=?",
                   (item["orden"], item["id"]))
    db.commit()
    db.close()
    return jsonify({"ok": True})

# ══════════════════════════════════════════════════════════════════════════════
# RUTAS: DESCARGAS (individuales y en ZIP)
# ══════════════════════════════════════════════════════════════════════════════
def _nombre_descarga(titulo, archivo_original, prefijo_id):
    """Genera un nombre de archivo legible a partir del título, conservando la extensión original."""
    ext = ""
    if "." in archivo_original:
        ext = "." + archivo_original.rsplit(".", 1)[1].lower()
    base = secure_filename(titulo) or f"archivo_{prefijo_id}"
    return f"{base}{ext}"

@app.route("/descargar-foto/<int:id>")
@login_requerido
def descargar_foto(id):
    db   = get_db()
    foto = db.execute("SELECT * FROM fotografias WHERE id=?", (id,)).fetchone()
    db.close()
    if not foto or not foto["archivo"]:
        abort(404)
    ruta = os.path.join(app.config["UPLOAD_FOLDER"], foto["archivo"])
    if not os.path.exists(ruta):
        abort(404)
    nombre_descarga = _nombre_descarga(foto["titulo"], foto["archivo"], foto["id"])
    return send_file(ruta, as_attachment=True, download_name=nombre_descarga)

@app.route("/descargar-video/<int:id>")
@login_requerido
def descargar_video(id):
    db    = get_db()
    video = db.execute("SELECT * FROM videos WHERE id=?", (id,)).fetchone()
    db.close()
    if not video or not video["archivo"]:
        abort(404)
    ruta = os.path.join(app.config["VIDEOS_FOLDER"], video["archivo"])
    if not os.path.exists(ruta):
        abort(404)
    nombre_descarga = _nombre_descarga(video["titulo"], video["archivo"], video["id"])
    return send_file(ruta, as_attachment=True, download_name=nombre_descarga)

@app.route("/descargas")
@login_requerido
def descargas():
    db = get_db()
    total_fotos  = db.execute("SELECT COUNT(*) FROM fotografias WHERE archivo IS NOT NULL AND archivo!=''").fetchone()[0]
    total_videos = db.execute("SELECT COUNT(*) FROM videos WHERE archivo IS NOT NULL AND archivo!=''").fetchone()[0]
    db.close()
    return render_template_string(HTML_DESCARGAS, total_fotos=total_fotos, total_videos=total_videos,
        header_usuario=header_usuario(), nav=nav("descargas"))

@app.route("/descargar-zip/<modo>")
@login_requerido
def descargar_zip(modo):
    """modo: 'fotos', 'videos' o 'todo'. Genera el ZIP en memoria y lo envía como descarga."""
    if modo not in {"fotos", "videos", "todo"}:
        abort(404)

    db = get_db()
    buffer = io.BytesIO()
    nombres_usados = set()

    def nombre_unico(nombre):
        if nombre not in nombres_usados:
            nombres_usados.add(nombre)
            return nombre
        base, ext = os.path.splitext(nombre)
        i = 2
        nuevo = f"{base} ({i}){ext}"
        while nuevo in nombres_usados:
            i += 1
            nuevo = f"{base} ({i}){ext}"
        nombres_usados.add(nuevo)
        return nuevo

    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        if modo in ("fotos", "todo"):
            fotos = db.execute("SELECT * FROM fotografias WHERE archivo IS NOT NULL AND archivo!=''").fetchall()
            for f in fotos:
                ruta = os.path.join(app.config["UPLOAD_FOLDER"], f["archivo"])
                if os.path.exists(ruta):
                    nombre = _nombre_descarga(f["titulo"], f["archivo"], f["id"])
                    carpeta = "Fotos/" if modo == "todo" else ""
                    zf.write(ruta, carpeta + nombre_unico(nombre))
        if modo in ("videos", "todo"):
            videos = db.execute("SELECT * FROM videos WHERE archivo IS NOT NULL AND archivo!=''").fetchall()
            for v in videos:
                ruta = os.path.join(app.config["VIDEOS_FOLDER"], v["archivo"])
                if os.path.exists(ruta):
                    nombre = _nombre_descarga(v["titulo"], v["archivo"], v["id"])
                    carpeta = "Videos/" if modo == "todo" else ""
                    zf.write(ruta, carpeta + nombre_unico(nombre))
    db.close()

    buffer.seek(0)
    nombre_zip = {
        "fotos":  "Archivo_Rommel_Fotos.zip",
        "videos": "Archivo_Rommel_Videos.zip",
        "todo":   "Archivo_Rommel_Coleccion_Completa.zip",
    }[modo]
    return send_file(buffer, mimetype="application/zip",
                      as_attachment=True, download_name=nombre_zip)

# ══════════════════════════════════════════════════════════════════════════════
# RUTAS: FICHA QR
# ══════════════════════════════════════════════════════════════════════════════
@app.route("/ficha/<int:id>")
@login_requerido
def ficha(id):
    db   = get_db()
    foto = db.execute("SELECT * FROM fotografias WHERE id=?", (id,)).fetchone()
    fuentes = db.execute("SELECT id, titulo, autor FROM bibliografia ORDER BY titulo").fetchall()
    db.close()
    if not foto:
        abort(404)
    base_url  = request.host_url.rstrip("/")
    ficha_url = f"{base_url}/ficha/{id}"
    afirmaciones = obtener_afirmaciones("fotografia", id)
    return render_template_string(HTML_FICHA, foto=foto, ficha_url=ficha_url,
        afirmaciones=afirmaciones, niveles_certeza=NIVELES_CERTEZA,
        fuentes=fuentes, admin=es_admin())

@app.route("/guardar-identificador/<int:id>", methods=["POST"])
@login_requerido
@solo_admin
def guardar_identificador(id):
    data  = request.get_json(silent=True) or {}
    valor = (data.get("identificador") or "").strip().upper()

    if valor and not re.match(r'^[A-Z]{3}-\d{6}-\d{2}$', valor):
        return jsonify({"ok": False, "error": "Formato inválido. Usa AAA-000000-00."}), 400

    db = get_db()
    foto = db.execute("SELECT id FROM fotografias WHERE id=?", (id,)).fetchone()
    if not foto:
        db.close()
        abort(404)
    try:
        db.execute("UPDATE fotografias SET identificador=? WHERE id=?", (valor or None, id))
        db.commit()
    except sqlite3.IntegrityError:
        db.close()
        return jsonify({"ok": False, "error": "Ese identificador ya está en uso en otra foto."}), 400
    db.close()
    return jsonify({"ok": True, "identificador": valor or None})


@app.route("/qr-etiquetas")
@login_requerido
def qr_etiquetas():
    db    = get_db()
    fotos = db.execute("SELECT id,titulo,fecha_foto,frente,ubicacion FROM fotografias ORDER BY fecha_foto ASC,id ASC").fetchall()
    db.close()
    base_url   = request.host_url.rstrip("/")
    fotos_json = json.dumps([dict(f) for f in fotos])
    return render_template_string(HTML_QR_ETIQUETAS,
        fotos=fotos, fotos_json=fotos_json, base_url=base_url)


# ══════════════════════════════════════════════════════════════════════════════
# RUTAS: VÍDEOS
# ══════════════════════════════════════════════════════════════════════════════
@app.route("/videos")
@login_requerido
def videos():
    db = get_db()
    q = request.args.get("q","").strip()
    frente_sel = request.args.get("frente","").strip()
    query = "SELECT * FROM videos WHERE 1=1"
    params = []
    if q:
        query  += " AND (titulo LIKE ? OR descripcion LIKE ? OR ubicacion LIKE ? OR etiquetas LIKE ?)"
        params += [f"%{q}%"] * 4
    if frente_sel:
        query += " AND frente=?"; params.append(frente_sel)
    query += " ORDER BY fecha_video DESC, id DESC"
    videos_list = db.execute(query, params).fetchall()
    total   = db.execute("SELECT COUNT(*) FROM videos").fetchone()[0]
    frentes = [r[0] for r in db.execute("SELECT DISTINCT frente FROM videos WHERE frente IS NOT NULL AND frente!='' ORDER BY frente").fetchall()]
    frentes_foto = [r[0] for r in db.execute("SELECT DISTINCT frente FROM fotografias WHERE frente IS NOT NULL AND frente!='' ORDER BY frente").fetchall()]
    frentes_all  = sorted(set(frentes + frentes_foto))
    db.close()
    return render_template_string(HTML_VIDEOS, videos=videos_list, total=total, q=q,
        frentes=frentes_all, frente_sel=frente_sel,
        admin=es_admin(), header_usuario=header_usuario(), nav=nav("videos"))

@app.route("/guardar-video", methods=["POST"])
@login_requerido
@solo_admin
def guardar_video():
    f  = request.form
    db = get_db()
    archivo = None
    if "archivo" in request.files:
        file = request.files["archivo"]
        if file.filename and allowed_video(file.filename):
            archivo = secure_filename(file.filename)
            file.save(os.path.join(app.config["VIDEOS_FOLDER"], archivo))
    if f.get("id"):
        if archivo:
            db.execute("UPDATE videos SET titulo=?,fecha_video=?,ubicacion=?,pais=?,frente=?,descripcion=?,fuente=?,etiquetas=?,duracion=?,archivo=? WHERE id=?",
                       (f["titulo"],f.get("fecha_video"),f.get("ubicacion"),f.get("pais"),f.get("frente"),f.get("descripcion"),f.get("fuente"),f.get("etiquetas"),f.get("duracion"),archivo,f["id"]))
        else:
            db.execute("UPDATE videos SET titulo=?,fecha_video=?,ubicacion=?,pais=?,frente=?,descripcion=?,fuente=?,etiquetas=?,duracion=? WHERE id=?",
                       (f["titulo"],f.get("fecha_video"),f.get("ubicacion"),f.get("pais"),f.get("frente"),f.get("descripcion"),f.get("fuente"),f.get("etiquetas"),f.get("duracion"),f["id"]))
    else:
        db.execute("INSERT INTO videos (titulo,fecha_video,ubicacion,pais,frente,descripcion,fuente,etiquetas,duracion,archivo,fecha_alta) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                   (f["titulo"],f.get("fecha_video"),f.get("ubicacion"),f.get("pais"),f.get("frente"),f.get("descripcion"),f.get("fuente"),f.get("etiquetas"),f.get("duracion"),archivo,datetime.now().strftime("%Y-%m-%d")))
    db.commit(); db.close()
    return redirect(url_for("videos"))

@app.route("/video/<filename>")
@login_requerido
def servir_video(filename):
    return send_from_directory(app.config["VIDEOS_FOLDER"], filename)

@app.route("/video-detalle/<int:id>")
@login_requerido
def video_detalle(id):
    db    = get_db()
    video = db.execute("SELECT * FROM videos WHERE id=?", (id,)).fetchone()
    db.close()
    if not video: abort(404)
    return jsonify(dict(video))

@app.route("/borrar-video/<int:id>", methods=["POST"])
@login_requerido
@solo_admin
def borrar_video(id):
    db    = get_db()
    video = db.execute("SELECT archivo FROM videos WHERE id=?", (id,)).fetchone()
    if video and video["archivo"]:
        ruta = os.path.join(app.config["VIDEOS_FOLDER"], video["archivo"])
        if os.path.exists(ruta): os.remove(ruta)
    db.execute("DELETE FROM videos WHERE id=?", (id,))
    db.commit(); db.close()
    return jsonify({"ok": True})

# ══════════════════════════════════════════════════════════════════════════════
# RUTAS: LÍNEA TEMPORAL
# ══════════════════════════════════════════════════════════════════════════════
@app.route("/linea-temporal")
@login_requerido
def linea_temporal():
    db    = get_db()
    fotos = db.execute("SELECT id,titulo,fecha_foto,archivo FROM fotografias WHERE fecha_foto IS NOT NULL AND fecha_foto!='' ORDER BY fecha_foto ASC").fetchall()
    db.close()
    momentos = defaultdict(list)
    for f in fotos:
        momentos[f["fecha_foto"]].append(dict(f))
    eventos = [{"fecha": fecha, "fotos": lista} for fecha, lista in momentos.items()]
    return render_template_string(HTML_TIMELINE, eventos=eventos,
        header_usuario=header_usuario(), nav=nav("timeline"))


# ══════════════════════════════════════════════════════════════════════════════
# RUTAS: MAPA
# ══════════════════════════════════════════════════════════════════════════════
@app.route("/mapa")
@login_requerido
def mapa():
    db        = get_db()
    fotos_gps = db.execute("SELECT * FROM fotografias WHERE lat IS NOT NULL AND lon IS NOT NULL").fetchall()
    grupos    = defaultdict(list)
    for f in fotos_gps:
        grupos[(f["lat"], f["lon"])].append(dict(f))
    puntos = []
    todas_fechas = set()
    for (lat, lon), flist in grupos.items():
        nombres = list(set(f["ubicacion"] for f in flist if f["ubicacion"]))
        fechas_punto = sorted([f["fecha_foto"] for f in flist if f["fecha_foto"]])
        fecha_min = fechas_punto[0] if fechas_punto else None
        if fecha_min:
            todas_fechas.add(fecha_min)
        puntos.append({"lat": lat, "lon": lon,
                       "nombre": " / ".join(nombres) if nombres else "Ubicación documentada",
                       "fecha_min": fecha_min,
                       "fotos": flist})
    fechas_disponibles = sorted(todas_fechas)
    db.close()
    return render_template_string(HTML_MAPA, puntos=puntos, n_fotos=len(fotos_gps),
        fechas_disponibles=fechas_disponibles,
        header_usuario=header_usuario(), nav=nav("mapa"))

# ══════════════════════════════════════════════════════════════════════════════
# INVESTIGACIÓN (PDFs)
# ══════════════════════════════════════════════════════════════════════════════
HTML_INVESTIGACION = """
<!DOCTYPE html><html lang="es"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Investigación · IIGM</title>
""" + CSS_BASE + """
<style>
.inv-hero{padding:2rem 1.5rem 1.2rem;background:var(--sepia);border-bottom:1px solid var(--border);}
.inv-hero h2{font-family:'Playfair Display',serif;font-size:1.6rem;color:var(--brown);margin-bottom:.3rem;}
.inv-hero p{font-size:.88rem;color:var(--muted);max-width:700px;line-height:1.6;}
.inv-filtros{display:flex;gap:.6rem;padding:1rem 1.5rem;background:var(--paper);
             border-bottom:1px solid var(--border);flex-wrap:wrap;}
.inv-filtros input,.inv-filtros select{padding:.5rem .75rem;border:1px solid var(--border);
  border-radius:4px;font-family:inherit;font-size:.85rem;background:#fff;}
.inv-filtros input{flex:1;min-width:200px;}
.inv-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:1.25rem;padding:1.5rem;}
.inv-card{background:#fff;border:1px solid var(--border);border-radius:8px;overflow:hidden;
          box-shadow:var(--shadow);display:flex;flex-direction:column;}
.inv-card-top{padding:1.1rem 1.2rem .6rem;flex:1;display:flex;gap:.9rem;}
.inv-icon{font-size:2.2rem;flex-shrink:0;}
.inv-titulo{font-family:'Playfair Display',serif;font-size:1.05rem;font-weight:600;color:var(--ink);line-height:1.3;}
.inv-meta{font-size:.76rem;color:var(--muted);margin-top:.3rem;display:flex;flex-wrap:wrap;gap:.5rem;}
.inv-desc{font-size:.83rem;color:var(--muted);line-height:1.5;margin-top:.5rem;
          display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;}
.inv-footer{padding:.7rem 1.1rem;border-top:1px solid var(--border);background:var(--paper);
            display:flex;gap:.5rem;flex-wrap:wrap;}
.inv-empty{grid-column:1/-1;text-align:center;padding:5rem 2rem;color:var(--muted);}
.upload-zone{border:2px dashed var(--border);border-radius:6px;padding:1.5rem;text-align:center;
             cursor:pointer;transition:border-color .2s;color:var(--muted);font-size:.875rem;}
.upload-zone:hover{border-color:var(--brown);background:var(--sepia);}
.inv-thumb{width:100%;aspect-ratio:4/3;object-fit:cover;background:var(--sepia);border-radius:4px;flex-shrink:0;}
.inv-icon-wrap{width:70px;flex-shrink:0;}
</style>
</head><body>

<header>
  <div><h1>Investigación</h1><small>{{ total }} documentos</small></div>
  <div class="header-right">
    {{ nav | safe }}
    {% if admin %}<button class="btn btn-primary" onclick="abrirNuevo()">+ Añadir documento</button>{% endif %}
    {{ header_usuario | safe }}
  </div>
</header>

<div class="inv-hero">
  <h2>📄 Documentos de Investigación</h2>
  <p>Archivos PDF (informes, transcripciones, notas) e imágenes de periódicos u otras fuentes documentales, con su información de referencia.</p>
</div>

<form class="inv-filtros" method="get" action="/investigacion">
  <input type="text" name="q" placeholder="Buscar por título, autor, descripción…" value="{{ q }}">
  <select name="categoria"><option value="">— Todas las categorías —</option>
    {% for c in categorias %}<option value="{{ c }}" {{ 'selected' if c==cat_sel }}>{{ c }}</option>{% endfor %}
  </select>
  <button type="submit" class="btn btn-primary">Buscar</button>
  <a href="/investigacion" class="btn btn-secondary">Limpiar</a>
</form>

<div class="inv-grid">
  {% if docs %}
    {% for d in docs %}
    <div class="inv-card">
      <div class="inv-card-top">
        <div class="inv-icon-wrap"><div class="inv-icon">📄</div></div>
        <div style="flex:1;min-width:0;">
          <div class="inv-titulo">{{ d.titulo }}</div>
          <div class="inv-meta">
            {% if d.fecha_doc %}<span>📅 {{ d.fecha_doc }}</span>{% endif %}
            {% if d.periodico %}<span>🗞 {{ d.periodico }}</span>{% endif %}
            {% if d.pagina %}<span>📖 pág. {{ d.pagina }}</span>{% endif %}
            {% if d.autor %}<span>✍️ {{ d.autor }}</span>{% endif %}
            {% if d.categoria %}<span>🏷 {{ d.categoria }}</span>{% endif %}
          </div>
          {% if d.descripcion %}<div class="inv-desc">{{ d.descripcion }}</div>{% endif %}
        </div>
      </div>
      <div class="inv-footer">
        {% if d.archivo %}
        <a href="/pdf/{{ d.archivo }}" target="_blank" class="btn btn-sm btn-secondary">👁 Ver</a>
        <a href="/descargar-pdf/{{ d.id }}" class="btn btn-sm btn-download">⬇️ Descargar</a>
        {% endif %}
        {% if admin %}
        <button class="btn btn-sm btn-edit-pro" onclick="editarDoc({{ d.id }})">✏️ Editar</button>
        <button class="btn btn-sm" style="background:var(--rust);color:#fff;"
                onclick="confirmarBorrarDoc({{ d.id }},'{{ d.titulo|replace("'","\\'")|safe }}')">🗑 Borrar</button>
        {% endif %}
      </div>
    </div>
    {% endfor %}
  {% else %}
  <div class="inv-empty"><div style="font-size:3rem;margin-bottom:1rem">📄</div><h3>No hay documentos todavía</h3></div>
  {% endif %}
</div>

{% if admin %}
<div class="overlay" id="modal-inv">
  <div class="modal">
    <div class="modal-header"><h2 id="inv-modal-title">Añadir documento</h2>
      <button class="btn btn-secondary btn-sm" onclick="cerrarModal('modal-inv')"
              style="color:var(--sepia);border-color:var(--sepia);">✕ Cerrar</button></div>
    <div class="modal-body">
      <form id="form-inv" enctype="multipart/form-data" method="post" action="/guardar-pdf">
        <input type="hidden" name="id" id="inv-id">
        <div class="form-grid">
          <div class="form-group span2"><label>Título *</label><input type="text" id="inv-titulo" name="titulo" required></div>
          <div class="form-group"><label>Fecha del documento</label><input type="date" id="inv-fecha" name="fecha_doc"></div>
          <div class="form-group"><label>Categoría</label>
            <input type="text" id="inv-categoria" name="categoria" list="inv-categorias-list">
            <datalist id="inv-categorias-list">{% for c in categorias %}<option value="{{ c }}">{% endfor %}</datalist>
          </div>
          <div class="form-group"><label>Nombre del periódico</label>
            <input type="text" id="inv-periodico" name="periodico" placeholder="Ej. ABC, La Vanguardia…"></div>
          <div class="form-group"><label>Página</label>
            <input type="text" id="inv-pagina" name="pagina" placeholder="Ej. 3, portada…"></div>
          <div class="form-group span2"><label>Autor / Procedencia</label><input type="text" id="inv-autor" name="autor"></div>
          <div class="form-group span2"><label>Descripción / Notas</label><textarea id="inv-descripcion" name="descripcion"></textarea></div>
          <div class="form-group span2">
            <label>Archivo (PDF o imagen del periódico)</label>
            <div class="upload-zone" id="inv-upload-zone" onclick="document.getElementById('inv-archivo').click()">
              <span id="inv-upload-text" style="font-size:1.1rem">📄🗞 Pulsa para seleccionar un PDF o una imagen</span>
            </div>
            <input type="file" id="inv-archivo" name="archivo" accept="application/pdf,image/*" style="display:none"
                   onchange="document.getElementById('inv-upload-text').textContent='📎 '+this.files[0].name">
          </div>
        </div>
      </form>
    </div>
    <div class="modal-footer">
      <button class="btn btn-secondary" onclick="cerrarModal('modal-inv')">Cancelar</button>
      <button class="btn btn-primary" onclick="document.getElementById('form-inv').submit()">💾 Guardar</button>
    </div>
  </div>
</div>
{% endif %}

<script>
function abrirModal(id){document.getElementById(id).classList.add('open');}
function cerrarModal(id){document.getElementById(id).classList.remove('open');}
document.querySelectorAll('.overlay').forEach(o=>o.addEventListener('click',e=>{if(e.target===o)o.classList.remove('open');}));

{% if admin %}
function abrirNuevo(){
  document.getElementById('inv-modal-title').textContent='Añadir documento';
  document.getElementById('form-inv').reset();
  document.getElementById('inv-id').value='';
  document.getElementById('inv-upload-text').textContent='📄🗞 Pulsa para seleccionar un PDF o una imagen';
  abrirModal('modal-inv');
}
function editarDoc(id){
  fetch('/investigacion-detalle/'+id).then(r=>r.json()).then(d=>{
    document.getElementById('inv-modal-title').textContent='Editar documento';
    document.getElementById('inv-id').value=d.id;
    document.getElementById('inv-titulo').value=d.titulo||'';
    document.getElementById('inv-fecha').value=d.fecha_doc||'';
    document.getElementById('inv-categoria').value=d.categoria||'';
    document.getElementById('inv-periodico').value=d.periodico||'';
    document.getElementById('inv-pagina').value=d.pagina||'';
    document.getElementById('inv-autor').value=d.autor||'';
    document.getElementById('inv-descripcion').value=d.descripcion||'';
    if(d.archivo) document.getElementById('inv-upload-text').textContent='📎 '+d.archivo+' (subido)';
    abrirModal('modal-inv');
  });
}
function confirmarBorrarDoc(id,titulo){
  if(confirm('¿Seguro que quieres borrar «'+titulo+'»?'))
    fetch('/borrar-pdf/'+id,{method:'POST'}).then(()=>location.reload());
}
{% endif %}
</script>
</body></html>
"""

# ══════════════════════════════════════════════════════════════════════════════
# PERSONAS
# ══════════════════════════════════════════════════════════════════════════════
HTML_PERSONAS = """
<!DOCTYPE html><html lang="es"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Personas · IIGM</title>
""" + CSS_BASE + """
<style>
.per-hero{padding:2rem 1.5rem 1.2rem;background:var(--sepia);border-bottom:1px solid var(--border);}
.per-hero h2{font-family:'Playfair Display',serif;font-size:1.6rem;color:var(--brown);margin-bottom:.3rem;}
.per-hero p{font-size:.88rem;color:var(--muted);max-width:700px;line-height:1.6;}
.per-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:1.25rem;padding:1.5rem;}
.per-card{background:#fff;border:1px solid var(--border);border-radius:8px;overflow:hidden;
          box-shadow:var(--shadow);text-align:center;padding:1.5rem 1rem;
          display:flex;flex-direction:column;align-items:center;gap:.5rem;transition:transform .15s;}
.per-card:hover{transform:translateY(-3px);}
.per-avatar{width:90px;height:90px;border-radius:50%;object-fit:cover;border:3px solid var(--tan);background:var(--sepia);}
.per-avatar-vacio{width:90px;height:90px;border-radius:50%;background:var(--sepia);border:3px solid var(--border);
                  display:flex;align-items:center;justify-content:center;font-size:2.2rem;color:var(--tan);}
.per-nombre{font-family:'Playfair Display',serif;font-size:1.1rem;font-weight:600;color:var(--ink);}
.per-meta{font-size:.78rem;color:var(--muted);line-height:1.4;}
.per-count{font-size:.72rem;background:var(--sepia);color:var(--brown);border:1px solid var(--border);
           border-radius:99px;padding:.15rem .6rem;margin-top:.3rem;}
.per-empty{grid-column:1/-1;text-align:center;padding:5rem 2rem;color:var(--muted);}
.upload-zone{border:2px dashed var(--border);border-radius:6px;padding:1.2rem;text-align:center;
             cursor:pointer;transition:border-color .2s;color:var(--muted);font-size:.875rem;}
.upload-zone:hover{border-color:var(--brown);background:var(--sepia);}
#per-preview{max-width:100%;max-height:140px;border-radius:50%;display:none;margin:.6rem auto 0;object-fit:cover;}
</style>
</head><body>

<header>
  <div><h1>Personas</h1><small>{{ total }} fichas biográficas</small></div>
  <div class="header-right">
    {{ nav | safe }}
    {% if admin %}<button class="btn btn-primary" onclick="abrirNueva()">+ Añadir persona</button>{% endif %}
    {{ header_usuario | safe }}
  </div>
</header>

<div class="per-hero">
  <h2>🧑‍✈️ Fichas de Personas</h2>
  <p>Catálogo de las personas identificadas en la colección. Pulsa en cualquier ficha para ver todas las fotografías en las que aparece.</p>
</div>

<div class="per-grid">
  {% if personas %}
    {% for p in personas %}
    <div class="per-card" style="position:relative;">
      <a href="/persona/{{ p.id }}" style="text-decoration:none;color:inherit;display:flex;flex-direction:column;align-items:center;gap:.5rem;">
        {% if p.foto_perfil %}<img src="/foto-perfil/{{ p.foto_perfil }}" class="per-avatar">
        {% else %}<div class="per-avatar-vacio">🧑</div>{% endif %}
        <div class="per-nombre">{{ p.nombre }}</div>
        <div class="per-meta">{% if p.rango %}{{ p.rango }}{% endif %}{% if p.unidad %} · {{ p.unidad }}{% endif %}</div>
        <div class="per-count">{{ p.num_fotos }} foto{{ 's' if p.num_fotos != 1 else '' }}</div>
      </a>
      {% if admin %}
      <div style="display:flex;gap:.4rem;margin-top:.7rem;">
        <button class="btn btn-sm btn-edit-pro"
                onclick='event.preventDefault();editarPersona({{ p.id }})'>✏️ Editar</button>
        <button class="btn btn-sm" style="background:var(--rust);color:#fff;"
                onclick='event.preventDefault();confirmarBorrarPersona({{ p.id }},{{ p.nombre|tojson|safe }})'>🗑 Borrar</button>
      </div>
      {% endif %}
    </div>
    {% endfor %}
  {% else %}
  <div class="per-empty"><div style="font-size:3rem;margin-bottom:1rem">🧑‍✈️</div><h3>No hay personas registradas todavía</h3></div>
  {% endif %}
</div>

{% if admin %}
<div class="overlay" id="modal-persona">
  <div class="modal">
    <div class="modal-header"><h2>Nueva persona</h2>
      <button class="btn btn-secondary btn-sm" onclick="cerrarModal('modal-persona')"
              style="color:var(--sepia);border-color:var(--sepia);">✕ Cerrar</button></div>
    <div class="modal-body">
      <form id="form-persona" enctype="multipart/form-data" method="post" action="/guardar-persona">
        <input type="hidden" name="id" id="persona-id">
        <div class="form-grid">
          <div class="form-group span2"><label>Nombre completo *</label><input type="text" name="nombre" required></div>
          <div class="form-group"><label>Rango / Cargo</label><input type="text" name="rango"></div>
          <div class="form-group"><label>Unidad / Regimiento</label><input type="text" name="unidad"></div>
          <div class="form-group"><label>Nacionalidad</label><input type="text" name="nacionalidad"></div>
          <div class="form-group"><label>Fecha de nacimiento</label><input type="date" name="fecha_nac"></div>
          <div class="form-group span2"><label>Fecha de fallecimiento</label><input type="date" name="fecha_fall"></div>
          <div class="form-group span2"><label>Biografía / Notas</label><textarea name="biografia" rows="4"></textarea></div>
          <div class="form-group span2">
  <label>Foto de perfil</label>
  <div class="upload-zone" onclick="document.getElementById('per-archivo').click()">
    <span id="per-upload-text">🧑 Pulsa para seleccionar una foto</span>
  </div>
  <input type="file" id="per-archivo" name="archivo" accept="image/*" style="display:none"
         onchange="document.getElementById('per-upload-text').textContent='📎 '+this.files[0].name;
                   document.getElementById('per-quitar-foto').checked=false;
                   const r=new FileReader(); r.onload=e=>{document.getElementById('per-preview').src=e.target.result;
                   document.getElementById('per-preview').style.display='block';}; r.readAsDataURL(this.files[0]);">
  <img id="per-preview" alt="Vista previa">
  <label id="per-quitar-wrap" style="display:none;flex-direction:row;align-items:center;gap:8px;
         font-size:.82rem;font-weight:400;text-transform:none;letter-spacing:0;color:var(--rust);margin-top:6px;cursor:pointer;">
    <input type="checkbox" id="per-quitar-foto" name="quitar_foto" style="width:auto;">
    🗑 Quitar la foto actual
  </label>
</div>
        </div>
      </form>
    </div>
    <div class="modal-footer">
      <button class="btn btn-secondary" onclick="cerrarModal('modal-persona')">Cancelar</button>
      <button class="btn btn-primary" onclick="document.getElementById('form-persona').submit()">💾 Guardar</button>
    </div>
  </div>
</div>
{% endif %}

<script>
function abrirModal(id){document.getElementById(id).classList.add('open');}
function cerrarModal(id){document.getElementById(id).classList.remove('open');}
document.querySelectorAll('.overlay').forEach(o=>o.addEventListener('click',e=>{if(e.target===o)o.classList.remove('open');}));

function abrirNueva(){
  document.querySelector('.modal-header h2').textContent = 'Nueva persona';
  document.getElementById('form-persona').reset();
  document.getElementById('persona-id').value = '';
  document.getElementById('per-preview').style.display='none';
  document.getElementById('per-upload-text').textContent = '🧑 Pulsa para seleccionar una foto';
  document.getElementById('per-quitar-wrap').style.display = 'none';
  document.getElementById('per-quitar-foto').checked = false;
  abrirModal('modal-persona');
}

function editarPersona(id){
  fetch('/persona-detalle/'+id).then(r=>r.json()).then(p=>{
    document.querySelector('.modal-header h2').textContent = 'Editar persona';
    document.getElementById('persona-id').value = p.id;
    const form = document.getElementById('form-persona');
    form.nombre.value       = p.nombre || '';
    form.rango.value        = p.rango || '';
    form.unidad.value       = p.unidad || '';
    form.nacionalidad.value = p.nacionalidad || '';
    form.fecha_nac.value    = p.fecha_nac || '';
    form.fecha_fall.value   = p.fecha_fall || '';
    form.biografia.value    = p.biografia || '';
    document.getElementById('per-quitar-foto').checked = false;
    if(p.foto_perfil){
      document.getElementById('per-preview').src = '/foto-perfil/'+p.foto_perfil;
      document.getElementById('per-preview').style.display = 'block';
      document.getElementById('per-upload-text').textContent = '📎 Foto actual (sube otra para cambiarla)';
      document.getElementById('per-quitar-wrap').style.display = 'flex';
    } else {
      document.getElementById('per-preview').style.display = 'none';
      document.getElementById('per-upload-text').textContent = '🧑 Pulsa para seleccionar una foto';
      document.getElementById('per-quitar-wrap').style.display = 'none';
    }
    abrirModal('modal-persona');
  });
}

function confirmarBorrarPersona(id, nombre){
  if(confirm('¿Seguro que quieres borrar la ficha de «'+nombre+'»?\\nSe eliminará también su vínculo con todas las fotos.'))
    fetch('/borrar-persona/'+id,{method:'POST'}).then(()=>location.reload());
}
</script>
</body></html>
"""

HTML_PERSONA_DETALLE = """
<!DOCTYPE html><html lang="es"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{{ persona.nombre }} · Archivo Rommel</title>
""" + CSS_BASE + """
<style>
.pd-hero{max-width:900px;margin:0 auto;padding:2rem 1.5rem;display:flex;gap:1.5rem;align-items:center;flex-wrap:wrap;}
.pd-avatar{width:120px;height:120px;border-radius:50%;object-fit:cover;border:4px solid var(--tan);}
.pd-avatar-vacio{width:120px;height:120px;border-radius:50%;background:var(--sepia);border:4px solid var(--border);
                 display:flex;align-items:center;justify-content:center;font-size:3rem;color:var(--tan);}
.pd-nombre{font-family:'Playfair Display',serif;font-size:1.8rem;color:var(--ink);}
.pd-meta{font-size:.88rem;color:var(--muted);margin-top:.4rem;line-height:1.6;}
.pd-bio{max-width:900px;margin:0 auto 1.5rem;padding:0 1.5rem;font-size:.95rem;line-height:1.7;color:var(--ink);white-space:pre-wrap;}
.pd-fotos-title{max-width:900px;margin:0 auto;padding:0 1.5rem;font-family:'Playfair Display',serif;color:var(--brown);}
.foto-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:6px;padding:1.5rem;max-width:900px;margin:0 auto;}
.foto-pura{position:relative;aspect-ratio:1/1;overflow:hidden;cursor:pointer;background:var(--sepia);border-radius:4px;}
.foto-pura img{width:100%;height:100%;object-fit:cover;display:block;transition:transform .2s;}
.foto-pura:hover img{transform:scale(1.05);}
.detail-img{width:100%;max-height:400px;object-fit:contain;background:var(--sepia);border-radius:4px;}
.detail-field{display:flex;flex-direction:column;gap:.2rem;}
.detail-field .lbl{font-size:.75rem;font-weight:600;color:var(--tan);text-transform:uppercase;letter-spacing:.05em;}
.detail-field .val{font-size:.95rem;color:var(--ink);}

/* ── Trayectoria / Condecoraciones ── */
.pd-hitos-title{max-width:900px;margin:1.8rem auto 0;padding:0 1.5rem;display:flex;
  align-items:center;justify-content:space-between;gap:1rem;flex-wrap:wrap;}
.pd-hitos-title h3{font-family:'Playfair Display',serif;color:var(--brown);font-size:1.25rem;}
.hitos-timeline{max-width:900px;margin:.6rem auto 0;padding:0 1.5rem 1rem;}
.hito-item{display:grid;grid-template-columns:150px 24px 1fr;gap:0 .9rem;position:relative;}
.hito-fecha{font-size:.82rem;color:var(--muted);padding:.55rem 0;text-align:right;white-space:nowrap;
  overflow:hidden;text-overflow:ellipsis;}
.hito-linea{position:relative;display:flex;justify-content:center;}
.hito-linea::before{content:'';position:absolute;top:0;bottom:0;width:2px;background:var(--border);}
.hito-item:first-child .hito-linea::before{top:1rem;}
.hito-item:last-child .hito-linea::before{bottom:calc(100% - 1.6rem);}
.hito-punto{width:12px;height:12px;border-radius:50%;background:var(--rust);border:2px solid var(--paper);
  margin-top:.85rem;position:relative;z-index:1;flex-shrink:0;}
.hito-cont{padding:.55rem 0 .9rem;}
.hito-titulo{font-weight:600;color:var(--ink);font-size:.95rem;}
.hito-detalle{font-size:.83rem;color:var(--muted);line-height:1.5;margin-top:.2rem;white-space:pre-wrap;}
.hito-acciones{display:flex;gap:.35rem;margin-top:.4rem;}
.hito-acciones button{background:none;border:1px solid var(--border);border-radius:4px;
  cursor:pointer;font-size:.72rem;padding:.15rem .45rem;color:var(--muted);}
.hito-acciones button:hover{background:var(--sepia);color:var(--ink);}
.hitos-empty{color:var(--muted);font-size:.85rem;font-style:italic;padding:.6rem 0 1rem;}
@media (max-width:600px){
  .hito-item{grid-template-columns:70px 20px 1fr;}
  .hito-fecha{font-size:.72rem;text-align:left;}
}
</style>
</head><body>
<header>
  <div><h1>Ficha de persona</h1></div>
  <div class="header-right">{{ nav | safe }}{{ header_usuario | safe }}</div>
</header>

<div class="pd-hero">
  {% if persona.foto_perfil %}<img src="/foto-perfil/{{ persona.foto_perfil }}" class="pd-avatar">
  {% else %}<div class="pd-avatar-vacio">🧑</div>{% endif %}
  <div>
    <div class="pd-nombre">{{ persona.nombre }}</div>
    <div class="pd-meta">
      {% if persona.rango %}⚔️ {{ persona.rango }}<br>{% endif %}
      {% if persona.unidad %}🎖 {{ persona.unidad }}<br>{% endif %}
      {% if persona.nacionalidad %}🏳 {{ persona.nacionalidad }}<br>{% endif %}
      {% if persona.fecha_nac %}📅 {{ persona.fecha_nac }}{% if persona.fecha_fall %} — {{ persona.fecha_fall }}{% endif %}{% endif %}
    </div>
  </div>
</div>
{% if persona.biografia %}<div class="pd-bio">{{ persona.biografia }}</div>{% endif %}

<div class="pd-hitos-title">
  <h3>⚔️ Trayectoria y ascensos</h3>
  {% if admin %}<button class="btn btn-sm btn-primary" onclick="abrirNuevoHito('ascenso')">+ Añadir ascenso</button>{% endif %}
</div>
<div class="hitos-timeline">
  {% for h in ascensos %}
  <div class="hito-item">
    <div class="hito-fecha">{{ h.fecha or '—' }}</div>
    <div class="hito-linea"><div class="hito-punto"></div></div>
    <div class="hito-cont">
      <div class="hito-titulo">{{ h.titulo }}</div>
      {% if h.detalle %}<div class="hito-detalle">{{ h.detalle }}</div>{% endif %}
      {% if admin %}
      <div class="hito-acciones">
        <button onclick="moverHito({{ h.id }},'up')" title="Subir">↑</button>
        <button onclick="moverHito({{ h.id }},'down')" title="Bajar">↓</button>
        <button onclick="editarHito({{ h.id }})" title="Editar">✏️</button>
        <button onclick="borrarHito({{ h.id }},'{{ h.titulo|replace("'","\\'")|safe }}')" title="Borrar">🗑</button>
      </div>
      {% endif %}
    </div>
  </div>
  {% else %}
  <div class="hitos-empty">Todavía no hay ascensos registrados.</div>
  {% endfor %}
</div>

<div class="pd-hitos-title">
  <h3>🎖 Condecoraciones</h3>
  {% if admin %}<button class="btn btn-sm btn-primary" onclick="abrirNuevoHito('condecoracion')">+ Añadir condecoración</button>{% endif %}
</div>
<div class="hitos-timeline">
  {% for h in condecoraciones %}
  <div class="hito-item">
    <div class="hito-fecha">{{ h.fecha or '—' }}</div>
    <div class="hito-linea"><div class="hito-punto"></div></div>
    <div class="hito-cont">
      <div class="hito-titulo">{{ h.titulo }}</div>
      {% if h.detalle %}<div class="hito-detalle">{{ h.detalle }}</div>{% endif %}
      {% if admin %}
      <div class="hito-acciones">
        <button onclick="moverHito({{ h.id }},'up')" title="Subir">↑</button>
        <button onclick="moverHito({{ h.id }},'down')" title="Bajar">↓</button>
        <button onclick="editarHito({{ h.id }})" title="Editar">✏️</button>
        <button onclick="borrarHito({{ h.id }},'{{ h.titulo|replace("'","\\'")|safe }}')" title="Borrar">🗑</button>
      </div>
      {% endif %}
    </div>
  </div>
  {% else %}
  <div class="hitos-empty">Todavía no hay condecoraciones registradas.</div>
  {% endfor %}
</div>

{% if admin %}
<!-- MODAL AÑADIR/EDITAR HITO -->
<div class="overlay" id="modal-hito">
  <div class="modal" style="max-width:560px;">
    <div class="modal-header">
      <h2 id="hito-modal-title">Nuevo ascenso</h2>
      <button class="btn btn-secondary btn-sm" onclick="cerrarModal('modal-hito')"
              style="color:var(--sepia);border-color:var(--sepia);">✕ Cerrar</button>
    </div>
    <div class="modal-body">
      <div class="form-grid">
        <div class="form-group span2">
          <label id="hito-lbl-titulo">Rango / grado *</label>
          <input type="text" id="h-titulo" placeholder="ej. Generalfeldmarschall">
        </div>
        <div class="form-group span2">
          <label>Fecha</label>
          <input type="text" id="h-fecha" placeholder="ej. 22 de junio de 1942">
          <div class="form-hint">Puedes escribirla como quieras (con patente, aproximada, etc.)</div>
        </div>
        <div class="form-group span2">
          <label>Detalle / notas</label>
          <textarea id="h-detalle" rows="3"
            placeholder="ej. Con Generalmajor y Comandante de la 7. Panzer-Division"></textarea>
        </div>
      </div>
      <input type="hidden" id="h-id">
      <input type="hidden" id="h-tipo">
      <input type="hidden" id="h-persona-id" value="{{ persona.id }}">
    </div>
    <div class="modal-footer">
      <button class="btn btn-secondary" onclick="cerrarModal('modal-hito')">Cancelar</button>
      <button class="btn btn-primary" onclick="guardarHito()">💾 Guardar</button>
    </div>
  </div>
</div>
{% endif %}

<div class="pd-fotos-title"><h3>📸 Fotografías ({{ fotos|length }})</h3></div>
<div class="foto-grid">
  {% for f in fotos %}
  <div class="foto-pura" onclick="verDetalle({{ f.id }})">
    {% if f.archivo %}<img src="/foto/{{ f.archivo }}" alt="{{ f.titulo }}">{% else %}📷{% endif %}
  </div>
  {% endfor %}
</div>

""" + MODAL_DETALLE_HTML + """
<div class="toast" id="toast"></div>
<script>
function abrirModal(id){document.getElementById(id).classList.add('open');}
function cerrarModal(id){document.getElementById(id).classList.remove('open');}
document.querySelectorAll('.overlay').forEach(o=>o.addEventListener('click',e=>{if(e.target===o)o.classList.remove('open');}));
function editarFoto(){}

function mostrarToast(msg, dur=2800){
  const t=document.getElementById('toast');
  t.textContent=msg; t.classList.add('show');
  clearTimeout(t._timer);
  t._timer=setTimeout(()=>t.classList.remove('show'), dur);
}

/* ── Hitos: ascensos y condecoraciones ── */
function abrirNuevoHito(tipo){
  document.getElementById('hito-modal-title').textContent = tipo === 'condecoracion' ? 'Nueva condecoración' : 'Nuevo ascenso';
  document.getElementById('hito-lbl-titulo').textContent = tipo === 'condecoracion' ? 'Nombre de la condecoración *' : 'Rango / grado *';
  document.getElementById('h-titulo').placeholder = tipo === 'condecoracion' ? 'ej. Cruz de Caballero de la Cruz de Hierro' : 'ej. Generalfeldmarschall';
  document.getElementById('h-id').value = '';
  document.getElementById('h-tipo').value = tipo;
  document.getElementById('h-titulo').value = '';
  document.getElementById('h-fecha').value = '';
  document.getElementById('h-detalle').value = '';
  abrirModal('modal-hito');
}

function editarHito(id){
  fetch('/hito-detalle/'+id).then(r=>r.json()).then(h=>{
    document.getElementById('hito-modal-title').textContent = h.tipo === 'condecoracion' ? 'Editar condecoración' : 'Editar ascenso';
    document.getElementById('hito-lbl-titulo').textContent = h.tipo === 'condecoracion' ? 'Nombre de la condecoración *' : 'Rango / grado *';
    document.getElementById('h-id').value      = h.id;
    document.getElementById('h-tipo').value    = h.tipo;
    document.getElementById('h-titulo').value  = h.titulo || '';
    document.getElementById('h-fecha').value   = h.fecha || '';
    document.getElementById('h-detalle').value = h.detalle || '';
    abrirModal('modal-hito');
  });
}

function guardarHito(){
  const titulo = document.getElementById('h-titulo').value.trim();
  if(!titulo){ alert('Este campo es obligatorio.'); return; }
  const payload = {
    id:         document.getElementById('h-id').value,
    persona_id: document.getElementById('h-persona-id').value,
    tipo:       document.getElementById('h-tipo').value,
    titulo:     titulo,
    fecha:      document.getElementById('h-fecha').value,
    detalle:    document.getElementById('h-detalle').value,
  };
  fetch('/guardar-hito', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify(payload)
  }).then(r=>r.json()).then(d=>{
    if(d.ok){ location.reload(); }
    else mostrarToast('⚠️ Error al guardar');
  });
}

function borrarHito(id, titulo){
  if(!confirm('¿Borrar «'+titulo+'»?')) return;
  fetch('/borrar-hito/'+id, {method:'POST'}).then(r=>r.json()).then(d=>{
    if(d.ok) location.reload();
    else mostrarToast('⚠️ Error al borrar');
  });
}

function moverHito(id, direccion){
  fetch('/mover-hito/'+id+'/'+direccion, {method:'POST'}).then(r=>r.json()).then(d=>{
    if(d.ok) location.reload();
    else mostrarToast('⚠️ Error al reordenar');
  });
}
""" + SCRIPT_DETALLE + """
</script>
</body></html>
"""

HTML_BIBLIOGRAFIA = """
<!DOCTYPE html><html lang="es"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Bibliografía · IIGM</title>
""" + CSS_BASE + """
<style>
.bib-hero{padding:2rem 1.5rem 1.2rem;background:var(--sepia);border-bottom:1px solid var(--border);}
.bib-hero h2{font-family:'Playfair Display',serif;font-size:1.6rem;color:var(--brown);margin-bottom:.3rem;}
.bib-hero p{font-size:.88rem;color:var(--muted);max-width:700px;line-height:1.6;}

/* ── Filtros ── */
.bib-filtros{display:flex;gap:.6rem;padding:1rem 1.5rem;background:var(--paper);
             border-bottom:1px solid var(--border);flex-wrap:wrap;align-items:center;}
.bib-filtros select,.bib-filtros input{padding:.45rem .75rem;border:1px solid var(--border);
  border-radius:4px;font-family:inherit;font-size:.82rem;background:#fff;color:var(--ink);}
.bib-filtros input{flex:1;min-width:180px;}
.bib-filtros select{min-width:140px;}

/* ── Grid de tarjetas ── */
.bib-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));
          gap:1.25rem;padding:1.5rem;}
.bib-card{background:#fff;border:1px solid var(--border);border-radius:8px;
          overflow:hidden;box-shadow:var(--shadow);display:flex;flex-direction:column;
          transition:box-shadow .15s,transform .15s;}
.bib-card:hover{box-shadow:0 4px 18px rgba(26,20,16,.12);transform:translateY(-2px);}
.bib-card-top{padding:1rem 1.1rem .7rem;flex:1;}
.bib-tipo-badge{display:inline-block;font-size:.65rem;font-weight:700;padding:2px 8px;
  border-radius:99px;text-transform:uppercase;letter-spacing:.06em;margin-bottom:.6rem;}
.tipo-web       {background:#e8f0fe;color:#3a5bba;}
.tipo-libro     {background:#fce8d5;color:#9b4a10;}
.tipo-archivo   {background:#e8f5e9;color:#2e6b35;}
.tipo-foro      {background:#f3e8fe;color:#6b3aaa;}
.tipo-documental{background:#fef9e8;color:#8a7020;}
.tipo-revista   {background:#fde8ee;color:#aa3a60;}
.tipo-otro      {background:#f0f0f0;color:#555;}
.bib-titulo{font-family:'Playfair Display',serif;font-size:1.05rem;font-weight:600;
            line-height:1.35;color:var(--ink);margin-bottom:.3rem;}
.bib-autor{font-size:.78rem;color:var(--muted);margin-bottom:.5rem;font-style:italic;}
.bib-desc{font-size:.83rem;color:var(--muted);line-height:1.55;
          display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;}
.bib-card-footer{padding:.65rem 1.1rem;border-top:1px solid var(--border);
                 background:var(--paper);display:flex;align-items:center;
                 justify-content:space-between;gap:.5rem;flex-wrap:wrap;}
.bib-meta-pills{display:flex;gap:.4rem;flex-wrap:wrap;}
.bib-pill{font-size:.67rem;padding:2px 8px;border-radius:99px;background:var(--sepia);
          color:var(--brown);border:1px solid var(--border);white-space:nowrap;}
.bib-actions{display:flex;gap:.4rem;align-items:center;}
.bib-link{display:inline-flex;align-items:center;gap:.3rem;font-size:.78rem;font-weight:600;
          color:var(--rust);text-decoration:none;padding:.3rem .6rem;border-radius:4px;
          border:1px solid rgba(139,58,42,.3);transition:background .15s;}
.bib-link:hover{background:rgba(139,58,42,.08);}

/* ── Fiabilidad (estrellas) ── */
.estrellas{display:flex;gap:1px;}
.estrella{font-size:.85rem;line-height:1;}

/* ── Contador por tipo ── */
.bib-stats{display:flex;gap:1.5rem;padding:.75rem 1.5rem;background:var(--sepia);
           border-bottom:1px solid var(--border);flex-wrap:wrap;overflow-x:auto;}
.stat-chip{display:flex;align-items:center;gap:.4rem;font-size:.78rem;color:var(--muted);white-space:nowrap;}
.stat-chip strong{color:var(--ink);}

/* ── Modal ── */
.form-hint{font-size:.75rem;color:var(--muted);margin-top:.25rem;}
.star-select{display:flex;gap:.4rem;align-items:center;margin-top:.3rem;}
.star-btn{font-size:1.3rem;background:none;border:none;cursor:pointer;opacity:.35;transition:opacity .15s;}
.star-btn.on{opacity:1;}

/* ── Vacío ── */
.bib-empty{grid-column:1/-1;text-align:center;padding:5rem 2rem;color:var(--muted);}
.bib-empty div{font-size:3rem;margin-bottom:1rem;}
</style>
</head><body>

<header>
  <div><h1>Bibliografía</h1><small>{{ total }} fuentes registradas</small></div>
  <div class="header-right">
    {{ nav | safe }}
    {% if admin %}<button class="btn btn-primary" onclick="abrirNueva()">+ Añadir fuente</button>{% endif %}
    {{ header_usuario | safe }}
  </div>
</header>

<div class="bib-hero">
  <h2>📚 Fuentes y Referencias</h2>
  <p>Repositorio de todas las fuentes consultadas: archivos, webs, libros, foros y documentales.
     Cada entrada recoge el origen, el enlace y una valoración de fiabilidad.</p>
</div>

<div class="bib-stats">
  {% for tipo, cnt in stats.items() %}
  <div class="stat-chip">
    <span class="bib-tipo-badge tipo-{{ tipo|lower|replace(' ','') }}" style="margin:0">{{ tipo }}</span>
    <strong>{{ cnt }}</strong>
  </div>
  {% endfor %}
</div>

<div class="bib-filtros">
  <input type="text" id="filtro-texto" placeholder="Buscar por título, autor, descripción…"
         oninput="filtrar()">
  <select id="filtro-tipo" onchange="filtrar()">
    <option value="">— Todos los tipos —</option>
    <option value="Web">🌐 Web / Sitio</option>
    <option value="Libro">📖 Libro</option>
    <option value="Archivo">🗂 Archivo histórico</option>
    <option value="Foro">💬 Foro / Comunidad</option>
    <option value="Documental">🎬 Documental</option>
    <option value="Revista">📰 Revista / Artículo</option>
    <option value="Otro">📌 Otro</option>
  </select>
  <select id="filtro-pais" onchange="filtrar()">
    <option value="">— Todos los países —</option>
    {% for p in paises %}<option value="{{ p }}">{{ p }}</option>{% endfor %}
  </select>
  <select id="filtro-fid" onchange="filtrar()">
    <option value="">— Cualquier fiabilidad —</option>
    <option value="5">★★★★★ Excelente</option>
    <option value="4">★★★★ Buena</option>
    <option value="3">★★★ Media</option>
    <option value="2">★★ Baja</option>
    <option value="1">★ Muy baja</option>
  </select>
</div>

<div class="bib-grid" id="bib-grid">
  {% if fuentes %}
    {% for f in fuentes %}
    <div class="bib-card"
         data-tipo="{{ f.tipo or '' }}"
         data-pais="{{ f.pais or '' }}"
         data-fid="{{ f.fiabilidad or 3 }}"
         data-texto="{{ (f.titulo + ' ' + (f.autor or '') + ' ' + (f.descripcion or ''))|lower }}">

      <div class="bib-card-top">
        <div>
          <span class="bib-tipo-badge tipo-{{ (f.tipo or 'otro')|lower|replace(' ','') }}">
            {% if f.tipo == 'Web' %}🌐
            {% elif f.tipo == 'Libro' %}📖
            {% elif f.tipo == 'Archivo' %}🗂
            {% elif f.tipo == 'Foro' %}💬
            {% elif f.tipo == 'Documental' %}🎬
            {% elif f.tipo == 'Revista' %}📰
            {% else %}📌{% endif %}
            {{ f.tipo or 'Otro' }}
          </span>
        </div>
        <div class="bib-titulo">{{ f.titulo }}</div>
        {% if f.autor %}<div class="bib-autor">{{ f.autor }}</div>{% endif %}
        {% if f.descripcion %}<div class="bib-desc">{{ f.descripcion }}</div>{% endif %}
      </div>

      <div class="bib-card-footer">
        <div class="bib-meta-pills">
          {% if f.pais %}<span class="bib-pill">🏳 {{ f.pais }}</span>{% endif %}
          {% if f.idioma %}<span class="bib-pill">🗣 {{ f.idioma }}</span>{% endif %}
          <span class="bib-pill estrellas" title="Fiabilidad">
            {% for i in range(1,6) %}
            <span class="estrella">{{ '★' if i <= (f.fiabilidad or 3) else '☆' }}</span>
            {% endfor %}
          </span>
        </div>
        <div class="bib-actions">
          {% if f.enlace %}
          <a href="{{ f.enlace }}" target="_blank" rel="noopener" class="bib-link">
            🔗 Abrir
          </a>
          {% endif %}
          {% if admin %}
          <button class="btn btn-sm btn-edit-pro" onclick="editarFuente({{ f.id }})">✏️</button>
          <button class="btn btn-sm" style="background:var(--rust);color:#fff;padding:.3rem .5rem;"
                  onclick="borrarFuente({{ f.id }},'{{ f.titulo|replace("'","\\'")|safe }}')">🗑</button>
          {% endif %}
        </div>
      </div>
    </div>
    {% endfor %}
  {% else %}
  <div class="bib-empty">
    <div>📚</div>
    <h3>Sin fuentes todavía</h3>
    {% if admin %}<p style="margin-top:.5rem;font-size:.9rem">Pulsa "+ Añadir fuente" para registrar la primera referencia.</p>{% endif %}
  </div>
  {% endif %}
</div>

{% if admin %}
<!-- MODAL AÑADIR/EDITAR -->
<div class="overlay" id="modal-bib">
  <div class="modal" style="max-width:640px;">
    <div class="modal-header">
      <h2 id="bib-modal-title">Nueva fuente</h2>
      <button class="btn btn-secondary btn-sm" onclick="cerrarModal('modal-bib')"
              style="color:var(--sepia);border-color:var(--sepia);">✕ Cerrar</button>
    </div>
    <div class="modal-body">
      <div class="form-grid">
        <div class="form-group span2">
          <label>Título / Nombre de la fuente *</label>
          <input type="text" id="b-titulo" placeholder="ej. Bundesarchiv — Militärarchiv">
        </div>
        <div class="form-group">
          <label>Tipo</label>
          <select id="b-tipo">
            <option value="Web">🌐 Web / Sitio</option>
            <option value="Libro">📖 Libro</option>
            <option value="Archivo">🗂 Archivo histórico</option>
            <option value="Foro">💬 Foro / Comunidad</option>
            <option value="Documental">🎬 Documental</option>
            <option value="Revista">📰 Revista / Artículo</option>
            <option value="Otro">📌 Otro</option>
          </select>
        </div>
        <div class="form-group">
          <label>País de origen</label>
          <input type="text" id="b-pais" placeholder="ej. Alemania" list="b-paises-list">
          <datalist id="b-paises-list">
            {% for p in paises %}<option value="{{ p }}">{% endfor %}
          </datalist>
        </div>
        <div class="form-group span2">
          <label>Enlace / URL</label>
          <input type="url" id="b-enlace" placeholder="https://…">
          <div class="form-hint">Deja en blanco si no tiene versión online (libro físico, etc.)</div>
        </div>
        <div class="form-group">
          <label>Autor / Institución</label>
          <input type="text" id="b-autor" placeholder="ej. Bundesarchiv / Karl-Heinz Frieser">
        </div>
        <div class="form-group">
          <label>Idioma principal</label>
          <input type="text" id="b-idioma" placeholder="ej. Alemán" list="b-idiomas-list">
          <datalist id="b-idiomas-list">
            <option value="Español"><option value="Alemán"><option value="Inglés">
            <option value="Francés"><option value="Italiano"><option value="Ruso">
          </datalist>
        </div>
        <div class="form-group span2">
          <label>Fiabilidad</label>
          <div class="star-select" id="star-select">
            <button type="button" class="star-btn" data-v="1" onclick="setFiabilidad(1)">★</button>
            <button type="button" class="star-btn" data-v="2" onclick="setFiabilidad(2)">★</button>
            <button type="button" class="star-btn" data-v="3" onclick="setFiabilidad(3)">★</button>
            <button type="button" class="star-btn" data-v="4" onclick="setFiabilidad(4)">★</button>
            <button type="button" class="star-btn" data-v="5" onclick="setFiabilidad(5)">★</button>
          </div>
          <div class="form-hint" id="fid-hint">3 — Fiabilidad media</div>
          <input type="hidden" id="b-fiabilidad" value="3">
        </div>
        <div class="form-group span2">
          <label>Descripción / Notas</label>
          <textarea id="b-descripcion" rows="3"
            placeholder="Qué tipo de documentación ofrece, en qué investigaciones la usé, observaciones sobre su fiabilidad…"></textarea>
        </div>
      </div>
      <input type="hidden" id="b-id">
    </div>
    <div class="modal-footer">
      <button class="btn btn-secondary" onclick="cerrarModal('modal-bib')">Cancelar</button>
      <button class="btn btn-primary" onclick="guardarFuente()">💾 Guardar</button>
    </div>
  </div>
</div>
{% endif %}

<div class="toast" id="toast"></div>

<script>
function abrirModal(id){document.getElementById(id).classList.add('open');}
function cerrarModal(id){document.getElementById(id).classList.remove('open');}
document.querySelectorAll('.overlay').forEach(o=>o.addEventListener('click',e=>{if(e.target===o)o.classList.remove('open');}));

/* ── Filtro en tiempo real ── */
function filtrar(){
  const txt  = document.getElementById('filtro-texto').value.toLowerCase();
  const tipo = document.getElementById('filtro-tipo').value;
  const pais = document.getElementById('filtro-pais').value;
  const fid  = parseInt(document.getElementById('filtro-fid').value||'0');
  let visible = 0;
  document.querySelectorAll('.bib-card').forEach(c => {
    const ok = (!txt  || c.dataset.texto.includes(txt))
            && (!tipo || c.dataset.tipo === tipo)
            && (!pais || c.dataset.pais === pais)
            && (!fid  || parseInt(c.dataset.fid) >= fid);
    c.style.display = ok ? '' : 'none';
    if(ok) visible++;
  });
  // Mostrar mensaje vacío si no hay resultados
  let emptyEl = document.getElementById('bib-no-result');
  if(!emptyEl){
    emptyEl = document.createElement('div');
    emptyEl.id = 'bib-no-result';
    emptyEl.className = 'bib-empty';
    emptyEl.innerHTML = '<div>🔍</div><h3>Sin resultados para este filtro</h3>';
    document.getElementById('bib-grid').appendChild(emptyEl);
  }
  emptyEl.style.display = (visible === 0) ? '' : 'none';
}

{% if admin %}
const FID_LABELS = ['','★ Muy baja','★★ Baja','★★★ Media','★★★★ Buena','★★★★★ Excelente'];
let fiabilidadActual = 3;

function setFiabilidad(v){
  fiabilidadActual = v;
  document.getElementById('b-fiabilidad').value = v;
  document.getElementById('fid-hint').textContent = v + ' — ' + FID_LABELS[v];
  document.querySelectorAll('.star-btn').forEach(b => {
    b.classList.toggle('on', parseInt(b.dataset.v) <= v);
  });
}
setFiabilidad(3); // default

function abrirNueva(){
  document.getElementById('bib-modal-title').textContent = 'Nueva fuente';
  document.getElementById('b-id').value = '';
  ['b-titulo','b-autor','b-pais','b-enlace','b-idioma','b-descripcion'].forEach(id=>{
    document.getElementById(id).value='';
  });
  document.getElementById('b-tipo').value = 'Web';
  setFiabilidad(3);
  abrirModal('modal-bib');
}

function editarFuente(id){
  fetch('/bibliografia-detalle/'+id).then(r=>r.json()).then(f=>{
    document.getElementById('bib-modal-title').textContent = 'Editar fuente';
    document.getElementById('b-id').value      = f.id;
    document.getElementById('b-titulo').value  = f.titulo || '';
    document.getElementById('b-tipo').value    = f.tipo   || 'Web';
    document.getElementById('b-autor').value   = f.autor  || '';
    document.getElementById('b-pais').value    = f.pais   || '';
    document.getElementById('b-enlace').value  = f.enlace || '';
    document.getElementById('b-idioma').value  = f.idioma || '';
    document.getElementById('b-descripcion').value = f.descripcion || '';
    setFiabilidad(f.fiabilidad || 3);
    abrirModal('modal-bib');
  });
}

function guardarFuente(){
  const titulo = document.getElementById('b-titulo').value.trim();
  if(!titulo){ alert('El título es obligatorio.'); return; }
  const payload = {
    id:          document.getElementById('b-id').value,
    titulo:      titulo,
    tipo:        document.getElementById('b-tipo').value,
    autor:       document.getElementById('b-autor').value,
    pais:        document.getElementById('b-pais').value,
    enlace:      document.getElementById('b-enlace').value,
    idioma:      document.getElementById('b-idioma').value,
    descripcion: document.getElementById('b-descripcion').value,
    fiabilidad:  parseInt(document.getElementById('b-fiabilidad').value),
  };
  fetch('/guardar-fuente', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify(payload)
  }).then(r=>r.json()).then(d=>{
    if(d.ok){ location.reload(); }
    else mostrarToast('⚠️ Error al guardar');
  });
}

function borrarFuente(id, titulo){
  if(!confirm('¿Borrar la fuente «'+titulo+'»?')) return;
  fetch('/borrar-fuente/'+id,{method:'POST'}).then(r=>r.json()).then(d=>{
    if(d.ok) location.reload();
    else mostrarToast('⚠️ Error al borrar');
  });
}
{% endif %}

function mostrarToast(msg, dur=2800){
  const t=document.getElementById('toast');
  t.textContent=msg; t.classList.add('show');
  clearTimeout(t._timer);
  t._timer=setTimeout(()=>t.classList.remove('show'), dur);
}
</script>
</body></html>
"""


# ══════════════════════════════════════════════════════════════════════════════
# RUTAS: BLOG
# ══════════════════════════════════════════════════════════════════════════════
@app.route("/blog")
@login_requerido
def blog():
    abrir_id = request.args.get("abrir", "").strip()
    db            = get_db()
    articulos_raw = db.execute("SELECT * FROM articulos").fetchall()
    todas_fotos   = db.execute("SELECT id,titulo,archivo,fecha_foto FROM fotografias ORDER BY fecha_foto ASC,id ASC").fetchall()
    articulos = []
    for art in articulos_raw:
        d = dict(art)
        fotos_v = db.execute("""SELECT f.id,f.archivo,f.titulo,f.fecha_foto FROM fotografias f
            JOIN articulos_fotografias af ON af.fotografia_id=f.id WHERE af.articulo_id=?""",
            (art["id"],)).fetchall()
        d["fotos"]      = fotos_v
        d["fotos_ids"]  = [f["id"] for f in fotos_v]
        fechas = [f["fecha_foto"] for f in fotos_v if f["fecha_foto"]]
        d["fecha_historica"] = min(fechas) if fechas else ""
        articulos.append(d)
    articulos.sort(key=lambda a: a["fecha_historica"] or "9999-99-99")

    grupos = defaultdict(list)
    for art in articulos:
        anio = art["fecha_historica"][:4] if art["fecha_historica"] else "Sin fecha"
        grupos[anio].append(art)
    anios_con_fecha = sorted([a for a in grupos if a != "Sin fecha"], reverse=True)
    anios_ordenados = anios_con_fecha + (["Sin fecha"] if "Sin fecha" in grupos else [])
    archivo_anios = [{"anio": a, "articulos": grupos[a]} for a in anios_ordenados]

    db.close()
    return render_template_string(HTML_BLOG, archivo_anios=archivo_anios, todas_fotos=todas_fotos,
        abrir_id=abrir_id,
        admin=es_admin(), header_usuario=header_usuario(), nav=nav("blog"))
@app.route("/guardar-blog", methods=["POST"])
@login_requerido
@solo_admin
def guardar_blog():
    f  = request.form
    db = get_db()
    bid = f.get("id")
    if bid:
        db.execute("UPDATE articulos SET titulo=?,contenido=? WHERE id=?",
                   (f["titulo_blog"], f["contenido_blog"], bid))
        db.execute("DELETE FROM articulos_fotografias WHERE articulo_id=?", (bid,))
        art_id = bid
    else:
        cur = db.execute("INSERT INTO articulos (titulo,contenido,fecha_pub) VALUES (?,?,?)",
                         (f["titulo_blog"],f["contenido_blog"],datetime.now().strftime("%d/%m/%Y")))
        art_id = cur.lastrowid
    for fid in request.form.getlist("fotos_ids"):
        db.execute("INSERT OR IGNORE INTO articulos_fotografias (articulo_id,fotografia_id) VALUES (?,?)",
                   (art_id, fid))
    db.commit(); db.close()
    return redirect(url_for("blog"))

@app.route("/borrar-blog/<int:id>", methods=["POST"])
@login_requerido
@solo_admin
def borrar_blog(id):
    db = get_db()
    db.execute("DELETE FROM articulos WHERE id=?", (id,))
    db.commit(); db.close()
    return redirect(url_for("blog"))
# ══════════════════════════════════════════════════════════════════════════════
# RUTAS: INVESTIGACIÓN (PDFs)
# ══════════════════════════════════════════════════════════════════════════════
@app.route("/investigacion")
@login_requerido
def investigacion():
    db = get_db()
    q = request.args.get("q","").strip()
    cat_sel = request.args.get("categoria","").strip()
    query = "SELECT * FROM investigacion WHERE 1=1"
    params = []
    if q:
        query  += " AND (titulo LIKE ? OR descripcion LIKE ? OR autor LIKE ?)"
        params += [f"%{q}%"] * 3
    if cat_sel:
        query += " AND categoria=?"; params.append(cat_sel)
    query += " ORDER BY fecha_doc DESC, id DESC"
    docs  = db.execute(query, params).fetchall()
    total = db.execute("SELECT COUNT(*) FROM investigacion").fetchone()[0]
    categorias = [r[0] for r in db.execute(
        "SELECT DISTINCT categoria FROM investigacion WHERE categoria IS NOT NULL AND categoria!='' ORDER BY categoria"
    ).fetchall()]
    db.close()
    return render_template_string(HTML_INVESTIGACION, docs=docs, total=total, q=q,
        categorias=categorias, cat_sel=cat_sel,
        admin=es_admin(), header_usuario=header_usuario(), nav=nav("investigacion"))

@app.route("/guardar-pdf", methods=["POST"])
@login_requerido
@solo_admin
def guardar_pdf():
    f  = request.form
    db = get_db()
    archivo = None
    tipo    = None
    if "archivo" in request.files:
        file = request.files["archivo"]
        if file.filename and allowed_investigacion(file.filename):
            archivo = secure_filename(file.filename)
            tipo    = tipo_investigacion(archivo)
            file.save(os.path.join(app.config["PDFS_FOLDER"], archivo))
    if f.get("id"):
        if archivo:
            db.execute("""UPDATE investigacion SET titulo=?,categoria=?,autor=?,fecha_doc=?,descripcion=?,
                          archivo=?,tipo_archivo=?,periodico=?,pagina=? WHERE id=?""",
                       (f["titulo"],f.get("categoria"),f.get("autor"),f.get("fecha_doc"),f.get("descripcion"),
                        archivo,tipo,f.get("periodico"),f.get("pagina"),f["id"]))
        else:
            db.execute("""UPDATE investigacion SET titulo=?,categoria=?,autor=?,fecha_doc=?,descripcion=?,
                          periodico=?,pagina=? WHERE id=?""",
                       (f["titulo"],f.get("categoria"),f.get("autor"),f.get("fecha_doc"),f.get("descripcion"),
                        f.get("periodico"),f.get("pagina"),f["id"]))
    else:
        db.execute("""INSERT INTO investigacion (titulo,categoria,autor,fecha_doc,descripcion,archivo,
                      tipo_archivo,periodico,pagina,fecha_alta)
                      VALUES (?,?,?,?,?,?,?,?,?,?)""",
                   (f["titulo"],f.get("categoria"),f.get("autor"),f.get("fecha_doc"),f.get("descripcion"),
                    archivo,tipo or "pdf",f.get("periodico"),f.get("pagina"),
                    datetime.now().strftime("%Y-%m-%d")))
    db.commit(); db.close()
    return redirect(url_for("investigacion"))

@app.route("/pdf/<filename>")
@login_requerido
def servir_pdf(filename):
    return send_from_directory(app.config["PDFS_FOLDER"], filename)

@app.route("/investigacion-detalle/<int:id>")
@login_requerido
def investigacion_detalle(id):
    db  = get_db()
    doc = db.execute("SELECT * FROM investigacion WHERE id=?", (id,)).fetchone()
    db.close()
    if not doc: abort(404)
    return jsonify(dict(doc))

@app.route("/descargar-pdf/<int:id>")
@login_requerido
def descargar_pdf(id):
    db  = get_db()
    doc = db.execute("SELECT * FROM investigacion WHERE id=?", (id,)).fetchone()
    db.close()
    if not doc or not doc["archivo"]:
        abort(404)
    ruta = os.path.join(app.config["PDFS_FOLDER"], doc["archivo"])
    if not os.path.exists(ruta):
        abort(404)
    nombre_descarga = _nombre_descarga(doc["titulo"], doc["archivo"], doc["id"])
    return send_file(ruta, as_attachment=True, download_name=nombre_descarga)

@app.route("/borrar-pdf/<int:id>", methods=["POST"])
@login_requerido
@solo_admin
def borrar_pdf(id):
    db  = get_db()
    doc = db.execute("SELECT archivo FROM investigacion WHERE id=?", (id,)).fetchone()
    if doc and doc["archivo"]:
        ruta = os.path.join(app.config["PDFS_FOLDER"], doc["archivo"])
        if os.path.exists(ruta): os.remove(ruta)
    db.execute("DELETE FROM investigacion WHERE id=?", (id,))
    db.commit(); db.close()
    return jsonify({"ok": True})

# ══════════════════════════════════════════════════════════════════════════════
# RUTAS: BIBLIOGRAFÍA
# ══════════════════════════════════════════════════════════════════════════════
# ══════════════════════════════════════════════════════════════════════════════
# RUTAS: PERSONAS
# ══════════════════════════════════════════════════════════════════════════════
@app.route("/personas")
@login_requerido
def personas():
    db = get_db()
    filas = db.execute("""
        SELECT p.*, COUNT(fp.fotografia_id) as num_fotos
        FROM personas p
        LEFT JOIN fotografias_personas fp ON fp.persona_id = p.id
        GROUP BY p.id ORDER BY p.nombre
    """).fetchall()
    total = db.execute("SELECT COUNT(*) FROM personas").fetchone()[0]
    db.close()
    return render_template_string(HTML_PERSONAS, personas=filas, total=total,
        admin=es_admin(), header_usuario=header_usuario(), nav=nav("personas"))

@app.route("/foto-perfil/<filename>")
@login_requerido
def servir_foto_perfil(filename):
    return send_from_directory(app.config["PERSONAS_FOLDER"], filename)

@app.route("/guardar-persona", methods=["POST"])
@login_requerido
@solo_admin
def guardar_persona():
    f  = request.form
    db = get_db()
    archivo = None
    if "archivo" in request.files:
        file = request.files["archivo"]
        if file.filename and allowed_image(file.filename):
            archivo = secure_filename(file.filename)
            file.save(os.path.join(app.config["PERSONAS_FOLDER"], archivo))
    quitar_foto = f.get("quitar_foto") == "on"
    if f.get("id"):
        if archivo:
            db.execute("""UPDATE personas SET nombre=?,rango=?,unidad=?,nacionalidad=?,
                          fecha_nac=?,fecha_fall=?,biografia=?,foto_perfil=? WHERE id=?""",
                       (f["nombre"], f.get("rango"), f.get("unidad"), f.get("nacionalidad"),
                        f.get("fecha_nac"), f.get("fecha_fall"), f.get("biografia"), archivo, f["id"]))
        elif quitar_foto:
            antigua = db.execute("SELECT foto_perfil FROM personas WHERE id=?", (f["id"],)).fetchone()
            if antigua and antigua["foto_perfil"]:
                ruta = os.path.join(app.config["PERSONAS_FOLDER"], antigua["foto_perfil"])
                if os.path.exists(ruta): os.remove(ruta)
            db.execute("""UPDATE personas SET nombre=?,rango=?,unidad=?,nacionalidad=?,
                          fecha_nac=?,fecha_fall=?,biografia=?,foto_perfil=NULL WHERE id=?""",
                       (f["nombre"], f.get("rango"), f.get("unidad"), f.get("nacionalidad"),
                        f.get("fecha_nac"), f.get("fecha_fall"), f.get("biografia"), f["id"]))
        else:
            db.execute("""UPDATE personas SET nombre=?,rango=?,unidad=?,nacionalidad=?,
                          fecha_nac=?,fecha_fall=?,biografia=? WHERE id=?""",
                       (f["nombre"], f.get("rango"), f.get("unidad"), f.get("nacionalidad"),
                        f.get("fecha_nac"), f.get("fecha_fall"), f.get("biografia"), f["id"]))
    else:
        db.execute("""INSERT INTO personas (nombre,rango,unidad,nacionalidad,fecha_nac,fecha_fall,biografia,foto_perfil,fecha_alta)
                      VALUES (?,?,?,?,?,?,?,?,?)""",
                   (f["nombre"], f.get("rango"), f.get("unidad"), f.get("nacionalidad"),
                    f.get("fecha_nac"), f.get("fecha_fall"), f.get("biografia"), archivo,
                    datetime.now().strftime("%Y-%m-%d")))
    db.commit(); db.close()
    return redirect(url_for("personas"))

@app.route("/persona-detalle/<int:id>")
@login_requerido
def persona_detalle_json(id):
    db = get_db()
    persona = db.execute("SELECT * FROM personas WHERE id=?", (id,)).fetchone()
    db.close()
    if not persona: abort(404)
    return jsonify(dict(persona))

@app.route("/persona/<int:id>")
@login_requerido
def persona_detalle(id):
    db = get_db()
    persona = db.execute("SELECT * FROM personas WHERE id=?", (id,)).fetchone()
    if not persona: abort(404)
    fotos = db.execute("""
        SELECT f.* FROM fotografias f
        JOIN fotografias_personas fp ON fp.fotografia_id = f.id
        WHERE fp.persona_id = ? ORDER BY f.fecha_foto DESC
    """, (id,)).fetchall()
    ascensos = db.execute("""
        SELECT * FROM hitos_persona WHERE persona_id=? AND tipo='ascenso'
        ORDER BY orden_manual ASC, id ASC
    """, (id,)).fetchall()
    condecoraciones = db.execute("""
        SELECT * FROM hitos_persona WHERE persona_id=? AND tipo='condecoracion'
        ORDER BY orden_manual ASC, id ASC
    """, (id,)).fetchall()
    db.close()
    return render_template_string(HTML_PERSONA_DETALLE, persona=persona, fotos=fotos,
        ascensos=ascensos, condecoraciones=condecoraciones,
        admin=es_admin(), header_usuario=header_usuario(), nav=nav("personas"))

@app.route("/borrar-persona/<int:id>", methods=["POST"])
@login_requerido
@solo_admin
def borrar_persona(id):
    db = get_db()
    persona = db.execute("SELECT foto_perfil FROM personas WHERE id=?", (id,)).fetchone()
    if persona and persona["foto_perfil"]:
        ruta = os.path.join(app.config["PERSONAS_FOLDER"], persona["foto_perfil"])
        if os.path.exists(ruta): os.remove(ruta)
    db.execute("DELETE FROM personas WHERE id=?", (id,))
    db.commit(); db.close()
    return jsonify({"ok": True})
# ══════════════════════════════════════════════════════════════════════════════
# RUTAS: HITOS DE PERSONA (ascensos / condecoraciones)
# ══════════════════════════════════════════════════════════════════════════════
@app.route("/guardar-hito", methods=["POST"])
@login_requerido
@solo_admin
def guardar_hito():
    data = request.get_json()
    if not data or not data.get("titulo") or not data.get("persona_id"):
        return jsonify({"ok": False}), 400
    tipo = data.get("tipo") if data.get("tipo") in ("ascenso", "condecoracion") else "ascenso"
    db = get_db()
    if data.get("id"):
        db.execute("""UPDATE hitos_persona SET tipo=?,titulo=?,fecha=?,detalle=? WHERE id=?""",
                   (tipo, data["titulo"], data.get("fecha"), data.get("detalle"), data["id"]))
    else:
        max_orden = db.execute(
            "SELECT COALESCE(MAX(orden_manual),0) FROM hitos_persona WHERE persona_id=? AND tipo=?",
            (data["persona_id"], tipo)).fetchone()[0]
        db.execute("""INSERT INTO hitos_persona (persona_id,tipo,titulo,fecha,detalle,orden_manual,fecha_alta)
                      VALUES (?,?,?,?,?,?,?)""",
                   (data["persona_id"], tipo, data["titulo"], data.get("fecha"), data.get("detalle"),
                    max_orden + 1, datetime.now().strftime("%Y-%m-%d")))
    db.commit(); db.close()
    return jsonify({"ok": True})

@app.route("/hito-detalle/<int:id>")
@login_requerido
def hito_detalle(id):
    db = get_db()
    h = db.execute("SELECT * FROM hitos_persona WHERE id=?", (id,)).fetchone()
    db.close()
    if not h: abort(404)
    return jsonify(dict(h))

@app.route("/borrar-hito/<int:id>", methods=["POST"])
@login_requerido
@solo_admin
def borrar_hito(id):
    db = get_db()
    db.execute("DELETE FROM hitos_persona WHERE id=?", (id,))
    db.commit(); db.close()
    return jsonify({"ok": True})

@app.route("/mover-hito/<int:id>/<direccion>", methods=["POST"])
@login_requerido
@solo_admin
def mover_hito(id, direccion):
    db = get_db()
    actual = db.execute("SELECT * FROM hitos_persona WHERE id=?", (id,)).fetchone()
    if not actual:
        db.close()
        return jsonify({"ok": False}), 404
    if direccion == "up":
        vecino = db.execute("""SELECT * FROM hitos_persona WHERE persona_id=? AND tipo=? AND orden_manual < ?
                                ORDER BY orden_manual DESC, id DESC LIMIT 1""",
                             (actual["persona_id"], actual["tipo"], actual["orden_manual"])).fetchone()
    else:
        vecino = db.execute("""SELECT * FROM hitos_persona WHERE persona_id=? AND tipo=? AND orden_manual > ?
                                ORDER BY orden_manual ASC, id ASC LIMIT 1""",
                             (actual["persona_id"], actual["tipo"], actual["orden_manual"])).fetchone()
    if vecino:
        db.execute("UPDATE hitos_persona SET orden_manual=? WHERE id=?", (vecino["orden_manual"], actual["id"]))
        db.execute("UPDATE hitos_persona SET orden_manual=? WHERE id=?", (actual["orden_manual"], vecino["id"]))
        db.commit()
    db.close()
    return jsonify({"ok": True})


@app.route("/bibliografia")
@login_requerido
def bibliografia():
    db      = get_db()
    fuentes = db.execute("SELECT * FROM bibliografia ORDER BY tipo ASC, titulo ASC").fetchall()
    total   = db.execute("SELECT COUNT(*) FROM bibliografia").fetchone()[0]
    paises  = [r[0] for r in db.execute(
        "SELECT DISTINCT pais FROM bibliografia WHERE pais IS NOT NULL AND pais!='' ORDER BY pais"
    ).fetchall()]
    # Estadísticas por tipo
    stats_raw = db.execute(
        "SELECT tipo, COUNT(*) as cnt FROM bibliografia WHERE tipo IS NOT NULL GROUP BY tipo ORDER BY cnt DESC"
    ).fetchall()
    stats = {r["tipo"]: r["cnt"] for r in stats_raw}
    db.close()
    return render_template_string(HTML_BIBLIOGRAFIA, fuentes=fuentes, total=total,
        paises=paises, stats=stats,
        admin=es_admin(), header_usuario=header_usuario(), nav=nav("bibliografia"))

@app.route("/guardar-fuente", methods=["POST"])
@login_requerido
@solo_admin
def guardar_fuente():
    data = request.get_json()
    if not data or not data.get("titulo"):
        return jsonify({"ok": False}), 400
    db = get_db()
    if data.get("id"):
        db.execute("""UPDATE bibliografia SET titulo=?,tipo=?,autor=?,pais=?,enlace=?,
                      idioma=?,descripcion=?,fiabilidad=? WHERE id=?""",
                   (data["titulo"], data.get("tipo"), data.get("autor"), data.get("pais"),
                    data.get("enlace"), data.get("idioma"), data.get("descripcion"),
                    data.get("fiabilidad", 3), data["id"]))
    else:
        db.execute("""INSERT INTO bibliografia
                      (titulo,tipo,autor,pais,enlace,idioma,descripcion,fiabilidad,fecha_alta)
                      VALUES (?,?,?,?,?,?,?,?,?)""",
                   (data["titulo"], data.get("tipo"), data.get("autor"), data.get("pais"),
                    data.get("enlace"), data.get("idioma"), data.get("descripcion"),
                    data.get("fiabilidad", 3), datetime.now().strftime("%Y-%m-%d")))
    db.commit(); db.close()
    return jsonify({"ok": True})

@app.route("/bibliografia-detalle/<int:id>")
@login_requerido
def bibliografia_detalle(id):
    db     = get_db()
    fuente = db.execute("SELECT * FROM bibliografia WHERE id=?", (id,)).fetchone()
    db.close()
    if not fuente: abort(404)
    return jsonify(dict(fuente))

@app.route("/borrar-fuente/<int:id>", methods=["POST"])
@login_requerido
@solo_admin
def borrar_fuente(id):
    db = get_db()
    db.execute("DELETE FROM bibliografia WHERE id=?", (id,))
    db.commit(); db.close()
    return jsonify({"ok": True})


# ══════════════════════════════════════════════════════════════════════════════
# RUTAS: AFIRMACIONES (certeza + fuente de cada dato histórico concreto)
# ══════════════════════════════════════════════════════════════════════════════
@app.route("/guardar-afirmacion", methods=["POST"])
@login_requerido
@solo_admin
def guardar_afirmacion():
    data = request.get_json()
    if not data or not data.get("entidad_tipo") or not data.get("entidad_id") or not data.get("campo"):
        return jsonify({"ok": False}), 400
    certeza = data.get("certeza") if data.get("certeza") in NIVELES_CERTEZA else "probable"
    fuente_id = data.get("fuente_id") or None
    db = get_db()
    db.execute("""
        INSERT INTO afirmaciones (entidad_tipo, entidad_id, campo, certeza, fuente_id, notas, fecha_alta)
        VALUES (?,?,?,?,?,?,?)
        ON CONFLICT(entidad_tipo, entidad_id, campo)
        DO UPDATE SET certeza=excluded.certeza, fuente_id=excluded.fuente_id, notas=excluded.notas
    """, (data["entidad_tipo"], data["entidad_id"], data["campo"], certeza, fuente_id,
          data.get("notas"), datetime.now().strftime("%Y-%m-%d")))
    db.commit()
    fila = db.execute("""
        SELECT a.*, b.titulo AS fuente_titulo, b.autor AS fuente_autor
        FROM afirmaciones a LEFT JOIN bibliografia b ON b.id = a.fuente_id
        WHERE a.entidad_tipo=? AND a.entidad_id=? AND a.campo=?
    """, (data["entidad_tipo"], data["entidad_id"], data["campo"])).fetchone()
    db.close()
    return jsonify({"ok": True, "afirmacion": dict(fila)})

@app.route("/borrar-afirmacion", methods=["POST"])
@login_requerido
@solo_admin
def borrar_afirmacion():
    data = request.get_json()
    if not data or not data.get("entidad_tipo") or not data.get("entidad_id") or not data.get("campo"):
        return jsonify({"ok": False}), 400
    db = get_db()
    db.execute("DELETE FROM afirmaciones WHERE entidad_tipo=? AND entidad_id=? AND campo=?",
               (data["entidad_tipo"], data["entidad_id"], data["campo"]))
    db.commit(); db.close()
    return jsonify({"ok": True})


# ══════════════════════════════════════════════════════════════════════════════
# ARRANQUE
# ══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    init_db()
    import socket
    try:
        ip = socket.gethostbyname(socket.gethostname())
    except Exception:
        ip = "<tu-IP>"

    print("\n" + "=" * 60)
    print("  ARCHIVO HISTÓRICO IIGM v4 arrancando...")
    print(f"  PC:     http://localhost:5000")
    if HOST == "0.0.0.0":
        print(f"  Móvil:  http://{ip}:5000  (misma red WiFi)")
    else:
        print("  Para acceso móvil ejecuta:  python app.py --host")
    print()
    print("  NOVEDADES v4:")
    print("  ⬇️  Descarga de fotos y vídeos individuales")
    print("  🗂  Descarga de la colección completa en ZIP (/descargas)")
    print()
    print("  ACCESO:")
    print("  Contraseña y administradores: ver config_local.json")
    print("  Lector (solo ve):  cualquier correo con la contraseña")
    print("=" * 60 + "\n")
    app.run(debug=False, use_reloader=False, host=HOST, port=5000)
