"""Markdown and TeX in assistant messages in the native work transcript."""
from functools import lru_cache

from mistune import HTMLRenderer, Markdown
from mistune.plugins.formatting import strikethrough
from mistune.plugins.table import table
from mistune.plugins.task_lists import task_lists
from mistune.plugins.url import url


class WorkRenderer(HTMLRenderer):
    def image(self, text, url, title=None):
        # Only formulas produced locally may supply images to the transcript.
        return text or '图片'

    def formula(self, text, display=False):
        from .formula_render import render_formula
        return render_formula(text, display)

    def display_equation(self, text):
        return '<p align="center">' + self.formula(text, display=True) + '</p>\n'

    def task_list_item(self, text, checked=False):
        return '<li>' + ('☑ ' if checked else '☐ ') + text + '</li>\n'


# Let Markdown handle fences, code spans, links and escapes. Consume the entire
# formula as one token before its TeX backslashes, asterisks or underscores can
# acquire Markdown meaning. Each alternative matches its own closing delimiter.
_INLINE_MATH = (
    r'\\\((?P<tex_inline>(?:[^\\\n]|\\(?!\)).)+?)\\\)'
    r'|\\\[(?P<tex_display>(?:[^\\]|\\(?!\])[\s\S])+?)\\\]'
    r'|\$\$(?P<dollar_display>(?:[^$\\]|\\[\s\S]|\$(?!\$))+?)\$\$'
    r'|(?<!\$)\$(?![\s$])(?P<dollar_inline>(?:[^$\\\n]|\\[^\n])+?)(?<!\s)\$(?![\d$])'
)
_BLOCK_MATH = (
    r'^ {0,3}(?:\\\[(?P<block_tex>(?:[^\\]|\\(?!\])[\s\S])+?)\\\]'
    r'|\$\$(?P<block_dollar>(?:[^$\\]|\\[\s\S]|\$(?!\$))+?)\$\$)[ \t]*$'
)


def _inline_formula(inline, match, state):
    text = match.group()
    display = text.startswith((r'\[', '$$'))
    delimiter_size = 1 if text.startswith('$') and not display else 2
    state.append_token(dict(type='formula', raw=text[delimiter_size:-delimiter_size],
                            attrs={'display': display}))
    return match.end()


def _display_equation(block, match, state):
    state.append_token(dict(type='display_equation', raw=match.group('block_tex') or match.group('block_dollar')))
    return match.end() + 1


def _math_plugin(md):
    md.inline.register('formula', _INLINE_MATH, _inline_formula, before='escape')
    md.block.register('display_equation', _BLOCK_MATH, _display_equation, before='list')
    for rules in (md.block.list_rules, md.block.block_quote_rules):
        md.block.insert_rule(rules, 'display_equation', before='list')


_parser = Markdown(renderer=WorkRenderer(escape=True),
                   plugins=[table, strikethrough, task_lists, url, _math_plugin])


@lru_cache(maxsize=64)
def markdown_body(text):
    return _parser(text)
