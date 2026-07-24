"""Configuração compartilhada dos testes da API.

Roda ANTES de qualquer import da app — garante que DATABASE_URL aponte
para o túnel VPS local (localhost:5434) e AUTH_ENABLED=false.
"""

import os

os.environ.setdefault(
    "DATABASE_URL",
    "postgres://fulled:9n7dx5GRZ4Pd20XEkN5zvj4AVqtWS8G8@localhost:5434/fulled",
)
os.environ.setdefault("AUTH_ENABLED", "false")
