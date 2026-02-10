"""
Multi-AI Research Orchestrator — Provider Modules
각 AI(Claude, Gemini, GPT)와의 통신을 담당합니다.
API 모드와 CLI 폴백을 모두 지원합니다.
"""
import os
import json
import time
import asyncio
import subprocess
import logging
from abc import ABC, abstractmethod
from typing import Optional

logger = logging.getLogger("providers")


class AIProvider(ABC):
    """AI 프로바이더 추상 클래스"""

    def __init__(self, name: str, config: dict):
        self.name = name
        self.config = config
        self.role = config.get("role", "연구 전문가")
        self.mode = config.get("mode", "api")
        self.enabled = config.get("enabled", True)

    @abstractmethod
    async def query(self, prompt: str, deep_research: bool = False) -> str:
        """프롬프트를 보내고 응답을 받습니다."""
        pass

    async def query_with_fallback(self, prompt: str, deep_research: bool = False) -> str:
        """API 실패 시 CLI로 폴백합니다."""
        try:
            return await self.query(prompt, deep_research)
        except Exception as e:
            logger.warning(f"[{self.name}] API 실패: {e}. CLI 폴백 시도...")
            return await self._cli_fallback(prompt)

    async def _cli_fallback(self, prompt: str) -> str:
        """CLI 명령으로 폴백"""
        raise NotImplementedError(f"[{self.name}] CLI 폴백 미구현")


# ═══════════════════════════════════════════════════════════
# Claude Provider (Anthropic API)
# ═══════════════════════════════════════════════════════════
class ClaudeProvider(AIProvider):
    def __init__(self, config: dict):
        super().__init__("Claude", config)
        self.api_key = self._resolve_key(config.get("api_key", ""))
        self.model = config.get("model", "claude-sonnet-4-5-20250929")
        self.research_model = config.get("research_model", self.model)
        self.max_tokens = config.get("max_tokens", 16000)

    def _resolve_key(self, key: str) -> str:
        if key.startswith("${") and key.endswith("}"):
            env_var = key[2:-1]
            return os.environ.get(env_var, "")
        return key

    async def query(self, prompt: str, deep_research: bool = False) -> str:
        if not self.api_key:
            return await self._cli_fallback(prompt)

        try:
            import anthropic
        except ImportError:
            logger.info("anthropic 패키지 설치 중...")
            subprocess.run(["pip", "install", "anthropic", "--break-system-packages", "-q"],
                           capture_output=True)
            import anthropic

        client = anthropic.Anthropic(api_key=self.api_key)
        model = self.research_model if deep_research else self.model

        kwargs = {
            "model": model,
            "max_tokens": self.max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }

        # 연구 모드: 웹 검색 도구 + extended thinking
        if deep_research:
            kwargs["tools"] = [{"type": "web_search_20250305", "name": "web_search"}]

        response = client.messages.create(**kwargs)

        # 응답 텍스트 추출
        texts = []
        for block in response.content:
            if hasattr(block, "text"):
                texts.append(block.text)
        return "\n".join(texts)

    async def _cli_fallback(self, prompt: str) -> str:
        """claude -p 명령 사용"""
        escaped = prompt.replace("'", "'\\''")
        cmd = f"claude -p '{escaped}'"
        proc = await asyncio.create_subprocess_shell(
            cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"Claude CLI 실패: {stderr.decode()}")
        return stdout.decode()


