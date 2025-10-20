from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    PRINTER_MODE: str = Field(default="local", env="PRINTER_MODE")
    PRINTER_LAYOUT: str = Field(default="2across", env="PRINTER_LAYOUT")
    PRINTER_DUPLICATE_SINGLE: bool = Field(default=True, env="PRINTER_DUPLICATE_SINGLE")
    PRINTER_HOST: str = Field(default="192.168.1.50", env="PRINTER_HOST")
    PRINTER_PORT: int = Field(default=9100, env="PRINTER_PORT")
    LABEL_TEMPLATE: str = Field(default="etiqueta_50x30", env="LABEL_TEMPLATE")

    class Config:
        env_file = ".env"
        case_sensitive = False


def _load_settings() -> Settings:
    return Settings()


settings = _load_settings()
