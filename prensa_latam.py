"""
Scraper ASYNC de NOTAS DE PRENSA / COMUNICADOS
Defensorías Públicas y Ombudspersons de las Américas.

- aiohttp + asyncio: instituciones en paralelo (semáforo configurable)
- Múltiples secciones por institución
- Extracción de fechas: URL, tags, texto, artículos individuales
- Genera: JSON · HTML interactivo · feed Atom · histórico JSONL

Uso:
    python3 prensa_latam.py                  # últimos 30 días
    python3 prensa_latam.py --dias 60
    python3 prensa_latam.py --concurrencia 8
    python3 prensa_latam.py --pais Colombia
    python3 prensa_latam.py --output-dir docs/data
"""

import argparse
import asyncio
import json
import logging
import re
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin
from xml.etree import ElementTree as ET

import aiohttp
from bs4 import BeautifulSoup

warnings.filterwarnings("ignore")

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(OUTPUT_DIR / "prensa.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

TIMEOUT       = 20
MAX_POR_SEC   = 20
DELAY_SEC     = 0.8   # entre secciones del mismo sitio
DELAY_ENRICH  = 0.4   # entre artículos individuales

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Accept-Language": "es-419,es;q=0.9,pt;q=0.8,en;q=0.7,fr;q=0.6",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# ─── Catálogo de instituciones ────────────────────────────────────────────────

INSTITUCIONES_LATAM = [

    # ── SUDAMÉRICA ────────────────────────────────────────────────────────────
    {
        "pais": "Argentina", "region": "Sudamérica",
        "nombre": "Defensoría General de la Nación",
        "tipo": "Defensoria Pública", "idioma": "es",
        "url_base": "https://www.mpd.gov.ar",
        "secciones": [
            {"url": "https://www.mpd.gov.ar/index.php/noticias-h",  "tipo": "noticias"},
            {"url": "https://www.mpd.gov.ar/index.php/prensa",      "tipo": "prensa"},
            {"url": "https://www.mpd.gov.ar/index.php/comunicados", "tipo": "comunicados"},
        ],
    },
    {
        "pais": "Argentina", "region": "Sudamérica",
        "nombre": "Defensoría del Pueblo de la Nación",
        "tipo": "Ombudsperson", "idioma": "es",
        "url_base": "https://www.defensoriadelpueblo.gov.ar",
        "secciones": [
            {"url": "https://www.defensoriadelpueblo.gov.ar/prensa",   "tipo": "prensa"},
            {"url": "https://www.defensoriadelpueblo.gov.ar/noticias", "tipo": "noticias"},
        ],
    },
    {
        "pais": "Bolivia", "region": "Sudamérica",
        "nombre": "Defensoría del Pueblo de Bolivia",
        "tipo": "Ombudsperson", "idioma": "es",
        "url_base": "https://www.defensoria.gob.bo",
        "secciones": [
            {"url": "https://www.defensoria.gob.bo/noticias",     "tipo": "noticias"},
            {"url": "https://www.defensoria.gob.bo/sala-de-prensa", "tipo": "prensa"},
        ],
    },
    {
        "pais": "Brasil", "region": "Sudamérica",
        "nombre": "Defensoria Pública da União",
        "tipo": "Defensoria Pública", "idioma": "pt",
        "url_base": "https://www.dpu.def.br",
        "secciones": [
            {"url": "https://www.dpu.def.br/listagem-de-todas-as-noticias", "tipo": "noticias"},
            {"url": "https://www.dpu.def.br/imprensa/noticias",             "tipo": "imprensa"},
        ],
    },
    {
        "pais": "Brasil", "region": "Sudamérica",
        "nombre": "Defensoria Pública do Estado de São Paulo",
        "tipo": "Defensoria Pública", "idioma": "pt",
        "url_base": "https://www.defensoria.sp.def.br",
        "secciones": [
            {"url": "https://www.defensoria.sp.def.br/noticias", "tipo": "noticias"},
            {"url": "https://www.defensoria.sp.def.br/imprensa", "tipo": "imprensa"},
        ],
    },
    {
        "pais": "Brasil", "region": "Sudamérica",
        "nombre": "Defensoria Pública do Estado do Rio de Janeiro",
        "tipo": "Defensoria Pública", "idioma": "pt",
        "url_base": "https://defensoria.rj.def.br",
        "secciones": [
            {"url": "http://defensoria.rj.def.br/noticias", "tipo": "noticias"},
        ],
    },
    {
        "pais": "Brasil", "region": "Sudamérica",
        "nombre": "Defensoria Pública do Estado de Pernambuco",
        "tipo": "Defensoria Pública", "idioma": "pt",
        "url_base": "https://www.defensoria.pe.def.br",
        "secciones": [
            {"url": "https://www.defensoria.pe.def.br/noticias/", "tipo": "noticias"},
        ],
    },
    {
        "pais": "Brasil", "region": "Sudamérica",
        "nombre": "Defensoria Pública do Estado do Amazonas",
        "tipo": "Defensoria Pública", "idioma": "pt",
        "url_base": "https://defensoria.am.def.br",
        "secciones": [
            {"url": "https://defensoria.am.def.br/noticias/", "tipo": "noticias"},
        ],
    },
    {
        "pais": "Brasil", "region": "Sudamérica",
        "nombre": "Defensoria Pública do Estado de Alagoas",
        "tipo": "Defensoria Pública", "idioma": "pt",
        "url_base": "https://defensoria.al.def.br",
        "secciones": [
            {"url": "https://defensoria.al.def.br/noticias/", "tipo": "noticias"},
        ],
    },
    {
        "pais": "Brasil", "region": "Sudamérica",
        "nombre": "Defensoria Pública do Estado do Ceará",
        "tipo": "Defensoria Pública", "idioma": "pt",
        "url_base": "https://www.defensoria.ce.def.br",
        "secciones": [
            {"url": "https://www.defensoria.ce.def.br/noticia/", "tipo": "noticias"},
        ],
    },
    {
        "pais": "Brasil", "region": "Sudamérica",
        "nombre": "Defensoria Pública do Estado do Rio Grande do Sul",
        "tipo": "Defensoria Pública", "idioma": "pt",
        "url_base": "https://www.defensoria.rs.def.br",
        "secciones": [
            {"url": "https://www.defensoria.rs.def.br/noticias/", "tipo": "noticias"},
        ],
    },
    {
        "pais": "Chile", "region": "Sudamérica",
        "nombre": "Defensoría Penal Pública",
        "tipo": "Defensoria Pública", "idioma": "es",
        "url_base": "https://www.dpp.cl",
        "secciones": [
            {"url": "https://www.dpp.cl/sala_prensa/noticias",    "tipo": "sala_prensa"},
            {"url": "https://www.dpp.cl/sala_prensa/comunicados", "tipo": "comunicados"},
        ],
    },
    {
        "pais": "Chile", "region": "Sudamérica",
        "nombre": "Defensoría de la Niñez",
        "tipo": "Ombudsperson", "idioma": "es",
        "url_base": "https://www.defensorianinez.cl",
        "secciones": [
            {"url": "https://www.defensorianinez.cl/noticias/", "tipo": "noticias"},
            {"url": "https://www.defensorianinez.cl/prensa/",   "tipo": "prensa"},
        ],
    },
    {
        "pais": "Chile", "region": "Sudamérica",
        "nombre": "Instituto Nacional de Derechos Humanos (INDH)",
        "tipo": "Ombudsperson", "idioma": "es",
        "url_base": "https://www.indh.cl",
        "secciones": [
            {"url": "https://www.indh.cl/noticias-indh/",       "tipo": "noticias"},
            {"url": "https://www.indh.cl/noticias-regionales/", "tipo": "noticias_regionales"},
        ],
    },
    {
        "pais": "Colombia", "region": "Sudamérica",
        "nombre": "Defensoría del Pueblo de Colombia",
        "tipo": "Ombudsperson", "idioma": "es",
        "url_base": "https://www.defensoria.gov.co",
        "secciones": [
            {"url": "https://www.defensoria.gov.co/es/noticias",      "tipo": "noticias"},
            {"url": "https://www.defensoria.gov.co/es/sala-de-prensa","tipo": "prensa"},
            {"url": "https://www.defensoria.gov.co/es/comunicados",   "tipo": "comunicados"},
        ],
    },
    {
        "pais": "Ecuador", "region": "Sudamérica",
        "nombre": "Defensoría del Pueblo del Ecuador",
        "tipo": "Ombudsperson", "idioma": "es",
        "url_base": "https://www.dpe.gob.ec",
        "secciones": [
            {"url": "https://www.dpe.gob.ec/prensa/",       "tipo": "prensa"},
            {"url": "https://www.dpe.gob.ec/noticias/",     "tipo": "noticias"},
            {"url": "https://www.dpe.gob.ec/comunicados/",  "tipo": "comunicados"},
        ],
    },
    {
        "pais": "Paraguay", "region": "Sudamérica",
        "nombre": "Defensoría del Pueblo del Paraguay",
        "tipo": "Ombudsperson", "idioma": "es",
        "url_base": "https://www.defensoria.gov.py",
        "secciones": [
            {"url": "https://www.defensoria.gov.py/noticias",    "tipo": "noticias"},
            {"url": "https://www.defensoria.gov.py/prensa",      "tipo": "prensa"},
            {"url": "https://www.defensoria.gov.py/comunicados", "tipo": "comunicados"},
        ],
    },
    {
        "pais": "Perú", "region": "Sudamérica",
        "nombre": "Defensoría del Pueblo del Perú",
        "tipo": "Ombudsperson", "idioma": "es",
        "url_base": "https://www.defensoria.gob.pe",
        "secciones": [
            {"url": "https://www.defensoria.gob.pe/nota_de_prensa/", "tipo": "notas_prensa"},
            {"url": "https://www.defensoria.gob.pe/noticias/",       "tipo": "noticias"},
            {"url": "https://www.defensoria.gob.pe/comunicados/",    "tipo": "comunicados"},
        ],
    },
    {
        "pais": "Uruguay", "region": "Sudamérica",
        "nombre": "Institución Nacional de Derechos Humanos y Defensoría del Pueblo",
        "tipo": "Ombudsperson", "idioma": "es",
        "url_base": "https://www.gub.uy",
        "secciones": [
            {"url": "https://www.gub.uy/institucion-nacional-derechos-humanos-uruguay/comunicacion/noticias",
             "tipo": "noticias"},
        ],
    },
    {
        "pais": "Venezuela", "region": "Sudamérica",
        "nombre": "Defensoría del Pueblo de Venezuela",
        "tipo": "Ombudsperson", "idioma": "es",
        "url_base": "https://www.defensoria.gob.ve",
        "secciones": [
            {"url": "https://www.defensoria.gob.ve/noticias/",      "tipo": "noticias"},
            {"url": "https://www.defensoria.gob.ve/sala-de-prensa/","tipo": "prensa"},
        ],
    },
    {
        "pais": "Guyana", "region": "Sudamérica",
        "nombre": "Office of the Ombudsman of Guyana",
        "tipo": "Ombudsperson", "idioma": "en",
        "url_base": "https://ombudsmangy.org",
        "secciones": [
            {"url": "https://ombudsmangy.org/news-press-releases/", "tipo": "news"},
        ],
    },

    # ── CENTROAMÉRICA ─────────────────────────────────────────────────────────
    {
        "pais": "Costa Rica", "region": "Centroamérica",
        "nombre": "Defensoría de los Habitantes",
        "tipo": "Ombudsperson", "idioma": "es",
        "url_base": "https://www.defensoriadh.go.cr",
        "secciones": [
            {"url": "https://www.defensoriadh.go.cr/prensa/",       "tipo": "prensa"},
            {"url": "https://www.defensoriadh.go.cr/comunicados/",  "tipo": "comunicados"},
            {"url": "https://www.defensoriadh.go.cr/noticias/",     "tipo": "noticias"},
        ],
    },
    {
        "pais": "El Salvador", "region": "Centroamérica",
        "nombre": "Procuraduría para la Defensa de los Derechos Humanos",
        "tipo": "Ombudsperson", "idioma": "es",
        "url_base": "https://www.pddh.gob.sv",
        "secciones": [
            {"url": "https://www.pddh.gob.sv/category/comunicados/",     "tipo": "comunicados"},
            {"url": "https://www.pddh.gob.sv/category/noticias/",        "tipo": "noticias"},
            {"url": "https://www.pddh.gob.sv/category/pronunciamientos/","tipo": "pronunciamientos"},
        ],
    },
    {
        "pais": "Guatemala", "region": "Centroamérica",
        "nombre": "Procuraduría de los Derechos Humanos",
        "tipo": "Ombudsperson", "idioma": "es",
        "url_base": "https://www.pdh.org.gt",
        "secciones": [
            {"url": "https://www.pdh.org.gt/noticias.html",     "tipo": "noticias"},
            {"url": "https://www.pdh.org.gt/comunicados.html",  "tipo": "comunicados"},
            {"url": "https://www.pdh.org.gt/sala-de-prensa.html","tipo": "prensa"},
        ],
    },
    {
        "pais": "Honduras", "region": "Centroamérica",
        "nombre": "Comisionado Nacional de los Derechos Humanos (CONADEH)",
        "tipo": "Ombudsperson", "idioma": "es",
        "url_base": "https://conadeh.hn",
        "secciones": [
            {"url": "https://conadeh.hn",               "tipo": "noticias"},
            {"url": "https://conadeh.hn/?page_id=2393", "tipo": "boletines"},
        ],
    },
    {
        "pais": "México", "region": "Centroamérica",
        "nombre": "Comisión Nacional de los Derechos Humanos (CNDH)",
        "tipo": "Ombudsperson", "idioma": "es",
        "url_base": "https://www.cndh.org.mx",
        "secciones": [
            {"url": "https://www.cndh.org.mx/tipo_noticias/comunicados",          "tipo": "comunicados"},
            {"url": "https://www.cndh.org.mx/tipo_noticias/boletines-de-prensa",  "tipo": "boletines"},
            {"url": "https://www.cndh.org.mx/noticias",                           "tipo": "noticias"},
        ],
    },
    {
        "pais": "Nicaragua", "region": "Centroamérica",
        "nombre": "Procuraduría para la Defensa de los Derechos Humanos de Nicaragua",
        "tipo": "Ombudsperson", "idioma": "es",
        "url_base": "https://www.pddh.gob.ni",
        "secciones": [
            {"url": "https://www.pddh.gob.ni/?page_id=19", "tipo": "noticias"},
        ],
    },
    {
        "pais": "Panamá", "region": "Centroamérica",
        "nombre": "Defensoría del Pueblo de Panamá",
        "tipo": "Ombudsperson", "idioma": "es",
        "url_base": "https://www.defensoria.gob.pa",
        "secciones": [
            {"url": "https://www.defensoria.gob.pa/comunicados/",    "tipo": "comunicados"},
            {"url": "https://www.defensoria.gob.pa/boletin-digital/","tipo": "boletin"},
        ],
    },
    {
        "pais": "Belice", "region": "Centroamérica",
        "nombre": "Ombudsman of Belize",
        "tipo": "Ombudsperson", "idioma": "en",
        "url_base": "https://www.ombudsman.gov.bz",
        "secciones": [
            {"url": "https://www.ombudsman.gov.bz/news/", "tipo": "news"},
        ],
    },

    # ── CARIBE ────────────────────────────────────────────────────────────────
    {
        # DNS off-line en mayo 2026; mantener para retentar
        "pais": "República Dominicana", "region": "Caribe",
        "nombre": "Defensoría del Pueblo de la República Dominicana",
        "tipo": "Ombudsperson", "idioma": "es",
        "url_base": "https://www.defensoriadelpueblo.gob.do",
        "secciones": [
            {"url": "https://www.defensoriadelpueblo.gob.do/noticias/",    "tipo": "noticias"},
            {"url": "https://www.defensoriadelpueblo.gob.do/comunicados/", "tipo": "comunicados"},
        ],
    },
    {
        "pais": "Jamaica", "region": "Caribe",
        "nombre": "Office of the Public Defender of Jamaica",
        "tipo": "Ombudsperson", "idioma": "en",
        "url_base": "https://opd.gov.jm",
        "secciones": [
            {"url": "https://opd.gov.jm/news",                  "tipo": "news"},
            {"url": "https://opd.gov.jm/articles/news-release", "tipo": "press_release"},
        ],
    },
    {
        "pais": "Trinidad y Tobago", "region": "Caribe",
        "nombre": "Office of the Ombudsman of Trinidad and Tobago",
        "tipo": "Ombudsperson", "idioma": "en",
        "url_base": "https://www.ombudsman.org.tt",
        "secciones": [
            {"url": "https://www.ombudsman.org.tt/news/",         "tipo": "news"},
            {"url": "https://www.ombudsman.org.tt/press-releases/","tipo": "press_release"},
        ],
    },
    {
        "pais": "Curaçao", "region": "Caribe",
        "nombre": "Ombudsman van Curaçao",
        "tipo": "Ombudsperson", "idioma": "nl",
        "url_base": "https://www.ombudsman.cw",
        "secciones": [
            {"url": "https://www.ombudsman.cw/nieuws/", "tipo": "news"},
        ],
    },
    {
        "pais": "Haití", "region": "Caribe",
        "nombre": "Office de la Protection du Citoyen (OPC)",
        "tipo": "Ombudsperson", "idioma": "fr",
        "url_base": "https://www.opc.gouv.ht",
        "secciones": [
            {"url": "https://www.opc.gouv.ht/actualites",  "tipo": "actualites"},
            {"url": "https://www.opc.gouv.ht/communiques", "tipo": "communiques"},
        ],
    },

    # ── NORTEAMÉRICA ─────────────────────────────────────────────────────────
    {
        "pais": "Canadá", "region": "Norteamérica",
        "nombre": "Canadian Human Rights Commission",
        "tipo": "Ombudsperson", "idioma": "en",
        "url_base": "https://www.chrc-ccdp.gc.ca",
        "secciones": [
            {"url": "https://www.chrc-ccdp.gc.ca/en/news",               "tipo": "news"},
            {"url": "https://www.chrc-ccdp.gc.ca/en/news/news-releases",  "tipo": "press_release"},
        ],
    },
    {
        "pais": "Canadá", "region": "Norteamérica",
        "nombre": "Protecteur du citoyen du Québec",
        "tipo": "Ombudsperson", "idioma": "fr",
        "url_base": "https://www.protecteurducitoyen.qc.ca",
        "secciones": [
            {"url": "https://www.protecteurducitoyen.qc.ca/fr/nouvelles", "tipo": "nouvelles"},
        ],
    },
    {
        "pais": "Canadá", "region": "Norteamérica",
        "nombre": "Ombudsman Ontario",
        "tipo": "Ombudsperson", "idioma": "en",
        "url_base": "https://www.ombudsman.on.ca",
        "secciones": [
            {"url": "https://www.ombudsman.on.ca/resources/news-releases", "tipo": "press_release"},
            {"url": "https://www.ombudsman.on.ca/resources/news",          "tipo": "news"},
        ],
    },
    {
        "pais": "Canadá", "region": "Norteamérica",
        "nombre": "BC Ombudsperson (British Columbia)",
        "tipo": "Ombudsperson", "idioma": "en",
        "url_base": "https://bcombudsperson.ca",
        "secciones": [
            {"url": "https://bcombudsperson.ca/news-releases/", "tipo": "press_release"},
        ],
    },
    {
        "pais": "Canadá", "region": "Norteamérica",
        "nombre": "Alberta Ombudsman",
        "tipo": "Ombudsperson", "idioma": "en",
        "url_base": "https://www.ombudsman.ab.ca",
        "secciones": [
            {"url": "https://www.ombudsman.ab.ca/news/", "tipo": "news"},
        ],
    },
    {
        "pais": "Canadá", "region": "Norteamérica",
        "nombre": "Nova Scotia Ombudsman",
        "tipo": "Ombudsperson", "idioma": "en",
        "url_base": "https://ombudsman.ns.ca",
        "secciones": [
            {"url": "https://ombudsman.ns.ca/news/", "tipo": "news"},
        ],
    },
    {
        "pais": "Canadá", "region": "Norteamérica",
        "nombre": "Ombudsman New Brunswick / Nouveau-Brunswick",
        "tipo": "Ombudsperson", "idioma": "en",
        "url_base": "https://www.ombudnb.ca",
        "secciones": [
            {"url": "https://www.ombudnb.ca/site/newsroom", "tipo": "news"},
        ],
    },
    {
        "pais": "Canadá", "region": "Norteamérica",
        "nombre": "Manitoba Ombudsman",
        "tipo": "Ombudsperson", "idioma": "en",
        "url_base": "https://www.ombudsman.mb.ca",
        "secciones": [
            {"url": "https://www.ombudsman.mb.ca", "tipo": "news"},
        ],
    },
    {
        "pais": "Canadá", "region": "Norteamérica",
        "nombre": "Saskatchewan Ombudsman",
        "tipo": "Ombudsperson", "idioma": "en",
        "url_base": "https://ombudsman.sk.ca",
        "secciones": [
            {"url": "https://ombudsman.sk.ca", "tipo": "news"},
        ],
    },

    # ── ORGANISMOS REGIONALES ─────────────────────────────────────────────────
    {
        "pais": "Regional", "region": "Américas",
        "nombre": "Asociación Interamericana de Defensorías Públicas (AIDEF)",
        "tipo": "Red Regional", "idioma": "es",
        "url_base": "https://www.aidef.org",
        "secciones": [
            {"url": "https://www.aidef.org/noticias/",    "tipo": "noticias"},
            {"url": "https://www.aidef.org/comunicados/", "tipo": "comunicados"},
        ],
    },
    {
        "pais": "Regional", "region": "Américas",
        "nombre": "CIDH - Comisión Interamericana de Derechos Humanos",
        "tipo": "Organismo Internacional", "idioma": "es",
        "url_base": "https://www.oas.org/es/cidh",
        "secciones": [
            # La homepage lista los comunicados recientes via links jsForm
            # /es/cidh/prensa/comunicados.asp redirige a wearesorry.htm (sitio reestructurado)
            {"url": "https://www.oas.org/es/cidh/", "tipo": "comunicados"},
        ],
    },
    {
        "pais": "Regional", "region": "Américas",
        "nombre": "FIO - Federación Iberoamericana del Ombudsman",
        "tipo": "Red Regional", "idioma": "es",
        "url_base": "https://www.portalfio.org",
        "secciones": [
            {"url": "https://www.portalfio.org/noticias/",    "tipo": "noticias"},
            {"url": "https://www.portalfio.org/comunicados/", "tipo": "comunicados"},
        ],
    },
]

# ─── Coordenadas geográficas ──────────────────────────────────────────────────

COORDS = {
    "Argentina":           [-34.6, -58.4],
    "Bolivia":             [-16.5, -68.1],
    "Brasil":              [-15.8, -47.9],
    "Chile":               [-33.5, -70.6],
    "Colombia":            [  4.7, -74.1],
    "Ecuador":             [ -0.2, -78.5],
    "Guyana":              [  4.9, -58.9],
    "Paraguay":            [-25.3, -57.6],
    "Perú":                [-12.0, -77.0],
    "Uruguay":             [-34.9, -56.2],
    "Venezuela":           [ 10.5, -66.9],
    "Costa Rica":          [  9.9, -84.1],
    "El Salvador":         [ 13.7, -89.2],
    "Guatemala":           [ 14.6, -90.5],
    "Honduras":            [ 14.1, -87.2],
    "México":              [ 19.4, -99.1],
    "Nicaragua":           [ 12.1, -86.3],
    "Panamá":              [  8.9, -79.5],
    "Belice":              [ 17.3, -88.8],
    "República Dominicana":[ 18.5, -69.9],
    "Jamaica":             [ 18.0, -76.8],
    "Trinidad y Tobago":   [ 10.7, -61.5],
    "Curaçao":             [ 12.1, -68.9],
    "Haití":               [ 18.5, -72.3],
    "Canadá":              [ 49.0, -95.0],
    "Regional":            [  4.0, -74.0],
}

COLORES_TIPO = {
    "Ombudsperson":          "#e74c3c",
    "Defensoria Pública":    "#2980b9",
    "Red Regional":          "#8e44ad",
    "Organismo Internacional":"#16a085",
}

COLORES_SECCION = {
    "comunicados":       "#e74c3c",
    "notas_prensa":      "#e67e22",
    "boletines":         "#f39c12",
    "boletin":           "#f39c12",
    "prensa":            "#e67e22",
    "sala_prensa":       "#e67e22",
    "press_release":     "#e67e22",
    "communiques":       "#e74c3c",
    "noticias":          "#3498db",
    "noticias_regionales":"#5dade2",
    "imprensa":          "#2980b9",
    "pronunciamientos":  "#9b59b6",
    "nouvelles":         "#3498db",
    "actualites":        "#3498db",
    "news":              "#3498db",
}

# ─── Parseo de fechas ──────────────────────────────────────────────────────────

TODOS_MESES = {
    # Español
    "enero":1,"febrero":2,"marzo":3,"abril":4,"mayo":5,"junio":6,
    "julio":7,"agosto":8,"septiembre":9,"octubre":10,"noviembre":11,"diciembre":12,
    # Portugués
    "janeiro":1,"fevereiro":2,"março":3,"maio":5,"junho":6,"julho":7,
    "setembro":9,"outubro":10,"novembro":11,"dezembro":12,
    # Francés
    "janvier":1,"février":2,"mars":3,"avril":4,"mai":5,"juin":6,
    "juillet":7,"août":8,"octobre":10,"novembre":11,"décembre":12,
    # Inglés
    "january":1,"february":2,"march":3,"april":4,"may":5,"june":6,
    "july":7,"august":8,"september":9,"october":10,"november":11,"december":12,
    # Abreviaciones inglesas
    "jan":1,"feb":2,"mar":3,"apr":4,"jun":6,"jul":7,"aug":8,
    "sep":9,"oct":10,"nov":11,"dec":12,
}


def parsear_fecha(texto: str) -> datetime | None:
    if not texto:
        return None
    texto = texto.strip()

    # ISO 8601
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", texto)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass

    # DD/MM/YYYY o DD.MM.YYYY
    m = re.search(r"(\d{1,2})[/\-\.](\d{1,2})[/\-\.](\d{4})", texto)
    if m:
        try:
            d = datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            if 1 <= d.month <= 12:
                return d
        except ValueError:
            pass

    # "11 de mayo de 2026" / "11 mayo 2026"
    m = re.search(
        r"(\d{1,2})\s+(?:de\s+)?([a-záéíóúàâêîôûüñç]+)(?:\s+de)?\s+(\d{4})",
        texto.lower(),
    )
    if m:
        mes = TODOS_MESES.get(m.group(2))
        if mes:
            try:
                return datetime(int(m.group(3)), mes, int(m.group(1)))
            except ValueError:
                pass

    # "May 11, 2026" / "mayo 07,2026" (sin espacio post-coma)
    m = re.search(r"([a-záéíóú]+)\s+(\d{1,2}),?\s*(\d{4})", texto.lower())
    if m:
        mes = TODOS_MESES.get(m.group(1))
        if mes:
            try:
                return datetime(int(m.group(3)), mes, int(m.group(2)))
            except ValueError:
                pass

    # "31, January 2026" — día primero, coma, mes, año (Jamaica OPD)
    m = re.search(r"(\d{1,2}),?\s+([a-záéíóú]+)\s+(\d{4})", texto.lower())
    if m:
        mes = TODOS_MESES.get(m.group(2))
        if mes:
            try:
                return datetime(int(m.group(3)), mes, int(m.group(1)))
            except ValueError:
                pass

    return None


def parsear_fecha_url(url: str) -> datetime | None:
    if not url:
        return None
    m = re.search(r"/(\d{4})/(\d{2})/(\d{2})/", url)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    m = re.search(r"/(\d{4})/(\d{2})/", url)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), 1)
        except ValueError:
            pass
    return None


