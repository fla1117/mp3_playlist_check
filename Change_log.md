# Change Log: mp3_playlist_check

모든 주요 변경 사항과 개선 이력을 기록합니다.

---

## [v0.3.4] - 2026-10-20
### Added & Improved
- **1. 언더스코어('_') 비표준 파일명 파싱 및 표준화 엔진 구현 (`src/scanner/tag_normalizer.py`)**:
  - `parse_underscore_filename(file_path_or_name)`: `[가수]_[제목].[확장자]` 형태(단일 언더스코어 포함 및 `" - "` 미포함)에서 아티스트와 타이틀을 정확히 분리 추출.
  - `standardize_underscore_filename(file_path, auto_tag=False)`: Windows 읽기 전용(`stat.S_IWRITE`) 속성 자동 해제 및 기존 파일 중복 충돌 시 `(1)` 넘버링을 적용하여 `[가수] - [제목].[확장자]` 표준 명명 규칙으로 안전 변환. `auto_tag=True` 옵션 지정 시 실제 오디오 파일 메타데이터 태그도 동시 기록.
  - `batch_standardize_underscore_directory(dir_path, repo, auto_tag, recursive)`: 지정 디렉터리 내 음원(`mp3`, `flac`, `m4a`, `wav`, `aac`, `ogg`, `wma`)을 일괄 스캔하여 비표준 언더스코어 파일명을 표준화하고 데이터베이스 경로 및 메타데이터 실시간 동기화.
- **2. 비표준 파일명 데이터베이스 감사 쿼리 추가 (`src/db/audit_ops.py`)**:
  - `get_nonstandard_naming_tracks()`: 활성 음원 중 파일명에 `_`가 포함되고 ` - `가 포함되지 않은 비표준 파일들을 조회하여 파싱된 가수/제목 및 변경 예정 파일명(`target_name`)을 포함한 감사 목록 제공.
- **3. GUI 품질 감사 탭(Tab 3) '비표준 파일명 정리' 카테고리 연동 (`src/gui/tab_audit.py`)**:
  - 감사 카테고리에 `📝 비표준 파일명 ('_') 정리` 탭 추가.
  - 현재 파일명, 변경 예정 파일명, 가수, 제목, 파일 경로 테이블 뷰 제공.
  - `✏️ 선택 파일 일괄 표준화 ('가수 - 제목')` 버튼: 선택된 항목에 대해 파일명 표준 변환, DB 경로 업데이트, 에러 로그(`operation_errors.log` 및 `record_scan_error`) 기록.
  - `📂 외부 폴더 직접 선택하여 일괄 정리...` 버튼: DB 인덱싱 여부와 관계없이 로컬 음악 폴더를 직접 선택하여 즉시 일괄 표준화 실행 가능.
- **4. CLI 일괄 표준화 커맨드 추가 (`src/cli.py`)**:
  - `rename-underscore <directory> [--db <db_path>]`: 터미널 환경에서 대규모 음원 폴더를 한 번에 일괄 표준화하고 결과를 Rich Table로 요약 출력.
- **5. 종합 단위/통합 테스트 추가 (`tests/test_v030_features.py`, `tests/test_gui_and_cli.py`)**:
  - `test_underscore_filename_standardization`: 정상/비정상 파일명 파싱, 자동 태깅, 파일명 충돌 회피 `(1)`, 배치 폴더 일괄 표준화 및 DB 경로 동기화 검증.
  - `test_cli_rename_underscore`: 공백 포함 경로에 대한 CLI `rename-underscore` 커맨드 정상 실행 검증 (전체 48개 테스트 100% 통과).

---

## [v0.3.3] - 2026-10-20
### Fixed & Improved
- **1. 확장자-컨테이너 불일치(Misnamed Container) 오디오 파일 태그/커버아트 안전 저장**:
  - `src/scanner/tag_normalizer.py` 및 `src/scanner/cover_manager.py`: 확장자(`.mp3`)와 실제 내부 컨테이너 포맷(`WAVE`, `FLAC`, `MP4`/`M4A`)이 다른 파일도 확장자 기반 단순 분기 대신 `mutagen.File(str(p))` 컨테이너 인스턴스 검사를 최우선 수행하도록 개선.
  - WAV 등 RIFF 기반 컨테이너 파일이 `.mp3`로 명명되어 있어도 파일 헤더 손상(RIFF 손상) 없이 RIFF ID3 청크에 태그와 앨범아트를 무손실 안전 기록.
