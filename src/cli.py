"""Typer + Rich CLI for mp3_playlist_check."""
import sys
from pathlib import Path
from typing import Optional

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.config import DEFAULT_DB_PATH
from src.db.repository import Repository
from src.matcher.scorer import MatcherEngine, MatchResult, MatchStatus
from src.scanner.file_walker import scan_directory
from src.youtube.extractor import YouTubeExtractor

app = typer.Typer(help="Local audio library checker against YouTube music.")
alias_app = typer.Typer(help="Manage artist aliases.")
app.add_typer(alias_app, name="alias")

console = Console()


def format_duration(seconds: float) -> str:
    """Format seconds into MM:SS string."""
    sec = int(round(seconds))
    mins = sec // 60
    rem = sec % 60
    return f"{mins:02d}:{rem:02d}"


def format_cover_art(track: dict) -> str:
    """Format cover art string for report."""
    has_cover = track.get("has_cover_art", 0)
    w = track.get("cover_width")
    h = track.get("cover_height")
    mime = track.get("cover_mime") or ""
    sub_fmt = mime.split("/")[-1].upper() if "/" in mime else mime.upper()

    if has_cover == 1:
        if w and h:
            return f"있음 ({w}x{h} {sub_fmt})"
        return "있음 (내장 태그)"
    elif has_cover == 2:
        return "있음 (폴더 외부 이미지)"
    return "없음"


@app.command()
def scan(
    directory: list[str] = typer.Argument(..., help="Path to local music directory"),
    db: Optional[str] = typer.Option(None, "--db", help="Path to SQLite database file"),
):
    """Scan local audio folder and perform incremental synchronization."""
    target_path_str = " ".join(directory).strip()
    repo = Repository(db or DEFAULT_DB_PATH)
    target = Path(target_path_str)
    if not target.exists():
        console.print(f"[bold red]오류: 디렉토리가 존재하지 않습니다: {target}[/bold red]")
        raise typer.Exit(code=1)

    console.print(f"[bold green]🔍 로컬 음원 폴더 스캔 시작:[/bold green] {target}")

    with console.status("[bold cyan]음원 파일 탐색 및 인덱싱 중...[/bold cyan]"):
        summary = scan_directory(target, repo)

    table = Table(title="📊 음원 라이브러리 동기화 결과", show_header=True, header_style="bold magenta")
    table.add_column("항목", style="cyan")
    table.add_column("건수", style="bold yellow", justify="right")

    table.add_row("발견된 총 파일 수", str(summary.total_files))
    table.add_row("신규 추가 (Added)", f"[green]{summary.added}[/green]")
    table.add_row("수정 갱신 (Updated)", f"[cyan]{summary.updated}[/cyan]")
    table.add_row("이동/이름변경 감지 (Moved)", f"[blue]{summary.moved}[/blue]")
    table.add_row("스킵 (Unchanged)", str(summary.skipped))
    table.add_row("유실/삭제 감지 (Missing)", f"[red]{summary.missing}[/red]")
    table.add_row("파싱 오류 (Errors)", f"[bold red]{summary.errors}[/bold red]")

    console.print(table)


