FROM python:3.12.13

WORKDIR /short_braid

COPY pyproject.toml uv.lock ./

RUN pip install uv

COPY . .

RUN uv sync 

CMD ["uv","run","0.0.0.0:8000"]