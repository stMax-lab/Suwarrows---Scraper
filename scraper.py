"""
SUWARROW WATCHER - Scraper con Playwright (browser reale)
-----------------------------------------------------------
Gira su GitHub Actions, ogni settimana. Scrive i risultati direttamente
sul foglio Google "Suwarrows Watcher -bis" usando un Service Account.
"""

import os
import json
import time
import random
import hashlib
from datetime import datetime, timezone

import gspread
from google.oauth2.service_account import Credentials
from playwright.sync_api import sync_playwright

# ===================== CONFIGURAZIONE =====================

NOME_FOGLIO = "Suwarrows Watcher -bis"
SCHEDA_RISULTATI = "Suwarrows Watcher -bis"
SCHEDA_LOG = "Log_Esecuzioni"

# Query ad ampio raggio: notizie, storia, natura, navigazione, radioamatori,
# geografia, clima, conservazione, aspetti legali.
QUERIES = [
    "Suwarrow atoll news",
    "Suwarrow Cook Islands",
    "Suwarrow National Park conservation",
    "Suwarrow marine reserve",
    "Tom Neale Suwarrow hermit",
    "Suwarrow cyclone damage",
    "Suwarrow coconut crab wildlife",
    "Suwarrow rat eradication biosecurity",
    "Suwarrow atoll sailing yacht",
    "Suwarrow ham radio DXpedition",
    "Suwarrow atoll history",
    "Suwarrow lagoon geography map",
    "Suwarrow ranger caretaker",
    "Cook Islands marine park Suwarrow legislation",
    "Suwarrow atoll climate change sea level",
]

RISULTATI_PER_QUERY = 15

# ===================== AUTENTICAZIONE GOOGLE =====================

def get_gspread_client():
    """Legge la chiave del service account dalla variabile d'ambiente
    (impostata da GitHub Actions leggendo il Secret) e autentica gspread."""
    key_json = os.environ["GOOGLE_SERVICE_ACCOUNT_KEY"]
    info = json.loads(key_json)
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(info, scopes=scopes)
    return gspread.authorize(creds)


# ===================== SCRAPING CON PLAYWRIGHT =====================

def accetta_cookie_se_presente(page):
    """Prova a cliccare il banner dei cookie di Google se compare."""
    selettori_possibili = [
        "button:has-text('Accetta tutto')",
        "button:has-text('Accept all')",
        "#L2AGLb",  # bottone 'Accetta tutto' di Google, id noto
    ]
    for sel in selettori_possibili:
        try:
            page.click(sel, timeout=3000)
            return
        except Exception:
            continue


def cerca_su_google(page, query, num_risultati, salva_debug=False):
    url = f"https://www.google.com/search?q={query.replace(' ', '+')}&num={num_risultati}&hl=en"
    page.goto(url, timeout=30000)
    accetta_cookie_se_presente(page)
    page.wait_for_timeout(1500)

    if salva_debug:
        print("=" * 60)
        print("DEBUG - Titolo della pagina vista da Playwright:")
        print(page.title())
        print("-" * 60)
        print("DEBUG - Primi 1000 caratteri del testo visibile nella pagina:")
        try:
            testo_visibile = page.inner_text("body")
        except Exception:
            testo_visibile = "(impossibile leggere il testo del body)"
        print(testo_visibile[:1000])
        print("=" * 60)

    risultati = []
    blocchi = page.query_selector_all("div.g, div[data-sokoban-container]")

    for blocco in blocchi:
        try:
            titolo_el = blocco.query_selector("h3")
            link_el = blocco.query_selector("a")
            snippet_el = blocco.query_selector("div[data-sncf], .VwiC3b, .yXK7lf")

            if not titolo_el or not link_el:
                continue

            titolo = titolo_el.inner_text().strip()
            url_risultato = link_el.get_attribute("href")
            estratto = snippet_el.inner_text().strip() if snippet_el else ""

            if url_risultato and url_risultato.startswith("http"):
                risultati.append({
                    "titolo": titolo,
                    "url": url_risultato,
                    "estratto": estratto,
                })
        except Exception:
            continue

    return risultati


# ===================== UTILITY =====================

def estrai_dominio(url):
    try:
        from urllib.parse import urlparse
        return urlparse(url).netloc
    except Exception:
        return ""


def calcola_hash(testo):
    return hashlib.md5(testo.encode("utf-8")).hexdigest()


def costruisci_mappa_url(foglio):
    """Restituisce {url: numero_riga} leggendo la colonna D (URL)."""
    valori = foglio.get_all_values()
    mappa = {}
    for i, riga in enumerate(valori[1:], start=2):  # salta intestazione
        if len(riga) >= 4 and riga[3]:
            mappa[riga[3]] = i
    return mappa


def scrivi_o_aggiorna_riga(foglio, mappa_url, timestamp, query, risultato):
    dominio = estrai_dominio(risultato["url"])
    hash_contenuto = calcola_hash(risultato["titolo"] + risultato["estratto"])
    riga_esistente = mappa_url.get(risultato["url"])

    if not riga_esistente:
        foglio.append_row([
            timestamp, query, risultato["titolo"], risultato["url"],
            dominio, risultato["estratto"], "", timestamp,
            hash_contenuto, "Nuovo", ""
        ])
        mappa_url[risultato["url"]] = len(foglio.get_all_values())
        return 1
    else:
        hash_precedente = foglio.cell(riga_esistente, 9).value
        if hash_precedente != hash_contenuto:
            foglio.update_cell(riga_esistente, 1, timestamp)
            foglio.update_cell(riga_esistente, 3, risultato["titolo"])
            foglio.update_cell(riga_esistente, 6, risultato["estratto"])
            foglio.update_cell(riga_esistente, 9, hash_contenuto)
            foglio.update_cell(riga_esistente, 10, "Aggiornato")
        else:
            foglio.update_cell(riga_esistente, 10, "Invariato")
        return 0


# ===================== MAIN =====================

def main():
    client = get_gspread_client()
    ss = client.open(NOME_FOGLIO)
    foglio_risultati = ss.worksheet(SCHEDA_RISULTATI)
    foglio_log = ss.worksheet(SCHEDA_LOG)

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    totale_risultati = 0
    errori = []

    mappa_url = costruisci_mappa_url(foglio_risultati)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            )
        )
        page = context.new_page()

        for indice, query in enumerate(QUERIES):
            try:
                risultati = cerca_su_google(
                    page, query, RISULTATI_PER_QUERY, salva_debug=(indice == 0)
                )
                for r in risultati:
                    totale_risultati += scrivi_o_aggiorna_riga(
                        foglio_risultati, mappa_url, timestamp, query, r
                    )
                # Pausa casuale per non sembrare un bot troppo regolare
                time.sleep(random.uniform(3, 6))
            except Exception as e:
                errori.append(f"Query '{query}': {e}")

        browser.close()

    foglio_log.append_row([
        timestamp,
        len(QUERIES),
        totale_risultati,
        "N/A (Playwright, no crediti API)",
        " | ".join(errori) if errori else "",
    ])

    print(f"Fatto. Nuovi/aggiornati: {totale_risultati}. Errori: {len(errori)}")


if __name__ == "__main__":
    main()
