"""
Scraper de noticias recientes de Defensorías y Ombudspersons de las Américas.
Extrae títulos, fechas y enlaces de publicaciones en los últimos N días.

Uso:
    python3 noticias_scraper.py               # últimos 14 días
    python3 noticias_scraper.py --dias 7
    python3 noticias_scraper.py --dias 30
    python3 noticias_scraper.py --pais Brasil
"""

import argparse
import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from instituciones import INSTITUCIONES

# ─── Config ────────────────────────────────────────────────────────────────────

TIMEOUT = 20
DELAY = 2.0
MAX_NOTICIAS_POR_SITIO = 20

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; DefensoriasResearchBot/1.0; "
        "+https://github.com/hub-humanitario)"
    ),
    "Accept-Language": "es-419,es;q=0.9,pt;q=0.8,en;q=0.7,fr;q=0.6",
}

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(OUTPUT_DIR / "noticias.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)


# ─── Rutas candidatas para secciones de noticias/prensa ───────────────────────

RUTAS_NOTICIAS = [
    "/noticias",
    "/news",
    "/prensa",
    "/sala-de-prensa",
    "/sala-prensa",
    "/comunicados",
    "/comunicados-de-prensa",
    "/novedades",
    "/actualidad",
    "/publicaciones",
    "/press",
    "/press-releases",
    "/newsroom",
    "/blog",
    "/boletin",
    "/boletines",
    "/avisos",
    "/informes",
    "/actualites",   # francés
    "/nouvelles",
    "/nouvelles-et-medias",
]

# Selectores para encontrar links de noticias en homepage
SELECTORES_LINKS_NOTICIAS = [
    "a[href*='noticia']",
    "a[href*='news']",
    "a[href*='prensa']",
    "a[href*='comunicado']",
    "a[href*='actualidad']",
    "a[href*='novedades']",
    "a[href*='publicacion']",
    "a[href*='boletin']",
    "a[href*='aviso']",
    "nav a",
]

# Selectores para items de noticia dentro de una página de listado
SELECTORES_ITEM_NOTICIA = [
    "article",
    ".noticia", ".news-item", ".news-card", ".press-item",
    ".entry", ".post", ".item-noticia",
    "li.views-row", "li.news-item",
    ".card", ".card-body",
    ".media-body",
    "tr",  # algunos sitios usan tablas
]

# Selectores para el título dentro de un item
SELECTORES_TITULO = [
    "h1", "h2", "h3", "h4",
    ".titulo", ".title", ".noticia-titulo",
    ".entry-title", ".card-title", ".post-title",
    "a",
]

# Selectores para la fecha dentro de un item
SELECTORES_FECHA = [
    "time", "time[datetime]",
    ".fecha", ".date", ".published", ".post-date",
    ".entry-date", ".news-date", ".created",
    "span.date", "span.fecha",
    ".meta", ".post-meta", ".article-meta",
    "abbr[title]",
]


# ─── Parseo de fechas ──────────────────────────────────────────────────────────

MESES_ES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4,
    "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
    "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
}
MESES_PT = {
    "janeiro": 1, "fevereiro": 2, "março": 3, "abril": 4,
    "maio": 5, "junho": 6, "julho": 7, "agosto": 8,
    "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12,
}
MESES_FR = {
    "janvier": 1, "février": 2, "mars": 3, "avril": 4,
    "mai": 5, "juin": 6, "juillet": 7, "août": 8,
    "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12,
}
MESES_EN = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4,
    "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
TODOS_MESES = {**MESES_ES, **MESES_PT, **MESES_FR, **MESES_EN}

YEAR_NOW = datetime.now().year


def parsear_fecha_de_url(url: str) -> datetime | None:
    """Extrae fecha de patrones comunes en URLs de CMS."""
    if not url:
        return None
    # /2026/05/11/ o /2026/05/
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
    # ?date=20260511 o &date=2026-05-11
    m = re.search(r"[?&](?:date|fecha|published)=(\d{4}[-/]\d{2}[-/]\d{2})", url)
    if m:
        return parsear_fecha(m.group(1))
    # /20260511- en slug
    m = re.search(r"/(\d{4})(\d{2})(\d{2})[_\-]", url)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    return None


