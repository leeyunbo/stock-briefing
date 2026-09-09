"""Slack mrkdwn → 이메일 HTML 변환기 테스트."""

import pytest

from app.publishing.mrkdwn_html import mrkdwn_to_html


@pytest.mark.parametrize(
    "src, expected",
    [
        ("*굵게* 텍스트", "<p><strong>굵게</strong> 텍스트</p>"),
        ("_기울임_ 텍스트", "<p><em>기울임</em> 텍스트</p>"),
        ("• a\n• b", "<ul><li>a</li><li>b</li></ul>"),
        ("- a\n- b", "<ul><li>a</li><li>b</li></ul>"),
        ("첫 줄\n둘째 줄", "<p>첫 줄<br>둘째 줄</p>"),
        ("위\n===\n아래", "<p>위</p><hr><p>아래</p>"),
        ("A & B < C", "<p>A &amp; B &lt; C</p>"),
        ("", ""),
        ("🔺 +1.2% *NVDA*", "<p>🔺 +1.2% <strong>NVDA</strong></p>"),
    ],
)
def test_mrkdwn_to_html(src, expected):
    assert mrkdwn_to_html(src) == expected


def test_blank_lines_split_paragraphs():
    assert mrkdwn_to_html("a\n\nb") == "<p>a</p><p>b</p>"


def test_bullet_then_text():
    assert mrkdwn_to_html("• a\n텍스트") == "<ul><li>a</li></ul><p>텍스트</p>"


def test_asterisk_inside_number_not_bold():
    # 곱셈 기호처럼 공백으로 둘러싸인 * 는 그대로
    assert mrkdwn_to_html("3 * 4") == "<p>3 * 4</p>"
