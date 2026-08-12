#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Coletor de eventos de 3 estrelas (alto impacto) do calendário econômico do
Investing.com. Renderiza a página com Playwright (Chromium headless), extrai os
eventos 3★ de HOJE (aba "Hoje", padrão) em horário de Brasília e grava events.json.

Uso local:  python scraper.py
No CI:       chamado pelo workflow .github/workflows/update.yml
"""

import json
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright

URL = "https://br.investing.com/economic-calendar/"
TZ = ZoneInfo("America/Sao_Paulo")

FLAGS = {
    "US": "🇺🇸", "CN": "🇨🇳", "BR": "🇧🇷", "EU": "🇪🇺", "UK": "🇬🇧", "GB": "🇬🇧",
    "JP": "🇯🇵", "DE": "🇩🇪", "FR": "🇫🇷", "CA": "🇨🇦", "AU": "🇦🇺", "NZ": "🇳🇿",
    "CH": "🇨🇭", "IN": "🇮🇳", "MX": "🇲🇽", "ZA": "🇿🇦", "KR": "🇰🇷", "IT": "🇮🇹",
    "ES": "🇪🇸", "RU": "🇷🇺", "ID": "🇮🇩", "SG": "🇸🇬", "HK": "🇭🇰", "PT": "🇵🇹",
    "AR": "🇦🇷", "TR": "🇹🇷",
}

# Mesma extração validada no navegador: conta <svg class="opacity-60"> (estrela
# cheia) na célula desktop de importância; 3 = alto impacto.
EXTRACT_JS = r"""
() => {
  const rows = Array.from(document.querySelectorAll('tr[id]')).filter(r => /-\d+-/.test(r.id));
  function impCell(r){
    for (const td of Array.from(r.children)){
      const cls = td.className;
      if (/md:table-cell/.test(cls) && !/md:hidden/.test(cls) && td.querySelector('use[href*="star"]')) return td;
    }
    return null;
  }
  const events = [];
  rows.forEach(r => {
    const cells = Array.from(r.children);
    const c = impCell(r);
    const stars = c ? c.querySelectorAll('svg.opacity-60').length : 0;
    if (stars !== 3) return;
    let time = null, cur = null;
    for (const td of cells){ const t = td.textContent.trim(); if (/^\d{2}:\d{2}$/.test(t)){ time = t; break; } }
    for (const td of cells){ const cls = td.className; if (/md:table-cell/.test(cls) && !/md:hidden/.test(cls)){ const t = td.textContent.trim(); if (/^[A-Z]{2,3}$/.test(t)){ cur = t; break; } } }
    let ev = null;
    for (const td of cells){ if (/w-full/.test(td.className)){ ev = td.textContent.trim(); break; } }
    if (ev){ ev = ev.split(/Atual:|Cons:|Anterior:/)[0].trim(); }
    events.push({ time, cur, name: ev });
  });
  return events;
}
"""

PT_WEEKDAYS = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira",
               "sexta-feira", "sábado", "domingo"]
PT_MONTHS = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
             "agosto", "setembro", "outubro", "novembro", "dezembro"]


def date_label(now):
    return f"{PT_WEEKDAYS[now.weekday()]}, {now.day} de {PT_MONTHS[now.month-1]} de {now.year}"


def scrape():
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        ctx = browser.new_context(
            locale="pt-BR",
            timezone_id="America/Sao_Paulo",
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/125.0.0.0 Safari/537.36"),
            viewport={"width": 1366, "height": 900},
        )
        page = ctx.new_page()
        page.goto(URL, wait_until="domcontentloaded", timeout=60000)

        # Detecta desafio Cloudflare/anti-bot: se aparecer, aborta SEM sobrescrever.
        html_head = (page.content() or "")[:4000].lower()
        if "just a moment" in html_head or "cf-challenge" in html_head:
            raise RuntimeError("Bloqueio Cloudflare detectado — dados anteriores preservados.")

        # Espera as linhas do calendário renderizarem.
        page.wait_for_selector("tr[id]", timeout=45000)
        page.wait_for_timeout(3000)

        raw = page.evaluate(EXTRACT_JS)
        browser.close()
    return raw


def build(raw, now):
    events = []
    for e in raw:
        t = e.get("time")
        if not t or len(t) != 5 or t[2] != ":":
            continue  # descarta eventos sem horário HH:MM
        cur = (e.get("cur") or "").strip()
        name = (e.get("name") or "").strip()
        if not name:
            continue
        iso = f"{now:%Y-%m-%d}T{t}:00-03:00"  # Brasil sem horário de verão: -03:00
        events.append({
            "iso": iso,
            "cur": cur,
            "flag": FLAGS.get(cur, "🏳️"),
            "name": name,
        })
    events.sort(key=lambda x: x["iso"])
    return events


def main():
    now = datetime.now(TZ)
    try:
        raw = scrape()
    except Exception as exc:
        print(f"[ERRO] Falha na coleta: {exc}", file=sys.stderr)
        sys.exit(1)  # não grava nada; mantém o events.json anterior

    events = build(raw, now)
    payload = {
        "dateLabel": date_label(now),
        "lastUpdated": now.strftime("%d/%m/%Y %H:%M") + " (GMT-3)",
        "events": events,
    }
    with open("events.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"[OK] {len(events)} eventos 3★ gravados em events.json ({payload['dateLabel']}).")


if __name__ == "__main__":
    main()
