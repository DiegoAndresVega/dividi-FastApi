"""El tique se valida por su contenido, no por lo que diga el cliente.

Antes bastaba con declarar `Content-Type: image/jpeg` para guardar cualquier
cosa en el volumen de tiques. Ahora la imagen se reabre y se vuelve a escribir
con Pillow: lo que no sea una imagen de verdad no pasa, y al reescribirla se
tiran los metadatos EXIF, que en una foto de móvil llevan las coordenadas GPS
de dónde se hizo.
"""

import io
from pathlib import Path

import pytest
from PIL import Image
from PIL.TiffImagePlugin import IFDRational

from app.config import settings
from tests.conftest import (
    imagen_de_prueba as imagen,
    make_standard_group,
    register_and_login,
)


def _racional(numerador, denominador=1):
    return IFDRational(numerador, denominador)


def jpeg_con_gps():
    """JPEG con coordenadas GPS, como el que sale de cualquier móvil."""
    exif = Image.Exif()
    exif[0x010F] = "TestCam"
    gps = exif.get_ifd(0x8825)
    gps[1] = "N"
    gps[2] = (_racional(40), _racional(24), _racional(59, 10))
    gps[3] = "W"
    gps[4] = (_racional(3), _racional(42), _racional(9, 10))

    buffer = io.BytesIO()
    Image.new("RGB", (64, 48), (10, 20, 30)).save(buffer, format="JPEG", exif=exif)
    return buffer.getvalue()


def gasto(client, headers):
    grupo, owner, _, _ = make_standard_group(client, headers)
    respuesta = client.post(
        f"/groups/{grupo['id']}/expenses",
        json={
            "description": "Compra",
            "amount": "30",
            "paid_by": owner["id"],
            "split_method": "equal",
        },
        headers=headers,
    )
    assert respuesta.status_code == 201, respuesta.text
    return grupo, respuesta.json()


def subir(client, headers, grupo, gasto_, contenido, nombre="tique.jpg", tipo="image/jpeg"):
    return client.post(
        f"/groups/{grupo['id']}/expenses/{gasto_['id']}/receipt",
        files={"file": (nombre, io.BytesIO(contenido), tipo)},
        headers=headers,
    )


def guardado(expense_id) -> Path:
    ficheros = list(Path(settings.receipts_dir).glob(f"{expense_id}.*"))
    assert len(ficheros) == 1, f"se esperaba un fichero y hay {len(ficheros)}"
    return ficheros[0]


@pytest.fixture
def sesion(client):
    headers = register_and_login(client, "ana@example.com")
    grupo, gasto_ = gasto(client, headers)
    return headers, grupo, gasto_


class TestContenidoFalseado:
    def test_un_texto_disfrazado_de_jpeg_se_rechaza(self, client, sesion):
        headers, grupo, gasto_ = sesion

        respuesta = subir(client, headers, grupo, gasto_, b"esto no es una imagen")

        assert respuesta.status_code == 415, respuesta.text

    def test_un_ejecutable_disfrazado_de_png_se_rechaza(self, client, sesion):
        headers, grupo, gasto_ = sesion
        # Cabecera ELF: un binario de Linux.
        elf = b"\x7fELF\x02\x01\x01\x00" + b"\x00" * 200

        respuesta = subir(
            client, headers, grupo, gasto_, elf, nombre="x.png", tipo="image/png"
        )

        assert respuesta.status_code == 415, respuesta.text

    def test_un_png_con_carga_pegada_al_final_pierde_la_carga(self, client, sesion):
        """Un PNG válido con datos añadidos detrás. Pillow lo reescribe desde
        los píxeles, así que lo pegado desaparece."""
        headers, grupo, gasto_ = sesion
        carga = b"<?php system($_GET['c']); ?>"

        respuesta = subir(client, headers, grupo, gasto_, imagen("PNG") + carga,
                          nombre="t.png", tipo="image/png")

        assert respuesta.status_code == 200, respuesta.text
        assert carga not in guardado(gasto_["id"]).read_bytes()

    def test_nada_se_escribe_en_disco_si_se_rechaza(self, client, sesion):
        headers, grupo, gasto_ = sesion

        subir(client, headers, grupo, gasto_, b"no soy una imagen")

        assert not list(Path(settings.receipts_dir).glob(f"{gasto_['id']}.*"))


