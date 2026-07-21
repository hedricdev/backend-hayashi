from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str
    IFRUTI_URL: str
    IFRUTI_CPF: str
    IFRUTI_EMPRESA: str
    IFRUTI_PASSWORD: str
    SPREADSHEET_ID: str
    GOOGLE_SERVICE_ACCOUNT_EMAIL: str
    GOOGLE_PRIVATE_KEY: str
    FRONTEND_URL: str = "https://app.hayashi.asynnc.cloud"

    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 480  # 8 horas

    AUTO_SYNC_ENABLED: bool = True
    AUTO_SYNC_INTERVALO_SEGUNDOS: int = 3600  # 1h

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