# ─── Extracción de contenido ──────────────────────────────────────────────────

SELECTORES_ITEMS = [
    "article", ".noticia", ".news-item", ".news-card", ".press-item",
    ".entry", ".post", "li.views-row", "li.news-item", ".card",
    ".media-body", ".comunicado", ".comunicados li", ".comunicados",
    ".press-release", ".item", ".documento", ".article-header", "li.media",
]

SELECTORES_TITULO = [
    "h1", "h2", "h3", "h4", ".title", ".titulo", ".entry-title",
    ".card-title", ".post-title", "a",
]

SELECTORES_FECHA_TAG = [
    "time[datetime]", "time",
    ".fecha", ".date", ".published", ".post-date", ".entry-date",
    ".news-date", "span.date", "span.fecha",
    ".meta", ".post-meta", "abbr[title]",
    ".field-content", ".views-field-created",
    "span.designation",       # Jamaica OPD: "31, January 2026"
    ".blog-post-details",
    ".date-display-single",   # Drupal
    ".field--name-created",   # Drupal 8+
    "small.text-muted",
]

TITULOS_IGNORAR = {
    # Inglés
    "select language", "search releases", "news releases", "latest news",
    "article categories", "categories", "more news", "read more",
    "load more", "older posts", "newer posts", "all news",
    "subscribe to our newsletter", "subscribe", "newsletter",
    "media gallery", "news and media", "back to news",
    "if you think you have been treated unfairly:",
    "can we look at your concern?", "looking to make a complaint",
    "important notice about fraud",
    "what's new", "what’s new",
    "our office", "contact us", "about us", "home", "events",
    "regina office", "saskatoon office", "winnipeg office",
    # Español
    "leer más", "ver más", "ver todas las noticias", "más noticias",
    "sala de prensa", "noticias", "comunicados", "prensa",
    # Francés
    "lire la suite", "toutes les nouvelles", "nouvelles",
    "communiqués de presse", "salle de presse",
    # Portugués
    "leia mais", "ver todas as notícias", "mais notícias",
}

