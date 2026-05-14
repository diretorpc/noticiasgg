from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.collectors import market, crypto, indicators_us, indicators_br, news, commodities_br, politics_br, polls_br

app = FastAPI(title="noticiasgg", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(market.router)
app.include_router(crypto.router)
app.include_router(indicators_us.router)
app.include_router(indicators_br.router)
app.include_router(news.router)
app.include_router(commodities_br.router)
app.include_router(politics_br.router)
app.include_router(polls_br.router)


@app.get("/api/health")
async def health():
    return {"status": "ok"}
