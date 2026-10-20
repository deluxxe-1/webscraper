#!/usr/bin/env python3
"""Notificaciones por correo electrónico del resultado del scraper.

El envío se realiza a través de una API HTTP de correo transaccional (HTTPS,
puerto 443) en lugar de SMTP, de forma que funciona en redes que bloquean los
puertos 25/465/587. Se soportan los proveedores Brevo y SendGrid,
seleccionables mediante variables de entorno:

    EMAIL_API      -> "brevo" (por defecto) o "sendgrid"
    EMAIL_API_KEY  -> clave de API del proveedor
    EMAIL_FROM     -> remitente verificado en el proveedor
    EMAIL_TO       -> destinatario (por defecto nikitakolchak2006@gmail.com)

Las credenciales nunca se escriben en el código. Si la configuración está
incompleta el envío se omite y se registra un aviso, de forma que el scraper
nunca falla por culpa de las notificaciones.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any, Dict, Mapping, Optional, Tuple

logger = logging.getLogger("alternate.notifier")

EMAIL_API: str = os.getenv("EMAIL_API", "brevo").strip().lower()
EMAIL_API_KEY: str = os.getenv("EMAIL_API_KEY", "")
EMAIL_FROM: str = os.getenv("EMAIL_FROM", "")
EMAIL_TO: str = os.getenv("EMAIL_TO", "nikitakolchak2006@gmail.com")

TIMEOUT: int = 30

_ENDPOINTS: Dict[str, str] = {
    "brevo": "https://api.brevo.com/v3/smtp/email",
    "sendgrid": "https://api.sendgrid.com/v3/mail/send",
}


def _construir_peticion(
    asunto: str, cuerpo: str, destinatario: str
) -> Tuple[str, Dict[str, str], bytes]:
    """Construye la URL, las cabeceras y el cuerpo JSON de la petición.

    Args:
        asunto: Línea de asunto del mensaje.
        cuerpo: Texto plano con el contenido del mensaje.
        destinatario: Dirección de correo de destino.

    Returns:
        Una tupla ``(url, cabeceras, cuerpo_json)`` lista para enviar.

    Raises:
        ValueError: Si ``EMAIL_API`` no corresponde a un proveedor soportado.
    """
    if EMAIL_API == "brevo":
        cabeceras = {
            "accept": "application/json",
            "content-type": "application/json",
            "api-key": EMAIL_API_KEY,
        }
        datos: Dict[str, Any] = {
            "sender": {"email": EMAIL_FROM},
            "to": [{"email": destinatario}],
            "subject": asunto,
            "textContent": cuerpo,
        }
    elif EMAIL_API == "sendgrid":
        cabeceras = {
            "Authorization": f"Bearer {EMAIL_API_KEY}",
            "Content-Type": "application/json",
        }
        datos = {
            "personalizations": [{"to": [{"email": destinatario}]}],
            "from": {"email": EMAIL_FROM},
            "subject": asunto,
            "content": [{"type": "text/plain", "value": cuerpo}],
        }
    else:
        raise ValueError(f"proveedor de correo no soportado: {EMAIL_API!r}")

    return _ENDPOINTS[EMAIL_API], cabeceras, json.dumps(datos).encode("utf-8")


def enviar_correo(asunto: str, cuerpo: str) -> bool:
    """Envía un correo electrónico mediante la API HTTPS configurada.

    Args:
        asunto: Línea de asunto del mensaje.
        cuerpo: Texto plano con el contenido del mensaje.

    Returns:
        ``True`` si el proveedor aceptó el envío, ``False`` en caso contrario
        (incluida la ausencia de configuración).
    """
    if not (EMAIL_API_KEY and EMAIL_FROM and EMAIL_TO):
        logger.warning(
            "Configuración del correo incompleta: no se envía el correo"
        )
        return False

    try:
        url, cabeceras, datos = _construir_peticion(asunto, cuerpo, EMAIL_TO)
    except ValueError as exc:
        logger.error("Configuración de correo inválida: %s", exc)
        return False

    peticion = urllib.request.Request(url, data=datos, headers=cabeceras, method="POST")
    try:
        with urllib.request.urlopen(peticion, timeout=TIMEOUT) as respuesta:
            if 200 <= respuesta.status < 300:
                logger.info(
                    "Correo enviado a %s mediante %s", EMAIL_TO, EMAIL_API
                )
                return True
            logger.error(
                "El proveedor %s respondió con el estado %s",
                EMAIL_API,
                respuesta.status,
            )
            return False
    except urllib.error.HTTPError as exc:
        detalle = exc.read().decode("utf-8", "replace")[:300]
        logger.error("Error HTTP al enviar el correo (%s): %s", exc.code, detalle)
        return False
    except (urllib.error.URLError, OSError) as exc:
        logger.error("No se pudo enviar el correo: %s", exc)
        return False


def enviar_resultado(
    exito: bool,
    productos: int,
    ruta_csv: Optional[str] = None,
    categorias: Optional[Mapping[str, int]] = None,
) -> bool:
    """Compone y envía el correo con el resultado de la ejecución.

    Args:
        exito: Indica si se han extraído productos en la ejecución.
        productos: Número total de productos obtenidos.
        ruta_csv: Ruta del fichero CSV generado (si se generó).
        categorias: Diccionario ``categoria -> nº de productos``.

    Returns:
        ``True`` si el correo se envió correctamente, ``False`` en caso contrario.
    """
    if exito:
        asunto = f"[Scraper] Ejecución correcta ({productos} productos)"
        estado = "CORRECTA"
    else:
        asunto = "[Scraper] Ejecución SIN productos"
        estado = "SIN PRODUCTOS"

    lineas = [
        "Resultado de la ejecución del scraper de alternate.es",
        "",
        f"Estado: {estado}",
        f"Productos extraídos: {productos}",
        f"Fichero CSV: {ruta_csv or 'no generado'}",
    ]
    if categorias:
        lineas.append("")
        lineas.append("Productos por categoría:")
        for nombre, total in categorias.items():
            lineas.append(f"  - {nombre}: {total}")

    return enviar_correo(asunto, "\n".join(lineas))
