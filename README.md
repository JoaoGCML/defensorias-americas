# Defensorías de las Américas — Monitor de Prensa

Monitor automático de notas de prensa, comunicados y noticias de **Defensorías Públicas** y **Ombudspersons de Derechos Humanos** de toda América, publicado como mapa interactivo en GitHub Pages.

## Mapa en vivo

> **[Ver mapa →](https://TU_USUARIO.github.io/TU_REPO/)**

El mapa se actualiza automáticamente cada mañana vía GitHub Actions.

---

## Cobertura

| Región | Instituciones |
|---|---|
| Sudamérica | Argentina (×2), Bolivia, Brasil (×4), Chile (×3), Colombia, Ecuador, Guyana, Paraguay, Perú, Uruguay, Venezuela |
| Centroamérica | Belice, Costa Rica, El Salvador, Guatemala, Honduras, México, Nicaragua, Panamá |
| Caribe | Haití, Jamaica, República Dominicana, Trinidad y Tobago |
| Norteamérica / Canadá | CHRC federal, Québec, Ontario, BC, Alberta, Nova Scotia, New Brunswick, Manitoba, Saskatchewan |
| Organismos Regionales | AIDEF, CIDH, FIO |

**Total: 41 instituciones** — solo organismos públicos oficiales y redes institucionales reconocidas.

---

## Funcionalidades

- **Mapa Leaflet** con marcadores por institución, popups con las últimas publicaciones, leyenda por tipo
- **Timeline** agrupada por fecha, con filtros por región / país / tipo / sección / fecha
- **Tabla** ordenable con todos los resultados
- **Feed Atom** (`docs/data/feed.xml`) — suscripción en cualquier lector RSS
- **Histórico** (`docs/data/historico.jsonl`) — una línea por ejecución, para análisis de tendencias
- **Scraping async** con `aiohttp` — 41 instituciones en ~60 segundos

---

## Uso local

```bash
# Instalar dependencias
pip install -r requirements.txt

# Últimos 30 días (default)
python prensa_latam.py

# Últimos 60 días, solo Colombia
python prensa_latam.py --dias 60 --pais Colombia

# Guardar en docs/ (formato GitHub Pages)
python prensa_latam.py --dias 30 --output-dir docs/data

# Opciones completas
python prensa_latam.py --help
```

Los archivos se guardan en `output/` (o en el directorio especificado con `--output-dir`):

| Archivo | Descripción |
|---|---|
| `latest_30d_YYYYMMDD_HHMM.json` | Datos completos del run |
| `latest.json` | Siempre el run más reciente |
| `latest_30d_YYYYMMDD_HHMM.html` | Mapa interactivo (abre en browser) |
| `index.html` | Copia del mapa para GitHub Pages |
| `feed.xml` | Feed Atom con las últimas publicaciones |
| `historico.jsonl` | Acumulado histórico (una línea por run) |

---

## GitHub Pages (publicación automática)

1. Haz fork o push de este repositorio a GitHub
2. En **Settings → Pages**, selecciona `main` branch y carpeta `/docs`
3. El workflow `.github/workflows/scrape.yml` corre cada día a las 07:00 UTC
4. También puedes lanzarlo manualmente desde **Actions → Run workflow**

Para activar el push automático desde Actions, el repositorio necesita permisos de escritura en **Settings → Actions → General → Workflow permissions → Read and write**.

---

## Estructura del repositorio

```
defensorias_scraper/
├── .github/
│   └── workflows/
│       └── scrape.yml       # Ejecución diaria automática
├── docs/                    # Servido por GitHub Pages
│   ├── index.html           # Mapa más reciente
│   └── data/
│       ├── latest.json      # Datos más recientes
│       ├── feed.xml         # Feed Atom
│       └── historico.jsonl  # Histórico acumulado
├── prensa_latam.py          # Scraper principal (async)
├── requirements.txt
└── README.md
```

---

## Limitaciones conocidas

- **Ecuador** — timeout constante (sitio lento)
- **República Dominicana** — DNS offline desde mayo 2026
- **Guatemala PDH, Ontario** — pueden devolver HTTP 403 según la IP
- **El Salvador, Panamá** — artículos sin fecha (contenido generado por JavaScript)
- **Manitoba** — todas las fechas aparecen como 2020-03-10 (bug en su CMS)

---

## Instituciones fuera de alcance

Este proyecto se limita a **organismos públicos oficiales** (defensorías estatales, ombudspersons gubernamentales y redes interinstitucionales reconocidas). ONGs, organizaciones de la sociedad civil y organismos privados —incluso los más relevantes en derechos humanos— quedan fuera de este repositorio.

---

## Licencia

Código: MIT. Los contenidos monitoreados pertenecen a cada institución.
