import json
import re
from datetime import datetime, timezone, timedelta
from playwright.sync_api import sync_playwright

# Fuso horário de Brasília (UTC-3)
BRT = timezone(timedelta(hours=-3))
ARQUIVO_SAIDA = "precos_pix.json"

PRODUTOS = [
    {
        "id": "deco-x50",
        "nome": "TP-Link Deco X50 (2-Pack)",
        "url_amazon": "https://www.amazon.com.br/s?k=TP-Link+Deco+X50+2+Pack&s=price-asc-rank",
        "url_meli": "https://lista.mercadolivre.com.br/tp-link-deco-x50-2-pack_OrderId_PRICE",
    },
    {
        "id": "deco-be22",
        "nome": "TP-Link Deco BE22 (2-Pack)",
        "url_amazon": "https://www.amazon.com.br/s?k=TP-Link+Deco+BE22+2+Pack&s=price-asc-rank",
        "url_meli": "https://lista.mercadolivre.com.br/tp-link-deco-be22-2-pack_OrderId_PRICE",
    },
    {
        "id": "electrolux-ls10e",
        "nome": "Lava-louças Electrolux LS10E (10 Serviços)",
        "url_amazon": "https://www.amazon.com.br/s?k=Lava-loucas+Electrolux+LS10E&s=price-asc-rank",
        "url_meli": "https://lista.mercadolivre.com.br/lava-loucas-electrolux-ls10e_OrderId_PRICE",
    },
    {
        "id": "samsung-wd13fg",
        "nome": "Lava e Seca Samsung WD13FG (13kg)",
        "url_amazon": "https://www.amazon.com.br/s?k=Lava+e+Seca+Samsung+WD13FG&s=price-asc-rank",
        "url_meli": "https://lista.mercadolivre.com.br/lava-e-seca-samsung-wd13fg_OrderId_PRICE",
    },
]


def limpar_preco(texto):
    """Converte strings como 'R$ 1.249,90' ou '1.249,90' em float arredondado."""
    if not texto:
        return None
    match = re.search(r"R\$\s*([\d\.]+,\d{2})", texto)
    valor_str = match.group(1) if match else re.sub(r"[^\d,]", "", texto)
    valor_str = valor_str.replace(".", "").replace(",", ".")
    try:
        valor = round(float(valor_str), 2)
        return valor if valor > 0 else None
    except ValueError:
        return None


def extrair_preco_pix_amazon(page):
    """Busca preço à vista no PIX na página da Amazon.com.br."""
    try:
        texto_pagina = page.inner_text("body")
        match_pix = re.search(r"R\$\s*([\d\.]+,\d{2})\s*(?:à vista|no Pix)", texto_pagina, re.IGNORECASE)
        if match_pix:
            preco = limpar_preco(match_pix.group(1))
            if preco:
                return preco

        el = page.query_selector(".s-main-slot .s-result-item .a-price .a-offscreen")
        return limpar_preco(el.inner_text()) if el else None
    except Exception as exc:
        print(f"[Aviso Amazon] Falha ao extrair preço PIX: {exc}")
        return None


def extrair_preco_pix_meli(page):
    """Busca preço à vista no PIX na vitrine do Mercado Livre."""
    try:
        el_pix = page.query_selector(".ui-search-price__second-line .andes-money-amount__fraction")
        if el_pix:
            centavos_el = page.query_selector(".ui-search-price__second-line .andes-money-amount__cents")
            centavos = centavos_el.inner_text() if centavos_el else "00"
            preco = limpar_preco(f"{el_pix.inner_text()},{centavos}")
            if preco:
                return preco

        texto_pagina = page.inner_text("body")
        match_pix = re.search(r"R\$\s*([\d\.]+,\d{2})\s*(?:à vista|no Pix)", texto_pagina, re.IGNORECASE)
        return limpar_preco(match_pix.group(1)) if match_pix else None
    except Exception as exc:
        print(f"[Aviso Mercado Livre] Falha ao extrair preço PIX: {exc}")
        return None


def coletar_precos_pix():
    """Executa a coleta nos turnos das 07:00 e 19:00 (BRT) e atualiza precos_pix.json."""
    agora = datetime.now(BRT)
    data_str = agora.strftime("%Y-%m-%d")
    turno = "07:00" if agora.hour < 13 else "19:00"

    try:
        with open(ARQUIVO_SAIDA, "r", encoding="utf-8") as f:
            dados = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        dados = {
            "version": 2,
            "paymentCondition": "PIX",
            "schedule": ["07:00", "19:00"],
            "isDemo": False,
            "history": {p["id"]: [] for p in PRODUTOS},
        }

    dados["version"] = 2
    dados["paymentCondition"] = "PIX"
    dados["schedule"] = ["07:00", "19:00"]
    dados["isDemo"] = False
    dados["updatedAt"] = agora.isoformat()
    if "history" not in dados or not isinstance(dados["history"], dict):
        dados["history"] = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
            ),
            locale="pt-BR",
        )
        page = context.new_page()

        for prod in PRODUTOS:
            page.goto(prod["url_amazon"], timeout=60000, wait_until="domcontentloaded")
            page.wait_for_timeout(2500)
            preco_amz = extrair_preco_pix_amazon(page)

            page.goto(prod["url_meli"], timeout=60000, wait_until="domcontentloaded")
            page.wait_for_timeout(2500)
            preco_meli = extrair_preco_pix_meli(page)

            registros = dados["history"].setdefault(prod["id"], [])

            # Evita sobrescrever com None se uma das lojas bloquear momentaneamente
            anterior = registros[-1] if registros else {}
            final_amz = preco_amz if preco_amz is not None else anterior.get("amazon")
            final_meli = preco_meli if preco_meli is not None else anterior.get("meli")

            if final_amz is not None and final_meli is not None:
                novo_registro = {
                    "date": data_str,
                    "slot": turno,
                    "paymentMethod": "PIX",
                    "amazon": final_amz,
                    "meli": final_meli,
                }
                idx = next(
                    (i for i, r in enumerate(registros) if r.get("date") == data_str and r.get("slot") == turno),
                    -1,
                )
                if idx >= 0:
                    registros[idx] = novo_registro
                else:
                    registros.append(novo_registro)

                print(f"[{data_str} {turno} | PIX] {prod['nome']}: Amazon R$ {final_amz:.2f} | MeLi R$ {final_meli:.2f}")
            else:
                print(f"[Ignorado] Sem preço válido para {prod['nome']} em {data_str} {turno}")

        browser.close()

    with open(ARQUIVO_SAIDA, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    coletar_precos_pix()