def parsear_fecha(texto: str) -> datetime | None:
    if not texto:
        return None
    texto = texto.strip()

    # ISO: 2026-05-11T... o 2026-05-11
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", texto)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass

    # DD/MM/YYYY o DD-MM-YYYY
    m = re.search(r"(\d{1,2})[/\-\.](\d{1,2})[/\-\.](\d{4})", texto)
    if m:
        try:
            return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            pass

    # MM/DD/YYYY (inglés)
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", texto)
    if m:
        try:
            d = datetime(int(m.group(3)), int(m.group(1)), int(m.group(2)))
            if d.month <= 12:
                return d
        except ValueError:
            pass

    # "11 de mayo de 2026" / "11 mayo 2026" / "11 mai 2026" / "11 May 2026"
    texto_lower = texto.lower()
    m = re.search(
        r"(\d{1,2})\s+(?:de\s+)?([a-záéíóúàâêîôûäëïöü]+)(?:\s+de)?\s+(\d{4})",
        texto_lower,
    )
    if m:
        dia, mes_str, anio = int(m.group(1)), m.group(2), int(m.group(3))
        mes = TODOS_MESES.get(mes_str)
        if mes:
            try:
                return datetime(anio, mes, dia)
            except ValueError:
                pass

    # "May 11, 2026" / "May 11 2026"
    m = re.search(
        r"([a-záéíóúàâêîôûäëïöü]+)\s+(\d{1,2}),?\s+(\d{4})",
        texto_lower,
    )
    if m:
        mes_str, dia, anio = m.group(1), int(m.group(2)), int(m.group(3))
        mes = TODOS_MESES.get(mes_str)
        if mes:
            try:
                return datetime(anio, mes, dia)
            except ValueError:
                pass

    # Solo DD/MM (año implícito = actual)
    m = re.search(r"(\d{1,2})[/\-](\d{1,2})$", texto.strip())
    if m:
        try:
            return datetime(YEAR_NOW, int(m.group(2)), int(m.group(1)))
        except ValueError:
            pass

    return None


def extraer_fecha_de_tag(tag) -> datetime | None:
    # Primero atributos semánticos
    for attr in ["datetime", "content", "title"]:
        val = tag.get(attr, "")
        if val:
            d = parsear_fecha(val)
            if d:
                return d
    # Luego texto visible
    return parsear_fecha(tag.get_text(strip=True))


# ─── HTTP helpers ──────────────────────────────────────────────────────────────

def get_soup(url: str, session: requests.Session) -> BeautifulSoup | None:
    try:
        r = session.get(url, timeout=TIMEOUT, headers=HEADERS, allow_redirects=True)
        r.raise_for_status()
        return BeautifulSoup(r.text, "html.parser")
    except requests.exceptions.SSLError:
        try:
            r = session.get(url, timeout=TIMEOUT, headers=HEADERS, verify=False, allow_redirects=True)
            r.raise_for_status()
            return BeautifulSoup(r.text, "html.parser")
        except Exception as e:
            log.debug(f"SSL fallback falló {url}: {e}")
            return None
    except Exception as e:
        log.debug(f"Error {url}: {e}")
        return None


def encontrar_url_noticias(soup: BeautifulSoup, url_base: str) -> str | None:
    """Busca la sección de noticias/prensa en la homepage."""
    parsed = urlparse(url_base)
    origen = f"{parsed.scheme}://{parsed.netloc}"

    # 1. Prueba rutas canónicas directamente
    for ruta in RUTAS_NOTICIAS:
        candidata = origen + ruta
        # Primero busca si aparece en el HTML antes de hacer request
        for a in soup.find_all("a", href=True):
            href = a["href"]
            href_abs = urljoin(url_base, href)
            if ruta in href.lower() or ruta in href_abs.lower():
                return href_abs

    # 2. Busca links con palabras clave en el texto del anchor
    keywords = ["noticia", "news", "prensa", "comunicado", "actualidad",
                "novedades", "publicación", "publicacion", "boletín", "boletin",
                "actualités", "nouvelles", "press"]
    for a in soup.find_all("a", href=True):
        texto = a.get_text(strip=True).lower()
        href = a["href"]
        if any(kw in texto for kw in keywords) and len(href) > 1:
            href_abs = urljoin(url_base, href)
            # Evita links externos
            if parsed.netloc in href_abs:
                return href_abs

    return None


