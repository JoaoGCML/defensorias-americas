"""
Scraper de Defensorías Públicas y Ombudspersons de Derechos Humanos en las Américas.

Uso:
    python scraper.py                  # scraping completo
    python scraper.py --pais Colombia  # filtrar por país
    python scraper.py --tipo Ombudsperson
    python scraper.py --region Caribe
    python scraper.py --dry-run        # solo lista las instituciones, no scrapea
"""

import argparse
import csv
import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from instituciones import INSTITUCIONES

# ─── Configuración ─────────────────────────────────────────────────────────────

TIMEOUT = 20
DELAY_ENTRE_REQUESTS = 2.0  # segundos entre requests (respetuoso con los servidores)
MAX_NOTICIAS = 5

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; DefensoriasResearchBot/1.0; "
        "+https://github.com/hub-humanitario/defensorias-scraper)"
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
        logging.FileHandler(OUTPUT_DIR / "scraper.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)


# ─── Selectores CSS por sección ────────────────────────────────────────────────
# Listas de selectores en orden de prioridad (se usa el primero que encuentre contenido)

SELECTORES_DESCRIPCION = [
    "meta[name='description']",
    "meta[property='og:description']",
    ".about-text p",
    "#sobre p",
    "#institucional p",
    ".mision p",
    ".quienes-somos p",
    "main p",
    "article p",
]

SELECTORES_CONTACTO = [
    ".contact-info",
    ".contacto",
    "#contacto",
    "footer .address",
    "footer address",
    ".footer-contact",
    "address",
]

SELECTORES_NOTICIAS = [
    # Contenedor de noticias/prensa
    ".news-list",
    ".noticias",
    ".novedades",
    ".press-releases",
    ".sala-prensa",
    "#noticias",
    "#news",
    "article.news",
    ".entry-title",
    "h2.news-title",
    # Fallback: cualquier lista de artículos
    "ul.posts li",
    ".post-title",
]

SELECTORES_TITULOS_NOTICIAS = [
    "h1", "h2", "h3", "h4",
    ".title", ".titulo", ".noticia-titulo",
    ".entry-title", ".post-title",
    "a[href*='noticia']",
    "a[href*='news']",
    "a[href*='prensa']",
    "a[href*='comunicado']",
]


# ─── Funciones de extracción ───────────────────────────────────────────────────

def get_soup(url: str, session: requests.Session) -> BeautifulSoup | None:
    try:
        resp = session.get(url, timeout=TIMEOUT, headers=HEADERS, allow_redirects=True)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")
    except requests.exceptions.SSLError:
        log.warning(f"SSL error en {url}, reintentando sin verificación...")
        try:
            resp = session.get(url, timeout=TIMEOUT, headers=HEADERS, verify=False, allow_redirects=True)
            resp.raise_for_status()
            return BeautifulSoup(resp.text, "html.parser")
        except Exception as e:
            log.error(f"Error (sin SSL) {url}: {e}")
            return None
    except Exception as e:
        log.error(f"Error al acceder {url}: {e}")
        return None


def extraer_descripcion(soup: BeautifulSoup) -> str:
    # Primero intenta meta tags
    for sel in ["meta[name='description']", "meta[property='og:description']"]:
        tag = soup.select_one(sel)
        if tag and tag.get("content", "").strip():
            return tag["content"].strip()

    # Luego busca párrafos en secciones típicas
    for sel in SELECTORES_DESCRIPCION[2:]:
        tags = soup.select(sel)
        texto = " ".join(t.get_text(separator=" ", strip=True) for t in tags[:3])
        texto = re.sub(r"\s+", " ", texto).strip()
        if len(texto) > 80:
            return texto[:1000]

    return ""


def extraer_contacto(soup: BeautifulSoup) -> dict:
    contacto = {"telefono": "", "email": "", "direccion": "", "redes_sociales": []}

    # Busca emails en texto visible
    texto_completo = soup.get_text()
    emails = re.findall(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", texto_completo)
    if emails:
        # Filtra emails genéricos de plataformas
        emails = [e for e in emails if not any(p in e for p in ["@sentry", "@jquery", "@example"])]
        contacto["email"] = emails[0] if emails else ""

    # Busca teléfonos
    telefonos = re.findall(
        r"(?:Tel[eé]fono|Phone|Fax|Tel\.?|☎)[\s:]*([+\d\s()\-\.]{7,20})",
        texto_completo,
        re.IGNORECASE,
    )
    if telefonos:
        contacto["telefono"] = telefonos[0].strip()

    # Busca dirección en secciones de contacto
    for sel in SELECTORES_CONTACTO:
        tag = soup.select_one(sel)
        if tag:
            direccion = tag.get_text(separator=", ", strip=True)
            if len(direccion) > 10:
                contacto["direccion"] = re.sub(r"\s+", " ", direccion)[:300]
                break

    # Redes sociales
    redes = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        for red in ["facebook.com", "twitter.com", "x.com", "instagram.com",
                    "youtube.com", "linkedin.com", "t.me", "wa.me"]:
            if red in href and href not in redes:
                redes.append(href)
    contacto["redes_sociales"] = redes[:8]

    return contacto


def extraer_noticias(soup: BeautifulSoup, url_base: str) -> list[dict]:
    noticias = []
    vistas = set()

    # Estrategia 1: buscar secciones de noticias/prensa
    for sel in SELECTORES_NOTICIAS:
        items = soup.select(sel)
        for item in items[:MAX_NOTICIAS * 2]:
            titulo = ""
            enlace = ""

            # Busca título dentro del item
            for t_sel in SELECTORES_TITULOS_NOTICIAS:
                t = item.select_one(t_sel) if hasattr(item, "select_one") else None
                if t:
                    titulo = t.get_text(strip=True)
                    if t.name == "a":
                        enlace = t.get("href", "")
                    break

            if not titulo:
                titulo = item.get_text(strip=True)[:120]

            # Busca enlace
            if not enlace:
                a = item.find("a", href=True)
                if a:
                    enlace = a.get("href", "")

            if enlace:
                enlace = urljoin(url_base, enlace)

            titulo = re.sub(r"\s+", " ", titulo).strip()

            if titulo and len(titulo) > 10 and titulo not in vistas:
                vistas.add(titulo)
                noticias.append({"titulo": titulo, "url": enlace})

            if len(noticias) >= MAX_NOTICIAS:
                break

        if len(noticias) >= MAX_NOTICIAS:
            break

    # Estrategia 2: fallback — cualquier <h2>/<h3> con enlace
    if not noticias:
        for h in soup.find_all(["h2", "h3"])[:20]:
            a = h.find("a", href=True)
            titulo = h.get_text(strip=True)
            if a and len(titulo) > 10 and titulo not in vistas:
                vistas.add(titulo)
                noticias.append({
                    "titulo": titulo,
                    "url": urljoin(url_base, a["href"]),
                })
            if len(noticias) >= MAX_NOTICIAS:
                break

    return noticias[:MAX_NOTICIAS]


def extraer_titular(soup: BeautifulSoup) -> str:
    for sel in ["h1", "meta[property='og:title']", "title"]:
        tag = soup.select_one(sel)
        if tag:
            if tag.name == "meta":
                return tag.get("content", "").strip()
            return tag.get_text(strip=True)
    return ""


def extraer_idioma_detectado(soup: BeautifulSoup) -> str:
    html = soup.find("html")
    if html and html.get("lang"):
        return html["lang"][:5]
    return ""


# ─── Scraper principal ─────────────────────────────────────────────────────────

def scrapear_institucion(inst: dict, session: requests.Session) -> dict:
    url = inst["url"]
    log.info(f"Scrapeando: {inst['nombre']} ({url})")

    resultado = {
        **inst,
        "estado_http": None,
        "url_final": url,
        "titular_pagina": "",
        "descripcion": "",
        "idioma_detectado": "",
        "contacto": {},
        "noticias_recientes": [],
        "timestamp": datetime.utcnow().isoformat(),
        "error": "",
    }

    soup = get_soup(url, session)
    if soup is None:
        resultado["error"] = "No se pudo acceder al sitio"
        return resultado

    resultado["titular_pagina"] = extraer_titular(soup)
    resultado["descripcion"] = extraer_descripcion(soup)
    resultado["idioma_detectado"] = extraer_idioma_detectado(soup)
    resultado["contacto"] = extraer_contacto(soup)
    resultado["noticias_recientes"] = extraer_noticias(soup, url)

    return resultado


# ─── Exportación ───────────────────────────────────────────────────────────────

def guardar_json(datos: list[dict], path: Path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)
    log.info(f"JSON guardado: {path}")


def guardar_csv(datos: list[dict], path: Path):
    if not datos:
        return

    campos = [
        "pais", "region", "nombre", "tipo", "url", "idioma",
        "estado_http", "url_final", "titular_pagina", "descripcion",
        "idioma_detectado", "contacto_email", "contacto_telefono",
        "contacto_direccion", "redes_sociales", "noticias_count",
        "timestamp", "error",
    ]

    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=campos, extrasaction="ignore")
        writer.writeheader()
        for d in datos:
            contacto = d.get("contacto", {})
            row = {
                **d,
                "contacto_email": contacto.get("email", ""),
                "contacto_telefono": contacto.get("telefono", ""),
                "contacto_direccion": contacto.get("direccion", ""),
                "redes_sociales": " | ".join(contacto.get("redes_sociales", [])),
                "noticias_count": len(d.get("noticias_recientes", [])),
            }
            writer.writerow(row)
    log.info(f"CSV guardado: {path}")


def guardar_markdown(datos: list[dict], path: Path):
    lineas = [
        "# Defensorías Públicas y Ombudspersons de Derechos Humanos en las Américas",
        f"\n_Generado: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}_\n",
        f"**Total instituciones scrapeadas:** {len(datos)}\n",
    ]

    regiones = sorted(set(d["region"] for d in datos))
    for region in regiones:
        lineas.append(f"\n## {region}\n")
        instituciones_region = [d for d in datos if d["region"] == region]
        for d in sorted(instituciones_region, key=lambda x: x["pais"]):
            lineas.append(f"### {d['nombre']} ({d['pais']})")
            lineas.append(f"- **Tipo:** {d['tipo']}")
            lineas.append(f"- **URL:** [{d['url']}]({d['url']})")
            if d.get("descripcion"):
                lineas.append(f"- **Descripción:** {d['descripcion'][:300]}...")
            contacto = d.get("contacto", {})
            if contacto.get("email"):
                lineas.append(f"- **Email:** {contacto['email']}")
            if contacto.get("telefono"):
                lineas.append(f"- **Teléfono:** {contacto['telefono']}")
            if contacto.get("redes_sociales"):
                redes = " | ".join(contacto["redes_sociales"][:3])
                lineas.append(f"- **Redes:** {redes}")
            if d.get("noticias_recientes"):
                lineas.append("- **Noticias recientes:**")
                for n in d["noticias_recientes"][:3]:
                    url_n = f"({n['url']})" if n.get("url") else ""
                    lineas.append(f"  - [{n['titulo']}]{url_n}")
            if d.get("error"):
                lineas.append(f"- **Error:** ⚠️ {d['error']}")
            lineas.append("")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lineas))
    log.info(f"Markdown guardado: {path}")