_UI_SUBSTRINGS = [
    "search release", "search news", "search press",
    "select language", "choose language",
    "subscribe to", "sign up for",
    "if you think you have been treated",
    "can we look at your concern",
    "looking to make a complaint",
]


def es_ui_element(titulo: str) -> bool:
    t = titulo.lower().strip()
    if t in TITULOS_IGNORAR:
        return True
    return any(sub in t for sub in _UI_SUBSTRINGS)


def extraer_fecha_tag(tag) -> datetime | None:
    for attr in ["datetime", "content", "title"]:
        v = tag.get(attr, "")
        if v:
            d = parsear_fecha(v)
            if d:
                return d
    return parsear_fecha(tag.get_text(strip=True))


def extraer_items(soup: BeautifulSoup, url_base: str, tipo_seccion: str) -> list[dict]:
    items_result = []
    vistas: set[str] = set()

    # Estrategia A: contenedores semánticos
    for sel in SELECTORES_ITEMS:
        items = soup.select(sel)
        if len(items) < 2:
            continue
        for item in items:
            titulo, enlace, fecha = "", "", None

            for f_sel in SELECTORES_FECHA_TAG:
                ftag = item.select_one(f_sel)
                if ftag:
                    fecha = extraer_fecha_tag(ftag)
                    if fecha:
                        break
            if not fecha:
                fecha = parsear_fecha(item.get_text(" ", strip=True))

            for t_sel in SELECTORES_TITULO:
                ttag = item.select_one(t_sel)
                if ttag and len(ttag.get_text(strip=True)) > 8:
                    titulo = ttag.get_text(strip=True)
                    if ttag.name == "a":
                        enlace = ttag.get("href", "")
                    else:
                        a = ttag.find("a", href=True) or item.find("a", href=True)
                        if a:
                            enlace = a.get("href", "")
                    break
            if not titulo:
                titulo = item.get_text(separator=" ", strip=True)[:150]

            titulo = re.sub(r"\s+", " ", titulo).strip()
            if enlace:
                enlace = urljoin(url_base, enlace)
                if not fecha:
                    fecha = parsear_fecha_url(enlace)

            if titulo and len(titulo) > 8 and titulo not in vistas and not es_ui_element(titulo):
                vistas.add(titulo)
                items_result.append({
                    "titulo": titulo,
                    "url": enlace,
                    "fecha": fecha.isoformat() if fecha else None,
                    "fecha_dt": fecha,
                    "tipo_seccion": tipo_seccion,
                    "es_pdf": enlace.lower().endswith(".pdf") if enlace else False,
                })

        if len(items_result) >= MAX_POR_SEC:
            break

    # Estrategia B: H2/H3/H4/H5 con texto de fecha inline o en container padre
    if not items_result:
        for h in soup.find_all(["h2", "h3", "h4", "h5"])[:40]:
            texto_h = h.get_text(strip=True)
            if len(texto_h) < 8:
                continue
            fecha_inline = parsear_fecha(texto_h[:20])
            titulo_limpio = re.sub(r"^\d{1,2}/\d{2}/\d{4}", "", texto_h).strip() or texto_h

            a = h.find("a", href=True) or h.find_next_sibling("a", href=True)
            if not a and h.parent:
                a = h.parent.find("a", href=True)
            enlace = urljoin(url_base, a["href"]) if a else ""
            if not fecha_inline and enlace:
                fecha_inline = parsear_fecha_url(enlace)
            # Buscar fecha en texto del container padre (patrón Perú)
            if not fecha_inline and h.parent:
                ctx = h.parent.get_text(" ", strip=True)[:120]
                fecha_inline = parsear_fecha(ctx)

            if titulo_limpio not in vistas and not es_ui_element(titulo_limpio):
                vistas.add(titulo_limpio)
                items_result.append({
                    "titulo": titulo_limpio, "url": enlace,
                    "fecha": fecha_inline.isoformat() if fecha_inline else None,
                    "fecha_dt": fecha_inline,
                    "tipo_seccion": tipo_seccion,
                    "es_pdf": enlace.lower().endswith(".pdf") if enlace else False,
                })
            if len(items_result) >= MAX_POR_SEC:
                break

    # Estrategia C2: <time datetime> → sube árbol → busca h2/h3/h4 (patrón BC)
    if not items_result:
        for t in soup.find_all("time")[:30]:
            dt = t.get("datetime", "")
            fecha = parsear_fecha(dt) if dt else None
            node = t.parent
            titulo, enlace = "", ""
            for _ in range(6):
                h = node.find(["h2", "h3", "h4"]) if node else None
                if h and len(h.get_text(strip=True)) > 10:
                    titulo = h.get_text(strip=True)
                    a = h.find("a", href=True) or (node.find("a", href=True) if node else None)
                    if a:
                        enlace = urljoin(url_base, a["href"])
                    break
                node = node.parent if (node and node.parent) else None
            if titulo and titulo not in vistas and not es_ui_element(titulo):
                vistas.add(titulo)
                items_result.append({
                    "titulo": titulo, "url": enlace,
                    "fecha": fecha.isoformat() if fecha else None,
                    "fecha_dt": fecha,
                    "tipo_seccion": tipo_seccion,
                    "es_pdf": False,
                })
            if len(items_result) >= MAX_POR_SEC:
                break

    # Estrategia D: PDFs de comunicados (patrón El Salvador)
    pdfs = [
        a for a in soup.find_all("a", href=True)
        if a["href"].lower().endswith(".pdf")
        and any(kw in a["href"].lower() + a.get_text().lower()
                for kw in ["comunicado", "nota", "prensa", "boletin", "pronunciamiento"])
    ]
    for a in pdfs[:10]:
        titulo = a.get_text(strip=True) or a["href"].split("/")[-1]
        titulo = re.sub(r"\s+", " ", titulo).strip()
        enlace = urljoin(url_base, a["href"])
        fecha = parsear_fecha_url(enlace) or parsear_fecha(a["href"])
        if titulo not in vistas:
            vistas.add(titulo)
            items_result.append({
                "titulo": titulo, "url": enlace,
                "fecha": fecha.isoformat() if fecha else None,
                "fecha_dt": fecha,
                "tipo_seccion": tipo_seccion + "_pdf",
                "es_pdf": True,
            })

    return items_result[:MAX_POR_SEC]