- **2. 태그 결측 목록(`get_missing_tags`) 필터 조건 정밀화 및 실시간 반영**:
  - `src/db/audit_ops.py`: `get_missing_tags()`에서 `album IS NULL` / `release_year IS NULL` 조건을 제외하고 `tag_source != 'ID3'` 조건으로 간소화/정밀화.
  - 추론된 메타데이터(가수/제목)를 파일 태그에 저장(`apply_fallback_tags_to_file`) 및 동기화(`sync_single_file`) 즉시 `tag_source`가 `ID3`로 승격되어 태그 결측 목록에서 실시간 제외되도록 개선.
- **3. GUI 감사 탭 개별 파일 작업 예외 격리(Fault Tolerance)**:
  - `src/gui/tab_audit.py`: `_apply_tags_to_checked_files()`, `_auto_fill_covers_for_checked()`, `_insert_local_image_for_checked()` 등 일괄 작업 시 개별 파일의 태그 기록이나 `sync_single_file()`을 `try...except`로 격리하여 단일 파일 실패 시에도 전체 프로세스가 중단되지 않도록 보호하고, 에러 로깅(`record_scan_error`, `operation_errors.log`) 연동.
- **4. 단위 테스트 추가 (`tests/test_v030_features.py`)**:
  - `test_misnamed_container_tag_apply_and_missing_tags_filter`: `.mp3` 확장자로 위장된 WAVE 파일의 초기 `FILENAME_FALLBACK` 감지, 태그 저장 후 RIFF 헤더 무손실 보존, `tag_source == 'ID3'` 승격 및 결측 목록 즉시 제외 라이프사이클 검증.
- **5. 공백/특수문자 경로 Windows 탐색기 열기(`/select,`) 버그 수정**:
  - `src/gui/theme_and_ime.py`: `open_in_explorer(file_path)` 호출 시 기존 리스트 인자(`["explorer", f"/select,{p}"]`)로 인해 공백 포함 경로에서 `subprocess.list2cmdline`이 `explorer "/select,C:\..."` 형태로 전체를 따옴표로 감싸 Windows 탐색기가 `/select` 스위치를 인식하지 못하고 `내 문서(C:\Users\user\Documents)`를 열던 문제를 문자열 커맨드(`f'explorer.exe /select,"{p}"'`)로 직접 전달하도록 수정.
  - 파일이 존재하지 않더라도 상위 폴더(`p.parent`)가 존재하면 `subprocess.run(f'explorer.exe "{p.parent}"')`로 상위 폴더를 열도록 폴백 로직 개선.
  - `tests/test_gui_and_cli.py`: 공백 및 한글 경로에 대한 `open_in_explorer` 커맨드 포맷 및 폴백 동작을 검증하는 단위 테스트 `test_open_in_explorer_command_format` 추가 (전체 46개 테스트 100% 통과).

---

## [v0.3.2] - 2026-10-20
### Fixed & Improved
- **Windows 읽기 전용(Read-Only, `FILE_ATTRIBUTE_READONLY`) 파일 처리 및 안전 삭제 권한 복구**:
  - **읽기 전용 속성 자동 해제 (`os.chmod`)**: Windows 환경에서 읽기 전용 속성이 걸려 있어 `Path.unlink()` 및 태그 저장이 `PermissionError: [WinError 5]`로 차단되던 문제 해결.
    - `src/gui/tab_audit.py`의 `_delete_selected_audit_files()`: `p.unlink()` 전 쓰기 권한 비트(`stat.S_IWRITE`) 확인 후 `os.chmod(p, stat.S_IWRITE | stat.S_IREAD)` 자동 적용.
    - `src/scanner/cover_manager.py`의 `embed_cover_art()`: 태그/이미지 바이너리 기록 전 쓰기 권한 자동 확보.
    - `src/scanner/tag_normalizer.py`의 `apply_fallback_tags_to_file()` 및 `rename_file_standard()`: 태그 저장 및 파일명 변경 전 쓰기 권한 자동 확보.
  - **삭제 실패 시 상세 에러 로깅 및 UI 가시화**:
    - `src/config.py`에 `OPERATION_LOG_PATH = DEFAULT_DATA_DIR / "operation_errors.log"` 상수 추가.
    - 파일 삭제 중 예외 발생 시 `data/operation_errors.log`에 `[DELETE_ERROR] {fpath} -> {type(e).__name__}: {e}` 형식으로 타임스탬프와 함께 append 기록.
    - `self.repo.record_scan_error` 동시 기록으로 GUI 탭 3의 `⚠️ 스캔 오류 파일 목록`에서도 실시간 확인 가능.
    - 완료 메시지박스(`messagebox.showinfo`)에 실패 건수 발생 시 대표 실패 사유(최대 3건의 파일명 및 에러 메시지)와 로그 파일 안내 상세 표시.
  - **단위 테스트 추가 (`tests/test_v030_features.py`)**:
    - `test_readonly_file_handling`: 읽기 전용(`os.chmod(path, stat.S_IREAD)`) 파일에 대한 커버아트 임베딩, 폴백 태그 저장, 표준 리네임, 쓰기 권한 해제 후 삭제까지 전체 라이프사이클 검증 (전체 44개 테스트 100% 통과).

