import os
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("GOOGLE_API_KEY")

if not api_key:
    print("No API Key found")
else:
    genai.configure(api_key=api_key)
    try:
        with open("models.txt", "w", encoding="utf-8") as f:
            f.write("Listing models...\n")
            for m in genai.list_models():
                if 'generateContent' in m.supported_generation_methods:
                    f.write(f"Model: {m.name}\n")
    except Exception as e:
        with open("models.txt", "w", encoding="utf-8") as f:
            f.write(f"Error listing models: {e}")
