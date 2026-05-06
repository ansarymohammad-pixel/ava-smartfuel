# AVA SmartFuel Backend

Backend FastAPI pour prix carburant en temps reel et score AVA.

## Lancer localement

```powershell
cd backend
pip install -e .[dev]
uvicorn app.main:app --reload
```

Documentation API:

```text
http://127.0.0.1:8000/docs
```

Endpoints:

- `GET /health`
- `GET /fuels`
- `GET /stations/nearby`
- `GET /predictions/price`