# ═══════════════════════════════════════════════════════════
# Gemini Provider (Google GenAI API)
# ═══════════════════════════════════════════════════════════
class GeminiProvider(AIProvider):
    def __init__(self, config: dict):
        super().__init__("Gemini", config)
        self.api_key = self._resolve_key(config.get("api_key", ""))
        self.model = config.get("model", "gemini-2.5-pro")
        self.research_agent = config.get("research_agent", "deep-research-pro-preview-12-2025")
        self.max_tokens = config.get("max_tokens", 16000)

    def _resolve_key(self, key: str) -> str:
        if key.startswith("${") and key.endswith("}"):
            env_var = key[2:-1]
            return os.environ.get(env_var, "")
        return key

    async def query(self, prompt: str, deep_research: bool = False) -> str:
        if not self.api_key:
            return await self._cli_fallback(prompt)

        try:
            from google import genai
        except ImportError:
            logger.info("google-genai 패키지 설치 중...")
            subprocess.run(["pip", "install", "google-genai", "--break-system-packages", "-q"],
                           capture_output=True)
            from google import genai

        client = genai.Client(api_key=self.api_key)

        if deep_research:
            return await self._deep_research(client, prompt)
        else:
            return await self._standard_query(client, prompt)

    async def _standard_query(self, client, prompt: str) -> str:
        from google import genai
        response = client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=genai.types.GenerateContentConfig(
                tools=[genai.types.Tool(google_search=genai.types.GoogleSearch())],
            ),
        )
        return response.text

    async def _deep_research(self, client, prompt: str) -> str:
        """Gemini Deep Research Agent 사용 (Interactions API)"""
        logger.info("[Gemini] Deep Research 시작 (5~15분 소요)...")

        interaction = client.interactions.create(
            agent=self.research_agent,
            input=prompt,
            background=True,
        )

        # 폴링
        max_wait = 1800  # 30분 타임아웃
        elapsed = 0
        while elapsed < max_wait:
            interaction = client.interactions.get(interaction.id)
            if interaction.status == "completed":
                return interaction.outputs[-1].text
            elif interaction.status == "failed":
                raise RuntimeError(f"Gemini Deep Research 실패: {interaction.error}")
            await asyncio.sleep(15)
            elapsed += 15
            if elapsed % 60 == 0:
                logger.info(f"  ... {elapsed}초 경과, 아직 진행 중")

        raise TimeoutError("Gemini Deep Research 타임아웃 (30분)")

    async def _cli_fallback(self, prompt: str) -> str:
        escaped = prompt.replace("'", "'\\''")
        cmd = f"gemini -p '{escaped}'"
        proc = await asyncio.create_subprocess_shell(
            cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"Gemini CLI 실패: {stderr.decode()}")
        return stdout.decode()


# ═══════════════════════════════════════════════════════════
# GPT Provider (OpenAI API)
# ═══════════════════════════════════════════════════════════
class GPTProvider(AIProvider):
    def __init__(self, config: dict):
        super().__init__("GPT", config)
        self.api_key = self._resolve_key(config.get("api_key", ""))
        self.model = config.get("model", "gpt-4.1")
        self.research_model = config.get("research_model", "o4-mini-deep-research-2025-06-26")
        self.max_tokens = config.get("max_tokens", 16000)

    def _resolve_key(self, key: str) -> str:
        if key.startswith("${") and key.endswith("}"):
            env_var = key[2:-1]
            return os.environ.get(env_var, "")
        return key

    async def query(self, prompt: str, deep_research: bool = False) -> str:
        if not self.api_key:
            return await self._cli_fallback(prompt)

        try:
            from openai import OpenAI
        except ImportError:
            logger.info("openai 패키지 설치 중...")
            subprocess.run(["pip", "install", "openai", "--break-system-packages", "-q"],
                           capture_output=True)
            from openai import OpenAI

        client = OpenAI(api_key=self.api_key)

        if deep_research:
            return await self._deep_research(client, prompt)
        else:
            return await self._standard_query(client, prompt)

    async def _standard_query(self, client, prompt: str) -> str:
        response = client.responses.create(
            model=self.model,
            input=[{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
            tools=[{"type": "web_search_preview"}],
        )

        texts = []
        for item in response.output:
            if hasattr(item, "content"):
                for block in item.content:
                    if hasattr(block, "text"):
                        texts.append(block.text)
            elif hasattr(item, "text"):
                texts.append(item.text)
        return "\n".join(texts) if texts else str(response.output)

    async def _deep_research(self, client, prompt: str) -> str:
        """OpenAI Deep Research 모델 사용"""
        logger.info("[GPT] Deep Research 시작 (5~20분 소요)...")

        response = client.responses.create(
            model=self.research_model,
            input=[{
                "role": "user",
                "content": [{"type": "input_text", "text": prompt}],
            }],
            reasoning={"summary": "auto"},
            tools=[{"type": "web_search_preview"}],
        )

        texts = []
        for item in response.output:
            if hasattr(item, "content"):
                for block in item.content:
                    if hasattr(block, "text"):
                        texts.append(block.text)
            elif hasattr(item, "text"):
                texts.append(item.text)
        return "\n".join(texts) if texts else str(response.output)

    async def _cli_fallback(self, prompt: str) -> str:
        escaped = prompt.replace("'", "'\\''")
        cmd = f"codex exec '{escaped}'"
        proc = await asyncio.create_subprocess_shell(
            cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"Codex CLI 실패: {stderr.decode()}")
        return stdout.decode()


# ═══════════════════════════════════════════════════════════
# 팩토리 함수
# ═══════════════════════════════════════════════════════════
def create_provider(name: str, config: dict) -> AIProvider:
    providers = {
        "claude": ClaudeProvider,
        "gemini": GeminiProvider,
        "gpt": GPTProvider,
    }
    cls = providers.get(name)
    if cls is None:
        raise ValueError(f"알 수 없는 프로바이더: {name}")
    return cls(config)
