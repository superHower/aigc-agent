import pytest

from backend.services.prompt_builder import PromptContext, PromptType, build_prompt


def test_text_prompt_contains_position_original_and_replacement():
    prompt = build_prompt(PromptContext(
        prompt_type=PromptType.TEXT,
        original='原文"A',
        replace="新品\\首发",
        position="top-left",
    ))
    assert '原文\\"A' in prompt
    assert '新品\\\\首发' in prompt
    assert "top-left" in prompt


@pytest.mark.parametrize("prompt_type,kwargs,marker", [
    (PromptType.BACKGROUND, {"background": "a studio"}, "Replace only the background"),
    (PromptType.SHADE, {"target": "lampshade", "color": "red"}, "Change only the lampshade color"),
    (PromptType.BULB, {"target": "bulb", "bulb": "a warm LED"}, "Replace only the bulb"),
    (PromptType.LOGO, {"brand": "STRYVAN", "position": "center"}, "STRYVAN wordmark"),
])
def test_all_prompt_types(prompt_type, kwargs, marker):
    assert marker in build_prompt(PromptContext(prompt_type=prompt_type, **kwargs))


def test_required_prompt_parameter_is_rejected():
    with pytest.raises(ValueError, match="replace is required"):
        build_prompt(PromptContext(prompt_type=PromptType.TEXT, original="old", position="center"))
