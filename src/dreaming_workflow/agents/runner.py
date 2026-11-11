from collections.abc import Sequence

from google.adk.agents import LlmAgent
from google.adk.agents.run_config import RunConfig
from google.adk.apps import App
from google.adk.models import BaseLlm
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from dreaming_workflow.agents.claude_model import (
    CONTEXT_CACHE,
    generate_content_config,
)
from dreaming_workflow.agents.tools import ToolFunction

APP_NAME = "dreaming-workflow"
USER_ID = "dream"


async def run_agent(
    *,
    name: str,
    model: BaseLlm,
    instruction: str,
    tools: Sequence[ToolFunction],
    message: str,
    max_llm_calls: int,
) -> None:
    """Run one agent in a fresh ADK session until it ends its turn."""
    agent = LlmAgent(
        name=name,
        model=model,
        # A static instruction reaches the model unchanged; ADK would treat
        # braces in a plain instruction as session-state placeholders.
        static_instruction=instruction,
        tools=list(tools),
        generate_content_config=generate_content_config(),
    )
    app = App(name=APP_NAME, root_agent=agent, context_cache_config=CONTEXT_CACHE)
    session_service = InMemorySessionService()
    session = await session_service.create_session(app_name=APP_NAME, user_id=USER_ID)
    async with Runner(app=app, session_service=session_service) as runner:
        async for _event in runner.run_async(
            user_id=USER_ID,
            session_id=session.id,
            new_message=types.Content(role="user", parts=[types.Part(text=message)]),
            run_config=RunConfig(max_llm_calls=max_llm_calls),
        ):
            pass
