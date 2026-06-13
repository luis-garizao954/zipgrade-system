import re
import io
import os
import uuid
import boto3
from pypdf import PdfReader
import fitz

R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID", "")
R2_ACCESS_KEY = os.getenv("R2_ACCESS_KEY", "")
R2_SECRET_KEY = os.getenv("R2_SECRET_KEY", "")
R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME", "zipgrade-pdfs")
R2_PUBLIC_URL = os.getenv("R2_PUBLIC_URL", "")

def get_r2_client():
    return boto3.client(
        "s3",
        endpoint_url=f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
        aws_access_key_id=R2_ACCESS_KEY,
        aws_secret_access_key=R2_SECRET_KEY,
        region_name="auto"
    )

def subir_imagen_r2(imagen_bytes: bytes, nombre_archivo: str) -> str:
    try:
        client = get_r2_client()
        client.put_object(
            Bucket=R2_BUCKET_NAME,
            Key=nombre_archivo,
            Body=imagen_bytes,
            ContentType="image/png"
        )
        return f"{R2_PUBLIC_URL}/{nombre_archivo}"
    except Exception as e:
        print(f"Error subiendo imagen a R2: {e}")
        return ""

async def procesar_pdf_zipgrade(contenido: bytes) -> list:
    reader = PdfReader(io.BytesIO(contenido))
    doc = fitz.open(stream=contenido, filetype="pdf")
    resultados = []

    for i, page in enumerate(reader.pages):
        texto = page.extract_text()
        if not texto:
            continue

        puntos = None
        posibles = None
        porcentaje = None

        m = re.search(r'Puntos obtenidos[:\s]+([\d.]+)', texto)
        if m:
            puntos = float(m.group(1))

        m = re.search(r'Puntos posibles[:\s]+([\d.]+)', texto)
        if m:
            posibles = float(m.group(1))

        m = re.search(r'%\s*C correctas[:\s]+([\d.]+)', texto)
        if m:
            porcentaje = float(m.group(1))

        lineas = [l.strip() for l in texto.split('\n') if l.strip()]
        primeras = " | ".join(lineas[:6])
        nombre = f"PAG{i+1}: {primeras[:80]}"

        if puntos is not None and posibles is not None:
            nota = round((puntos / posibles) * 5.0, 1) if posibles > 0 else 0

            # Renderizar página completa del estudiante
            imagen_url = ""
            try:
                fitz_page = doc[i]
                mat = fitz.Matrix(2.0, 2.0)  # 2x zoom = buena calidad
                pix = fitz_page.get_pixmap(matrix=mat)
                img_bytes = pix.tobytes("png")
                nombre_archivo = f"hojas/pag{i+1}_{uuid.uuid4()}.png"
                imagen_url = subir_imagen_r2(img_bytes, nombre_archivo)
            except Exception as e:
                print(f"Error procesando imagen pagina {i+1}: {e}")

            resultados.append({
                "nombre": nombre,
                "puntos": puntos,
                "posibles": posibles,
                "porcentaje": porcentaje or 0,
                "nota": nota,
                "pagina": i + 1,
                "imagen_url": imagen_url
            })

    doc.close()
    return resultados