# ─── CLI ───────────────────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(description="Scraper de Defensorías y Ombudspersons de las Américas")
    parser.add_argument("--pais", help="Filtrar por país")
    parser.add_argument("--tipo", help="Filtrar por tipo (Ombudsperson, Defensoria Pública, Red Regional...)")
    parser.add_argument("--region", help="Filtrar por región (Sudamérica, Caribe, Centroamérica, Norteamérica, Américas)")
    parser.add_argument("--dry-run", action="store_true", help="Solo listar instituciones sin scrapear")
    parser.add_argument("--delay", type=float, default=DELAY_ENTRE_REQUESTS, help="Segundos entre requests")
    parser.add_argument("--output", default="defensorias", help="Prefijo de archivos de salida")
    return parser.parse_args()


def main():
    args = parse_args()

    instituciones = INSTITUCIONES

    if args.pais:
        instituciones = [i for i in instituciones if args.pais.lower() in i["pais"].lower()]
    if args.tipo:
        instituciones = [i for i in instituciones if args.tipo.lower() in i["tipo"].lower()]
    if args.region:
        instituciones = [i for i in instituciones if args.region.lower() in i["region"].lower()]

    log.info(f"Instituciones a procesar: {len(instituciones)}")

    if args.dry_run:
        print(f"\n{'PAÍS':<20} {'TIPO':<22} {'NOMBRE':<55} URL")
        print("-" * 130)
        for i in instituciones:
            print(f"{i['pais']:<20} {i['tipo']:<22} {i['nombre']:<55} {i['url']}")
        print(f"\nTotal: {len(instituciones)} instituciones")
        return

    session = requests.Session()
    session.headers.update(HEADERS)

    resultados = []
    for idx, inst in enumerate(instituciones, 1):
        log.info(f"[{idx}/{len(instituciones)}] {inst['pais']} — {inst['nombre']}")
        resultado = scrapear_institucion(inst, session)
        resultados.append(resultado)

        if idx < len(instituciones):
            time.sleep(args.delay)

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M")
    prefix = args.output

    guardar_json(resultados, OUTPUT_DIR / f"{prefix}_{timestamp}.json")
    guardar_csv(resultados, OUTPUT_DIR / f"{prefix}_{timestamp}.csv")
    guardar_markdown(resultados, OUTPUT_DIR / f"{prefix}_{timestamp}.md")

    ok = sum(1 for r in resultados if not r.get("error"))
    log.info(f"\nCompletado: {ok}/{len(resultados)} sitios accesibles.")
    log.info(f"Archivos en: {OUTPUT_DIR}/")


if __name__ == "__main__":
    main()
