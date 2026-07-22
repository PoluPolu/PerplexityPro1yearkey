import os
import smtplib
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
try:
    from ddgs import DDGS
except ImportError:
    from duckduckgo_search import DDGS
import feedparser
from google import genai

# Pobieranie sekretów
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
SENDER_EMAIL = os.environ.get("SENDER_EMAIL")
SENDER_PASSWORD = os.environ.get("SENDER_PASSWORD")
RECIPIENT_EMAIL = os.environ.get("RECIPIENT_EMAIL")

PEPPER_RSS_URL = "https://www.pepper.pl/rss/szerokie-wyszukiwanie/perplexity"


def fetch_pepper_deals():
  """Pobiera oferty z Pepper.pl (RSS)"""
  feed = feedparser.parse(PEPPER_RSS_URL)
  deals = []
  for entry in feed.entries[:8]:
    deals.append(
        f"Tytuł: {entry.title}\nLink: {entry.link}\nOpis: {entry.summary}\n---"
    )
  return "\n".join(deals) if deals else "Brak nowych wpisów w Pepper RSS."


def fetch_marketplace_deals():
  """Przeszukuje Allegro, Ceneo, G2A i G2G za pomocą DuckDuckGo"""
  results = []
  target_sites = [
      ("Allegro", "perplexity pro site:allegro.pl"),
      ("Ceneo", "perplexity pro site:ceneo.pl"),
      ("G2A", "perplexity pro site:g2a.com"),
      ("G2G", "perplexity pro site:g2g.com"),
  ]

  try:
    with DDGS() as ddgs:
      for site_name, query in target_sites:
        search_results = list(ddgs.text(query, max_results=3))
        if search_results:
          results.append(f"=== ŹRÓDŁO: {site_name} ===")
          for item in search_results:
            results.append(
                f"Tytuł: {item.get('title')}\n"
                f"Link: {item.get('href')}\n"
                f"Opis: {item.get('body')}\n---"
            )
  except Exception as e:
    print(f"Błąd podczas wyszukiwania w marketach: {e}")

  return (
      "\n".join(results)
      if results
      else "Brak wyników z wyszukiwarki dla giełd/sklepów."
  )


def analyze_with_ai(pepper_data, market_data):
  """Łączy dane i podsumowuje je przez Gemini API"""
  if not GEMINI_API_KEY:
    raise ValueError("Brak klucza GEMINI_API_KEY!")

  client = genai.Client(api_key=GEMINI_API_KEY)

  prompt = f"""
    Jesteś analitykiem okazjonalnym. Przeanalizuj zgromadzone dane z rożnych źródeł pod kątem ofert subskrypcji, kluczy i kodów promocyjnych do **Perplexity Pro**.

    --- DANE Z PEPPER.PL ---
    {pepper_data}

    --- DANE Z ALLEGRO, CENEO, G2A, G2G ---
    {market_data}

    WYMAGANIA CO DO RAPORTU:
    1. Przefiltruj wyniki i odrzuć oferty niezwiązane z Perplexity Pro.
    2. Pogrupuj znalezione oferty według platform (Pepper, Allegro, Ceneo, G2A, G2G).
    3. Dla każdej pasującej oferty podaj:
       - Nazwę / Tytuł
       - Szacowaną cenę (jeśli podana w opisie/tytule)
       - Link bezpośredni
       - Krótki komentarz (opłacalność, czy oferta wymaga nowego konta itp.)
    4. Jeśli na danej platformie nie znaleziono nic pasującego, napisz krótko: "Brak nowych ofert".
    """

  # Models ordered by preference — only currently supported model IDs.
  # See: https://ai.google.dev/gemini-api/docs/models
  candidate_models = [
      "gemini-2.5-flash-lite",       # lightest 2.5 model, lowest quota usage
      "gemini-2.5-flash",            # full 2.5-flash
      "gemini-2.0-flash",            # 2.0 fallback
      "gemini-2.0-flash-lite",       # smallest 2.0 fallback
  ]

  import re

  def _parse_retry_delay(err_msg: str, fallback: int) -> int:
    """Extract the suggested retry delay (seconds) from a 429 error message."""
    # The API returns retryDelay as e.g. '49s' inside the JSON error body
    match = re.search(r"retryDelay['\"]:\s*['\"](\d+)s", err_msg)
    if match:
      return int(match.group(1)) + 5  # honour API hint + small buffer
    return fallback

  last_exception = None
  for model_name in candidate_models:
    for attempt in range(1, 4):
      try:
        print(f"Próba generowania raportu za pomocą modelu: {model_name} (próba {attempt})...")
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
        )
        if response and response.text:
          print(f"Sukces z użyciem modelu {model_name}!")
          return response.text
      except Exception as e:
        last_exception = e
        err_msg = str(e)
        print(f"Błąd dla modelu {model_name}: {err_msg}")
        if "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg:
          # Always honour the full delay the API tells us to wait
          wait_time = _parse_retry_delay(err_msg, fallback=60 * attempt)
          print(f"Przekroczono limit/rate limit. Czekam {wait_time} s przed kolejną próbą...")
          time.sleep(wait_time)
        else:
          # 404 / NOT_FOUND — model unavailable, skip to next immediately
          print(f"Model {model_name} niedostępny, przechodzę do następnego...")
          break

  print(f"Ostrzeżenie: Nie udało się wygenerować raportu przez Gemini API po przetestowaniu wszystkich modeli. Ostatni błąd: {last_exception}")
  print("Generowanie raportu awaryjnego (bez analizy AI)...")
  return f"""[RAPORT AWARYJNY - Brak dostępu do Gemini API / przekroczony limit]

Ze względu na ograniczenia API Gemini, poniżej przesyłamy surowe zebrane dane bez podsumowania AI.

--- DANE Z PEPPER.PL ---
{pepper_data}

--- DANE Z ALLEGRO, CENEO, G2A, G2G ---
{market_data}
"""


def send_email(subject, body):
  """Wysyła raport na adres e-mail"""
  if not all([SENDER_EMAIL, SENDER_PASSWORD, RECIPIENT_EMAIL]):
    raise ValueError("Brak kompletnych danych SMTP w sekretach!")

  msg = MIMEMultipart()
  msg["From"] = SENDER_EMAIL
  msg["To"] = RECIPIENT_EMAIL
  msg["Subject"] = subject

  msg.attach(MIMEText(body, "plain", "utf-8"))

  with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
    server.login(SENDER_EMAIL, SENDER_PASSWORD)
    server.send_message(msg)


if __name__ == "__main__":
  print("1. Pobieranie danych z Pepper RSS...")
  pepper_data = fetch_pepper_deals()

  print("2. Przeszukiwanie Allegro, Ceneo, G2A, G2G...")
  market_data = fetch_marketplace_deals()

  print("3. Analiza i generowanie raportu przez Gemini...")
  summary = analyze_with_ai(pepper_data, market_data)

  print("4. Wysyłanie wiadomości e-mail...")
  send_email("Codzienny raport: Okazje Perplexity Pro (Multi-Site)", summary)
  print("Gotowe! Raport został pomyślnie przesłany.")