@app.command()
def check(
    youtube_url: str = typer.Argument(..., help="YouTube video or playlist URL"),
    db: Optional[str] = typer.Option(None, "--db", help="Path to SQLite database file"),
):
    """Check if YouTube music or playlist exists in the local audio library."""
    repo = Repository(db or DEFAULT_DB_PATH)
    extractor = YouTubeExtractor(repo)
    engine = MatcherEngine(repo)

    console.print(f"[cyan]🔗 YouTube 메타데이터 수집 중... ({youtube_url})[/cyan]")

    try:
        result = extractor.extract(youtube_url)
    except Exception as e:
        console.print(f"[bold red]오류: YouTube 정보를 불러올 수 없습니다: {e}[/bold red]")
        raise typer.Exit(code=1)

    if not result.tracks:
        console.print("[bold red]분석할 트랙을 찾을 수 없습니다.[/bold red]")
        return

    # Single video check
    if len(result.tracks) == 1 and not result.is_playlist and not result.tracks[0].is_chapter:
        track_info = result.tracks[0]
        match_res = engine.match(
            raw_title=track_info.raw_title,
            uploader=track_info.uploader,
            yt_artist=track_info.yt_artist,
            yt_track=track_info.yt_track,
            duration_sec=track_info.duration_sec,
        )

        console.print(f"\n[입력 URL] {youtube_url}")
        dur_str = format_duration(track_info.duration_sec)
        console.print(f"[유튜브 정보] {track_info.raw_title} | 길이: {dur_str}\n")

        if match_res.status == MatchStatus.EXACT_MATCH:
            mt = match_res.matched_track
            loc_dur = mt.get("duration_sec", 0.0)
            diff_sec = int(round(abs(track_info.duration_sec - loc_dur)))
            spec_str = f"{mt.get('file_ext', '').upper()} | {mt.get('bitrate_kbps', 0)} kbps | {format_duration(loc_dur)} (영상과 {diff_sec}초 차이)"
            album_str = f"{mt.get('album') or '알 수 없음'} ({mt.get('release_year') or '연도미상'}) - Track #{mt.get('track_number') or '01'}"
            cover_str = format_cover_art(mt)

            panel_text = (
                f"[bold green]✅ 판별 결과: 보유 중 (일치율: {match_res.score:.0f}% | EXACT_MATCH)[/bold green]\n"
                f"• 로컬 곡명   : {mt.get('title')}\n"
                f"• 아티스트    : {mt.get('artist')}\n"
                f"• 앨범명      : {album_str}\n"
                f"• 음원 스펙   : {spec_str}\n"
                f"• 썸네일 유무 : {cover_str}\n"
                f"• 파일 경로   : {mt.get('file_path')}"
            )
            console.print(Panel(panel_text, style="green", expand=False))

        elif match_res.status == MatchStatus.PARTIAL_MATCH:
            mt = match_res.matched_track
            loc_dur_str = format_duration(mt.get("duration_sec", 0.0))
            panel_text = (
                f"[bold yellow]⚠️ 판별 결과: 원곡 보유 중이나 버전/재생시간 상이 가능성 있음 (일치율: {match_res.score:.0f}% | PARTIAL_MATCH)[/bold yellow]\n"
                f"- 사유: {match_res.reason}\n"
                f"- 로컬 보유 파일: {mt.get('file_path')} ({loc_dur_str})"
            )
            console.print(Panel(panel_text, style="yellow", expand=False))

        else:
            panel_text = (
                f"[bold red]❌ 판별 결과: 로컬 라이브러리에 없는 곡입니다. (일치율: {match_res.score:.0f}% | NOT_FOUND)[/bold red]\n"
                f"- 사유: {match_res.reason}"
            )
            console.print(Panel(panel_text, style="red", expand=False))

    # Playlist or Compilation video check
    else:
        title_header = result.playlist_title or "모음집 / 챕터 영상"
        console.print(f"\n[bold cyan]📋 {title_header} 분석 결과 (총 {len(result.tracks)}곡)[/bold cyan]\n")

        table = Table(show_header=True, header_style="bold blue")
        table.add_column("#", justify="center", width=4)
        table.add_column("상태", justify="center", width=12)
        table.add_column("YouTube 제목", style="white", max_width=40)
        table.add_column("길이", justify="center", width=8)
        table.add_column("로컬 매칭 곡", style="cyan", max_width=30)
        table.add_column("일치율", justify="right", width=8)
        table.add_column("로컬 파일 경로", style="dim", max_width=45)

        exact_cnt = 0
        partial_cnt = 0
        not_found_cnt = 0

        for i, t in enumerate(result.tracks, 1):
            m = engine.match(
                raw_title=t.raw_title,
                uploader=t.uploader,
                yt_artist=t.yt_artist,
                yt_track=t.yt_track,
                duration_sec=t.duration_sec,
            )

            if m.status == MatchStatus.EXACT_MATCH:
                exact_cnt += 1
                status_str = "[green]✅ 보유[/green]"
                loc_name = f"{m.matched_track.get('artist')} - {m.matched_track.get('title')}"
                loc_path = m.matched_track.get("file_path", "")
            elif m.status == MatchStatus.PARTIAL_MATCH:
                partial_cnt += 1
                status_str = "[yellow]⚠️ 유사[/yellow]"
                loc_name = f"{m.matched_track.get('artist')} - {m.matched_track.get('title')}"
                loc_path = m.matched_track.get("file_path", "")
            else:
                not_found_cnt += 1
                status_str = "[red]❌ 미보유[/red]"
                loc_name = "-"
                loc_path = "-"

            table.add_row(
                str(i),
                status_str,
                t.raw_title,
                format_duration(t.duration_sec),
                loc_name,
                f"{m.score:.0f}%",
                loc_path,
            )

        console.print(table)
        pct = (exact_cnt / len(result.tracks)) * 100
        console.print(
            f"\n[bold]요약:[/bold] 총 {len(result.tracks)}곡 중 [green]{exact_cnt}곡 보유 ({pct:.1f}%)[/green], "
            f"[yellow]{partial_cnt}곡 유사[/yellow], [red]{not_found_cnt}곡 미보유[/red]"
        )


