import os, requests
from dotenv import load_dotenv
load_dotenv()

url = "https://api.aviationstack.com/v1/airports"

params = {
    "access_key": os.getenv("AVIATIONSTACK_API_KEY")
}

response = requests.get(url, params=params)

print(response.status_code)
print(response.json())