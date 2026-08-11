"""Release manifest를 사람이 검토하기 쉬운 단일 HTML 대시보드로 렌더링한다."""

from __future__ import annotations

from html import escape
from typing import Any


_LABEL_EMOJI = {
    "porosity": "🫧",
    "slag_inclusion": "🪨",
    "crack": "⚡",
    "lack_of_fusion": "🧩",
    "incomplete_penetration": "🕳️",
    "undercut": "🌙",
}


def _text(value: object) -> str:
    """동적 값을 HTML 본문에 안전하게 넣는다."""
    return escape(str(value), quote=True)


def _status_copy(status: str) -> tuple[str, str]:
    """manifest 상태를 화면용 한글 문구와 CSS class로 바꾼다."""
    return {
        "passed": ("검수 통과", "passed"),
        "review": ("검토 필요", "review"),
        "failed": ("검수 실패", "failed"),
    }.get(status, ("상태 미확인", "unknown"))


def _render_label_distribution(label_counts: dict[str, int]) -> str:
    if not label_counts:
        return '<p class="empty">검출된 결함 annotation이 없습니다.</p>'
    maximum = max(label_counts.values()) or 1
    rows = []
    for label, count in label_counts.items():
        width = max(3, round(count / maximum * 100))
        rows.append(
            f"""
            <div class="distribution-row">
              <div class="distribution-label"><span>{_LABEL_EMOJI.get(label, '•')}</span>{_text(label)}</div>
              <div class="distribution-track"><span style="width:{width}%"></span></div>
              <strong>{count}</strong>
            </div>
            """
        )
    return "".join(rows)


def _render_annotation_issues(issues: list[dict[str, Any]]) -> str:
    if not issues:
        return '<p class="empty good">겹침 또는 라벨 충돌 후보가 없습니다.</p>'
    rows = []
    for issue in issues:
        labels = " ↔ ".join(str(label) for label in issue.get("labels", []))
        indices = ", ".join(str(index) for index in issue.get("annotation_indices", []))
        rows.append(
            f"""
            <tr>
              <td><span class="severity {escape(str(issue.get('severity', 'warning')))}">{_text(issue.get('severity', 'warning'))}</span></td>
              <td><code>{_text(issue.get('code', 'unknown'))}</code></td>
              <td>{_text(issue.get('file', ''))}<small>annotation {indices}</small></td>
              <td>{_text(labels)}</td>
              <td>{float(issue.get('iou', 0)):.3f}</td>
            </tr>
            """
        )
    return f"""
      <div class="table-wrap"><table>
        <thead><tr><th>등급</th><th>검사 결과</th><th>파일</th><th>라벨</th><th>IoU</th></tr></thead>
        <tbody>{''.join(rows)}</tbody>
      </table></div>
    """


def _render_status_reasons(reasons: list[dict[str, Any]]) -> str:
    """자동 상태가 결정된 직접 근거를 사람이 읽는 카드로 만든다."""
    return "".join(
        f"""
        <div class="reason-card">
          <strong>{int(reason.get('count', 0))}</strong>
          <div><code>{_text(reason.get('code', 'unknown'))}</code><p>{_text(reason.get('message', ''))}</p></div>
        </div>
        """
        for reason in reasons
    )


def _render_metric_guide(thresholds: dict[str, Any]) -> str:
    """IoU와 perceptual hash 수치를 읽는 기준을 현재 실행값으로 설명한다."""
    return f"""
      <div class="metric-guide">
        <div><b>IoU</b><span>0~1 사이 값이며 1에 가까울수록 Polygon 모양이 비슷합니다. 중복 annotation 기준은 <strong>{float(thresholds.get('duplicate_annotation_iou', 0.9)):.2f}</strong>입니다.</span></div>
        <div><b>Hash 거리</b><span>0~128 사이 값이며 0에 가까울수록 이미지 구조가 비슷합니다. 현재 후보 기준은 <strong>{int(thresholds.get('perceptual_hash_distance', 8))} 이하</strong>입니다.</span></div>
        <div><b>밝기 Δ</b><span>평균 밝기 차이입니다. 현재 후보 기준은 <strong>{float(thresholds.get('brightness_tolerance', 24)):.1f} 이하</strong>이며 Hash 거리와 함께 만족해야 합니다.</span></div>
      </div>
    """


