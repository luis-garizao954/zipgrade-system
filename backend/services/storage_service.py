import boto3
from botocore.config import Config
import uuid
from backend.config import settings

def get_r2_client():
    return boto3.client(
        "s3",
        endpoint_url=f"https://{settings.R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
        aws_access_key_id=settings.R2_ACCESS_KEY,
        aws_secret_access_key=settings.R2_SECRET_KEY,
        config=Config(signature_version="s3v4"),
        region_name="auto"
    )

def subir_pdf(pdf_bytes: bytes, profe_id: str, quiz_id: str, apellido: str) -> str:
    """
    Sube un PDF individual al bucket R2 y retorna la URL pública.
    Estructura: profes/{profe_id}/quizzes/{quiz_id}/{apellido}_{uuid}.pdf
    """
    r2 = get_r2_client()
    key = f"profes/{profe_id}/quizzes/{quiz_id}/{apellido}_{uuid.uuid4().hex[:8]}.pdf"
    r2.put_object(
        Bucket=settings.R2_BUCKET,
        Key=key,
        Body=pdf_bytes,
        ContentType="application/pdf"
    )
    url = f"{settings.R2_PUBLIC_URL}/{key}"
    return url

def eliminar_pdf(pdf_url: str):
    """Elimina un PDF del bucket cuando se necesite."""
    r2 = get_r2_client()
    key = pdf_url.replace(f"{settings.R2_PUBLIC_URL}/", "")
    r2.delete_object(Bucket=settings.R2_BUCKET, Key=key)

def generar_url_temporal(pdf_url: str, segundos: int = 3600) -> str:
    """Genera URL firmada temporal (1 hora por defecto) para descarga segura."""
    r2 = get_r2_client()
    key = pdf_url.replace(f"{settings.R2_PUBLIC_URL}/", "")
    url = r2.generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.R2_BUCKET, "Key": key},
        ExpiresIn=segundos
    )
    return url
