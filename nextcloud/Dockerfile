FROM node:22-alpine AS frontend
WORKDIR /build
COPY package.json webpack.config.js ./
RUN npm install --no-audit --no-fund
COPY ex_app/index.html ./ex_app/index.html
COPY ex_app/img ./ex_app/img
COPY ex_app/src ./ex_app/src
RUN npm run build

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_ID=skjalf \
    APP_VERSION=0.1.0 \
    APP_PORT=23000 \
    APP_PERSISTENT_STORAGE=/app_data \
    HF_HOME=/app_data/models
WORKDIR /app/ex_app
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
COPY ex_app/lib ./lib
COPY --from=frontend /build/ex_app/index.html ./index.html
COPY --from=frontend /build/ex_app/js ./js
COPY --from=frontend /build/ex_app/img ./img
EXPOSE 23000
VOLUME ["/app_data"]
CMD ["uvicorn", "lib.main:APP", "--host", "0.0.0.0", "--port", "23000", "--workers", "1"]
