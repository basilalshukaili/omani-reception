"""Render the P1 system prompt from a validated ``BusinessConfig``.

This is the narrow seam between configuration and the LLM. The Jinja2 template
lives next to this module so editing the prompt does not require a code change.

In P4 the dialect layer will add lexicon-rendered partials, retrieved Omani
phrasings, and few-shot examples; for P1 we ship a single, self-contained
Arabic template that already embeds the lexicon and banned-tokens guidance
inline. The interface here is intentionally stable across phases — later
phases just enrich the context dict passed to the template.
"""

from __future__ import annotations

from pathlib import Path

import structlog
from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from engine.config.schema import BusinessConfig

__all__ = ["SystemPromptBuilder"]

log = structlog.get_logger(__name__)

# Template name relative to ``templates_dir``. Hardcoded for P1; a future
# version can pick a template based on ``persona.region`` or business overrides.
_P1_TEMPLATE = "p1_system_prompt.j2"


class SystemPromptBuilder:
    """Render the P1 system prompt from business config + persona.

    The builder is stateless beyond its Jinja environment, so a single
    instance can be shared across all conversations.
    """

    def __init__(self, templates_dir: Path | None = None) -> None:
        """Initialize the builder.

        Args:
            templates_dir: Directory holding the Jinja templates. Defaults to
                ``engine/prompts/templates`` next to this module.
        """
        if templates_dir is None:
            templates_dir = Path(__file__).resolve().parent / "templates"
        if not templates_dir.is_dir():
            raise FileNotFoundError(f"templates_dir does not exist: {templates_dir}")

        self._templates_dir = templates_dir
        # autoescape stays off — the template is plain text, not HTML, and
        # escaping Arabic punctuation would corrupt the prompt. We do enable
        # StrictUndefined so a typo in the template (e.g., ``persona.nmae``)
        # raises immediately instead of rendering as empty.
        self._env = Environment(
            loader=FileSystemLoader(str(templates_dir)),
            autoescape=select_autoescape(disabled_extensions=("j2",), default=False),
            undefined=StrictUndefined,
            trim_blocks=False,
            lstrip_blocks=False,
            keep_trailing_newline=True,
        )

    @property
    def templates_dir(self) -> Path:
        """The directory the Jinja environment loads from."""
        return self._templates_dir

    def build(self, config: BusinessConfig) -> str:
        """Render the system prompt for the given business config.

        Returns:
            The rendered prompt as a single Arabic string, ready to be sent
            as the ``system`` message to an LLM provider.
        """
        template = self._env.get_template(_P1_TEMPLATE)
        rendered = template.render(
            business=config.business,
            persona=config.persona,
            llm=config.llm,
            dialect=config.dialect,
        )
        log.debug(
            "system_prompt.rendered",
            business_id=config.business.id,
            persona_name=config.persona.name,
            chars=len(rendered),
        )
        return rendered
