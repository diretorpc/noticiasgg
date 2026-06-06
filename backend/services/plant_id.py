import logging
import os
import httpx
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger("noticiasgg.plant_id")

PLANT_ID_URL = "https://plant.id/api/v3/identification"
CROP_HEALTH_URL = "https://crop.kindwise.com/api/v1/identification"
INSECT_ID_URL = "https://insect.kindwise.com/api/v1/identification"
_MIN_CONFIDENCE = 0.15


def _build_data_uri(image_b64: str, mime: str) -> str:
    clean_mime = mime.split(";")[0].strip()
    if image_b64.startswith("data:"):
        return image_b64
    return f"data:{clean_mime};base64,{image_b64}"


def _call_plant_id(data_uri: str, api_key: str) -> dict:
    resp = httpx.post(
        PLANT_ID_URL,
        headers={"Api-Key": api_key, "Content-Type": "application/json"},
        json={"images": [data_uri]},
        timeout=30,
    )
    logger.info("plant.id status: %s", resp.status_code)
    resp.raise_for_status()
    data = resp.json()

    suggestions = (
        data.get("result", {})
        .get("classification", {})
        .get("suggestions", [])
    )
    if not suggestions:
        return {}

    top = suggestions[0]
    if top.get("probability", 0) < _MIN_CONFIDENCE:
        logger.info("plant.id confiança baixa: %.1f%%", top.get("probability", 0) * 100)
        return {}

    details = top.get("details", {})
    common_names = details.get("common_names") or top.get("common_names") or []
    description = (details.get("description") or {}).get("value", "")

    logger.info("plant.id identificou: %s (%.1f%%)", top.get("name"), top["probability"] * 100)
    return {
        "nome_cientifico": top.get("name"),
        "nomes_comuns": common_names[:4],
        "confianca_pct": round(top["probability"] * 100, 1),
        "familia": (details.get("taxonomy") or {}).get("family"),
        "descricao": description[:600] if description else None,
    }


def _call_crop_health(data_uri: str, api_key: str) -> dict:
    resp = httpx.post(
        CROP_HEALTH_URL,
        headers={"Api-Key": api_key, "Content-Type": "application/json"},
        json={"images": [data_uri]},
        timeout=30,
    )
    logger.info("crop.health status: %s", resp.status_code)
    resp.raise_for_status()
    data = resp.json()
    result = data.get("result", {})

    is_healthy = (result.get("is_healthy") or {}).get("binary")
    diseases = (result.get("disease") or {}).get("suggestions", [])

    top_diseases = [
        {"nome": d.get("name"), "confianca_pct": round(d.get("probability", 0) * 100, 1)}
        for d in diseases[:3]
        if d.get("probability", 0) >= 0.10
    ]

    logger.info("crop.health saudavel=%s doenças=%d", is_healthy, len(top_diseases))
    return {"saudavel": is_healthy, "doencas_detectadas": top_diseases}


def _call_insect_id(data_uri: str, api_key: str) -> dict:
    resp = httpx.post(
        INSECT_ID_URL,
        headers={"Api-Key": api_key, "Content-Type": "application/json"},
        json={"images": [data_uri]},
        timeout=30,
    )
    logger.info("insect.id status: %s", resp.status_code)
    resp.raise_for_status()
    data = resp.json()

    suggestions = (
        data.get("result", {})
        .get("classification", {})
        .get("suggestions", [])
    )
    if not suggestions:
        return {}

    top = suggestions[0]
    if top.get("probability", 0) < _MIN_CONFIDENCE:
        logger.info("insect.id confiança baixa: %.1f%%", top.get("probability", 0) * 100)
        return {}

    details = top.get("details", {})
    common_names = details.get("common_names") or top.get("common_names") or []

    logger.info("insect.id identificou: %s (%.1f%%)", top.get("name"), top["probability"] * 100)
    return {
        "nome_cientifico": top.get("name"),
        "nomes_comuns": common_names[:4],
        "confianca_pct": round(top["probability"] * 100, 1),
        "ordem": (details.get("taxonomy") or {}).get("order"),
        "familia": (details.get("taxonomy") or {}).get("family"),
    }


def identify(image_b64: str, mime: str = "image/jpeg") -> dict:
    plant_key = os.getenv("PLANT_ID_API_KEY")
    crop_key = os.getenv("CROP_HEALTH_API_KEY")
    insect_key = os.getenv("INSECT_ID_API_KEY")

    if not plant_key and not crop_key and not insect_key:
        logger.error("nenhuma API key de identificação configurada")
        return {"identificado": False, "erro": "nenhuma API key configurada"}

    data_uri = _build_data_uri(image_b64, mime)
    logger.info("identify chamado — mime=%s plant=%s crop=%s insect=%s",
                mime, bool(plant_key), bool(crop_key), bool(insect_key))

    plant_result: dict = {}
    health_result: dict = {}
    insect_result: dict = {}

    futures_map = {}
    with ThreadPoolExecutor(max_workers=3) as ex:
        if plant_key:
            futures_map[ex.submit(_call_plant_id, data_uri, plant_key)] = "plant"
        if crop_key:
            futures_map[ex.submit(_call_crop_health, data_uri, crop_key)] = "health"
        if insect_key:
            futures_map[ex.submit(_call_insect_id, data_uri, insect_key)] = "insect"

        for future in as_completed(futures_map):
            kind = futures_map[future]
            try:
                result = future.result()
                if kind == "plant":
                    plant_result = result
                elif kind == "health":
                    health_result = result
                else:
                    insect_result = result
            except Exception as e:
                logger.error("erro na API %s: %s", kind, e)

    # Retorna identificado se pelo menos plant.id ou insect.id reconheceu algo
    if not plant_result.get("nome_cientifico") and not insect_result.get("nome_cientifico"):
        logger.warning("nenhuma API identificou o sujeito na imagem")
        return {"identificado": False}

    combined: dict = {"identificado": True}
    if plant_result.get("nome_cientifico"):
        combined["planta"] = plant_result
    if health_result:
        combined["saude_planta"] = health_result
    if insect_result.get("nome_cientifico"):
        combined["inseto"] = insect_result

    return combined