class TestMetadatos:
    def test_las_coordenadas_gps_no_se_guardan(self, client, sesion):
        headers, grupo, gasto_ = sesion
        original = jpeg_con_gps()
        # El fixture debe traer GPS, si no el test no probaría nada.
        assert Image.open(io.BytesIO(original)).getexif().get_ifd(0x8825)

        assert subir(client, headers, grupo, gasto_, original).status_code == 200

        almacenada = Image.open(guardado(gasto_["id"]))
        assert not almacenada.getexif().get_ifd(0x8825), "quedan coordenadas GPS"

    def test_no_queda_ningun_metadato_exif(self, client, sesion):
        headers, grupo, gasto_ = sesion

        subir(client, headers, grupo, gasto_, jpeg_con_gps())

        assert not dict(Image.open(guardado(gasto_["id"])).getexif())


class TestOrientacion:
    def test_una_foto_vertical_no_se_guarda_tumbada(self, client, sesion):
        """Los móviles guardan la foto apaisada y anotan en el EXIF cuánto hay
        que girarla. Si se tira el EXIF sin aplicarlo antes, la foto queda de
        lado para siempre."""
        headers, grupo, gasto_ = sesion
        exif = Image.Exif()
        exif[0x0112] = 6  # Orientation: girar 90 grados
        buffer = io.BytesIO()
        Image.new("RGB", (80, 40), (10, 20, 30)).save(
            buffer, format="JPEG", exif=exif
        )

        assert subir(client, headers, grupo, gasto_, buffer.getvalue()).status_code == 200

        almacenada = Image.open(guardado(gasto_["id"]))
        assert almacenada.size == (40, 80), "la foto se guardó sin enderezar"
        assert not dict(almacenada.getexif()), "y además debe ir sin metadatos"


class TestFormatosValidos:
    @pytest.mark.parametrize(
        "formato,extension", [("JPEG", ".jpg"), ("PNG", ".png"), ("WEBP", ".webp")]
    )
    def test_se_aceptan_y_se_guardan_con_su_extension_real(
        self, client, sesion, formato, extension
    ):
        headers, grupo, gasto_ = sesion

        respuesta = subir(client, headers, grupo, gasto_, imagen(formato))

        assert respuesta.status_code == 200, respuesta.text
        assert guardado(gasto_["id"]).suffix == extension

    def test_la_extension_la_decide_el_contenido_no_el_cliente(self, client, sesion):
        """Se sube un PNG de verdad diciendo que es JPEG. Manda el contenido."""
        headers, grupo, gasto_ = sesion

        respuesta = subir(
            client, headers, grupo, gasto_, imagen("PNG"),
            nombre="mentira.jpg", tipo="image/jpeg",
        )

        assert respuesta.status_code == 200, respuesta.text
        assert guardado(gasto_["id"]).suffix == ".png"

    def test_la_imagen_se_puede_descargar_despues(self, client, sesion):
        headers, grupo, gasto_ = sesion
        subir(client, headers, grupo, gasto_, imagen("PNG"))

        descarga = client.get(
            f"/groups/{grupo['id']}/expenses/{gasto_['id']}/receipt", headers=headers
        )

        assert descarga.status_code == 200
        assert Image.open(io.BytesIO(descarga.content)).format == "PNG"


class TestLimites:
    def test_un_fichero_vacio_se_rechaza(self, client, sesion):
        headers, grupo, gasto_ = sesion

        assert subir(client, headers, grupo, gasto_, b"").status_code == 400

    def test_una_imagen_con_demasiados_pixeles_se_rechaza(
        self, client, sesion, monkeypatch
    ):
        """Una bomba de descompresión: pocos bytes, muchísimos píxeles al
        abrirla. Se comprueba el límite antes de procesarla."""
        headers, grupo, gasto_ = sesion
        monkeypatch.setattr("app.routers.receipts.MAX_RECEIPT_PIXELS", 100)

        respuesta = subir(client, headers, grupo, gasto_, imagen("PNG", (64, 48)))

        assert respuesta.status_code == 413, respuesta.text
