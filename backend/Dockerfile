# Legal Metrology Inspection Platform — backend API
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps: pillow needs zlib/libjpeg; tesseract is the FALLBACK OCR engine
# (PaddleOCR — the PRIMARY engine — ships pure-Python wheels via pip). libgl1 +
# libglib2.0-0 are required by opencv-contrib-python, which paddlex[ocr-core]
# pins as an explicit dependency (paddlex refuses to create the OCR pipeline
# without that distribution installed, even though opencv-python-headless
# provides the same cv2 module) — without libGL cv2 fails to import at runtime.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libjpeg62-turbo zlib1g libgl1 libglib2.0-0 tesseract-ocr tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# requirements.txt intentionally includes paddlex[ocr-core] — the OCR pipeline
# creation fails without its extras. opencv-contrib-python (part of that extra)
# and opencv-python-headless collide on the `cv2` namespace; both work here
# because libGL/libglib2.0-0 are installed above.
RUN pip install -r requirements.txt

COPY app ./app
COPY data ./data

EXPOSE 8000

# Single worker keeps in-memory demo OCR state trivial; DB is the source of truth.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