def _render_duplicate_pairs(
    pairs: list[dict[str, Any]],
    thresholds: dict[str, Any],
) -> str:
    if not pairs:
        return '<p class="empty good">중복 또는 유사 이미지 후보가 없습니다.</p>'
    cards = []
    for pair_index, pair in enumerate(pairs, start=1):
        files = pair.get("files", ["", ""])
        thumbnails = pair.get("thumbnails", [])
        hash_distance = int(pair.get("hamming_distance", 0))
        brightness_difference = float(pair.get("brightness_difference", 0))
        if pair.get("code") == "exact_duplicate":
            explanation = "SHA-256 checksum이 같아 파일 내용이 완전히 동일합니다."
        else:
            explanation = (
                f"Hash 거리 {hash_distance} ≤ {int(thresholds.get('perceptual_hash_distance', 8))}, "
                f"밝기 차이 {brightness_difference:.1f} ≤ {float(thresholds.get('brightness_tolerance', 24)):.1f}이므로 "
                "시각적 유사 후보로 분류됐습니다. 중복 확정은 아닙니다."
            )

        def render_candidate(index: int) -> str:
            file_name = files[index] if len(files) > index else ""
            if len(thumbnails) > index:
                visual = (
                    f'<img src="{_text(thumbnails[index])}" '
                    f'alt="{_text(file_name)} 미리보기" loading="lazy">'
                )
            else:
                visual = '<div class="thumbnail-missing">미리보기 없음</div>'
            return f"""
              <figure>{visual}<figcaption>{_text(file_name)}</figcaption></figure>
            """

        cards.append(
            f"""
            <article class="pair-card">
              <div class="pair-heading">
                <div><span>PAIR {pair_index:02d}</span><code>{_text(pair.get('code', 'unknown'))}</code></div>
                <div class="pair-metrics"><strong>Hash {hash_distance}</strong><strong>밝기 Δ {brightness_difference:.1f}</strong></div>
              </div>
              <div class="comparison-grid">{render_candidate(0)}{render_candidate(1)}</div>
              <p class="pair-explanation">{_text(explanation)}</p>
            </article>
            """
        )
    return '<div class="pair-list">' + "".join(cards) + "</div>"


def _render_errors(errors: list[dict[str, Any]]) -> str:
    if not errors:
        return '<p class="empty good">파싱 및 파일 검사 오류가 없습니다.</p>'
    return "".join(
        f'<div class="error-line"><code>{_text(item.get("file", ""))}</code><span>{_text(item.get("error", ""))}</span></div>'
        for item in errors
    )