---

## [v0.3.1] - 2026-10-20
### Refactored & Modularized
- **Zero Test Modification 원칙 준수 대규모 모듈화 리팩토링 (43/43 테스트 100% 통과)**:
  - **1. 스캐너 이미지 유틸리티 분리 (`src/scanner/image_utils.py`)**:
    - `src/scanner/tag_extractor.py`에 혼재되어 있던 바이너리 이미지 헤더 파싱(`_parse_image_dimensions`, JPEG/PNG/GIF/WEBP) 및 디렉터리 내 외부 커버아트 탐색 로직(`_find_external_cover`)을 별도 유틸 모듈로 독립 분리.
  - **2. 매처 엔진 및 유사도 산출 모듈화 (`src/matcher/`)**:
    - `src/matcher/models.py`: 매칭 열거형(`MatchStatus`) 및 판별 결과 데이터클래스(`MatchResult`) 전용 모델 모듈 분리.
    - `src/matcher/similarity.py`: 포맷 가중치(`FORMAT_QUALITY_WEIGHTS`), 재생시간 점수(`calculate_duration_score`), 제목 일치율(`calculate_title_score`), 아티스트 일치율(`calculate_artist_score`), 종합 점수 평가 로직(`evaluate_candidate`, `get_match_status`) 모듈화.
    - `src/matcher/scorer.py`: `MatcherEngine` 오케스트레이션 클래스 중심 경량화 및 하위 호환성 re-export 유지.
  - **3. 데이터베이스 리포지토리 믹스인 패턴 분리 (`src/db/`)**:
    - `src/db/seed_data.py`: 기본 아티스트 별칭 시드 데이터(`DEFAULT_ARTIST_ALIASES`, `DEFAULT_SEEDS`) 독립.
    - `src/db/track_ops.py`: 트랙 CRUD, 경로 이동 감지, FTS5 하이브리드 후보 검색, 스캔 에러 로깅, 라이브러리 통계 연산(`TrackOpsMixin`).
    - `src/db/audit_ops.py`: 커버아트/메타데이터 결측 감사, Union-Find 기반 고급 중복 그룹 클러스터링 및 6단계 음질 우선 정렬(`AuditOpsMixin`).
    - `src/db/alias_cache_ops.py`: $O(1)$ 아티스트 별칭 인메모리 캐시, 대표 아티스트 정규화, YouTube 메타데이터 캐시(`AliasCacheOpsMixin`).
    - `src/db/repository.py`: 위 세 믹스인을 다중 상속하는 70줄 규모의 슬림한 `Repository` 클래스로 전면 재구성.
  - **4. 모놀리식 GUI 패키지화 (`src/gui.py` → `src/gui/` 패키지)**:
    - 1,944줄의 거대 단일 파일 `src/gui.py`를 삭제하고 책임별 믹스인 패키지로 전면 분할:
      - `src/gui/theme_and_ime.py`: 팔레트 색상 상수, `ThemeMixin`, `get_entry_text_with_ime`, `open_in_explorer`, 포맷팅 헬퍼.
      - `src/gui/tab_youtube.py`: YouTube 단일/모음집/챕터 판별, CSV 내보내기, 클립보드 복사(`YouTubeTabMixin`).
      - `src/gui/tab_library.py`: 로컬 폴더 스캔, 한글 IME 실시간 검색, 라이브러리 브라우저(`LibraryTabMixin`).
      - `src/gui/tab_audit.py`: 커버/태그/중복/오류 감사 테이블, 안전 삭제 가드, 커버아트 자동 수집/내장, 표준 리네임(`AuditTabMixin`).
      - `src/gui/tab_aliases.py`: 아티스트 별칭 사전 CRUD 트리뷰(`AliasesTabMixin`).
      - `src/gui/app.py`: `MusicCheckerGUI` 메인 윈도우 클래스 및 `main()` 진입점.
      - `src/gui/__init__.py`: 패키지 re-export (`MusicCheckerGUI`, `main`, `get_entry_text_with_ime`, `open_in_explorer`).
      - `src/gui/__main__.py`: `python -m src.gui` (`run_gui.bat`) 명령줄 패키지 직접 실행 지원.

