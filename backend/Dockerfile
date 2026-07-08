FROM python:3.12-slim

WORKDIR /srv/sentinel

# INSTALL_ML=true bakes the transformer stack (torch/transformers, ~2 GB) into
# the image so NLP_MODE=full works in Docker. Default false keeps the image
# small; full mode then falls back to lite inside the container.
ARG INSTALL_ML=false

COPY requirements.txt requirements-ml.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && if [ "$INSTALL_ML" = "true" ]; then \
         pip install --no-cache-dir -r requirements-ml.txt; \
       fi

COPY app ./app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