def render_dashboard(manifest: dict[str, Any]) -> str:
    """외부 자원 없이 열 수 있는 WeldVision 계열 임시 QA 대시보드를 만든다."""
    summary = manifest["summary"]
    qa = manifest["qa"]
    checks = manifest["checks"]
    annotation_issues = checks["annotation_issues"]
    duplicate_images = checks["duplicate_images"]
    thresholds = manifest.get("thresholds", {})
    status_text, status_class = _status_copy(str(manifest["status"]))
    errors = (
        list(qa.get("errors", []))
        + list(checks.get("alignment_issues", []))
        + list(duplicate_images.get("errors", []))
    )
    dataset_digest = str(manifest.get("dataset_digest", ""))
    duplicate_file_count = int(summary.get("duplicate_images", 0))
    duplicate_pair_count = int(summary.get("duplicate_pairs", 0))

    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Welding QA Validation Dashboard</title>
  <style>
    :root {{ color-scheme: dark; --bg:#090a0f; --panel:#151720; --panel-2:#1d1517; --line:#30333f; --text:#f7f3ed; --muted:#a9adb8; --red:#ff4d4d; --orange:#ff8a35; --yellow:#ffd166; --green:#52d28b; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; min-height:100vh; color:var(--text); background:radial-gradient(circle at 76% 0%,#311719 0,transparent 34%),linear-gradient(145deg,#08090d,#11131a 55%,#130d0e); font-family:Inter,"Pretendard","Noto Sans KR",system-ui,sans-serif; }}
    body::before {{ content:""; position:fixed; inset:0; pointer-events:none; opacity:.13; background:repeating-linear-gradient(0deg,transparent 0 3px,rgba(255,255,255,.035) 4px); }}
    .shell {{ width:min(1180px,calc(100% - 32px)); margin:auto; padding:44px 0 64px; position:relative; }}
    header {{ display:flex; justify-content:space-between; align-items:flex-end; gap:24px; padding-bottom:26px; border-bottom:1px solid var(--line); }}
    .eyebrow {{ color:var(--orange); font:700 12px/1.2 ui-monospace,monospace; letter-spacing:.18em; text-transform:uppercase; }}
    h1 {{ font-size:clamp(30px,5vw,58px); margin:10px 0 8px; letter-spacing:-.045em; }}
    header p {{ color:var(--muted); margin:0; }}
    .status {{ flex:none; padding:12px 16px; border:1px solid; border-radius:999px; font-weight:800; }}
    .status.passed {{ color:var(--green); border-color:var(--green); background:#10271c; }}
    .status.review {{ color:var(--yellow); border-color:var(--yellow); background:#2b2510; }}
    .status.failed {{ color:#ff8b8b; border-color:var(--red); background:#301416; }}
    .status.unknown {{ color:var(--muted); border-color:var(--line); }}
    .cards {{ display:grid; grid-template-columns:repeat(4,1fr); gap:14px; margin:24px 0; }}
    .card,.panel {{ background:linear-gradient(145deg,rgba(29,31,42,.96),rgba(18,20,27,.96)); border:1px solid var(--line); border-radius:16px; box-shadow:0 18px 42px rgba(0,0,0,.22); }}
    .card {{ padding:19px; min-height:122px; display:flex; flex-direction:column; justify-content:space-between; }}
    .card span {{ color:var(--muted); font-size:13px; }} .card strong {{ font-size:32px; }} .card em {{ color:var(--orange); font-style:normal; font-size:12px; }}
    .grid {{ display:grid; grid-template-columns:1fr 1fr; gap:18px; margin-top:18px; }}
    .panel {{ padding:22px; overflow:hidden; }} .panel.wide {{ grid-column:1/-1; }}
    h2 {{ font-size:18px; margin:0 0 18px; }} h2 span {{ color:var(--orange); margin-right:7px; }}
    .distribution-row {{ display:grid; grid-template-columns:minmax(160px,1fr) 2fr 36px; gap:12px; align-items:center; margin:13px 0; }}
    .distribution-label {{ display:flex; gap:9px; color:#ddd9d3; font:13px ui-monospace,monospace; }}
    .distribution-track {{ height:8px; background:#282b35; border-radius:99px; overflow:hidden; }} .distribution-track span {{ display:block; height:100%; background:linear-gradient(90deg,var(--red),var(--orange)); border-radius:inherit; }}
    .table-wrap {{ overflow:auto; }} table {{ width:100%; border-collapse:collapse; font-size:13px; }} th {{ color:var(--muted); text-align:left; font-weight:600; border-bottom:1px solid var(--line); padding:10px; white-space:nowrap; }} td {{ padding:12px 10px; border-bottom:1px solid #292c35; vertical-align:top; }} td small {{ display:block; color:var(--muted); margin-top:5px; }} code {{ color:#ffd6bd; font-family:ui-monospace,monospace; }}
    .severity {{ display:inline-block; border-radius:99px; padding:3px 8px; font-size:11px; text-transform:uppercase; }} .severity.error {{ color:#ff9696; background:#351719; }} .severity.warning {{ color:var(--yellow); background:#332b10; }}
    .empty {{ color:var(--muted); padding:22px; margin:0; border:1px dashed var(--line); border-radius:12px; }} .empty.good {{ color:#9ee8bd; }}
    .pair-list {{ display:grid; gap:16px; }} .pair-card {{ border:1px solid #333641; background:#101219; border-radius:14px; overflow:hidden; }}
    .pair-heading {{ display:flex; justify-content:space-between; gap:16px; align-items:center; padding:13px 15px; border-bottom:1px solid #2b2e38; }} .pair-heading>div:first-child {{ display:flex; gap:10px; align-items:center; }} .pair-heading span {{ color:var(--orange); font:700 11px ui-monospace,monospace; }}
    .pair-metrics {{ display:flex; gap:8px; }} .pair-metrics strong {{ color:var(--muted); background:#1b1e27; border-radius:99px; padding:5px 9px; font-size:11px; }}
    .comparison-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:1px; background:#333641; }} figure {{ margin:0; min-width:0; background:#0a0b0f; }} figure img,.thumbnail-missing {{ display:block; width:100%; aspect-ratio:16/9; object-fit:contain; background:#07080b; }} .thumbnail-missing {{ display:grid; place-items:center; color:var(--muted); }} figcaption {{ padding:10px 12px; color:#d7d3ce; font:12px ui-monospace,monospace; overflow-wrap:anywhere; }}
    .pair-explanation {{ margin:0; padding:12px 15px; color:#c6c1ba; font-size:12px; border-top:1px solid #2b2e38; background:#15171f; }}
    .decision-panel {{ display:grid; grid-template-columns:minmax(0,1.1fr) minmax(320px,.9fr); gap:22px; margin-bottom:18px; }} .decision-panel h2 {{ grid-column:1/-1; margin-bottom:0; }} .reason-list {{ display:grid; gap:10px; }} .reason-card {{ display:grid; grid-template-columns:44px 1fr; align-items:start; gap:12px; padding:13px; background:#11131a; border:1px solid #2d303a; border-radius:12px; }} .reason-card>strong {{ color:var(--orange); font-size:26px; line-height:1; }} .reason-card p {{ color:#c6c1ba; margin:6px 0 0; font-size:13px; }}
    .metric-guide {{ display:grid; gap:10px; }} .metric-guide>div {{ padding:13px; border-left:3px solid var(--orange); background:#171921; border-radius:0 10px 10px 0; }} .metric-guide b {{ display:block; margin-bottom:5px; }} .metric-guide span {{ color:var(--muted); font-size:12px; line-height:1.55; }} .metric-guide strong {{ color:var(--yellow); }}
    .error-line {{ display:grid; grid-template-columns:minmax(140px,1fr) 2fr; gap:14px; padding:12px 0; border-bottom:1px solid var(--line); }} .error-line span {{ color:#ffb0b0; }}
    .release {{ display:grid; grid-template-columns:repeat(3,1fr); gap:12px; }} .release div {{ background:#11131a; border:1px solid #292c35; border-radius:12px; padding:14px; }} .release span {{ display:block; color:var(--muted); font-size:12px; margin-bottom:8px; }} .release strong,.release code {{ word-break:break-all; font-size:13px; }}
    footer {{ color:#7f8490; text-align:center; margin-top:30px; font-size:12px; }}
    @media (max-width:820px) {{ .cards {{ grid-template-columns:1fr 1fr; }} .grid {{ grid-template-columns:1fr; }} .panel.wide {{ grid-column:auto; }} .release {{ grid-template-columns:1fr; }} .decision-panel {{ grid-template-columns:1fr; }} .decision-panel h2 {{ grid-column:auto; }} }}
    @media (max-width:520px) {{ .shell {{ width:min(100% - 20px,1180px); padding-top:28px; }} header {{ align-items:flex-start; flex-direction:column; }} .cards {{ grid-template-columns:1fr; }} .distribution-row {{ grid-template-columns:1fr 36px; }} .distribution-track {{ grid-column:1/-1; grid-row:2; }} .pair-heading {{ align-items:flex-start; flex-direction:column; }} .comparison-grid {{ grid-template-columns:1fr; }} }}
  </style>
</head>
<body>
  <main class="shell">
    <header>
      <div><div class="eyebrow">WeldVision · Annotation Control</div><h1>🔥 Welding QA</h1><p>용접 결함 데이터셋 자동 검수 및 릴리스 준비 현황</p></div>
      <div class="status {status_class}">{status_text}</div>
    </header>

    <section class="cards" aria-label="QA 요약">
      <article class="card"><span>검사 이미지</span><strong>{int(summary['images'])}</strong><em>IMAGE FILES</em></article>
      <article class="card"><span>유효 JSON</span><strong>{int(summary['valid_files'])}</strong><em>{int(summary['invalid_files'])} INVALID</em></article>
      <article class="card"><span>결함 Annotation</span><strong>{int(summary['annotations'])}</strong><em>POLYGONS</em></article>
      <article class="card"><span>검토 항목</span><strong>{int(summary['review_items'])}</strong><em>{duplicate_file_count} IMAGES · {duplicate_pair_count} PAIRS</em></article>
    </section>

    <section class="panel decision-panel" aria-label="자동 판정 설명">
      <h2><span>?</span>왜 이 상태로 판정됐나요?</h2>
      <div class="reason-list">{_render_status_reasons(manifest.get('status_reasons', []))}</div>
      {_render_metric_guide(thresholds)}
    </section>

    <section class="grid">
      <article class="panel"><h2><span>◈</span>결함 분포</h2>{_render_label_distribution(qa.get('label_counts', {}))}</article>
      <article class="panel"><h2><span>◎</span>검사 방식</h2>{_render_label_distribution(qa.get('modality_counts', {}))}</article>
      <article class="panel wide"><h2><span>⚠</span>Annotation 충돌·중첩</h2>{_render_annotation_issues(annotation_issues)}</article>
      <article class="panel wide"><h2><span>▣</span>유사 이미지 비교 · {duplicate_file_count}장 / {duplicate_pair_count}쌍</h2>{_render_duplicate_pairs(duplicate_images.get('pairs', []), thresholds)}</article>
      <article class="panel wide"><h2><span>×</span>파싱·파일 오류</h2>{_render_errors(errors)}</article>
      <article class="panel wide"><h2><span>⌁</span>Release Manifest</h2>
        <div class="release">
          <div><span>생성 시각 (UTC)</span><strong>{_text(manifest.get('generated_at', ''))}</strong></div>
          <div><span>검사 방식</span><strong>{_text(manifest.get('modality') or 'ALL')}</strong></div>
          <div><span>Dataset SHA-256</span><code>{_text(dataset_digest)}</code></div>
        </div>
      </article>
    </section>
    <footer>임시 WeldVision 테마 · 실제 QA 결과만 표시 · 검사자의 최종 판정을 대체하지 않습니다.</footer>
  </main>
</body>
</html>
"""