---

## [v0.3.0] - 2026-10-20
### Added & Improved
- **1. 중복 음원 정밀 클러스터링 및 지능형 정리 (Union-Find & 안전 삭제)**:
  - **Union-Find 기반 중복 감지**: `Repository.get_duplicates()`를 전면 고도화하여 대표 아티스트 별칭(`resolve_canonical_artist`) 및 곡명/태그 피처링 분리(`extract_features`)를 결합. '아이유' ↔ 'IU', '잔소리 (feat. 임슬옹)' ↔ '잔소리 (with 임슬옹)' 등의 이명/피처링 분기 음원을 하나의 중복 그룹(`dup_group_key`)으로 통합 클러스터링.
  - **품질 기반 정렬 (음질 최우선 원칙)**: 포맷 가중치(`flac`> `wav`> `m4a`> `mp3`> `ogg`> `aac`) 내림차순 → 비트레이트(`bitrate_kbps`) 내림차순(`320k` > `160k` 무조건 우선) → 커버아트 보유 여부 내림차순 → 커버아트 해상도(`width * height`) 내림차순(`480x480` > `240x240`) → 파일 크기 내림차순 → ID 오름차순으로 완벽 정렬. 저음질(160k)에 커버아트가 있더라도 고음질(320k 커버 없음) 원본이 보존 대상 1순위로 확정.
  - **지브라 줄무늬 & 체크박스 UI**: 탭 3 중복 목록 테이블에 체크박스 컬럼(`☐`/`☑`)과 그룹별 교차 배경색(`group_even`: `#ffffff`, `group_odd`: `#f1f5f9`), 체크 항목 강조(`checked`: `#fee2e2`) 적용.
  - **`[⚡ 저음질/하위 중복 자동 선택]`**: 각 중복 그룹의 1순위 음원(원곡)은 유지하고 품질이 낮거나 하위인 음원만 원클릭 일괄 선택.
  - **`[🗑️ 선택 파일 삭제 (N건)]` 및 안전 가드**:
    - 하단 바의 **가장 우측 끝(`side="right"`)**에 직관적인 삭제 버튼 배치.
    - **안전 삭제 가드(Safety Guard)**: 중복 그룹 내 모든 파일이 선택된 경우 삭제를 원천 차단하여 라이브러리에서 곡이 완전 유실되는 사고 방지.
    - 선택 파일 디스크 영구 삭제(`unlink`), DB 영구 제거(`delete_tracks_by_ids`), FTS5 자동 동기화 및 탭 2/3 실시간 통계 갱신.

- **2. 앨범 커버아트 자동 채우기 및 로컬 이미지 삽입 (`src/scanner/cover_manager.py`)**:
  - **커버아트 추출 및 임베딩 엔진**: MP3(ID3 APIC), FLAC(Vorbis Picture), M4A/MP4(`covr`) 바이너리 태그 추출 및 무손실 내장 지원.
  - **2단계 하이브리드 자동 수집 (`fetch_cover_art_auto`)**:
    - 1순위 (로컬 공유): 동일 앨범명 또는 동일 폴더 내 다른 음원에 이미 내장된 커버아트를 우선 재사용하여 네트워크 트래픽 절약.
    - 2순위 (iTunes Search API): 로컬에 없을 경우 Apple iTunes Search API(`country=KR`)에서 600x600 고해상도 공식 앨범아트를 실시간 조회 및 자동 다운로드.
  - **UI 작업 연동**:
    - `[🖼️ 선택 곡 커버아트 자동 채우기]`: 멀티스레드 백그라운드 처리로 대량(100곡 이상) 커버아트 자동 탐색/내장 시에도 GUI 멈춤 없음.
    - `[📁 내 PC 이미지로 커버 넣기...]`: 사용자 PC의 이미지 파일(JPG, PNG 등)을 선택하여 다중 음원에 일괄 내장.

