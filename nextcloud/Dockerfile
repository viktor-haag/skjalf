FROM node:22-alpine AS frontend
WORKDIR /src
COPY package.json ./
RUN npm install --no-audit --no-fund
COPY ex_app/src ./src
COPY webpack.config.js ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_HOST=0.0.0.0 \
    APP_PORT=23000 \
    APP_ID=skjalf \
    APP_VERSION=0.1.0 \
    AA_VERSION=3.0.0 \
    HF_HOME=/app_data/models
WORKDIR /app/ex_app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY ex_app/lib ./lib
COPY ex_app/static ./static
COPY --from=frontend /src/js ./js
COPY --from=frontend /src/css ./css
EXPOSE 23000
CMD ["uvicorn", "lib.main:APP", "--host", "0.0.0.0", "--port", "23000", "--workers", "1"]
