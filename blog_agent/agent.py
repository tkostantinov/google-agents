# agent.py

import os
import datetime

from dotenv import load_dotenv

from google.adk.agents import Agent, LoopAgent
from google.adk.models.lite_llm import LiteLlm
from google.adk.tools import agent_tool

# Load environment variables from .env file

load_dotenv()

# Mistral API (see README.md). litellm reads MISTRAL_API_KEY from the environment automatically.
MISTRAL_MODEL = os.getenv("MISTRAL_MODEL", "mistral-large-latest")

# This pipeline makes several rapid, sequential calls per request; automatic
# retry-with-backoff absorbs 429s from the API's own rate limit (this key is
# capped at 4 requests/minute, so retries need to span past a minute boundary).
MODEL = LiteLlm(
    model=f"mistral/{MISTRAL_MODEL}",
    num_retries=10,
    retry_strategy="exponential_backoff_retry",
)

# Ollama runs in Docker (see README.md); point litellm's ollama_chat provider at it.
# OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1")
# os.environ.setdefault("OLLAMA_API_BASE", os.getenv("OLLAMA_API_BASE", "http://localhost:11434"))

# MODEL = LiteLlm(model=f"ollama_chat/{OLLAMA_MODEL}")


# --- Sub-Agent Planner ---

blog_planner = Agent(
    name="BlogPlanner",
    model=MODEL,
    description="Create a practical skimmable output in Markdown.",
    instruction="""
You are a techincal content strategist. Produce a clear Markdown outline with:
- Title
- Short intro
- 4-6 main sections (each with 2-3 bullets)
- Conclusion

If `codebase_context` exists in state, weave in specific section/snippets.
Return only the outline im Markdown.
""",
    output_key="blog_outline",
)


class OutlineValidationChecker(Agent):
    def __init__(self):
        super().__init__(
            name="OutlineValidationChecker",
            model=MODEL,
            description="Validates that the outline is usable.",
            instruction="""
Check the outline in state['blog_outline']. If it has a title, intro, 
4-6 sections and a conclusion, resopond exactly "ok", 
Otherwise respond exactly "retry" and list missing pieces.
""",
            output_key="validation_result",
        )

robust_blog_planner = LoopAgent(
    name="RobustBlogPlanner",
    description="Retries planning if validation fails.",
    sub_agents=[blog_planner, OutlineValidationChecker()],
    max_iterations=3,
)


# --- Sub-Agent Writer ---
blog_writer = Agent(
    name="BlogWriter",
    model=MODEL,
    description="Writes a technical blog post from the outline.",
    instruction="""
Write a complete Markdown article in `blog_outline`.

Guidelines:
- Audience: software engineers; skip basics and focus on practical insigts.
- Explain both the 'how' and 'why'.
- Include consise code snippets when helpful.
- Follow the outlines's structure (H2/H3).
- Output only the final article in Markdown (no fence around the whole post). 
""",
    output_key="blog_post",
)



class BlogPostValidationChecker(Agent):
    def __init__(self):
        super().__init__(
            name="BlogPostValidationChecker",
            model=MODEL,
            description="Validates thae final post.",
            instruction="""
Check `blog_post` for: intro, clear sections matching the outline, 
conclusion, and techincal clarity.
If passes, respond "ok". Else respond "retry" with the specific fixes.
""",
            output_key="validation_result",
        )


robust_blog_writer = LoopAgent(
    name="RobustBlogWriter",
    description="Retries writing if validation fails.",
    sub_agents=[blog_writer, BlogPostValidationChecker()],
    max_iterations=3,
)

# expose planner and writer as tools so that the root agent can call them explicitly
planner_tool = agent_tool.AgentTool(agent=robust_blog_planner)
writer_tool = agent_tool.AgentTool(agent=robust_blog_writer)

root_agent = Agent(
    name="RootAgent",
    model=MODEL,
    description="Minimal multi-agent Blogger that plans and writes.",
    instruction=f"""
If the user gives a topic:
1) Call the planner tool to generate the outline. Call it with exactly one
   argument named "request", a string containing the topic — for example:
   {{"request": "benefits of using type hints in python"}}
2) Call the writer tool the same way (one "request" string argument) to
   produce the full draft.
3) End with 3 alternative titles and 2 tweet-length hooks.

If the trends tool fails or times out, continue with a sensible outline and a draft anyway.

Date: {datetime.datetime.now().strftime("%Y-%m-%d")}
""",
    tools=[
        planner_tool, # calls the RobustBlogPlanner sub-agent
        writer_tool, # calls the RobustBlogWriter sub-agent
        ],
)

