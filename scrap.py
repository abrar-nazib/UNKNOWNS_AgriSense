import requests

url = "https://czis.cropzoning.gov.bd/?upz=203025"

response = requests.get(url)

print(response.text)