@app.command()
def stats(
    missing_covers: bool = typer.Option(False, "--missing-covers", help="List active tracks without cover art"),
    missing_tags: bool = typer.Option(False, "--missing-tags", help="List active tracks with missing metadata"),
    duplicates: bool = typer.Option(False, "--duplicates", help="List duplicate tracks"),
    db: Optional[str] = typer.Option(None, "--db", help="Path to SQLite database file"),
):
    """View audio library statistics and quality audit reports (FR-10)."""
    repo = Repository(db or DEFAULT_DB_PATH)

    if missing_covers:
        tracks = repo.get_missing_covers()
        table = Table(title=f"🖼️ 커버 아트 누락 곡 목록 (총 {len(tracks)}곡)", header_style="bold yellow")
        table.add_column("ID", justify="center", width=5)
        table.add_column("아티스트", style="cyan")
        table.add_column("곡명", style="bold white")
        table.add_column("파일 경로", style="dim")
        for t in tracks:
            table.add_row(str(t["id"]), t.get("artist") or "-", t.get("title") or "-", t["file_path"])
        console.print(table)
        return

    if missing_tags:
        tracks = repo.get_missing_tags()
        table = Table(title=f"🏷️ 메타데이터 결측 곡 목록 (총 {len(tracks)}곡)", header_style="bold red")
        table.add_column("ID", justify="center", width=5)
        table.add_column("출처", justify="center", width=18)
        table.add_column("아티스트", style="cyan")
        table.add_column("곡명", style="bold white")
        table.add_column("앨범", style="dim")
        table.add_column("파일 경로", style="dim")
        for t in tracks:
            table.add_row(
                str(t["id"]),
                t.get("tag_source") or "-",
                t.get("artist") or "[red]누락[/red]",
                t.get("title") or "[red]누락[/red]",
                t.get("album") or "[red]누락[/red]",
                t["file_path"],
            )
        console.print(table)
        return

    if duplicates:
        tracks = repo.get_duplicates()
        table = Table(title=f"👯 중복 보유 곡 목록 (총 {len(tracks)}곡)", header_style="bold magenta")
        table.add_column("아티스트", style="cyan")
        table.add_column("곡명", style="bold white")
        table.add_column("포맷", justify="center")
        table.add_column("비트레이트", justify="right")
        table.add_column("파일 경로", style="dim")
        for t in tracks:
            table.add_row(
                t.get("artist") or "-",
                t.get("title") or "-",
                t.get("file_ext", "").upper(),
                f"{t.get('bitrate_kbps') or 0} kbps",
                t["file_path"],
            )
        console.print(table)
        return

    # Default: general statistics
    st = repo.get_stats()
    table = Table(title="📈 로컬 음원 라이브러리 종합 통계", header_style="bold blue")
    table.add_column("구분", style="cyan")
    table.add_column("수치", style="bold yellow", justify="right")

    table.add_row("활성 음원 수 (Active Tracks)", str(st["total_active"]))
    table.add_row("유실/삭제 파일 수 (Missing Tracks)", f"[red]{st['total_missing']}[/red]")

    # Formats
    fmt_str = ", ".join(f"{ext.upper()}: {cnt}" for ext, cnt in st["by_format"].items()) or "없음"
    table.add_row("포맷별 분포", fmt_str)

    # Cover art
    ca = st["cover_art"]
    table.add_row("커버 아트 보유 (내장)", f"[green]{ca['embedded']}[/green]")
    table.add_row("커버 아트 보유 (폴더 이미지)", f"[cyan]{ca['folder']}[/cyan]")
    table.add_row("커버 아트 누락", f"[bold red]{ca['none']}[/bold red]")
    table.add_row("스캔 오류 누적", str(st["total_errors"]))

    console.print(table)


@alias_app.command("list")
def list_aliases(db: Optional[str] = typer.Option(None, "--db", help="Path to SQLite database file")):
    """List all registered artist aliases."""
    repo = Repository(db or DEFAULT_DB_PATH)
    aliases = repo.get_aliases()
    table = Table(title=f"👥 아티스트 별칭 사전 (총 {len(aliases)}개)", header_style="bold cyan")
    table.add_column("대표 아티스트 (Canonical)", style="bold green")
    table.add_column("별칭 (Alias)", style="yellow")
    for a in aliases:
        table.add_row(a["canonical_norm_artist"], a["alias_norm_artist"])
    console.print(table)


@alias_app.command("add")
def add_alias(
    canonical: str = typer.Argument(..., help="Canonical artist name (e.g. 아이유)"),
    alias: str = typer.Argument(..., help="Alias name (e.g. iu)"),
    db: Optional[str] = typer.Option(None, "--db", help="Path to SQLite database file"),
):
    """Add a new artist alias to the database."""
    repo = Repository(db or DEFAULT_DB_PATH)
    repo.add_alias(canonical, alias)
    console.print(f"[bold green]✅ 별칭 등록 완료:[/bold green] '{canonical}' ↔ '{alias}'")


if __name__ == "__main__":
    app()
