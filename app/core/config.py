from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    app_name: str = "AVA SmartFuel"
    official_fuel_api_url: str = (
        "https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets/"
        "prix-des-carburants-en-france-flux-instantane-v2/records"
    )
    spanish_fuel_api_url: str = (
        "https://sedeaplicaciones.minetur.gob.es/ServiciosRESTCarburantes/"
        "PreciosCarburantes/EstacionesTerrestres/"
    )
    italian_prices_csv_url: str = "https://www.mimit.gov.it/images/exportCSV/prezzo_alle_8.csv"
    italian_stations_csv_url: str = (
        "https://www.mimit.gov.it/images/exportCSV/anagrafica_impianti_attivi.csv"
    )
    default_radius_km: float = 50
    default_limit: int = 50
    official_cache_ttl_seconds: int = 21600
    nearby_cache_ttl_seconds: int = 300
    database_url: str = "postgresql://ava_user:change-me@127.0.0.1:5432/ava_smartfuel"
    jwt_secret: str = "change-this-secret-before-production"


settings = Settings()