# ─── I/O async ────────────────────────────────────────────────────────────────

async def get_soup(url: str, session: aiohttp.ClientSession) -> tuple[BeautifulSoup | None, str]:
    try:
        async with session.get(url) as r:
            r.raise_for_status()
            html = await r.text(errors="replace")
            return BeautifulSoup(html, "html.parser"), str(r.url)
    except Exception as e:
        log.debug(f"    error {url}: {e}")
        return None, url


async def enriquecer_fechas(items: list[dict], session: aiohttp.ClientSession, max_fetch: int = 8):
    sin_fecha = [n for n in items if not n["fecha_dt"] and n["url"] and not n["es_pdf"]][:max_fetch]
    for n in sin_fecha:
        soup_art, _ = await get_soup(n["url"], session)
        await asyncio.sleep(DELAY_ENRICH)
        if not soup_art:
            continue
        fecha = None
        for sel in [
            "meta[property='article:published_time']",
            "meta[name='date']", "meta[name='DC.date']", "meta[name='pubdate']",
            "time[datetime]", ".fecha", ".date", ".published",
            ".entry-date", ".post-date", "span.date", "span.fecha",
            ".article-date", ".news-date",
            "span.designation", ".blog-post-details",
            ".field--name-created", "small.text-muted",
        ]:
            tag = soup_art.select_one(sel)
            if tag:
                fecha = extraer_fecha_tag(tag)
                if fecha:
                    break
        if not fecha:
            texto = soup_art.get_text(" ", strip=True)[:2000]
            fecha = parsear_fecha(texto)
        if fecha:
            n["fecha"] = fecha.isoformat()
            n["fecha_dt"] = fecha
            log.info(f"        ✓ fecha: {fecha.date()} ← {n['url'][:65]}")


async def scrapear_institucion(
    inst: dict, session: aiohttp.ClientSession, dias: int, sem: asyncio.Semaphore
) -> dict:
    corte = datetime.now() - timedelta(days=dias)
    resultado = {
        **{k: v for k, v in inst.items() if k != "secciones"},
        "secciones_scrapeadas": [],
        "todos_items": [],
        "items_en_periodo": [],
        "items_sin_fecha": [],
        "error": "",
        "timestamp": datetime.utcnow().isoformat(),
    }

    todos: list[dict] = []
    async with sem:
        for sec in inst["secciones"]:
            soup, url_final = await get_soup(sec["url"], session)
            await asyncio.sleep(DELAY_SEC)

            if not soup:
                log.debug(f"    sin acceso: {sec['url']}")
                resultado["secciones_scrapeadas"].append(
                    {"url": sec["url"], "tipo": sec["tipo"], "ok": False, "items": 0}
                )
                continue

            items = extraer_items(soup, url_final, sec["tipo"])
            await enriquecer_fechas(items, session)

            resultado["secciones_scrapeadas"].append(
                {"url": sec["url"], "tipo": sec["tipo"], "ok": True, "items": len(items)}
            )
            todos.extend(items)
            log.info(f"    [{sec['tipo']}] {len(items)} items — {sec['url'][:65]}")

    # Deduplicar por URL y por título normalizado
    vistas_url: set[str] = set()
    vistas_tit: set[str] = set()
    todos_dedup = []
    for item in todos:
        url = item.get("url", "")
        tit_norm = re.sub(r"\s+", " ", item["titulo"].lower().strip())
        if url and url in vistas_url:
            continue
        if tit_norm in vistas_tit:
            continue
        if url:
            vistas_url.add(url)
        vistas_tit.add(tit_norm)
        todos_dedup.append(item)

    resultado["todos_items"] = [
        {k: v for k, v in n.items() if k != "fecha_dt"} for n in todos_dedup
    ]

    en_periodo = [
        {k: v for k, v in n.items() if k != "fecha_dt"}
        for n in todos_dedup if n["fecha_dt"] and n["fecha_dt"] >= corte
    ]
    sin_fecha = [
        {k: v for k, v in n.items() if k != "fecha_dt"}
        for n in todos_dedup if not n["fecha_dt"]
    ]

    resultado["items_en_periodo"] = sorted(en_periodo, key=lambda x: x["fecha"], reverse=True)
    resultado["items_sin_fecha"] = sin_fecha[:8]

    log.info(
        f"  → total: {len(todos_dedup)} | "
        f"en {dias}d: {len(en_periodo)} | sin fecha: {len(sin_fecha)}"
    )
    return resultado


# ─── Feed Atom ────────────────────────────────────────────────────────────────

def _slugify(text: str) -> str:
    import unicodedata
    text = unicodedata.normalize("NFD", text.lower())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


def _collect_feed_items(datos: dict, filtro_pais: str = "", filtro_region: str = "") -> list[dict]:
    items: list[dict] = []
    for inst in datos["instituciones"]:
        if filtro_pais   and inst["pais"]           != filtro_pais:   continue
        if filtro_region and inst.get("region", "") != filtro_region: continue
        for item in inst.get("items_en_periodo", []):
            items.append({**item, "_inst": inst["nombre"], "_pais": inst["pais"],
                          "_region": inst.get("region", ""), "_tipo": inst["tipo"]})
    items.sort(key=lambda x: x.get("fecha", ""), reverse=True)
    return items


def generar_feed_atom(datos: dict, output_path: Path, site_url: str = "",
                      filtro_pais: str = "", filtro_region: str = "", label: str = ""):
    """Genera un feed Atom (RFC 4287). Acepta filtros opcionales por país o región."""
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    titulo = "Notas de Prensa — Defensorías de las Américas"
    if label:
        titulo += f" · {label}"

    root = ET.Element("feed", xmlns="http://www.w3.org/2005/Atom")
    ET.SubElement(root, "title").text = titulo
    feed_id = f"urn:defensorias-americas:prensa:{_slugify(label) if label else 'all'}"
    ET.SubElement(root, "id").text = feed_id
    ET.SubElement(root, "updated").text = now_iso
    link = ET.SubElement(root, "link")
    link.set("rel", "self")
    link.set("href", site_url or "https://example.org/feed.xml")
    ET.SubElement(root, "rights").text = "Contenido de fuentes institucionales públicas"

    all_items = _collect_feed_items(datos, filtro_pais, filtro_region)

    for item in all_items[:100]:
        entry = ET.SubElement(root, "entry")
        ET.SubElement(entry, "title").text = item["titulo"]
        item_url = item.get("url", "")
        entry_id = item_url or f"urn:defensorias-americas:{hash(item['titulo'])}"
        ET.SubElement(entry, "id").text = entry_id
        if item_url:
            lnk = ET.SubElement(entry, "link")
            lnk.set("href", item_url)
            if item.get("es_pdf"):
                lnk.set("type", "application/pdf")
        fecha_str = item.get("fecha", "")
        if fecha_str:
            ET.SubElement(entry, "updated").text = (
                fecha_str.replace(" ", "T") + "Z" if "T" not in fecha_str else fecha_str
            )
        summ = f"{item['_inst']} ({item['_pais']}) — {item.get('tipo_seccion', '')}"
        ET.SubElement(entry, "summary").text = summ

    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    with open(output_path, "wb") as f:
        f.write(b'<?xml version="1.0" encoding="utf-8"?>\n')
        tree.write(f, encoding="utf-8", xml_declaration=False)
    log.info(f"Feed Atom: {output_path}  ({len(all_items)} entradas){' ['+label+']' if label else ''}")


def generar_json_feed(datos: dict, output_path: Path, site_url: str = "",
                      filtro_pais: str = "", filtro_region: str = "", label: str = ""):
    """Genera un JSON Feed 1.1 (https://jsonfeed.org/version/1.1)."""
    titulo = "Notas de Prensa — Defensorías de las Américas"
    if label:
        titulo += f" · {label}"
    all_items = _collect_feed_items(datos, filtro_pais, filtro_region)
    feed = {
        "version": "https://jsonfeed.org/version/1.1",
        "title": titulo,
        "feed_url": site_url or "",
        "items": [],
    }
    for item in all_items[:100]:
        fecha_str = item.get("fecha", "")
        feed["items"].append({
            "id":            item.get("url") or f"urn:defensorias:{hash(item['titulo'])}",
            "url":           item.get("url", ""),
            "title":         item["titulo"],
            "summary":       f"{item['_inst']} ({item['_pais']})",
            "date_published": (fecha_str.replace(" ", "T") + "Z" if fecha_str and "T" not in fecha_str else fecha_str) or None,
            "tags":          [item["_pais"], item["_region"], item.get("tipo_seccion", "")],
        })
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(feed, f, ensure_ascii=False, indent=2)
    log.info(f"JSON Feed: {output_path}  ({len(all_items)} entradas){' ['+label+']' if label else ''}")


# ─── Histórico JSONL ──────────────────────────────────────────────────────────

def guardar_historico(datos: dict, historico_path: Path):
    """Añade un resumen del run actual al archivo histórico (JSONL)."""
    por_pais: dict[str, int] = {}
    for inst in datos["instituciones"]:
        pais = inst["pais"]
        por_pais[pais] = por_pais.get(pais, 0) + len(inst.get("items_en_periodo", []))

    entrada = {
        "timestamp":       datos["timestamp"],
        "dias":            datos["dias"],
        "total_con_fecha": sum(len(i.get("items_en_periodo", [])) for i in datos["instituciones"]),
        "total_sin_fecha": sum(len(i.get("items_sin_fecha", []))   for i in datos["instituciones"]),
        "por_pais":        por_pais,
    }
    historico_path.parent.mkdir(parents=True, exist_ok=True)
    with open(historico_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entrada, ensure_ascii=False) + "\n")
    log.info(f"Histórico: {historico_path}")


# ─── Generador de mapa HTML ───────────────────────────────────────────────────

