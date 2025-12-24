import os
import re
import time
import random
from datetime import datetime, timezone, timedelta

import requests
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError


# ====== CONFIG via Secrets/Env ======
URL = os.getenv("MONITOR_URL", "").strip()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

# Quando rodar manualmente com test_alert=1, força envio de mensagem
TEST_ALERT = os.getenv("TEST_ALERT", "1").strip() == "1"

# timezone Brasil (ajuste se quiser)
BRT = timezone(timedelta(hours=-3))


def now_str():
    return datetime.now(BRT).strftime("%d/%m/%Y %H:%M:%S")


def tg_send_message(text: str) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ Telegram não configurado (faltando TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID).")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    resp = requests.post(url, data={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "disable_notification": "true",  # modo silencioso (só alerta)
    }, timeout=30)

    try:
        data = resp.json()
    except Exception:
        data = {"raw": resp.text}

    if not resp.ok or not data.get("ok"):
        print("❌ Erro Telegram sendMessage:", data)
    else:
        print("✅ Telegram sendMessage OK")


def tg_send_photo(caption: str, image_path: str) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ Telegram não configurado (faltando TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID).")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    with open(image_path, "rb") as f:
        resp = requests.post(url, data={
            "chat_id": TELEGRAM_CHAT_ID,
            "caption": caption,
            "disable_notification": "true",
        }, files={"photo": f}, timeout=60)

    try:
        data = resp.json()
    except Exception:
        data = {"raw": resp.text}

    if not resp.ok or not data.get("ok"):
        print("❌ Erro Telegram sendPhoto:", data)
    else:
        print("✅ Telegram sendPhoto OK")


def normalize(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"\s+", " ", s)
    return s


def check_once() -> dict:
    """
    Abre a URL e captura:
    - texto do body (resumo)
    - screenshot
    - status interpretado
    """
    if not URL:
        raise RuntimeError("MONITOR_URL está vazio. Configure MONITOR_URL.")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        context = browser.new_context(
            viewport={"width": 1280, "height": 720},
            locale="es-ES",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/123.0.0.0 Safari/537.36"
            ),
        )

        page = context.new_page()

        # Jitter para reduzir padrão (anti-bloqueio básico)
        time.sleep(random.uniform(1.2, 3.0))

        page.goto(URL, wait_until="domcontentloaded", timeout=90_000)

        # Espera renderizar algo “confiável” antes do print (evita imagem branca)
        try:
            # tenta esperar pelo texto comum da página “sem vagas”
            page.wait_for_selector("text=No hay horas disponibles", timeout=25_000)
        except PWTimeoutError:
            # se não achou, espera qualquer coisa típica do widget
            try:
                page.wait_for_selector("text=bookitit", timeout=20_000)
            except PWTimeoutError:
                # último recurso: aguarda rede ficar mais calma
                page.wait_for_load_state("networkidle", timeout=20_000)

        # garante um pequeno delay pós-render (ajuda muito em SPA)
        time.sleep(random.uniform(0.8, 2.0))

        screenshot_path = "page.png"
        page.screenshot(path=screenshot_path, full_page=True)

        body_text = normalize(page.locator("body").inner_text(timeout=10_000))

        browser.close()

    # Interpretação:
    sem_vaga = (
        "No hay horas disponibles" in body_text
        or "Inténtelo de nuevo dentro de unos días" in body_text
        or "No hay citas disponibles" in body_text
    )

    # “Possível vaga / página mudou”
    # (ex: aparece seleção, calendário, horas, botões diferentes, etc)
    possivel_vaga = (not sem_vaga) and len(body_text) > 30

    status = "SEM_VAGA" if sem_vaga else ("POSSIVEL_VAGA" if possivel_vaga else "ESTADO_INDEFINIDO")

    return {
        "status": status,
        "body_preview": body_text[:500],
        "screenshot": screenshot_path,
    }


def main():
    print("🟦 Monitor iniciado:", now_str())
    print("URL:", URL)

    # Envio de teste (sem depender do site)
    if TEST_ALERT:
        tg_send_message(f"✅ Teste OK (GitHub Actions) — {now_str()}")
        # continua rodando o check também (opcional)
        print("ℹ️ TEST_ALERT=1, mensagem de teste enviada.")

    result = check_once()
    status = result["status"]
    preview = result["body_preview"]
    shot = result["screenshot"]

    print("STATUS:", status)
    print("PREVIEW:", preview)

    if status == "SEM_VAGA":
        # Não envia para não floodar. (Se quiser, eu te mostro como ativar.)
        print(f"⏳ Sem vaga — {now_str()}")
        return

    # Se chegou aqui: POSSIVEL_VAGA ou ESTADO_INDEFINIDO
    caption = (
        "🚨 ATENÇÃO: estado diferente de 'sem vagas'\n"
        f"🕒 {now_str()}\n"
        f"🔗 {URL}\n\n"
        "📌 Pode ser vaga disponível OU site mudou/tela diferente.\n"
        "✅ Abra o link agora para conferir."
    )

    tg_send_photo(caption=caption, image_path=shot)


if __name__ == "__main__":
    main()
