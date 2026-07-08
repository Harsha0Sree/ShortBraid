FROM python:3.12.13

WORKDIR /short_braid

COPY pyproject.toml uv.lock ./

RUN pip install uv

RUN uv sync 

COPY . .

CMD ["uv","run","uvicorn","app.main:app","--host","0.0.0.0","--port","8000"]