- **3. 태그 파일 영구 반영 및 표준 파일명 일괄 변경 (`src/scanner/tag_normalizer.py`)**:
  - `sanitize_filename`: 윈도우 파일 시스템 금지 문자(`/ \ : * ? " < > |`) 자동 치환, 연속 공백 정리 및 양끝 마침표/공백 트림.
  - `[🏷️ 추론된 가수·제목을 실제 태그에 저장]`: 파일명 및 상위 디렉터리 구조로부터 추론된 메타데이터를 실제 오디오 파일의 ID3v2 / Vorbis / MP4 태그에 영구 기록 (`apply_fallback_tags_to_file`).
  - `[✏️ 파일명을 '가수 - 제목' 형식으로 통일]`: 파일명을 표준 규칙(`[가수] - [제목].[확장자]`)으로 일괄 리네임 (`rename_file_standard`), 동명 파일 충돌 시 `(1)` 자동 넘버링, DB 파일 경로(`Repository.update_track_path`) 및 FTS5 인덱스 실시간 갱신.

- **4. YouTube 플레이리스트/챕터 결과 내보내기 & Excel 한글 호환 (탭 1)**:
  - **`[📋 미보유 곡 목록 복사]`**: 모음집/플레이리스트 판별 결과 중 로컬에 없는 `NOT_FOUND` 음원만 필터링하여 순번, 제목, 재생시간 텍스트로 클립보드에 원클릭 복사.
  - **`[📥 결과 CSV 저장...]`**: 판별 테이블 전체 결과(순번, 상태, 유튜브제목, 영상길이, 로컬매칭음원, 일치율, 파일경로, 사유)를 CSV 파일로 저장. Excel에서 별도의 텍스트 가져오기 마법사 없이 즉시 한글이 열리도록 **UTF-8 with BOM (`utf-8-sig`)** 인코딩 적용.

- **5. UI 사용성 및 대량 작업 지원**:
  - 탭 3 하단 공통 액션 영역에 **`[☑ 전체 선택]` (`_check_all_audit_items`)** 추가로 커버아트 누락(138곡 등) 및 태그 결측 곡의 원클릭 전체 선택 지원.
  - `[☑ 선택 토글]`, `[☐ 전체 해제]`, `[📂 탐색기에서 열기]`, `[📋 파일 경로 복사]` 단축 조작 지원.

- **6. 검증 자동화 테스트 (`tests/test_v030_features.py`)**:
  - 태그 정규화, 표준 리네임 충돌 방지, 커버아트 추출/내장/로컬 앨범 공유, iTunes API 모의 조회, Union-Find 중복 클러스터링, 다중 삭제 및 `utf-8-sig` CSV BOM 검증 테스트 8종 추가 (전체 41개 테스트 100% 통과).

---

## [v0.2.1] - 2026-10-20
### Fixed
- **Windows `cmd.exe` 배치 파일 파싱 에러 수정**:
  - `run_gui.bat`의 UTF-8 한글 및 LF(`\n`) 줄바꿈으로 인한 `cmd.exe` 바이트 오프셋 잘림 현상 해결.
  - 순수 7비트 ASCII 및 CRLF(`\r\n`) 포맷으로 런처 재작성 및 `test_run_gui_bat_crlf_and_ascii` 검증 테스트 추가.