# ─── Extracción de noticias con fecha ─────────────────────────────────────────

def extraer_noticias_con_fecha(soup: BeautifulSoup, url_base: str) -> list[dict]:
    noticias = []
    vistas = set()

    # Estrategia A: busca contenedores de artículo
    for sel in SELECTORES_ITEM_NOTICIA:
        items = soup.select(sel)
        if len(items) < 2:
            continue

        for item in items:
            titulo = ""
            enlace = ""
            fecha = None

            # Busca fecha en el item
            for f_sel in SELECTORES_FECHA:
                ftag = item.select_one(f_sel)
                if ftag:
                    fecha = extraer_fecha_de_tag(ftag)
                    if fecha:
                        break
            # También busca en todo el texto del item patrones de fecha
            if not fecha:
                texto_item = item.get_text(" ", strip=True)
                fecha = parsear_fecha(texto_item)

            # Busca título y enlace
            for t_sel in SELECTORES_TITULO:
                ttag = item.select_one(t_sel)
                if ttag:
                    titulo = ttag.get_text(strip=True)
                    if ttag.name == "a":
                        enlace = ttag.get("href", "")
                    else:
                        a = ttag.find("a", href=True) or item.find("a", href=True)
                        if a:
                            enlace = a.get("href", "")
                    if titulo and len(titulo) > 8:
                        break

            if not titulo:
                titulo = item.get_text(separator=" ", strip=True)[:120]

            titulo = re.sub(r"\s+", " ", titulo).strip()
            if enlace:
                enlace = urljoin(url_base, enlace)

            # Extrae fecha de la URL si todavía no la tenemos
            if not fecha and enlace:
                fecha = parsear_fecha_de_url(enlace)

            if titulo and len(titulo) > 8 and titulo not in vistas:
                vistas.add(titulo)
                noticias.append({
                    "titulo": titulo,
                    "url": enlace,
                    "fecha": fecha.isoformat() if fecha else None,
                    "fecha_dt": fecha,
                })

        if len(noticias) >= MAX_NOTICIAS_POR_SITIO:
            break

    # Estrategia B: busca fechas en texto cercano a <h2>/<h3>
    if not noticias:
        for h in soup.find_all(["h2", "h3"])[:30]:
            titulo = h.get_text(strip=True)
            if len(titulo) < 8:
                continue

            a = h.find("a", href=True) or h.find_next("a", href=True)
            enlace = urljoin(url_base, a["href"]) if a else ""

            # Busca fecha en el padre o hermanos cercanos
            fecha = None
            parent = h.parent
            if parent:
                for f_sel in SELECTORES_FECHA:
                    ftag = parent.select_one(f_sel)
                    if ftag:
                        fecha = extraer_fecha_de_tag(ftag)
                        if fecha:
                            break

            # Extrae fecha de la URL si todavía no la tenemos
            if not fecha and enlace:
                fecha = parsear_fecha_de_url(enlace)

            if titulo not in vistas:
                vistas.add(titulo)
                noticias.append({
                    "titulo": titulo,
                    "url": enlace,
                    "fecha": fecha.isoformat() if fecha else None,
                    "fecha_dt": fecha,
                })

            if len(noticias) >= MAX_NOTICIAS_POR_SITIO:
                break

    return noticias[:MAX_NOTICIAS_POR_SITIO]


# ─── Scraper por institución ───────────────────────────────────────────────────

