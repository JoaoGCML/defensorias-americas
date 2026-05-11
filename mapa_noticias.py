"""
Genera un mapa HTML interativo de noticias recientes de las Defensorías de las Américas.
Usa Leaflet.js para el mapa geográfico + timeline cronológica + tabla filtrable.

Uso:
    python3 mapa_noticias.py output/noticias_14d_TIMESTAMP.json
    python3 mapa_noticias.py --dias 7   # ejecuta scraping y genera mapa
    python3 mapa_noticias.py --dias 14
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

OUTPUT_DIR = Path(__file__).parent / "output"

# Coordenadas de países en las Américas [lat, lon]
COORDS_PAISES = {
    "Argentina":            [-34.6, -58.4],
    "Bolivia":              [-16.5, -68.1],
    "Brasil":               [-15.8, -47.9],
    "Chile":                [-33.5, -70.6],
    "Colombia":             [4.7, -74.1],
    "Ecuador":              [-0.2, -78.5],
    "Guyana":               [6.8, -58.2],
    "Paraguay":             [-25.3, -57.6],
    "Perú":                 [-12.0, -77.0],
    "Suriname":             [5.8, -55.2],
    "Uruguay":              [-34.9, -56.2],
    "Venezuela":            [10.5, -66.9],
    "Belice":               [17.3, -88.2],
    "Costa Rica":           [9.9, -84.1],
    "El Salvador":          [13.7, -89.2],
    "Guatemala":            [14.6, -90.5],
    "Honduras":             [14.1, -87.2],
    "México":               [19.4, -99.1],
    "Nicaragua":            [12.1, -86.3],
    "Panamá":               [8.9, -79.5],
    "Barbados":             [13.1, -59.6],
    "Cuba":                 [23.1, -82.4],
    "Haití":                [18.5, -72.3],
    "Jamaica":              [18.0, -76.8],
    "República Dominicana": [18.5, -69.9],
    "Trinidad y Tobago":    [10.7, -61.5],
    "Canadá":               [45.4, -75.7],
    "Estados Unidos":       [38.9, -77.0],
    "Regional":             [4.0, -74.0],
}

COLORES_TIPO = {
    "Ombudsperson":         "#e74c3c",
    "Defensoria Pública":   "#2980b9",
    "Red Regional":         "#8e44ad",
    "Organismo Internacional": "#16a085",
}


def cargar_datos(json_path: str) -> dict:
    with open(json_path, encoding="utf-8") as f:
        return json.load(f)


def generar_html(datos: dict, output_path: Path):
    dias = datos["dias"]
    ts = datos["timestamp"]
    instituciones = datos["instituciones"]

    # Prepara datos para JS
    markers = []
    todas_noticias = []

    for inst in instituciones:
        pais = inst["pais"]
        coords = COORDS_PAISES.get(pais)
        if not coords:
            continue

        noticias_periodo = inst.get("noticias_en_periodo", [])
        noticias_sin_fecha = inst.get("noticias_sin_fecha", [])
        todas = inst.get("noticias", [])
        tiene_error = bool(inst.get("error"))

        # Jitter para múltiples instituciones del mismo país
        idx_pais = sum(1 for m in markers if m["pais"] == pais)
        jitter_lat = idx_pais * 0.4
        jitter_lon = idx_pais * 0.4

        color = COLORES_TIPO.get(inst["tipo"], "#7f8c8d")
        n_recientes = len(noticias_periodo)

        marcador = {
            "pais": pais,
            "nombre": inst["nombre"],
            "tipo": inst["tipo"],
            "url": inst["url"],
            "url_noticias": inst.get("url_noticias", inst["url"]),
            "lat": coords[0] + jitter_lat,
            "lon": coords[1] + jitter_lon,
            "color": color,
            "n_recientes": n_recientes,
            "n_total": len(todas),
            "error": inst.get("error", ""),
            "noticias_periodo": noticias_periodo[:10],
            "noticias_sin_fecha": noticias_sin_fecha[:5],
        }
        markers.append(marcador)

        for n in noticias_periodo:
            todas_noticias.append({
                "fecha": n.get("fecha", ""),
                "titulo": n["titulo"],
                "url": n.get("url", ""),
                "institucion": inst["nombre"],
                "pais": pais,
                "tipo": inst["tipo"],
                "color": color,
                "con_fecha": True,
            })

        # Añade también las noticias sin fecha (como "recientes sin datar")
        for n in inst.get("noticias_sin_fecha", []):
            todas_noticias.append({
                "fecha": "",
                "titulo": n["titulo"],
                "url": n.get("url", ""),
                "institucion": inst["nombre"],
                "pais": pais,
                "tipo": inst["tipo"],
                "color": color,
                "con_fecha": False,
            })

    # Ordena por fecha desc
    todas_noticias.sort(key=lambda x: x["fecha"] or "", reverse=True)

    markers_json = json.dumps(markers, ensure_ascii=False)
    noticias_json = json.dumps(todas_noticias, ensure_ascii=False)

    fecha_generacion = datetime.utcnow().strftime("%d/%m/%Y %H:%M UTC")

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Mapa de Noticias — Defensorías y Ombudspersons de las Américas (últimos {dias} días)</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: 'Segoe UI', system-ui, sans-serif; background: #0f1923; color: #e8edf2; }}

  /* ── Header ── */
  header {{
    background: linear-gradient(135deg, #1a2a3a 0%, #0f1923 100%);
    border-bottom: 2px solid #2a4a6a;
    padding: 16px 24px;
    display: flex; align-items: center; gap: 20px;
    flex-wrap: wrap;
  }}
  header h1 {{ font-size: 1.1rem; font-weight: 600; color: #7eb8e8; flex: 1; min-width: 200px; }}
  header p {{ font-size: 0.78rem; color: #8a9ab0; }}
  .stats-row {{ display: flex; gap: 16px; flex-wrap: wrap; }}
  .stat {{ background: #1e3448; border: 1px solid #2a4a6a; border-radius: 8px;
           padding: 8px 16px; text-align: center; }}
  .stat .n {{ font-size: 1.4rem; font-weight: 700; color: #7eb8e8; }}
  .stat .l {{ font-size: 0.7rem; color: #8a9ab0; text-transform: uppercase; letter-spacing: .05em; }}

  /* ── Tabs ── */
  .tabs {{ display: flex; background: #111d2a; border-bottom: 2px solid #1e3448; }}
  .tab-btn {{ padding: 12px 24px; cursor: pointer; font-size: 0.85rem; color: #8a9ab0;
              border: none; background: none; transition: all .2s; border-bottom: 2px solid transparent; margin-bottom: -2px; }}
  .tab-btn:hover {{ color: #7eb8e8; }}
  .tab-btn.active {{ color: #7eb8e8; border-bottom-color: #7eb8e8; font-weight: 600; }}

  /* ── Panels ── */
  .panel {{ display: none; }}
  .panel.active {{ display: block; }}

  /* ── Mapa ── */
  #map {{ height: calc(100vh - 160px); width: 100%; }}

  /* ── Timeline ── */
  #panel-timeline {{ padding: 20px 24px; max-height: calc(100vh - 160px); overflow-y: auto; }}
  .timeline-filtros {{ display: flex; gap: 12px; margin-bottom: 20px; flex-wrap: wrap; align-items: center; }}
  .timeline-filtros input, .timeline-filtros select {{
    background: #1e3448; border: 1px solid #2a4a6a; color: #e8edf2;
    padding: 8px 12px; border-radius: 6px; font-size: 0.85rem; outline: none;
  }}
  .timeline-filtros input {{ flex: 1; min-width: 200px; }}
  .timeline-filtros input:focus, .timeline-filtros select:focus {{
    border-color: #7eb8e8;
  }}
  #conteo-filtrado {{ font-size: 0.8rem; color: #8a9ab0; padding: 8px 0; }}

  .dia-grupo {{ margin-bottom: 28px; }}
  .dia-titulo {{ font-size: 0.9rem; font-weight: 700; color: #7eb8e8;
                 border-bottom: 1px solid #1e3448; padding-bottom: 8px; margin-bottom: 12px; }}
  .noticia-card {{
    background: #1a2a3a; border: 1px solid #2a4a6a; border-left: 4px solid;
    border-radius: 6px; padding: 12px 16px; margin-bottom: 8px;
    transition: background .15s;
  }}
  .noticia-card:hover {{ background: #1e3448; }}
  .noticia-card .nc-titulo {{ font-size: 0.88rem; color: #c8d8e8; margin-bottom: 6px; line-height: 1.4; }}
  .noticia-card .nc-titulo a {{ color: inherit; text-decoration: none; }}
  .noticia-card .nc-titulo a:hover {{ color: #7eb8e8; text-decoration: underline; }}
  .noticia-card .nc-meta {{ font-size: 0.75rem; color: #6a8aa0; display: flex; gap: 12px; flex-wrap: wrap; }}
  .tag-tipo {{
    display: inline-block; padding: 2px 8px; border-radius: 4px;
    font-size: 0.68rem; font-weight: 600; color: #fff; opacity: .85;
  }}

  /* ── Tabla ── */
  #panel-tabla {{ padding: 20px 24px; max-height: calc(100vh - 160px); overflow-y: auto; }}
  .tabla-filtros {{ display: flex; gap: 12px; margin-bottom: 16px; flex-wrap: wrap; }}
  .tabla-filtros input, .tabla-filtros select {{
    background: #1e3448; border: 1px solid #2a4a6a; color: #e8edf2;
    padding: 8px 12px; border-radius: 6px; font-size: 0.85rem; outline: none;
  }}
  .tabla-filtros input {{ flex: 1; min-width: 200px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.82rem; }}
  thead th {{ background: #1e3448; color: #7eb8e8; padding: 10px 12px;
              text-align: left; font-weight: 600; border-bottom: 2px solid #2a4a6a;
              position: sticky; top: 0; cursor: pointer; white-space: nowrap; }}
  thead th:hover {{ background: #253d55; }}
  thead th::after {{ content: ' ↕'; color: #4a6a80; font-size: 0.7rem; }}
  tbody tr {{ border-bottom: 1px solid #1a2d3f; transition: background .1s; }}
  tbody tr:hover {{ background: #1e3448; }}
  tbody td {{ padding: 10px 12px; vertical-align: top; }}
  tbody td a {{ color: #7eb8e8; text-decoration: none; }}
  tbody td a:hover {{ text-decoration: underline; }}
  .fecha-chip {{ background: #1e3448; border: 1px solid #2a4a6a; border-radius: 4px;
                  padding: 2px 8px; font-size: 0.75rem; color: #a8b8c8; white-space: nowrap; }}
  .sin-fecha {{ color: #4a6a80; font-style: italic; font-size: 0.75rem; }}

  /* ── Leaflet popup override ── */
  .leaflet-popup-content-wrapper {{
    background: #1a2a3a; color: #e8edf2; border: 1px solid #2a4a6a;
    border-radius: 8px; box-shadow: 0 4px 16px rgba(0,0,0,.5);
  }}
  .leaflet-popup-tip {{ background: #1a2a3a; }}
  .leaflet-popup-content {{ font-family: 'Segoe UI', system-ui, sans-serif; font-size: 0.82rem; }}
  .popup-titulo {{ font-weight: 700; color: #7eb8e8; margin-bottom: 6px; font-size: 0.9rem; }}
  .popup-pais {{ color: #8a9ab0; font-size: 0.75rem; margin-bottom: 8px; }}
  .popup-noticias {{ list-style: none; }}
  .popup-noticias li {{ padding: 4px 0; border-bottom: 1px solid #1e3448; line-height: 1.35; }}
  .popup-noticias li:last-child {{ border-bottom: none; }}
  .popup-noticias a {{ color: #a8d8f8; text-decoration: none; }}
  .popup-noticias a:hover {{ text-decoration: underline; }}
  .popup-noticias .pfecha {{ color: #5a7a90; font-size: 0.72rem; display: block; }}
  .popup-link {{ display: block; margin-top: 8px; color: #7eb8e8; text-decoration: none; font-size: 0.78rem; }}
  .popup-sin-noticias {{ color: #5a7a90; font-style: italic; }}
  .popup-error {{ color: #c0392b; font-size: 0.75rem; }}

  /* Leyenda */
  .leyenda {{
    background: #1a2a3a; border: 1px solid #2a4a6a; border-radius: 8px;
    padding: 10px 14px; font-size: 0.78rem;
  }}
  .leyenda h4 {{ color: #7eb8e8; margin-bottom: 8px; font-size: 0.8rem; }}
  .leyenda-item {{ display: flex; align-items: center; gap: 8px; margin-bottom: 5px; }}
  .leyenda-dot {{ width: 12px; height: 12px; border-radius: 50%; flex-shrink: 0; }}

  ::-webkit-scrollbar {{ width: 8px; }}
  ::-webkit-scrollbar-track {{ background: #0f1923; }}
  ::-webkit-scrollbar-thumb {{ background: #2a4a6a; border-radius: 4px; }}
</style>
</head>
<body>

<header>
  <div>
    <h1>Defensorías y Ombudspersons de las Américas — Noticias recientes</h1>
    <p>Generado: {fecha_generacion} &nbsp;·&nbsp; Ventana: últimos {dias} días</p>
  </div>
  <div class="stats-row" id="stats-row"></div>
</header>

<div class="tabs">
  <button class="tab-btn active" onclick="switchTab('mapa')">🗺 Mapa</button>
  <button class="tab-btn" onclick="switchTab('timeline')">📅 Timeline</button>
  <button class="tab-btn" onclick="switchTab('tabla')">📋 Tabla</button>
</div>

<!-- MAPA -->
<div id="panel-mapa" class="panel active">
  <div id="map"></div>
</div>

<!-- TIMELINE -->
<div id="panel-timeline" class="panel">
  <div class="timeline-filtros">
    <input id="tl-buscar" type="text" placeholder="Buscar en titulares..." oninput="filtrarTimeline()">
    <select id="tl-pais" onchange="filtrarTimeline()"><option value="">Todos los países</option></select>
    <select id="tl-tipo" onchange="filtrarTimeline()"><option value="">Todos los tipos</option></select>
    <select id="tl-fecha" onchange="filtrarTimeline()">
      <option value="">Todas</option>
      <option value="con">Con fecha confirmada</option>
      <option value="sin">Sin fecha (recientes detectadas)</option>
    </select>
  </div>
  <div id="conteo-filtrado"></div>
  <div id="timeline-container"></div>
</div>

<!-- TABLA -->
<div id="panel-tabla" class="panel">
  <div class="tabla-filtros">
    <input id="tb-buscar" type="text" placeholder="Buscar en titulares..." oninput="filtrarTabla()">
    <select id="tb-pais" onchange="filtrarTabla()"><option value="">Todos los países</option></select>
    <select id="tb-tipo" onchange="filtrarTabla()"><option value="">Todos los tipos</option></select>
    <select id="tb-fecha" onchange="filtrarTabla()">
      <option value="">Todas</option>
      <option value="con">Con fecha confirmada</option>
      <option value="sin">Sin fecha</option>
    </select>
  </div>
  <table id="tabla-noticias">
    <thead>
      <tr>
        <th onclick="sortTabla(0)">Fecha</th>
        <th onclick="sortTabla(1)">Titular</th>
        <th onclick="sortTabla(2)">Institución</th>
        <th onclick="sortTabla(3)">País</th>
        <th onclick="sortTabla(4)">Tipo</th>
      </tr>
    </thead>
    <tbody id="tabla-body"></tbody>
  </table>
</div>

<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
// ── Datos ────────────────────────────────────────────────────────────────────
const MARKERS = {markers_json};
const NOTICIAS = {noticias_json};
const DIAS = {dias};

// ── Stats header ─────────────────────────────────────────────────────────────
(function() {{
  const total = MARKERS.length;
  const accesibles = MARKERS.filter(m => !m.error).length;
  const conNoticias = MARKERS.filter(m => m.n_recientes > 0).length;
  const totalNoticias = NOTICIAS.length;
  const statsEl = document.getElementById('stats-row');
  const conFecha = NOTICIAS.filter(n => n.con_fecha).length;
  const sinFecha = NOTICIAS.filter(n => !n.con_fecha).length;
  const items = [
    [total, 'Instituciones'],
    [accesibles, 'Accesibles'],
    [conNoticias, 'Con noticias'],
    [conFecha, `Datadas (${{DIAS}}d)`],
    [sinFecha, 'Sin fecha'],
  ];
  statsEl.innerHTML = items.map(([n, l]) =>
    `<div class="stat"><div class="n">${{n}}</div><div class="l">${{l}}</div></div>`
  ).join('');
}})();

// ── Tabs ──────────────────────────────────────────────────────────────────────
function switchTab(name) {{
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('panel-' + name).classList.add('active');
  event.target.classList.add('active');
  if (name === 'mapa') map.invalidateSize();
}}

// ── Mapa ──────────────────────────────────────────────────────────────────────
const map = L.map('map', {{ center: [5, -75], zoom: 3, zoomControl: true }});
L.tileLayer('https://{{s}}.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}{{r}}.png', {{
  attribution: '&copy; <a href="https://carto.com/" style="color:#7eb8e8">CARTO</a>',
  subdomains: 'abcd', maxZoom: 19
}}).addTo(map);

function crearIcono(color, count, error) {{
  const size = count > 0 ? Math.min(38, 20 + count * 3) : 18;
  const opacity = error ? 0.35 : (count > 0 ? 1 : 0.6);
  const badge = count > 0 ? `<div style="
    position:absolute; top:-6px; right:-6px;
    background:#e74c3c; color:#fff; border-radius:50%;
    width:18px; height:18px; font-size:10px; font-weight:700;
    display:flex; align-items:center; justify-content:center;
    border:2px solid #0f1923;">${{count}}</div>` : '';

  return L.divIcon({{
    className: '',
    html: `<div style="
      width:${{size}}px; height:${{size}}px; border-radius:50%;
      background:${{color}}; border:2px solid rgba(255,255,255,.4);
      opacity:${{opacity}}; position:relative;
      display:flex; align-items:center; justify-content:center;
      box-shadow:0 2px 8px rgba(0,0,0,.5);">${{badge}}</div>`,
    iconSize: [size, size],
    iconAnchor: [size/2, size/2],
    popupAnchor: [0, -(size/2 + 4)],
  }});
}}

MARKERS.forEach(m => {{
  const icon = crearIcono(m.color, m.n_recientes, !!m.error);

  let popupHTML = `<div class="popup-titulo">${{m.nombre}}</div>
    <div class="popup-pais">🌎 ${{m.pais}} &nbsp;·&nbsp; ${{m.tipo}}</div>`;

  if (m.error) {{
    popupHTML += `<div class="popup-error">⚠ Sin acceso al sitio</div>`;
  }} else if (m.noticias_periodo && m.noticias_periodo.length > 0) {{
    popupHTML += `<ul class="popup-noticias">`;
    m.noticias_periodo.slice(0, 5).forEach(n => {{
      const titulo = n.titulo.length > 80 ? n.titulo.slice(0, 77) + '…' : n.titulo;
      const enlace = n.url ? `<a href="${{n.url}}" target="_blank">${{titulo}}</a>` : titulo;
      const fecha = n.fecha ? `<span class="pfecha">${{formatFecha(n.fecha)}}</span>` : '';
      popupHTML += `<li>${{fecha}}${{enlace}}</li>`;
    }});
    popupHTML += `</ul>`;
  }} else {{
    const sinFecha = m.noticias_sin_fecha || [];
    if (sinFecha.length > 0) {{
      popupHTML += `<div style="color:#5a8090;font-size:.75rem;margin-bottom:4px">Sin fechas detectadas:</div><ul class="popup-noticias">`;
      sinFecha.slice(0, 3).forEach(n => {{
        const titulo = n.titulo.length > 70 ? n.titulo.slice(0, 67) + '…' : n.titulo;
        const enlace = n.url ? `<a href="${{n.url}}" target="_blank">${{titulo}}</a>` : titulo;
        popupHTML += `<li>${{enlace}}</li>`;
      }});
      popupHTML += `</ul>`;
    }} else {{
      popupHTML += `<div class="popup-sin-noticias">Sin noticias en los últimos ${{DIAS}} días</div>`;
    }}
  }}

  popupHTML += `<a class="popup-link" href="${{m.url_noticias || m.url}}" target="_blank">
    → Ver sitio oficial</a>`;

  L.marker([m.lat, m.lon], {{ icon }})
    .addTo(map)
    .bindPopup(popupHTML, {{ maxWidth: 340 }});
}});

// Leyenda
const leyenda = L.control({{ position: 'bottomright' }});
leyenda.onAdd = function() {{
  const div = L.DomUtil.create('div', 'leyenda');
  div.innerHTML = `<h4>Tipo de institución</h4>` +
    Object.entries({{
      'Ombudsperson': '#e74c3c',
      'Defensoria Pública': '#2980b9',
      'Red Regional': '#8e44ad',
      'Organismo Internacional': '#16a085',
    }}).map(([k, c]) =>
      `<div class="leyenda-item">
        <div class="leyenda-dot" style="background:${{c}}"></div>
        <span>${{k}}</span></div>`
    ).join('') +
    `<div style="margin-top:10px;font-size:.72rem;color:#5a7a90">
      Número = noticias recientes</div>`;
  return div;
}};
leyenda.addTo(map);

// ── Timeline ─────────────────────────────────────────────────────────────────
function formatFecha(isoStr) {{
  if (!isoStr) return 'Sin fecha';
  const [y, m, d] = isoStr.split('T')[0].split('-');
  return `${{d}}/${{m}}/${{y}}`;
}}

function formatFechaTitulo(isoStr) {{
  const meses = ['ene','feb','mar','abr','may','jun','jul','ago','sep','oct','nov','dic'];
  const [y, m, d] = isoStr.split('T')[0].split('-');
  return `${{parseInt(d)}} ${{meses[parseInt(m)-1]}} ${{y}}`;
}}

// Pobla selects
const paises = [...new Set([...NOTICIAS.map(n => n.pais), ...MARKERS.map(m => m.pais)])].sort();
const tipos = [...new Set([...NOTICIAS.map(n => n.tipo), ...MARKERS.map(m => m.tipo)])].sort();

['tl-pais', 'tb-pais'].forEach(id => {{
  const sel = document.getElementById(id);
  paises.forEach(p => {{ const o = document.createElement('option'); o.value = p; o.textContent = p; sel.appendChild(o); }});
}});
['tl-tipo', 'tb-tipo'].forEach(id => {{
  const sel = document.getElementById(id);
  tipos.forEach(t => {{ const o = document.createElement('option'); o.value = t; o.textContent = t; sel.appendChild(o); }});
}});

function filtrarNoticias(buscar, pais, tipo, fecha) {{
  return NOTICIAS.filter(n => {{
    if (pais && n.pais !== pais) return false;
    if (tipo && n.tipo !== tipo) return false;
    if (fecha === 'con' && !n.con_fecha) return false;
    if (fecha === 'sin' && n.con_fecha) return false;
    if (buscar) {{
      const q = buscar.toLowerCase();
      return n.titulo.toLowerCase().includes(q) || n.institucion.toLowerCase().includes(q);
    }}
    return true;
  }});
}}

function filtrarTimeline() {{
  const buscar = document.getElementById('tl-buscar').value;
  const pais = document.getElementById('tl-pais').value;
  const tipo = document.getElementById('tl-tipo').value;
  const fecha = document.getElementById('tl-fecha').value;
  renderTimeline(filtrarNoticias(buscar, pais, tipo, fecha));
}}

function renderTimeline(noticias) {{
  const container = document.getElementById('timeline-container');
  document.getElementById('conteo-filtrado').textContent =
    `${{noticias.length}} publicaciones`;

  if (noticias.length === 0) {{
    container.innerHTML = '<p style="color:#5a7a90;padding:20px">Sin resultados con los filtros aplicados.</p>';
    return;
  }}

  // Agrupa por fecha
  const grupos = {{}};
  noticias.forEach(n => {{
    const key = n.fecha ? n.fecha.split('T')[0] : 'sin-fecha';
    if (!grupos[key]) grupos[key] = [];
    grupos[key].push(n);
  }});

  const keys = Object.keys(grupos).sort().reverse();
  container.innerHTML = keys.map(k => {{
    const items = grupos[k];
    const titulo = k === 'sin-fecha' ? 'Sin fecha detectada' : formatFechaTitulo(k);
    const cards = items.map(n => {{
      const enlace = n.url
        ? `<a href="${{n.url}}" target="_blank">${{n.titulo}}</a>`
        : n.titulo;
      return `<div class="noticia-card" style="border-left-color:${{n.color}}">
        <div class="nc-titulo">${{enlace}}</div>
        <div class="nc-meta">
          <span class="tag-tipo" style="background:${{n.color}}">${{n.tipo}}</span>
          <span>${{n.pais}}</span>
          <span>${{n.institucion}}</span>
        </div>
      </div>`;
    }}).join('');
    return `<div class="dia-grupo">
      <div class="dia-titulo">${{titulo}} <span style="color:#4a6a80;font-weight:400">(${{items.length}})</span></div>
      ${{cards}}
    </div>`;
  }}).join('');
}}

renderTimeline(NOTICIAS);

// ── Tabla ────────────────────────────────────────────────────────────────────
let sortCol = 0, sortAsc = false;

function filtrarTabla() {{
  const buscar = document.getElementById('tb-buscar').value;
  const pais = document.getElementById('tb-pais').value;
  const tipo = document.getElementById('tb-tipo').value;
  const fecha = document.getElementById('tb-fecha').value;
  renderTabla(filtrarNoticias(buscar, pais, tipo, fecha));
}}

function sortTabla(col) {{
  if (sortCol === col) sortAsc = !sortAsc;
  else {{ sortCol = col; sortAsc = true; }}
  filtrarTabla();
}}

function renderTabla(noticias) {{
  const keys = ['fecha', 'titulo', 'institucion', 'pais', 'tipo'];
  const sorted = [...noticias].sort((a, b) => {{
    const va = (a[keys[sortCol]] || '').toString().toLowerCase();
    const vb = (b[keys[sortCol]] || '').toString().toLowerCase();
    return sortAsc ? va.localeCompare(vb) : vb.localeCompare(va);
  }});

  document.getElementById('tabla-body').innerHTML = sorted.map(n => {{
    const fecha = n.fecha
      ? `<span class="fecha-chip">${{formatFecha(n.fecha)}}</span>`
      : `<span class="sin-fecha">⚠ sin fecha</span>`;
    const titulo = n.url
      ? `<a href="${{n.url}}" target="_blank">${{n.titulo}}</a>`
      : n.titulo;
    return `<tr>
      <td>${{fecha}}</td>
      <td>${{titulo}}</td>
      <td>${{n.institucion}}</td>
      <td>${{n.pais}}</td>
      <td><span class="tag-tipo" style="background:${{n.color}}">${{n.tipo}}</span></td>
    </tr>`;
  }}).join('');
}}

renderTabla(NOTICIAS);
</script>
</body>
</html>"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Mapa HTML generado: {output_path}")
    return output_path


# ─── CLI ──────────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("json_file", nargs="?", help="Archivo JSON generado por noticias_scraper.py")
    p.add_argument("--dias", type=int, default=14)
    p.add_argument("--pais", help="Filtrar por país al hacer scraping")
    p.add_argument("--region", help="Filtrar por región al hacer scraping")
    p.add_argument("--output", default="mapa_noticias")
    return p.parse_args()


def main():
    args = parse_args()

    if args.json_file:
        json_path = args.json_file
    else:
        # Ejecuta el scraper
        print(f"Ejecutando scraper de noticias (últimos {args.dias} días)...")
        cmd = [sys.executable, str(Path(__file__).parent / "noticias_scraper.py"),
               "--dias", str(args.dias)]
        if args.pais:
            cmd += ["--pais", args.pais]
        if args.region:
            cmd += ["--region", args.region]

        result = subprocess.run(cmd, capture_output=True, text=True)
        print(result.stdout)
        if result.stderr:
            print(result.stderr)

        # Encuentra el JSON más reciente
        jsons = sorted(OUTPUT_DIR.glob("noticias_*.json"), key=lambda p: p.stat().st_mtime)
        if not jsons:
            print("ERROR: No se encontró archivo JSON de noticias.")
            sys.exit(1)
        json_path = str(jsons[-1])
        print(f"Usando: {json_path}")

    datos = cargar_datos(json_path)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M")
    output_path = OUTPUT_DIR / f"{args.output}_{datos['dias']}d_{ts}.html"
    generar_html(datos, output_path)


if __name__ == "__main__":
    main()
