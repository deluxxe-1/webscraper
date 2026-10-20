# Práctica Web Scraping

Adquisición de datos de productos electrónicos mediante **Web Scraping** para
monitorizar la fluctuación de precios (Black Friday, Navidades, rebajas...).

## Web analizada

`www.alternate.es` — tienda de informática y electrónica (HTML estático, con
paginación real `?page=N`). Se respeta su `robots.txt`.

## Categorías

- Monitores
- Tarjetas gráficas
- Procesadores

Cada categoría supera los 50 artículos, por lo que se cumple el requisito del
enunciado (mínimo 50 artículos y mínimo 3 categorías).

## Tecnologías

- Python 3.8+
- [Scrapy](https://scrapy.org/) (librería moderna, distinta de BeautifulSoup)
- `csv` (escritura de resultados)
- `logging` (registro de la ejecución)
- `urllib` (notificación por correo mediante API HTTP, sin SMTP)

## Estructura del proyecto

```
├── spider.py          # Spider de Scrapy + orquestación (CSV, log, correo)
├── notifier.py        # Envío de correo electrónico (API HTTP)
├── requirements.txt   # Dependencias
├── data/              # CSVs generados (uno por día)
├── logs/              # Logs de cada ejecución
└── README.md
```

## Instalación

```bash
python3 -m venv venv
source venv/bin/activate          # En Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## Ejecución

```bash
python3 spider.py
```

Opciones útiles para pruebas:

```bash
python3 spider.py --max-paginas 2
python3 spider.py --categorias Monitores,Procesadores
```

## Salida

- **CSV diario** en `data/` con el nombre `fecha{YYYY-MM-DD}-alternate.csv` y las
  cabeceras: `nombre, descripcion, categoria, precio, divisa, referencia,
  url_imagen, url_articulo, timestamp, id, stock, descuento`.
  El campo `descuento` es el porcentaje calculado a partir del precio de tarifa.
- **Log** en `logs/scraper_{YYYY-MM-DD}.log` con los niveles `INFO`, `WARNING`
  y `ERROR`.

## Notificación por correo

El correo se envía mediante la **API HTTP de un proveedor de correo
transaccional** (HTTPS, puerto 443), en lugar de SMTP, para que funcione en
redes que bloquean los puertos 25/465/587. Se soportan **Brevo** (por defecto)
y **SendGrid**. La configuración se lee de variables de entorno (no se guardan
credenciales en el código).

Requisitos en el proveedor:
- **Brevo**: verificar un remitente en *Senders* y crear una clave en *SMTP &
  API → API Keys*.
- **SendGrid**: verificar un *Single Sender* y crear una clave en *Settings →
  API Keys*.

```bash
export EMAIL_API="brevo"                       # o "sendgrid"
export EMAIL_API_KEY="tu_api_key"
export EMAIL_FROM="tu_remitente_verificado@ejemplo.com"
# Opcional: si se omite, se usa nikitakolchak2006@gmail.com
export EMAIL_TO="nikitakolchak2006@gmail.com"
```

Si falta la clave o el remitente, el scraper funciona igual pero omite el
correo y registra un aviso.

## Automatización (crontab)

Ejecución diaria a las 00:00 (medianoche). La configuración del correo se pasa
como variables de entorno en la propia línea del `crontab`, ya que `cron` no
lee el perfil del usuario:

```bash
# Editar con: crontab -e
0 0 * * * cd $HOME/scraper && EMAIL_API='brevo' EMAIL_API_KEY='tu_api_key' EMAIL_FROM='tu_remitente@ejemplo.com' EMAIL_TO='nikitakolchak2006@gmail.com' ./venv/bin/python spider.py >> $HOME/scraper/logs/cron.log 2>&1
```

Los cinco campos de una línea de `crontab` son:
`minuto hora día-del-mes mes día-de-la-semana comando`.
Es decir, `0 0 * * *` se lee como «a las 00:00 de todos los días».
