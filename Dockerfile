FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    NEOCARE_RECOMMENDATION_MODE=rules \
    NEOCARE_AUTH_DB=/data/neocare_auth.sqlite3

WORKDIR /app
COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY api.py assessment.py auth_store.py main.py cloud_start.py index.html neocare-i18n.js ./
COPY assets/fonts/Amiri-Regular.ttf assets/fonts/Amiri-Bold.ttf assets/fonts/Amiri-Italic.ttf assets/fonts/OFL.txt ./assets/fonts/

EXPOSE 8000
CMD ["python", "cloud_start.py"]