- **Windows 한글 IME(자모 조합) 입력 끊김 및 지연 해결**:
  - `StringVar.trace_add("write")` 동기 트리뷰 재렌더링 제거.
  - `<KeyRelease>` 150ms 디바운스(`after_cancel`/`after(150)`) 및 `[🔍 검색]`, `[✖ 초기화]` 버튼 추가.
  - 5개 텍스트 입력창 전체를 `ttk.Entry`에서 네이티브 `tk.Entry` 및 `맑은 고딕(Malgun Gothic)` 글꼴로 전환하여 한글 IME 포커스 확보.
  - `imm32.dll` (`ImmGetCompositionStringW(GCS_COMPSTR)`) 조합 중(Pre-edit) 글자 보조 인식 헬퍼 구현.
  - 라이브러리 검색 시 `normalize_text` 기반 공백/특수문자 무시 검색 지원(`좋은날` ↔ `좋은 날`).

---

## [v0.2.0] - 2026-10-20
### Added & Changed
- **Windows 데스크톱 네이티브 GUI 전환 (`src/gui.py`)**:
  - Tkinter/TTK 기반 4개 탭 구조 구현 (1: 유튜브 매칭, 2: 폴더 스캔/라이브러리, 3: 품질 감사 통계, 4: 아티스트 별칭 사전).
  - 백그라운드 스레드 기반 스캔 및 yt-dlp 메타데이터 비동기 추출.
  - 원클릭 배치 런처(`run_gui.bat`) 및 `pyproject.toml` GUI 진입점(`mp3-check-gui`) 등록.
- **경로 및 아키텍처 안정화**:
  - `src/config.py`의 모든 경로(`PROJECT_ROOT`, `DEFAULT_DB_PATH`, `SETTINGS_PATH`)를 절대 경로로 고정.
  - CLI 폴더 인자 따옴표 누락(공백 포함 경로) 자동 결합 처리.
  - 외부 작업 디렉터리(`C:\Users\user` 등)에서 직접 실행 시 모듈 임포트 실패 방지를 위한 `PROJECT_ROOT` `sys.path` 선제 등록.
  - 기본 음원 폴더(`F:\2. 음악\Music\3차 편집`) 감지 시 자동 기본 경로 설정.
- **Anti-Slop 정돈**:
  - PRD/TRD 범위를 벗어난 플레이어 재생 기능(`play_audio_file`) 제거 및 경로 복사/탐색기 열기 기능으로 일원화.
  - 탭 1 플레이리스트 테이블과 하단 액션 버튼 영역을 `pl_table_frame` 컨테이너로 격리하여 레이아웃 찌그러짐 해결.
  - 탭 2 스캔 완료 시 탭 3 품질 통계 실시간 자동 동기화.

---

## [v0.1.1] - 2026-10-20
### Optimized & Fixed
- **아티스트 별칭 매칭 최적화**:
  - `Repository._alias_cache` 인메모리 딕셔너리 도입으로 $O(1)$ 정규 아티스트 매핑 처리 및 N+1 DB 쿼리 제거.
  - `delete_alias(alias)` 메서드 추가.
- **스캐너 증분 스캔 I/O 최적화**:
  - 디렉터리 스캔 전 전체 활성 파일 경로 맵을 메모리에 사전 적재하여 DB 단건 조회 병목 해소.
- **유실 음원 판별 경로 접두사 버그 수정**:
  - `Path.is_relative_to` 기반 접두사 경계 검증을 적용하여 인접 폴더(예: `Music_Backup` vs `Music`) 간 오탐 방지.

---

## [v0.1.0] - 2026-10-19
### Initial Release
- **기획 및 아키텍처 수립**:
  - PRD 및 TRD 분석, 파일명 표준화(`PRD_mp3_playlist_check.md`, `TRD_mp3_playlist_check.md`).
  - SQLite FTS5 검색 인덱스 및 동기화 트리거 설계.
- **코어 엔진 구현**:
  - `src/scanner`: Mutagen 기반 ID3/FLAC/M4A 메타데이터 추출, CP949/EUC-KR 한글 깨짐 자동 복구, 내장/폴더 커버아트 감지.
  - `src/matcher`: RapidFuzz 기반 가중치 스코어링(제목/아티스트/버전/시간), 재생시간 Teaser/Shorts 필터링.
  - `src/youtube`: yt-dlp 기반 단일 영상, 플레이리스트, 타임스탬프 챕터 자동 분할 및 캐싱.
  - `src/cli.py`: Typer + Rich 기반 콘솔 CLI 인터페이스.
  - 단위 및 통합 테스트 27개 구현 및 통과.
