#!/usr/bin/env python3
"""Adquisición de datos de productos electrónicos mediante Web Scraping.

Práctica de *Big Data Aplicado* (IES Abastos). El script rastrea varias
categorías de la tienda de informática `www.alternate.es`, recorre toda la
paginación, normaliza los datos, guarda un CSV diario, registra un log de la
ejecución y notifica por correo electrónico el resultado.

Uso:
    python spider.py
    python spider.py --max-paginas 2
    python spider.py --categorias Monitores,Procesadores
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import os
import re
import sys
from typing import Any, Dict, List, Optional, Sequence

import scrapy
from scrapy.crawler import CrawlerProcess

from notifier import enviar_resultado

# --------------------------------------------------------------------------- #
# Configuración general
# --------------------------------------------------------------------------- #
BASE_DIR: str = os.path.dirname(os.path.abspath(__file__))
DATA_DIR: str = os.path.join(BASE_DIR, "data")
LOGS_DIR: str = os.path.join(BASE_DIR, "logs")

TIENDA: str = "alternate"
BASE_URL: str = "https://www.alternate.es"
FECHA_EJECUCION: str = dt.date.today().isoformat()
LOG_FILE: str = os.path.join(LOGS_DIR, f"scraper_{FECHA_EJECUCION}.log")

USER_AGENT: str = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# Categorías a rastrear (el enunciado exige un mínimo de 3 categorías).
CATEGORIAS: Dict[str, str] = {
    "Monitores": f"{BASE_URL}/Monitores",
    "Tarjetas gráficas": f"{BASE_URL}/Tarjetas-gráficas",
    "Procesadores": f"{BASE_URL}/Procesadores",
}

# Cabeceras del CSV, en el orden indicado por el enunciado.
CAMPOS_CSV: List[str] = [
    "nombre",
    "descripcion",
    "categoria",
    "precio",
    "divisa",
    "referencia",
    "url_imagen",
    "url_articulo",
    "timestamp",
    "id",
    "stock",
    "descuento",
]

SIMBOLOS_DIVISA: Dict[str, str] = {"€": "EUR", "$": "USD", "£": "GBP"}

# Expresión regular para obtener el identificador del artículo desde su URL,
# por ejemplo ".../html/product/100208770" -> "100208770".
PATRON_ID = re.compile(r"/product/(\d+)")


# --------------------------------------------------------------------------- #
# Funciones auxiliares de limpieza y normalización
# --------------------------------------------------------------------------- #
def limpiar_texto(texto: Optional[str]) -> str:
    """Elimina espacios sobrantes y caracteres de control de un texto.

    Args:
        texto: Cadena de entrada (puede ser ``None``).

    Returns:
        La cadena sin espacios redundantes ni caracteres de control, o una
        cadena vacía si la entrada era ``None``.
    """
    if not texto:
        return ""
    texto = texto.replace("\xa0", " ")
    texto = re.sub(r"[\r\n\t]+", " ", texto)
    return re.sub(r"\s{2,}", " ", texto).strip()


def normalizar_precio(texto: Optional[str]) -> Optional[float]:
    """Convierte un precio en formato español a un número decimal.

    Elimina símbolos de divisa y separadores innecesarios y transforma el
    formato ``"1.299,99 €"`` en el valor numérico ``1299.99``.

    Args:
        texto: Precio tal y como aparece en la web, por ejemplo ``"€ 1.385,00"``.

    Returns:
        El precio como ``float`` redondeado a 2 decimales, o ``None`` si no se
        pudo interpretar.
    """
    if not texto:
        return None
    limpio = re.sub(r"[^\d,.\-]", "", texto.replace("\xa0", ""))
    if not limpio or limpio in {"-", ".", ","}:
        return None
    if "," in limpio and "." in limpio:
        limpio = limpio.replace(".", "").replace(",", ".")
    elif "," in limpio:
        limpio = limpio.replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(?:\.\d{3})+", limpio):
        limpio = limpio.replace(".", "")
    try:
        return round(float(limpio), 2)
    except ValueError:
        return None


def detectar_divisa(texto: Optional[str]) -> str:
    """Devuelve el código de divisa a partir de su símbolo.

    Args:
        texto: Texto que contiene el precio (por ejemplo ``"€ 1.385,00"``).

    Returns:
        El código ISO de la divisa (por defecto ``"EUR"``).
    """
    if texto:
        for simbolo, codigo in SIMBOLOS_DIVISA.items():
            if simbolo in texto:
                return codigo
    return "EUR"


def calcular_descuento(
    precio: Optional[float], precio_regular: Optional[float]
) -> float:
    """Calcula el porcentaje de descuento respecto al precio de tarifa.

    Args:
        precio: Precio final (con descuento) del producto.
        precio_regular: Precio original sin descuento, si está disponible.

    Returns:
        El descuento en porcentaje redondeado a 2 decimales, o ``0.0`` si no
        aplica.
    """
    if precio and precio_regular and precio_regular > precio:
        return round((precio_regular - precio) / precio_regular * 100, 2)
    return 0.0


def extraer_id(url: Optional[str]) -> str:
    """Obtiene el identificador único del artículo a partir de su URL.

    Args:
        url: URL del artículo, por ejemplo
            ``"https://www.alternate.es/.../html/product/100208770"``.

    Returns:
        El identificador numérico como cadena, o una cadena vacía si no se
        encuentra.
    """
    coincidencia = PATRON_ID.search(url or "")
    return coincidencia.group(1) if coincidencia else ""


def nombre_csv(fecha: dt.date | None = None, tienda: str = TIENDA) -> str:
    """Genera el nombre del fichero CSV con el formato del enunciado.

    Args:
        fecha: Fecha a usar en el nombre (por defecto, la fecha de hoy).
        tienda: Nombre de la tienda analizada.

    Returns:
        Un nombre de fichero con el formato ``fecha{YYYY-MM-DD}-{tienda}.csv``.
    """
    fecha = fecha or dt.date.today()
    return f"fecha{fecha.isoformat()}-{tienda}.csv"


def parsear_producto(
    producto: scrapy.Selector, categoria: str, timestamp: str
) -> Dict[str, Any]:
    """Extrae y normaliza los datos de una tarjeta de producto.

    Args:
        producto: Selector de cada ``<a class="productBox">``.
        categoria: Nombre de la categoría que se está rastreando.
        timestamp: Marca temporal de la extracción.

    Returns:
        Un diccionario con los campos definidos en :data:`CAMPOS_CSV`.
    """
    url_articulo = producto.attrib.get("href", "").strip()

    precio_texto = limpiar_texto(producto.css("span.price").xpath("string(.)").get())
    precio = normalizar_precio(precio_texto)

    regular_texto = limpiar_texto(
        producto.css("span.striked-price").xpath("string(.)").get()
        or producto.css("span.dynamic-stage-striked-price").xpath("string(.)").get()
    )
    precio_regular = normalizar_precio(regular_texto)

    imagen = producto.css("img.productPicture::attr(src)").get() or ""
    if imagen.startswith("//"):
        imagen = f"https:{imagen}"
    elif imagen.startswith("/"):
        imagen = BASE_URL + imagen

    identificador = extraer_id(url_articulo)

    return {
        "nombre": limpiar_texto(
            producto.css("div.product-name").xpath("string(.)").get()
        ),
        "descripcion": limpiar_texto(
            producto.css("span.product-name-sub").xpath("string(.)").get()
        ),
        "categoria": categoria,
        "precio": precio if precio is not None else "",
        "divisa": detectar_divisa(precio_texto),
        "referencia": identificador,
        "url_imagen": imagen,
        "url_articulo": url_articulo,
        "timestamp": timestamp,
        "id": identificador,
        "stock": limpiar_texto(
            producto.css("div.delivery-info span").xpath("string(.)").get()
        ),
        "descuento": calcular_descuento(precio, precio_regular),
    }


def escribir_csv(
    items: Sequence[Dict[str, Any]], ruta: Optional[str] = None
) -> str:
    """Escribe los productos extraídos en un fichero CSV con cabeceras.

    Args:
        items: Lista de diccionarios de producto.
        ruta: Ruta de destino del CSV. Si es ``None`` se genera en ``data/``
            con el nombre diario.

    Returns:
        La ruta del fichero CSV escrito.
    """
    if ruta is None:
        ruta = os.path.join(DATA_DIR, nombre_csv())
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    with open(ruta, "w", newline="", encoding="utf-8") as fichero:
        escritor = csv.DictWriter(fichero, fieldnames=CAMPOS_CSV)
        escritor.writeheader()
        for item in items:
            escritor.writerow({campo: item.get(campo, "") for campo in CAMPOS_CSV})
    return ruta


# --------------------------------------------------------------------------- #
# Spider
# --------------------------------------------------------------------------- #
class AlternateSpider(scrapy.Spider):
    """Spider que recorre las categorías de alternate.es y extrae sus productos.

    El spider visita cada categoría, sigue la paginación mediante el enlace
    "Página siguiente" hasta agotar los resultados y extrae los datos de cada
    producto desde la propia página de listado.

    Attributes:
        name: Nombre identificativo del spider.
        resultados: Lista con todos los productos extraídos.
        contadores: Número de productos extraídos por categoría.
    """

    name = "alternate"
    allowed_domains = ["alternate.es"]

    custom_settings: Dict[str, Any] = {
        "USER_AGENT": USER_AGENT,
        "ROBOTSTXT_OBEY": True,
        "DOWNLOAD_DELAY": 1.0,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 4,
        "DOWNLOAD_TIMEOUT": 30,
        "RETRY_ENABLED": True,
        "RETRY_TIMES": 3,
        "RETRY_HTTP_CODES": [403, 408, 429, 500, 502, 503, 504],
        "AUTOTHROTTLE_ENABLED": True,
        "AUTOTHROTTLE_START_DELAY": 1.0,
        "AUTOTHROTTLE_MAX_DELAY": 15.0,
        "DEFAULT_REQUEST_HEADERS": {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "es-ES,es;q=0.9",
        },
        "LOG_LEVEL": "INFO",
        "LOG_FILE": LOG_FILE,
        "LOG_ENCODING": "utf-8",
        "TWISTED_REACTOR": "twisted.internet.asyncioreactor.AsyncioSelectorReactor",
    }

    def __init__(
        self,
        categorias: Optional[Any] = None,
        max_paginas: Optional[Any] = None,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """Inicializa el spider y sus contadores.

        Args:
            categorias: Nombres de categoría separados por comas o secuencia de
                nombres. Si es ``None`` se rastrean todas las de :data:`CATEGORIAS`.
            max_paginas: Número máximo de páginas por categoría (para pruebas).
        """
        super().__init__(*args, **kwargs)
        if categorias:
            nombres = (
                [c.strip() for c in categorias.split(",") if c.strip()]
                if isinstance(categorias, str)
                else list(categorias)
            )
            self.categorias: Dict[str, str] = {
                nombre: CATEGORIAS[nombre] for nombre in nombres if nombre in CATEGORIAS
            }
        else:
            self.categorias = dict(CATEGORIAS)

        self.max_paginas: Optional[int] = (
            int(max_paginas) if max_paginas not in (None, "", 0) else None
        )
        self.resultados: List[Dict[str, Any]] = []
        self.contadores: Dict[str, int] = {nombre: 0 for nombre in self.categorias}
        self._ids_vistos: set = set()

    async def start(self):
        """Genera las peticiones iniciales para cada categoría."""
        self.logger.info("Spider iniciado: %d categorías", len(self.categorias))
        for nombre, url in self.categorias.items():
            yield scrapy.Request(
                url,
                callback=self.parse_listado,
                cb_kwargs={"categoria": nombre, "pagina": 1},
                errback=self.gestionar_error,
            )

    def parse_listado(
        self, response: scrapy.http.Response, categoria: str, pagina: int
    ):
        """Extrae los productos de una página de listado y sigue la paginación.

        Args:
            response: Respuesta HTTP de la página de categoría.
            categoria: Nombre de la categoría que se está procesando.
            pagina: Número de página actual (empezando en 1).
        """
        productos = response.css("a.productBox")
        if not productos:
            self.logger.warning(
                "Categoría '%s': sin productos en la página %d (%s)",
                categoria,
                pagina,
                response.url,
            )

        timestamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        nuevos = 0
        for producto in productos:
            item = parsear_producto(producto, categoria, timestamp)
            identificador = str(item.get("id", ""))
            if identificador and identificador in self._ids_vistos:
                continue
            if identificador:
                self._ids_vistos.add(identificador)
            self.resultados.append(item)
            nuevos += 1
            yield item

        self.contadores[categoria] = self.contadores.get(categoria, 0) + nuevos
        self.logger.info(
            "Categoría '%s': %d productos extraídos (página %d)",
            categoria,
            nuevos,
            pagina,
        )

        siguiente = response.css(
            "a[aria-label='Página siguiente']::attr(href)"
        ).get()
        if siguiente and (self.max_paginas is None or pagina < self.max_paginas):
            yield response.follow(
                siguiente,
                callback=self.parse_listado,
                cb_kwargs={"categoria": categoria, "pagina": pagina + 1},
                errback=self.gestionar_error,
            )

    def gestionar_error(self, failure: Any) -> None:
        """Registra los errores de descarga de una petición.

        Args:
            failure: Objeto ``Failure`` de Twisted con el error producido.
        """
        self.logger.error(
            "Error de descarga en %s: %s", failure.request.url, failure.value
        )

    def closed(self, reason: str) -> None:
        """Escribe el CSV y envía el correo con el resultado de la ejecución.

        Args:
            reason: Motivo de cierre del spider proporcionado por Scrapy.
        """
        total = len(self.resultados)
        self.logger.info("Crawl finalizado (%s): %d productos extraídos", reason, total)
        ruta: Optional[str] = None
        try:
            ruta = escribir_csv(self.resultados)
            self.logger.info("CSV generado correctamente: %s", ruta)
        except OSError as exc:
            self.logger.error("Error al escribir el CSV: %s", exc)
        enviar_resultado(
            exito=total > 0,
            productos=total,
            ruta_csv=ruta,
            categorias=self.contadores,
        )


# --------------------------------------------------------------------------- #
# Punto de entrada
# --------------------------------------------------------------------------- #
def parsear_argumentos(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    """Define y analiza los argumentos de línea de comandos.

    Args:
        argv: Lista de argumentos (por defecto, ``sys.argv[1:]``).

    Returns:
        El espacio de nombres con los argumentos analizados.
    """
    parser = argparse.ArgumentParser(
        description="Scraper de productos de alternate.es"
    )
    parser.add_argument(
        "--categorias",
        help="Nombres de categorías separados por comas (por defecto: todas)",
    )
    parser.add_argument(
        "--max-paginas",
        dest="max_paginas",
        type=int,
        default=None,
        help="Número máximo de páginas por categoría (por defecto: todas)",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Configura el entorno y lanza el proceso de crawling.

    Args:
        argv: Argumentos de línea de comandos (por defecto, ``sys.argv[1:]``).

    Returns:
        Código de salida del proceso (0 si todo fue correcto).
    """
    argumentos = parsear_argumentos(argv)
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(LOGS_DIR, exist_ok=True)

    proceso = CrawlerProcess()
    proceso.crawl(
        AlternateSpider,
        categorias=argumentos.categorias,
        max_paginas=argumentos.max_paginas,
    )
    proceso.start()
    return 0


if __name__ == "__main__":
    sys.exit(main())
