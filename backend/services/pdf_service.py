import anthropic
import base64
import io
from pypdf import PdfReader, PdfWriter
from typing import List, Dict
from backend.config import settings

client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

def separar_pdf_por_paginas(pdf_bytes: bytes) -> List[bytes]:
    """Separa un PDF en páginas individuales. Cada página = un estudiante."""
    reader = PdfReader(io.BytesIO(pdf_bytes))
    paginas = []
    for i in range(len(reader.pages)):
        writer = PdfWriter()
        writer.add_page(reader.pages[i])
        buf = io.BytesIO()
        writer.write(buf)
        paginas.append(buf.getvalue())
    return paginas

def pdf_pagina_a_imagen_base64(pdf_bytes: bytes) -> str:
    """Convierte la primera página de un PDF a imagen base64 para Claude Vision."""
    try:
        import fitz  # pymupdf
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        page = doc[0]
        mat = fitz.Matrix(2, 2)  # 2x zoom para mejor calidad OCR
        pix = page.get_pixmap(matrix=mat)
        img_bytes = pix.tobytes("png")
        return base64.standard_b64encode(img_bytes).decode("utf-8")
    except Exception as e:
        raise RuntimeError(f"Error convirtiendo PDF a imagen: {e}")

def leer_apellido_con_ia(imagen_base64: str) -> Dict:
    """Usa Claude Vision para leer el apellido manuscrito de la hoja."""
    try:
        response = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=200,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": imagen_base64
                        }
                    },
                    {
                        "type": "text",
                        "text": (
                            "Esta es una hoja de respuestas de examen. "
                            "Busca el apellido o nombre escrito a mano por el estudiante. "
                            "Normalmente aparece en la parte superior de la hoja. "
                            "Responde SOLO con un JSON con este formato exacto, sin texto adicional:\n"
                            '{"apellido": "APELLIDO_DETECTADO", "confianza": "alta|media|baja"}'
                        )
                    }
                ]
            }]
        )
        import json
        texto = response.content[0].text.strip()
        texto = texto.replace("```json", "").replace("```", "").strip()
        return json.loads(texto)
    except Exception:
        return {"apellido": "", "confianza": "baja"}

def procesar_pdf_zipgrade(pdf_bytes: bytes) -> List[Dict]:
    """
    Procesa el PDF completo de ZipGrade:
    1. Separa por páginas
    2. Por cada página, extrae el apellido con IA
    3. Retorna lista de resultados pendientes de confirmación
    """
    paginas = separar_pdf_por_paginas(pdf_bytes)
    resultados = []
    for i, pagina_bytes in enumerate(paginas):
        try:
            imagen_b64 = pdf_pagina_a_imagen_base64(pagina_bytes)
            deteccion = leer_apellido_con_ia(imagen_b64)
            resultados.append({
                "pagina": i + 1,
                "apellido_detectado": deteccion.get("apellido", ""),
                "confianza": deteccion.get("confianza", "baja"),
                "pdf_bytes": pagina_bytes,
                "imagen_preview": imagen_b64,
                "necesita_revision": deteccion.get("confianza") in ["baja", "media"]
            })
        except Exception as e:
            resultados.append({
                "pagina": i + 1,
                "apellido_detectado": "",
                "confianza": "baja",
                "pdf_bytes": pagina_bytes,
                "imagen_preview": None,
                "necesita_revision": True,
                "error": str(e)
            })
    return resultados