def generar_mapa(datos: dict, output_path: Path, feed_url: str = ""):
    dias = datos["dias"]
    instituciones = datos["instituciones"]

    markers = []
    todas_noticias = []

    for inst in instituciones:
        pais = inst["pais"]
        coords = COORDS.get(pais)
        if not coords:
            continue

        color = COLORES_TIPO.get(inst["tipo"], "#7f8c8d")
        items_periodo = inst.get("items_en_periodo", [])
        items_sin = inst.get("items_sin_fecha", [])

        # Circular offset: count total institutions per country first (pre-pass above)
        n_mismo_pais = sum(1 for m in markers if m["pais"] == pais)
        n_total_pais = sum(1 for i in instituciones if i["pais"] == pais and COORDS.get(i["pais"]))
        if n_total_pais <= 1:
            jlat, jlon = 0.0, 0.0
        else:
            import math
            r = 0.55
            angle = (2 * math.pi * n_mismo_pais) / n_total_pais
            jlat = r * math.sin(angle)
            jlon = r * math.cos(angle)

        markers.append({
            "pais": pais, "region": inst.get("region", ""),
            "nombre": inst["nombre"], "tipo": inst["tipo"],
            "url": inst["url_base"],
            "lat": coords[0] + jlat, "lon": coords[1] + jlon,
            "color": color,
            "n_periodo": len(items_periodo),
            "n_sin_fecha": len(items_sin),
            "error": inst.get("error", ""),
            "items_periodo":   items_periodo[:6],
            "items_sin_fecha": items_sin[:4],
            "secciones": [s for s in inst.get("secciones_scrapeadas", []) if s["ok"]],
        })

        for n in items_periodo:
            todas_noticias.append({
                "fecha": n.get("fecha", ""),
                "titulo": n["titulo"],
                "url": n.get("url", ""),
                "es_pdf": n.get("es_pdf", False),
                "tipo_seccion": n.get("tipo_seccion", ""),
                "institucion": inst["nombre"],
                "pais": pais,
                "region": inst.get("region", ""),
                "tipo": inst["tipo"],
                "color": color,
                "con_fecha": True,
            })
        for n in items_sin:
            todas_noticias.append({
                "fecha": "",
                "titulo": n["titulo"],
                "url": n.get("url", ""),
                "es_pdf": n.get("es_pdf", False),
                "tipo_seccion": n.get("tipo_seccion", ""),
                "institucion": inst["nombre"],
                "pais": pais,
                "region": inst.get("region", ""),
                "tipo": inst["tipo"],
                "color": color,
                "con_fecha": False,
            })

    todas_noticias.sort(key=lambda x: x["fecha"], reverse=True)

    markers_j  = json.dumps(markers,        ensure_ascii=False)
    noticias_j = json.dumps(todas_noticias, ensure_ascii=False)
    fecha_gen  = datetime.utcnow().strftime("%d/%m/%Y %H:%M UTC")

    inst_all_j = json.dumps([{
        "nombre": i["nombre"], "pais": i["pais"],
        "region": i.get("region", ""),
        "tipo": i["tipo"],
        "n_periodo": len(i.get("items_en_periodo", [])),
        "n_sin_fecha": len(i.get("items_sin_fecha", [])),
        "ok": bool(i.get("secciones_scrapeadas")),
        "error": i.get("error", ""),
        "url": i.get("url_base", ""),
    } for i in instituciones], ensure_ascii=False)

    n_con_fecha = sum(1 for n in todas_noticias if n["con_fecha"])
    n_sin_fecha = sum(1 for n in todas_noticias if not n["con_fecha"])
    n_pdfs      = sum(1 for n in todas_noticias if n["es_pdf"])
    n_inst_ok   = sum(1 for i in instituciones if i.get("secciones_scrapeadas"))

    colores_sec_j = json.dumps(COLORES_SECCION, ensure_ascii=False)

    html = f"""<!DOCTYPE html>
<html lang="es" id="root">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Notas de Prensa — Defensorías de las Américas (últimos {dias} días)</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
{'<link rel="alternate" type="application/atom+xml" title="Feed Atom — todas las instituciones" href="' + feed_url + '">' if feed_url else ''}
{'<link rel="alternate" type="application/feed+json" title="JSON Feed — todas las instituciones" href="' + feed_url.replace("feed.xml","feed.json") + '">' if feed_url else ''}
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Segoe UI',system-ui,sans-serif;background:#0d1b2a;color:#dce8f0}}
header{{background:linear-gradient(135deg,#132334,#0d1b2a);border-bottom:2px solid #1e3a52;
  padding:14px 22px;display:flex;align-items:flex-start;gap:20px;flex-wrap:wrap}}
header h1{{font-size:1.05rem;font-weight:700;color:#64b5e8;flex:1;min-width:180px}}
header p{{font-size:.75rem;color:#7a8fa0;margin-top:3px}}
.stats{{display:flex;gap:10px;flex-wrap:wrap;align-items:center}}
.stat{{background:#132334;border:1px solid #1e3a52;border-radius:8px;padding:7px 14px;text-align:center}}
.stat .n{{font-size:1.3rem;font-weight:700;color:#64b5e8}}
.stat .l{{font-size:.68rem;color:#7a8fa0;text-transform:uppercase;letter-spacing:.04em}}

.tabs{{display:flex;background:#0d1822;border-bottom:2px solid #1a3045}}
.tab{{padding:11px 22px;cursor:pointer;font-size:.83rem;color:#7a8fa0;border:none;
  background:none;border-bottom:2px solid transparent;margin-bottom:-2px;transition:all .2s;
  display:inline-flex;align-items:center;gap:6px}}
.tab:hover{{color:#64b5e8}}.tab.on{{color:#64b5e8;border-bottom-color:#64b5e8;font-weight:600}}
.tab svg{{flex-shrink:0}}

.panel{{display:none}}.panel.on{{display:block}}
#map{{height:calc(100vh - 195px);width:100%}}
.map-search{{position:relative;padding:8px 12px;background:#0d1822;border-bottom:1px solid #1a3045;display:flex;gap:8px;align-items:center}}
.map-search input{{flex:1;background:#132334;border:1px solid #1e3a52;color:#dce8f0;padding:6px 11px;border-radius:6px;font-size:.82rem;outline:none}}
.map-search input:focus{{border-color:#64b5e8}}
.map-search .ms-count{{font-size:.72rem;color:#5a7a90;white-space:nowrap}}
#ptl,#ptb{{padding:18px 22px;max-height:calc(100vh - 160px);overflow-y:auto}}

.filtros{{display:flex;gap:8px;margin-bottom:14px;flex-wrap:wrap;align-items:center}}
.filtros input,.filtros select{{
  background:#132334;border:1px solid #1e3a52;color:#dce8f0;
  padding:7px 11px;border-radius:6px;font-size:.82rem;outline:none}}
.filtros input{{flex:1;min-width:160px}}
.filtros input:focus,.filtros select:focus{{border-color:#64b5e8}}
#tl-cnt,#tb-cnt{{font-size:.75rem;color:#7a8fa0;padding:4px 0 10px}}

.dg{{margin-bottom:22px}}
.dg-titulo{{font-size:.88rem;font-weight:700;color:#64b5e8;
  border-bottom:1px solid #1a3045;padding-bottom:5px;margin-bottom:8px}}
.card{{background:#132334;border:1px solid #1e3a52;border-left:4px solid;
  border-radius:6px;padding:10px 13px;margin-bottom:6px;transition:background .15s}}
.card:hover{{background:#1a3045}}
.card .ct{{font-size:.85rem;color:#c0d4e8;margin-bottom:4px;line-height:1.4}}
.card .ct a{{color:inherit;text-decoration:none}}.card .ct a:hover{{color:#64b5e8;text-decoration:underline}}
.card .cm{{font-size:.72rem;color:#5a7a90;display:flex;gap:8px;flex-wrap:wrap;align-items:center}}
.tag{{display:inline-block;padding:2px 7px;border-radius:3px;font-size:.65rem;font-weight:600;color:#fff;opacity:.9}}
.sec-tag{{display:inline-block;padding:1px 6px;border-radius:3px;font-size:.65rem;
  color:#a0b8c8;background:#1a3045;border:1px solid #2a4a60}}
.pdf-tag{{background:#c0392b;font-size:.65rem;padding:1px 5px;border-radius:3px;color:#fff}}

table{{width:100%;border-collapse:collapse;font-size:.8rem}}
thead th{{background:#132334;color:#64b5e8;padding:9px 11px;text-align:left;
  font-weight:600;border-bottom:2px solid #1e3a52;position:sticky;top:0;cursor:pointer;white-space:nowrap}}
thead th:hover{{background:#1a3045}}
tbody tr{{border-bottom:1px solid #112030;transition:background .1s}}
tbody tr:hover{{background:#1a3045}}
tbody td{{padding:8px 11px;vertical-align:top}}
tbody td a{{color:#64b5e8;text-decoration:none}}tbody td a:hover{{text-decoration:underline}}
.fc{{background:#132334;border:1px solid #1e3a52;border-radius:3px;
  padding:2px 7px;font-size:.72rem;color:#a0b8c8;white-space:nowrap}}
.sf{{color:#3a5a70;font-style:italic;font-size:.72rem}}

.leaflet-popup-content-wrapper{{background:#132334;color:#dce8f0;
  border:1px solid #1e3a52;border-radius:8px;box-shadow:0 4px 18px rgba(0,0,0,.6)}}
.leaflet-popup-tip{{background:#132334}}
.leaflet-popup-content{{font-family:'Segoe UI',sans-serif;font-size:.8rem}}
.pt{{font-weight:700;color:#64b5e8;margin-bottom:3px;font-size:.88rem}}
.pp{{color:#7a8fa0;font-size:.72rem;margin-bottom:6px}}
.plist{{list-style:none}}
.plist li{{padding:3px 0;border-bottom:1px solid #1a3045;line-height:1.3}}
.plist li:last-child{{border-bottom:none}}
.plist a{{color:#90c8e8;text-decoration:none}}.plist a:hover{{text-decoration:underline}}
.pfecha{{color:#4a6a80;font-size:.68rem;display:block}}
.plink{{display:block;margin-top:6px;color:#64b5e8;text-decoration:none;font-size:.75rem}}
.perr{{color:#c0392b;font-size:.72rem}}
.legend{{background:#132334;border:1px solid #1e3a52;border-radius:8px;padding:9px 13px;font-size:.75rem}}
.legend h4{{color:#64b5e8;margin-bottom:6px;font-size:.77rem}}
.li{{display:flex;align-items:center;gap:6px;margin-bottom:3px}}
.ld{{width:11px;height:11px;border-radius:50%;flex-shrink:0}}
::-webkit-scrollbar{{width:7px}}
::-webkit-scrollbar-track{{background:#0d1b2a}}
::-webkit-scrollbar-thumb{{background:#1e3a52;border-radius:4px}}
.lang-sw{{display:flex;gap:4px;align-items:center;margin-left:auto}}
.lb{{background:none;border:1px solid #1e3a52;color:#7a8fa0;padding:3px 9px;
  border-radius:4px;font-size:.73rem;font-weight:600;cursor:pointer;transition:all .15s}}
.lb:hover{{border-color:#64b5e8;color:#64b5e8}}.lb.on{{border-color:#64b5e8;color:#64b5e8;background:#132334}}
.rss-btn{{display:inline-flex;align-items:center;gap:5px;padding:4px 11px;
  border-radius:4px;font-size:.73rem;font-weight:600;text-decoration:none;
  background:#b34700;color:#fff;border:1px solid #e05a00;transition:background .15s}}
.rss-btn:hover{{background:#e05a00}}
.stat-link{{cursor:pointer}}
.stat-link:hover .n{{color:#90d0f0}}
.stat-link:hover{{border-color:#3a6a90}}
.modal-bg{{display:none;position:fixed;inset:0;background:rgba(0,0,0,.7);z-index:9000;align-items:center;justify-content:center}}
.modal-bg.on{{display:flex}}
.modal{{background:#132334;border:1px solid #1e3a52;border-radius:10px;
  width:min(820px,95vw);max-height:85vh;display:flex;flex-direction:column;overflow:hidden}}
.modal-hdr{{display:flex;align-items:center;justify-content:space-between;
  padding:14px 18px;border-bottom:1px solid #1e3a52}}
.modal-hdr h3{{font-size:.9rem;color:#64b5e8;margin:0}}
.modal-close{{background:none;border:none;color:#7a8fa0;font-size:1.3rem;cursor:pointer;line-height:1}}
.modal-close:hover{{color:#dce8f0}}
.modal-body{{overflow-y:auto;padding:12px 18px}}
.inst-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:8px}}
.inst-card{{background:#0d1b2a;border:1px solid #1e3a52;border-radius:6px;
  padding:9px 12px;display:flex;flex-direction:column;gap:3px}}
.inst-card.ok{{border-left:3px solid #27ae60}}
.inst-card.nok{{border-left:3px solid #c0392b;opacity:.7}}
.ic-name{{font-size:.82rem;color:#c0d4e8;line-height:1.3}}
.ic-name a{{color:inherit;text-decoration:none}}.ic-name a:hover{{color:#64b5e8}}
.ic-meta{{font-size:.7rem;color:#5a7a90;display:flex;gap:6px;flex-wrap:wrap}}
.ic-n{{font-weight:700;color:#64b5e8}}
</style>
</head>
<body>
<header>
  <div>
    <h1 id="pg-title">Notas de Prensa y Comunicados — Defensorías de las Américas</h1>
    <p><span id="pg-gen">Generado</span>: {fecha_gen} &nbsp;·&nbsp;
       <span id="pg-win">Ventana</span>: {dias} <span id="pg-days">días</span> &nbsp;·&nbsp;
       {n_inst_ok} <span id="pg-acc">instituciones accesibles</span></p>
  </div>
  <div class="stats">
    <div class="stat stat-link" onclick="openInstModal()" title="Ver todas las instituciones"><div class="n">{len(instituciones)}</div><div class="l" id="sl-inst">Instituciones</div></div>
    <div class="stat"><div class="n">{n_con_fecha}</div><div class="l" id="sl-cf">Con fecha</div></div>
    <div class="stat"><div class="n">{n_sin_fecha}</div><div class="l" id="sl-sf">Sin fecha</div></div>
    <div class="stat"><div class="n">{n_pdfs}</div><div class="l">PDFs</div></div>
  </div>
  <div class="lang-sw">
    {'<a href="' + feed_url + '" class="rss-btn" title="Assinar feed RSS/Atom — cole esta URL no seu leitor de feeds">&#9656; RSS</a>' if feed_url else ''}
    <button class="lb on" id="lb-es" onclick="setLang('es')">ES</button>
    <button class="lb"    id="lb-en" onclick="setLang('en')">EN</button>
    <button class="lb"    id="lb-pt" onclick="setLang('pt')">PT</button>
    <button class="lb"    id="lb-fr" onclick="setLang('fr')">FR</button>
  </div>
</header>

<div class="modal-bg" id="inst-modal" onclick="if(event.target===this)closeInstModal()">
  <div class="modal">
    <div class="modal-hdr">
      <h3 id="inst-modal-title">Instituciones monitoreadas</h3>
      <button class="modal-close" onclick="closeInstModal()">&#x2715;</button>
    </div>
    <div class="modal-body" id="inst-modal-body"></div>
  </div>
</div>

<div class="tabs">
  <button class="tab on" id="tab-mapa" onclick="sw('mapa',this)"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="3 6 9 3 15 6 21 3 21 18 15 21 9 18 3 21"/><line x1="9" y1="3" x2="9" y2="18"/><line x1="15" y1="6" x2="15" y2="21"/></svg><span id="tab-mapa-lbl">Mapa</span></button>
  <button class="tab"    id="tab-tl"   onclick="sw('tl',this)"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg><span id="tab-tl-lbl">Timeline</span></button>
  <button class="tab"    id="tab-tb"   onclick="sw('tb',this)"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="1"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="3" y1="15" x2="21" y2="15"/><line x1="9" y1="9" x2="9" y2="21"/></svg><span id="tab-tb-lbl">Tabla</span></button>
</div>

<div id="pmapa" class="panel on">
  <div class="map-search">
    <input id="map-q" type="search" placeholder="Buscar institución, país o titular..." oninput="filtrarMapa(this.value)" autocomplete="off">
    <span class="ms-count" id="map-cnt"></span>
  </div>
  <div id="map"></div>
</div>

<div id="ptl" class="panel">
  <div class="filtros">
    <input id="tl-q" placeholder="Buscar titular o institución..." oninput="ftl()">
    <select id="tl-r" onchange="ftl()"><option value="" id="tl-r-all">Todas las regiones</option></select>
    <select id="tl-p" onchange="ftl()"><option value="" id="tl-p-all">Todos los países</option></select>
    <select id="tl-t" onchange="ftl()"><option value="" id="tl-t-all">Todos los tipos</option></select>
    <select id="tl-s" onchange="ftl()">
      <option value=""            id="tl-s-all">Todas las secciones</option>
      <option value="comunicados">Comunicados</option>
      <option value="notas_prensa">Notas de prensa</option>
      <option value="press_release">Press releases</option>
      <option value="prensa">Prensa / Imprensa</option>
      <option value="boletines">Boletines</option>
      <option value="noticias">Noticias</option>
      <option value="pdf">PDFs</option>
    </select>
    <select id="tl-f" onchange="ftl()">
      <option value=""   id="tl-f-all">Todas</option>
      <option value="si" id="tl-f-si">Con fecha confirmada</option>
      <option value="no" id="tl-f-no">Sin fecha detectada</option>
    </select>
  </div>
  <div id="tl-cnt"></div>
  <div id="tl-body"></div>
</div>

<div id="ptb" class="panel">
  <div class="filtros">
    <input id="tb-q" placeholder="Buscar..." oninput="ftb()">
    <select id="tb-r" onchange="ftb()"><option value="" id="tb-r-all">Todas las regiones</option></select>
    <select id="tb-p" onchange="ftb()"><option value="" id="tb-p-all">Todos los países</option></select>
    <select id="tb-t" onchange="ftb()"><option value="" id="tb-t-all">Todos los tipos</option></select>
    <select id="tb-f" onchange="ftb()">
      <option value=""    id="tb-f-all">Todas</option>
      <option value="si"  id="tb-f-si">Con fecha</option>
      <option value="no"  id="tb-f-no">Sin fecha</option>
      <option value="pdf" id="tb-f-pdf">Solo PDFs</option>
    </select>
  </div>
  <table><thead><tr>
    <th id="th-0" onclick="srt(0)">Fecha ↕</th>
    <th id="th-1" onclick="srt(1)">Titular ↕</th>
    <th id="th-2" onclick="srt(2)">Sección ↕</th>
    <th id="th-3" onclick="srt(3)">Institución ↕</th>
    <th id="th-4" onclick="srt(4)">País ↕</th>
    <th id="th-5" onclick="srt(5)">Región ↕</th>
  </tr></thead><tbody id="tb-body"></tbody></table>
</div>

<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const MK   = {markers_j};
const NN   = {noticias_j};
const DIAS = {dias};
const COLORES_SECCION = {colores_sec_j};
const INST_ALL = {inst_all_j};
const FEED_BASE = '{feed_url.rsplit("/", 1)[0] + "/" if feed_url else ""}';

// ── Traducciones ──────────────────────────────────────────────────────────────
const LANGS = {{
  es: {{
    title:"Notas de Prensa y Comunicados — Defensorías de las Américas",
    tab_map:"Mapa", tab_tl:"Timeline", tab_tb:"Tabla",
    sl_inst:"Instituciones", sl_cf:"Con fecha", sl_sf:"Sin fecha",
    pg_gen:"Generado", pg_win:"Ventana", pg_days:"días", pg_acc:"instituciones accesibles",
    ph_tl:"Buscar titular o institución...", ph_tb:"Buscar...",
    all_r:"Todas las regiones", all_p:"Todos los países", all_t:"Todos los tipos",
    all_s:"Todas las secciones", all_f:"Todas", f_si:"Con fecha confirmada",
    f_no:"Sin fecha detectada", f_pdf:"Solo PDFs", f_si2:"Con fecha", f_no2:"Sin fecha",
    th:["Fecha ↕","Titular ↕","Sección ↕","Institución ↕","País ↕","Región ↕"],
    npubs: n=>`${{n}} publicaciones`,
    noresults:"Sin resultados.",
    nodate_grp:"Sin fecha detectada",
    nodate_lbl:"Sin fechas detectadas:",
    nopubs: d=>`Sin publicaciones en ${{d}} días`,
    noaccess:"⚠ Sin acceso",
    plus_sf: n=>`+${{n}} sin fecha`,
    site:"→ Sitio oficial",
    leg_title:"Tipo de institución", leg_note:"Número = publicaciones recientes",
    meses:['ene','feb','mar','abr','may','jun','jul','ago','sep','oct','nov','dic'],
  }},
  en: {{
    title:"Press Releases & Communiqués — Ombudspersons of the Americas",
    tab_map:"Map", tab_tl:"Timeline", tab_tb:"Table",
    sl_inst:"Institutions", sl_cf:"Dated", sl_sf:"Undated",
    pg_gen:"Generated", pg_win:"Window", pg_days:"days", pg_acc:"institutions accessible",
    ph_tl:"Search headline or institution...", ph_tb:"Search...",
    all_r:"All regions", all_p:"All countries", all_t:"All types",
    all_s:"All sections", all_f:"All", f_si:"Dated only",
    f_no:"Undated only", f_pdf:"PDFs only", f_si2:"Dated", f_no2:"Undated",
    th:["Date ↕","Headline ↕","Section ↕","Institution ↕","Country ↕","Region ↕"],
    npubs: n=>`${{n}} publications`,
    noresults:"No results.",
    nodate_grp:"No date detected",
    nodate_lbl:"No dates detected:",
    nopubs: d=>`No publications in the last ${{d}} days`,
    noaccess:"⚠ No access",
    plus_sf: n=>`+${{n}} undated`,
    site:"→ Official website",
    leg_title:"Institution type", leg_note:"Number = recent publications",
    meses:['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'],
  }},
  pt: {{
    title:"Notas de Imprensa e Comunicados — Defensorias das Américas",
    tab_map:"Mapa", tab_tl:"Linha do tempo", tab_tb:"Tabela",
    sl_inst:"Instituições", sl_cf:"Com data", sl_sf:"Sem data",
    pg_gen:"Gerado", pg_win:"Janela", pg_days:"dias", pg_acc:"instituições acessíveis",
    ph_tl:"Buscar título ou instituição...", ph_tb:"Buscar...",
    all_r:"Todas as regiões", all_p:"Todos os países", all_t:"Todos os tipos",
    all_s:"Todas as seções", all_f:"Todas", f_si:"Com data confirmada",
    f_no:"Sem data detectada", f_pdf:"Somente PDFs", f_si2:"Com data", f_no2:"Sem data",
    th:["Data ↕","Título ↕","Seção ↕","Instituição ↕","País ↕","Região ↕"],
    npubs: n=>`${{n}} publicações`,
    noresults:"Sem resultados.",
    nodate_grp:"Sem data detectada",
    nodate_lbl:"Sem datas detectadas:",
    nopubs: d=>`Sem publicações nos últimos ${{d}} dias`,
    noaccess:"⚠ Sem acesso",
    plus_sf: n=>`+${{n}} sem data`,
    site:"→ Site oficial",
    leg_title:"Tipo de instituição", leg_note:"Número = publicações recentes",
    meses:['jan','fev','mar','abr','mai','jun','jul','ago','set','out','nov','dez'],
  }},
  fr: {{
    title:"Communiqués de presse — Défenseurs des droits des Amériques",
    tab_map:"Carte", tab_tl:"Chronologie", tab_tb:"Tableau",
    sl_inst:"Institutions", sl_cf:"Datés", sl_sf:"Sans date",
    pg_gen:"Généré", pg_win:"Fenêtre", pg_days:"jours", pg_acc:"institutions accessibles",
    ph_tl:"Rechercher un titre ou institution...", ph_tb:"Rechercher...",
    all_r:"Toutes les régions", all_p:"Tous les pays", all_t:"Tous les types",
    all_s:"Toutes les sections", all_f:"Tous", f_si:"Avec date confirmée",
    f_no:"Sans date détectée", f_pdf:"PDFs seulement", f_si2:"Datés", f_no2:"Sans date",
    th:["Date ↕","Titre ↕","Section ↕","Institution ↕","Pays ↕","Région ↕"],
    npubs: n=>`${{n}} publications`,
    noresults:"Aucun résultat.",
    nodate_grp:"Sans date détectée",
    nodate_lbl:"Sans dates détectées :",
    nopubs: d=>`Aucune publication dans les ${{d}} derniers jours`,
    noaccess:"⚠ Pas d'accès",
    plus_sf: n=>`+${{n}} sans date`,
    site:"→ Site officiel",
    leg_title:"Type d'institution", leg_note:"Nombre = publications récentes",
    meses:['jan','fév','mar','avr','mai','jun','jul','aoû','sep','oct','nov','déc'],
  }},
}};

let T = LANGS['es'];

function setLang(code) {{
  T = LANGS[code] || LANGS['es'];
  document.getElementById('root').lang = code;
  // Elementos estáticos
  document.getElementById('pg-title').textContent = T.title;
  document.getElementById('pg-gen').textContent   = T.pg_gen;
  document.getElementById('pg-win').textContent   = T.pg_win;
  document.getElementById('pg-days').textContent  = T.pg_days;
  document.getElementById('pg-acc').textContent   = T.pg_acc;
  document.getElementById('sl-inst').textContent  = T.sl_inst;
  document.getElementById('sl-cf').textContent    = T.sl_cf;
  document.getElementById('sl-sf').textContent    = T.sl_sf;
  document.getElementById('tab-mapa-lbl').textContent = T.tab_map;
  document.getElementById('tab-tl-lbl').textContent   = T.tab_tl;
  document.getElementById('tab-tb-lbl').textContent   = T.tab_tb;
  // Placeholders
  document.getElementById('tl-q').placeholder = T.ph_tl;
  document.getElementById('tb-q').placeholder = T.ph_tb;
  // Selects — opciones estáticas
  const sf = {{
    'tl-r-all':T.all_r,'tb-r-all':T.all_r,
    'tl-p-all':T.all_p,'tb-p-all':T.all_p,
    'tl-t-all':T.all_t,'tb-t-all':T.all_t,
    'tl-s-all':T.all_s,
    'tl-f-all':T.all_f,'tb-f-all':T.all_f,
    'tl-f-si':T.f_si,'tl-f-no':T.f_no,
    'tb-f-si':T.f_si2,'tb-f-no':T.f_no2,'tb-f-pdf':T.f_pdf,
  }};
  Object.entries(sf).forEach(([id,txt])=>{{const el=document.getElementById(id);if(el)el.textContent=txt;}});
  // Cabeceras tabla
  T.th.forEach((txt,i)=>{{const el=document.getElementById('th-'+i);if(el)el.textContent=txt;}});
  // Lang buttons
  document.querySelectorAll('.lb').forEach(b=>b.classList.toggle('on',b.id==='lb-'+code));
  // Re-render dinámico
  ftl(); ftb();
  // Leyenda del mapa
  if(window._legEl) window._legEl.innerHTML = buildLegend();
}}

// ── Mapa ─────────────────────────────────────────────────────────────────────
function sw(name, btn) {{
  document.querySelectorAll('.panel').forEach(p=>p.classList.remove('on'));
  document.querySelectorAll('.tab').forEach(b=>b.classList.remove('on'));
  document.getElementById('p'+name).classList.add('on');
  btn.classList.add('on');
  if(name==='mapa') map.invalidateSize();
}}

const map = L.map('map',{{center:[2,-65],zoom:3}});
L.tileLayer('https://{{s}}.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}{{r}}.png',{{
  attribution:'&copy; CARTO',subdomains:'abcd',maxZoom:19}}).addTo(map);

function mkIcon(color, count, err) {{
  const s  = count>0 ? Math.min(36,18+count*2.5) : 16;
  const ph = Math.round(s * 1.5);
  const op = err ? .25 : count>0 ? 1 : .5;
  const badge = count>0 ? `<div style="position:absolute;top:-8px;right:-8px;
    background:#e74c3c;color:#fff;border-radius:50%;width:17px;height:17px;
    font-size:9px;font-weight:700;display:flex;align-items:center;
    justify-content:center;border:2px solid #0d1b2a;line-height:1">${{count}}</div>` : '';
  const pin = `<svg width="${{s}}" height="${{ph}}" viewBox="0 0 24 32" style="display:block">
    <path d="M12 0C7.6 0 4 3.6 4 8c0 5.3 8 20 8 20s8-14.7 8-20c0-4.4-3.6-8-8-8z"
      fill="${{color}}" stroke="rgba(255,255,255,.35)" stroke-width="1.2" opacity="${{op}}"/>
    <circle cx="12" cy="8.5" r="3.5" fill="rgba(255,255,255,.45)" opacity="${{op}}"/>
  </svg>`;
  return L.divIcon({{className:'',iconSize:[s,ph],iconAnchor:[s/2,ph],popupAnchor:[0,-(ph+2)],
    html:`<div style="position:relative">${{pin}}${{badge}}</div>`}});
}}

const _markers = [];
MK.forEach(m=>{{
  const ic = mkIcon(m.color, m.n_periodo, !!m.error);
  let html = `<div class="pt">${{m.nombre}}</div>
    <div class="pp">${{m.pais}} · ${{m.tipo}}</div>`;
  if(m.error) html+=`<div class="perr">${{T.noaccess}}</div>`;
  else if(m.items_periodo.length) {{
    html+=`<ul class="plist">`;
    m.items_periodo.slice(0,5).forEach(n=>{{
      const t = n.titulo.length>75?n.titulo.slice(0,72)+'…':n.titulo;
      const lnk = n.url?`<a href="${{n.url}}" target="_blank">${{t}}</a>`:t;
      const f = n.fecha?`<span class="pfecha">${{fmtF(n.fecha)}}</span>`:'';
      const pdf = n.es_pdf?'<span class="pdf-tag">PDF</span> ':'';
      const sc = n.tipo_seccion?`<span style="color:#3a5a70;font-size:.65rem"> [${{n.tipo_seccion}}]</span>`:'';
      html+=`<li>${{f}}${{pdf}}${{lnk}}${{sc}}</li>`;
    }});
    html+='</ul>';
    if(m.n_sin_fecha>0) html+=`<div style="color:#4a6a80;font-size:.7rem;margin-top:3px">${{T.plus_sf(m.n_sin_fecha)}}</div>`;
  }} else if(m.items_sin_fecha.length) {{
    html+=`<div style="color:#5a7a90;font-size:.73rem;margin-bottom:4px">${{T.nodate_lbl}}</div><ul class="plist">`;
    m.items_sin_fecha.slice(0,3).forEach(n=>{{
      const t=n.titulo.length>65?n.titulo.slice(0,62)+'…':n.titulo;
      html+=`<li>${{n.url?`<a href="${{n.url}}" target="_blank">${{t}}</a>`:t}}</li>`;
    }});
    html+='</ul>';
  }} else {{
    html+=`<div style="color:#4a6a80;font-style:italic">${{T.nopubs(DIAS)}}</div>`;
  }}
  if(m.secciones.length>0)
    html+=`<div style="color:#3a6080;font-size:.68rem;margin-top:5px">
      ${{m.secciones.map(s=>s.tipo).join(', ')}}</div>`;
  html+=`<a class="plink" href="${{m.url}}" target="_blank">${{T.site}}</a>`;
  const mk = L.marker([m.lat,m.lon],{{icon:ic}}).addTo(map).bindPopup(html,{{maxWidth:360}});
  _markers.push({{lf:mk, m}});
}});

function filtrarMapa(q) {{
  const term = q.trim().toLowerCase();
  let vis = 0;
  _markers.forEach(({{lf, m}}) => {{
    const match = !term ||
      m.nombre.toLowerCase().includes(term) ||
      m.pais.toLowerCase().includes(term) ||
      m.tipo.toLowerCase().includes(term) ||
      m.items_periodo.some(n => n.titulo.toLowerCase().includes(term));
    lf.setOpacity(match ? 1 : 0.08);
    if(match) vis++;
  }});
  const cnt = document.getElementById('map-cnt');
  if(cnt) cnt.textContent = term ? `${{vis}} / ${{_markers.length}}` : '';
}}

// ── Modal de instituciones ────────────────────────────────────────────────────
function openInstModal() {{
  const modal = document.getElementById('inst-modal');
  const body  = document.getElementById('inst-modal-body');
  document.getElementById('inst-modal-title').textContent =
    T.sl_inst + ' — ' + INST_ALL.length;

  const byRegion = {{}};
  INST_ALL.forEach(i => {{
    if(!byRegion[i.region]) byRegion[i.region] = [];
    byRegion[i.region].push(i);
  }});

  let html = '';
  Object.keys(byRegion).sort().forEach(reg => {{
    html += `<div style="margin-bottom:14px">
      <div style="font-size:.72rem;font-weight:700;color:#64b5e8;
        text-transform:uppercase;letter-spacing:.08em;margin-bottom:6px">${{reg}}</div>
      <div class="inst-grid">`;
    byRegion[reg].sort((a,b)=>a.pais.localeCompare(b.pais)).forEach(i => {{
      const acc = i.ok ? 'ok' : 'nok';
      const badge = i.n_periodo > 0
        ? `<span class="ic-n">${{i.n_periodo}}</span>`
        : (i.ok ? '<span style="color:#3a6a50;font-size:.68rem">0</span>' : '<span style="color:#c0392b;font-size:.68rem">✗</span>');
      const name = i.url
        ? `<a href="${{i.url}}" target="_blank">${{i.nombre}}</a>`
        : i.nombre;
      const slug = i.pais.toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g,'').replace(/[^a-z0-9]+/g,'-').replace(/^-|-$/g,'');
      const feedLink = FEED_BASE && i.n_periodo > 0
        ? `<a href="${{FEED_BASE}}feed-${{slug}}.xml" target="_blank" title="Feed RSS deste país" style="color:#b34700;font-size:.65rem;text-decoration:none">&#9656;RSS</a>`
        : '';
      html += `<div class="inst-card ${{acc}}">
        <div class="ic-name">${{name}}</div>
        <div class="ic-meta">
          <span>${{i.pais}}</span>
          <span style="color:#3a5a70">${{i.tipo}}</span>
          ${{badge}}
          ${{feedLink}}
        </div>
      </div>`;
    }});
    html += '</div></div>';
  }});
  body.innerHTML = html;
  modal.classList.add('on');
}}
function closeInstModal() {{
  document.getElementById('inst-modal').classList.remove('on');
}}
document.addEventListener('keydown', e => {{ if(e.key==='Escape') closeInstModal(); }});

function buildLegend() {{
  return '<h4>'+T.leg_title+'</h4>'+
    Object.entries({{"Ombudsperson":"#e74c3c","Defensoria Pública":"#2980b9",
      "Red Regional":"#8e44ad","Org. Internacional":"#16a085"}})
    .map(([k,c])=>`<div class="li"><div class="ld" style="background:${{c}}"></div><span>${{k}}</span></div>`)
    .join('')+
    `<hr style="border-color:#1e3a52;margin:7px 0">
    <div style="font-size:.68rem;color:#4a6a80">${{T.leg_note}}</div>`;
}}

const leg = L.control({{position:'bottomright'}});
leg.onAdd=function(){{
  const d=L.DomUtil.create('div','legend');
  d.innerHTML=buildLegend();
  window._legEl=d;
  return d;
}};
leg.addTo(map);

// ── Helpers fecha ─────────────────────────────────────────────────────────────
function fmtF(iso) {{
  if(!iso) return '—';
  const [y,m,d]=iso.split('T')[0].split('-');
  return `${{d}}/${{m}}/${{y}}`;
}}
function fmtFLg(iso) {{
  const [y,m,d]=iso.split('T')[0].split('-');
  return `${{parseInt(d)}} ${{T.meses[parseInt(m)-1]}} ${{y}}`;
}}

// ── Selects dinámicos ─────────────────────────────────────────────────────────
const regiones=[...new Set(NN.map(n=>n.region))].sort();
const paises  =[...new Set(NN.map(n=>n.pais))  ].sort();
const tipos   =[...new Set(NN.map(n=>n.tipo))   ].sort();

['tl-r','tb-r'].forEach(id=>{{
  const s=document.getElementById(id);
  regiones.forEach(r=>{{const o=document.createElement('option');o.value=r;o.textContent=r;s.appendChild(o)}});
}});
['tl-p','tb-p'].forEach(id=>{{
  const s=document.getElementById(id);
  paises.forEach(p=>{{const o=document.createElement('option');o.value=p;o.textContent=p;s.appendChild(o)}});
}});
['tl-t','tb-t'].forEach(id=>{{
  const s=document.getElementById(id);
  tipos.forEach(t=>{{const o=document.createElement('option');o.value=t;o.textContent=t;s.appendChild(o)}});
}});

// ── Filtrado ──────────────────────────────────────────────────────────────────
function filtrar(q,r,p,t,s,f) {{
  return NN.filter(n=>{{
    if(r && n.region!==r) return false;
    if(p && n.pais!==p) return false;
    if(t && n.tipo!==t) return false;
    if(s==='pdf' && !n.es_pdf) return false;
    if(s && s!=='pdf' && !n.tipo_seccion.includes(s)) return false;
    if(f==='si' && !n.con_fecha) return false;
    if(f==='no' && n.con_fecha) return false;
    if(q) {{const qL=q.toLowerCase();
      return n.titulo.toLowerCase().includes(qL)||n.institucion.toLowerCase().includes(qL);}}
    return true;
  }});
}}

function ftl() {{
  renderTL(filtrar(
    document.getElementById('tl-q').value,
    document.getElementById('tl-r').value,
    document.getElementById('tl-p').value,
    document.getElementById('tl-t').value,
    document.getElementById('tl-s').value,
    document.getElementById('tl-f').value,
  ));
}}

function renderTL(items) {{
  document.getElementById('tl-cnt').textContent = T.npubs(items.length);
  if(!items.length) {{
    document.getElementById('tl-body').innerHTML=`<p style="color:#4a6a80;padding:16px">${{T.noresults}}</p>`;
    return;
  }}
  const grupos={{}};
  items.forEach(n=>{{const k=n.fecha?n.fecha.split('T')[0]:'__sf';
    if(!grupos[k])grupos[k]=[];grupos[k].push(n);}});
  const keys=Object.keys(grupos).sort().reverse();
  document.getElementById('tl-body').innerHTML=keys.map(k=>{{
    const grp=grupos[k];
    const tit=k==='__sf'?T.nodate_grp:fmtFLg(k);
    const cards=grp.map(n=>{{
      const pdf=n.es_pdf?'<span class="pdf-tag">PDF</span> ':'';
      const lnk=n.url?`<a href="${{n.url}}" target="_blank">${{n.titulo}}</a>`:n.titulo;
      const secC=COLORES_SECCION[n.tipo_seccion]||'#4a6a80';
      const sec=n.tipo_seccion?`<span class="sec-tag" style="border-color:${{secC}};color:${{secC}}">${{n.tipo_seccion}}</span>`:'';
      return `<div class="card" style="border-left-color:${{n.color}}">
        <div class="ct">${{pdf}}${{lnk}}</div>
        <div class="cm">
          <span class="tag" style="background:${{n.color}}">${{n.tipo}}</span>
          ${{sec}}<span>${{n.region}}</span><span>${{n.pais}}</span><span>${{n.institucion}}</span>
        </div></div>`;
    }}).join('');
    return `<div class="dg">
      <div class="dg-titulo">${{tit}} <span style="color:#3a5a70;font-weight:400">(${{grp.length}})</span></div>
      ${{cards}}</div>`;
  }}).join('');
}}
renderTL(NN);

// ── Tabela ────────────────────────────────────────────────────────────────────
let sCol=0, sAsc=false;
function srt(c){{if(sCol===c)sAsc=!sAsc;else{{sCol=c;sAsc=true;}}ftb();}}
function ftb() {{
  renderTB(filtrar(
    document.getElementById('tb-q').value,
    document.getElementById('tb-r').value,
    document.getElementById('tb-p').value,
    document.getElementById('tb-t').value,'',
    document.getElementById('tb-f').value,
  ));
}}
function renderTB(items) {{
  const keys=['fecha','titulo','tipo_seccion','institucion','pais','region'];
  const sorted=[...items].sort((a,b)=>{{
    const va=(a[keys[sCol]]||'').toString().toLowerCase();
    const vb=(b[keys[sCol]]||'').toString().toLowerCase();
    return sAsc?va.localeCompare(vb):vb.localeCompare(va);
  }});
  document.getElementById('tb-body').innerHTML=sorted.map(n=>{{
    const fecha=n.fecha?`<span class="fc">${{fmtF(n.fecha)}}</span>`:`<span class="sf">⚠ ${{T.sl_sf.toLowerCase()}}</span>`;
    const pdf=n.es_pdf?'<span class="pdf-tag">PDF</span> ':'';
    const lnk=n.url?`<a href="${{n.url}}" target="_blank">${{pdf}}${{n.titulo}}</a>`:`${{pdf}}${{n.titulo}}`;
    return `<tr><td>${{fecha}}</td><td>${{lnk}}</td>
      <td style="color:#5a7a90">${{n.tipo_seccion}}</td>
      <td>${{n.institucion}}</td><td>${{n.pais}}</td><td>${{n.region}}</td></tr>`;
  }}).join('');
}}
renderTB(NN);
</script>
</body>
</html>"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    log.info(f"Mapa HTML: {output_path}")


# ─── Main ─────────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(description="Scraper async de notas de prensa — Defensorías de las Américas")
    p.add_argument("--dias",          type=int,   default=30,              help="Ventana temporal en días (default: 30)")
    p.add_argument("--pais",                                               help="Filtrar por país")
    p.add_argument("--concurrencia",  type=int,   default=6,               help="Instituciones en paralelo (default: 6)")
    p.add_argument("--output",        default="prensa_latam",              help="Prefijo del archivo de salida")
    p.add_argument("--output-dir",    default=str(OUTPUT_DIR),             help="Directorio de salida")
    p.add_argument("--historico",     default="",                          help="Ruta del archivo JSONL histórico")
    p.add_argument("--feed-url",      default="",                          help="URL pública del feed Atom (para el <link> del HTML)")
    return p.parse_args()


async def run(args):
    instituciones = INSTITUCIONES_LATAM
    if args.pais:
        instituciones = [i for i in instituciones if args.pais.lower() in i["pais"].lower()]

    log.info(f"Scrapeando {len(instituciones)} instituciones — últimos {args.dias} días — concurrencia: {args.concurrencia}")

    sem = asyncio.Semaphore(args.concurrencia)
    connector = aiohttp.TCPConnector(ssl=False, limit=40)
    timeout = aiohttp.ClientTimeout(total=TIMEOUT)

    async with aiohttp.ClientSession(headers=HEADERS, connector=connector, timeout=timeout) as session:
        tasks = [
            scrapear_institucion(inst, session, args.dias, sem)
            for inst in instituciones
        ]
        raw = await asyncio.gather(*tasks, return_exceptions=True)

    resultados = []
    for inst, r in zip(instituciones, raw):
        if isinstance(r, Exception):
            log.error(f"  ERROR {inst['nombre']}: {r}")
            resultados.append({
                **{k: v for k, v in inst.items() if k != "secciones"},
                "secciones_scrapeadas": [], "todos_items": [],
                "items_en_periodo": [], "items_sin_fecha": [],
                "error": str(r), "timestamp": datetime.utcnow().isoformat(),
            })
        else:
            resultados.append(r)

    ts    = datetime.utcnow().strftime("%Y%m%d_%H%M")
    datos = {"dias": args.dias, "timestamp": ts, "instituciones": resultados}

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / f"{args.output}_{args.dias}d_{ts}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)

    # Copia como latest.json si el directorio es docs/data o similar
    latest_path = out_dir / "latest.json"
    with open(latest_path, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)

    html_path = out_dir / f"{args.output}_{args.dias}d_{ts}.html"
    feed_path = out_dir / "feed.xml"

    # Feed principal
    generar_feed_atom(datos, feed_path, site_url=args.feed_url)
    # JSON Feed principal
    generar_json_feed(datos, out_dir / "feed.json",
                      site_url=args.feed_url.replace("feed.xml", "feed.json") if args.feed_url else "")

    # Feeds por país (solo los que tienen publicaciones en el periodo)
    paises_activos  = sorted({i["pais"]           for i in datos["instituciones"] if i.get("items_en_periodo")})
    regiones_activas = sorted({i.get("region","") for i in datos["instituciones"] if i.get("items_en_periodo") and i.get("region")})

    for pais in paises_activos:
        slug = _slugify(pais)
        base = args.feed_url.rsplit("/", 1)[0] + "/" if args.feed_url else ""
        generar_feed_atom(datos, out_dir / f"feed-{slug}.xml",
                          site_url=f"{base}feed-{slug}.xml",
                          filtro_pais=pais, label=pais)
        generar_json_feed(datos, out_dir / f"feed-{slug}.json",
                          site_url=f"{base}feed-{slug}.json",
                          filtro_pais=pais, label=pais)

    for region in regiones_activas:
        slug = _slugify(region)
        base = args.feed_url.rsplit("/", 1)[0] + "/" if args.feed_url else ""
        generar_feed_atom(datos, out_dir / f"feed-{slug}.xml",
                          site_url=f"{base}feed-{slug}.xml",
                          filtro_region=region, label=region)

    generar_mapa(datos, html_path, feed_url=args.feed_url)

    # Copia como index.html si el directorio tiene pinta de docs/
    if "docs" in str(out_dir):
        index_path = out_dir.parent / "index.html" if out_dir.name == "data" else out_dir / "index.html"
        import shutil
        shutil.copy(html_path, index_path)
        log.info(f"index.html: {index_path}")

    if args.historico:
        guardar_historico(datos, Path(args.historico))
    else:
        guardar_historico(datos, out_dir / "historico.jsonl")

    total_c = sum(len(r["items_en_periodo"]) for r in resultados)
    total_s = sum(len(r["items_sin_fecha"])  for r in resultados)
    log.info(f"\nTotal: {total_c} publicações com data | {total_s} sem data")
    log.info(f"JSON:  {json_path}")
    log.info(f"HTML:  {html_path}")
    log.info(f"Feed:  {feed_path}")


if __name__ == "__main__":
    asyncio.run(run(parse_args()))
