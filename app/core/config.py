from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    minio_endpoint: str
    minio_access_key: str
    minio_secret_key: str
    bucket_name: str
    database_url: str
    model_config = SettingsConfigDict(env_file=".env")


settings = Settings()
