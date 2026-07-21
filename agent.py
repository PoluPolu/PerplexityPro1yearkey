import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import feedparser
from google import genai

# Pobieranie danych z sekretów GitHub Actions
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
SENDER_EMAIL = os.environ.get("SENDER_EMAIL")
SENDER_PASSWORD = os.environ.get("SENDER_PASSWORD")
RECIPIENT_EMAIL = os.environ.get("RECIPIENT_EMAIL")

PEPPER_RSS_URL = "https://www.pepper.pl/rss/szerokie-wyszukiwanie/perplexity"


def fetch_pepper_deals():
  """Pobiera najnowsze wpisy z RSS Pepper.pl"""
  feed = feedparser.parse(PEPPER_RSS_URL)
  deals = []
  for entry in feed.entries[:10]:
    deals.append(
        f"Tytuł: {entry.title}\nLink: {entry.link}\nOpis: {entry.summary}\n---"
    )
  return "\n".join(deals) if deals else "Brak nowych wpisów w RSS."


def analyze_with_ai(raw_data):
  """Analizuje zebrane dane za pomocą Google Gemini API"""
  if not GEMINI_API_KEY:
    raise ValueError("Brak klucza GEMINI_API_KEY w zmiennych środowiskowych!")

  # Inicjalizacja klienta Gemini
  client = genai.Client(api_key=GEMINI_API_KEY)

  prompt = f"""
    Przeanalizuj poniższe wpisy z serwisu okazjonalnego Pepper.pl.
    Wybierz wyłącznie oferty dotyczące dostępu, kluczy, kodów promocyjnych lub subskrypcji Perplexity Pro.
    Zignoruj oferty niezwiązane z tematem.
    
    Wpisy:
    {raw_data}
    
    Sformatuj odpowiedź czytelnie w punktach:
    - Tytuł okazji
    - Cena / Zniżka
    - Link bezpośredni
    - Krótki komentarz opłacalności
    
    Jeśli nie ma żadnej pasującej oferty, napisz krótko: 'Dzisiaj brak nowych promocji na Perplexity Pro w serwisie Pepper.pl.'
    """

  # Wywołanie modelu Gemini (szybki i darmowy model Flash)
  response = client.models.generate_content(
      model="gemini-2.5-flash",
      contents=prompt,
  )

  return response.text


def send_email(subject, body):
  """Wysyła e-mail przez serwer SMTP Gmaila"""
  if not all([SENDER_EMAIL, SENDER_PASSWORD, RECIPIENT_EMAIL]):
    raise ValueError("Brak danych do wysyłki e-maila w zmiennych środowiskowych!")

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
  raw_deals = fetch_pepper_deals()

  print("2. Analizowanie przez Gemini API...")
  summary = analyze_with_ai(raw_deals)

  print("3. Wysyłanie e-maila...")
  send_email("Codzienny raport: Okazje Perplexity Pro", summary)
  print("Gotowe! Raport przesłany pomyślnie.")