def scrapear_noticias_institucion(inst: dict, session: requests.Session, dias: int) -> dict:
    url = inst["url"]
    corte = datetime.now() - timedelta(days=dias)
    log.info(f"  {inst['pais']} | {inst['nombre'][:50]}")

    resultado = {
        **inst,
        "url_noticias": "",
        "noticias": [],
        "noticias_en_periodo": [],
        "error": "",
        "timestamp": datetime.utcnow().isoformat(),
    }

    # Carga homepage
    soup_home = get_soup(url, session)
    if not soup_home:
        resultado["error"] = "Sin acceso"
        return resultado

    # Busca URL de sección de noticias
    url_noticias = encontrar_url_noticias(soup_home, url)

    if url_noticias and url_noticias != url:
        log.info(f"    → sección noticias: {url_noticias}")
        soup_noticias = get_soup(url_noticias, session)
        time.sleep(0.8)
    else:
        url_noticias = url
        soup_noticias = soup_home

    resultado["url_noticias"] = url_noticias

    if not soup_noticias:
        soup_noticias = soup_home

    noticias = extraer_noticias_con_fecha(soup_noticias, url_noticias)

    # Para artículos sin fecha: visita los primeros 5 para extraer fecha del artículo
    sin_fecha_links = [n for n in noticias if not n["fecha_dt"] and n["url"]][:5]
    if sin_fecha_links:
        log.info(f"    → buscando fechas en {len(sin_fecha_links)} artículos...")
        for n in sin_fecha_links:
            art_soup = get_soup(n["url"], session)
            time.sleep(0.5)
            if not art_soup:
                continue
            # Busca fecha en meta tags y tags semánticos del artículo
            fecha = None
            for sel in ["meta[property='article:published_time']",
                        "meta[name='date']", "meta[name='DC.date']",
                        "time[datetime]", ".fecha", ".date", ".published",
                        ".entry-date", ".post-date", "span.date"]:
                tag = art_soup.select_one(sel)
                if tag:
                    fecha = extraer_fecha_de_tag(tag)
                    if fecha:
                        break
            # Busca en todo el texto del artículo
            if not fecha:
                texto_art = art_soup.get_text(" ", strip=True)[:2000]
                fecha = parsear_fecha(texto_art)
            if fecha:
                n["fecha"] = fecha.isoformat()
                n["fecha_dt"] = fecha
                log.info(f"      fecha encontrada: {fecha.date()} en {n['url'][:60]}")

    resultado["noticias"] = [
        {k: v for k, v in n.items() if k != "fecha_dt"}
        for n in noticias
    ]

    # Filtra por período
    en_periodo = []
    sin_fecha = []
    for n in noticias:
        if n["fecha_dt"] and n["fecha_dt"] >= corte:
            en_periodo.append({k: v for k, v in n.items() if k != "fecha_dt"})
        elif not n["fecha_dt"]:
            sin_fecha.append({k: v for k, v in n.items() if k != "fecha_dt"})

    resultado["noticias_en_periodo"] = en_periodo
    resultado["noticias_sin_fecha"] = sin_fecha[:5]

    log.info(
        f"    → {len(noticias)} total | "
        f"{len(en_periodo)} en últimos {dias}d | "
        f"{len(sin_fecha)} sin fecha"
    )
    return resultado


# ─── Main ──────────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--dias", type=int, default=14, help="Ventana de días (default: 14)")
    p.add_argument("--pais", help="Filtrar por país")
    p.add_argument("--region", help="Filtrar por región")
    p.add_argument("--delay", type=float, default=DELAY)
    p.add_argument("--output", default="noticias")
    return p.parse_args()


def main():
    args = parse_args()
    instituciones = INSTITUCIONES

    if args.pais:
        instituciones = [i for i in instituciones if args.pais.lower() in i["pais"].lower()]
    if args.region:
        instituciones = [i for i in instituciones if args.region.lower() in i["region"].lower()]

    log.info(f"Scrapeando noticias de {len(instituciones)} instituciones (últimos {args.dias} días)")

    session = requests.Session()
    session.headers.update(HEADERS)

    resultados = []
    for idx, inst in enumerate(instituciones, 1):
        log.info(f"[{idx}/{len(instituciones)}]")
        r = scrapear_noticias_institucion(inst, session, args.dias)
        resultados.append(r)
        if idx < len(instituciones):
            time.sleep(args.delay)

    # Guarda JSON con todos los datos
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M")
    out_json = OUTPUT_DIR / f"{args.output}_{args.dias}d_{ts}.json"
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump({"dias": args.dias, "timestamp": ts, "instituciones": resultados}, f,
                  ensure_ascii=False, indent=2)

    # Estadísticas
    total_noticias = sum(len(r["noticias_en_periodo"]) for r in resultados)
    con_noticias = sum(1 for r in resultados if r["noticias_en_periodo"])
    log.info(f"\nResultado: {con_noticias} instituciones con noticias | {total_noticias} noticias en {args.dias} días")
    log.info(f"JSON: {out_json}")

    return out_json


if __name__ == "__main__":
    main()
