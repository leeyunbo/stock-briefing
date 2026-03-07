"""차트 미리보기 HTML 생성 스크립트."""

import base64
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from app.publishing.chart import parse_chart_directives, render_chart

# 샘플 HTML (LLM이 생성할 법한 형태)
SAMPLE_HTML = """
<h2>넷플릭스 실적 서프라이즈와 스트리밍 전쟁</h2>

<p>넷플릭스가 4분기 실적 발표에서 시장 예상치를 크게 상회하며 주가가 급등했습니다.
광고 기반 요금제의 성공과 비밀번호 공유 단속 효과가 본격적으로 나타나고 있습니다.</p>

<!-- CHART:line ticker=NFLX period=3mo title="넷플릭스 3개월 주가 추이" -->

<h3>스트리밍 빅3 주가 비교</h3>

<p>넷플릭스의 강세가 두드러지는 가운데, 디즈니+와 워너브라더스의 스트리밍 사업도
변화를 맞이하고 있습니다. 최근 3개월간 주요 스트리밍 기업의 주가 흐름을 비교해보면
넷플릭스의 독주가 확연합니다.</p>

<!-- CHART:compare ticker=NFLX,DIS,WBD period=3mo title="스트리밍 빅3 주가 비교 (정규화)" -->

<h3>주요 기술주 등락률</h3>

<p>넷플릭스의 급등이 기술주 전반에 미치는 영향을 살펴봅니다.
최근 5거래일 기준 주요 기술주의 등락률입니다.</p>

<!-- CHART:bar tickers=NFLX,AAPL,GOOGL,MSFT,AMZN period=5d title="주요 기술주 5일 등락률" -->

<h3>투자 시사점</h3>
<p>넷플릭스의 실적 호조는 스트리밍 시장의 구조적 변화를 반영합니다.</p>
"""

def main():
    directives = parse_chart_directives(SAMPLE_HTML)
    print(f"차트 지시자 {len(directives)}개 발견")

    html = SAMPLE_HTML

    for i, directive in enumerate(directives):
        print(f"  [{i+1}] {directive['type']}: {directive['params']}")
        chart_bytes = render_chart(directive)

        if chart_bytes:
            b64_data = base64.b64encode(chart_bytes).decode()
            title_text = directive["params"].get("title", f"chart-{i}")
            img_tag = (
                f'<figure style="margin:1.5rem 0;">'
                f'<img src="data:image/png;base64,{b64_data}" alt="{title_text}" '
                f'style="width:100%;max-width:800px;height:auto;border-radius:12px;'
                f'box-shadow:0 2px 12px rgba(0,0,0,0.08);" />'
                f'</figure>'
            )
            html = html.replace(directive["placeholder"], img_tag)
            print(f"      ✓ 렌더링 완료 ({len(chart_bytes):,} bytes)")
        else:
            html = html.replace(directive["placeholder"], "<p>[차트 렌더링 실패]</p>")
            print(f"      ✗ 렌더링 실패")

    # HTML 페이지로 래핑
    full_html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>차트 미리보기 — MoneyDive</title>
<style>
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Apple SD Gothic Neo', sans-serif;
    max-width: 720px;
    margin: 2rem auto;
    padding: 0 1rem;
    color: #191F28;
    line-height: 1.7;
    background: #FAFBFC;
  }}
  h2 {{ font-size: 1.6rem; margin-top: 2rem; }}
  h3 {{ font-size: 1.2rem; margin-top: 1.5rem; color: #333D4B; }}
  p {{ color: #4E5968; }}
  figure {{ text-align: center; }}
  .badge {{
    display: inline-block;
    background: #EFF6FF;
    color: #3182F6;
    padding: 4px 12px;
    border-radius: 20px;
    font-size: 0.85rem;
    font-weight: 600;
    margin-bottom: 1rem;
  }}
</style>
</head>
<body>
<div class="badge">차트 미리보기</div>
{html}
</body>
</html>"""

    out_path = os.path.join(os.path.dirname(__file__), "chart_preview.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(full_html)

    print(f"\n✓ 미리보기 저장: {out_path}")
    print(f"  브라우저에서 열어보세요: open {out_path}")


if __name__ == "__main__":
    main()
