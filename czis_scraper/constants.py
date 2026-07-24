BASE_URL = "https://czis.cropzoning.gov.bd"

ADMIN_ENDPOINT = f"{BASE_URL}/cz_assets/php/getAdminByCode.php"

# tab key -> (result field name, human-readable label)
AGRO_CLIMATIC_TYPES = {
    "pktp": "Pre-Kharif Transition Period",
    "krgp": "Kharif/Rabi Growing Period",
    "cwz": "Cool Winter Zone",
    "hsz": "Hot Summer Zone",
}

EDAPHIC_TYPES = {
    "landtype": "Land Type",
    "texture": "Soil Texture",
    "consistency": "Soil Consistency",
    "drainage": "Soil Drainage",
    "reaction": "Soil Reaction (pH)",
    "moisture": "Soil Moisture",
    "salinity": "Soil Salinity",
    "recession": "Soil Water Recession",
    "relief": "Relief",
}
