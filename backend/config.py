from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # LLM
    llm_base_url: str = "http://localhost:8080/v1"
    llm_model: str = "qwen2.5-7b-instruct"
    llm_temperature: float = 0.1
    llm_top_p: float = 0.1
    llm_max_tokens: int = 1024

    # Backend
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000
    cors_origins: str = "http://localhost:5173"

    # Knowledge base
    chroma_persist_dir: str = "./.data/chroma"
    chroma_collection: str = "localcowork"
    embed_model: str = "nomic-ai/nomic-embed-text-v1.5"
    embed_device: str = "cpu"

    # MCP Servers
    filesystem_sandbox_dir: str = "~/Documents/localcowork"
    document_output_dir: str = "./.data/documents"
    audit_log_path: str = "./.data/audit/tool_calls.jsonl"

    # Agent
    max_tool_calls: int = 10
    tool_timeout: int = 30

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",")]

    @property
    def sandbox_path(self) -> Path:
        return Path(self.filesystem_sandbox_dir).expanduser().resolve()

    @property
    def audit_path(self) -> Path:
        return Path(self.audit_log_path).expanduser().resolve()


settings = Settings()
