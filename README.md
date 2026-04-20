# claude-vector-memory

`claude-vector-memory`는 Markdown 기반 메모리 파일을 그대로 원본으로 유지하면서, SQLite + FTS5 + sqlite-vec 기반의 고품질 검색 인덱스를 만들어 주는 독립형 프로젝트입니다.

이 프로젝트의 핵심 목표는 다음과 같습니다.
- `MEMORY.md`, `memory/*.md` 같은 **기존 파일 기반 메모리 구조를 유지**할 것
- 데이터베이스는 어디까지나 **파생 산출물**로 취급할 것
- 키워드 검색과 의미 기반 검색을 함께 사용해 **에이전트 회상 품질을 높일 것**
- OpenClaw 본체와 분리된 **독립 설치형 프로젝트**로 사용할 수 있을 것
- **싱글 에이전트 / 멀티 에이전트** 환경 모두에서 안전하게 운영할 수 있을 것

---

## 1. 이 프로젝트가 하는 일

이 프로젝트는 다음을 수행합니다.

- `MEMORY.md` 와 `memory/*.md` 파일을 읽습니다
- 문서를 `##` 헤딩 기준으로 chunk 단위로 분할합니다
- SQLite DB에 인덱싱합니다
- FTS5 전체 텍스트 검색을 구성합니다
- sqlite-vec 기반 벡터 검색을 구성합니다
- 하이브리드 검색 파이프라인을 제공합니다
  - FTS5 keyword recall
  - neural vector recall
  - reciprocal rank fusion
  - recency boost
  - cross-encoder reranking
- `sync`, `rebuild`, `search`, `doctor`, `verify` 같은 운영 명령을 제공합니다

중요한 점은, **Markdown 파일이 항상 source of truth**라는 것입니다.
DB는 언제든 다시 만들 수 있는 인덱스일 뿐입니다.

---

## 2. 어떤 상황에 쓰면 좋은가

이 프로젝트는 다음 같은 경우에 적합합니다.

- 이미 `MEMORY.md`, `memory/*.md` 기반으로 메모리를 운영 중인 경우
- 에이전트가 오래된 메모리를 더 잘 회상하길 원하는 경우
- 한국어/영어/혼합 질의에 대해 더 나은 semantic search가 필요한 경우
- OpenClaw를 싱글 에이전트 또는 멀티 에이전트로 운영하는 경우
- 에이전트별 메모리는 분리하되, 검색 엔진은 공용으로 유지하고 싶은 경우
- 공개 가능한 범용 memory plugin-style 프로젝트를 찾는 경우

---

## 3. 설치 방식

이 프로젝트는 **GitHub/source 설치 방식만 사용**합니다.
PyPI 배포를 전제로 하지 않으며, 패키지 저장소에서 설치하는 방식은 지원하지 않습니다.

권장 설치 방식은 다음 하나입니다.

```bash
git clone <repo-url>
cd claude-vector-memory
uv sync --all-extras
```

주의:
- macOS/Homebrew Python 환경에서는 시스템 Python에 직접 설치하는 방식이 막힐 수 있습니다
- 따라서 일반적으로는 **`uv sync --all-extras` 방식이 가장 안전한 기본 설치 방법**입니다

---

## 4. 권장 검색 품질 모드

현재 기준 최고 품질 모드는 다음입니다.

- local neural embedding
- 모델: `intfloat/multilingual-e5-small` (384d)
- hybrid retrieval
- cross-encoder reranking

이를 위해 가장 권장되는 설치 방법은 아래입니다.

```bash
uv sync --all-extras
```

이 명령은 프로젝트에서 사용하는 optional dependency까지 함께 설치합니다.
즉, 최고 품질 검색에 필요한 neural embedding 및 reranking 의존성까지 한 번에 준비합니다.

---

# 5. Getting Started

이 섹션은 **실제로 그대로 따라 하면 설치와 설정이 끝나는 형태**로 작성되어 있습니다.

---

## Step 1. 메모리 파일 구조 준비

기본적으로 아래와 같은 구조를 준비합니다.

```text
my-agent/
├── MEMORY.md
└── memory/
    ├── 2026-04-19.md
    ├── 2026-04-20.md
    └── lessons.md
```

권장 사항:
- `MEMORY.md` 는 장기 메모리
- `memory/*.md` 는 일일 메모리 또는 세부 메모리
- DB 파일은 직접 편집하지 않음

---

## Step 2. 설치

```bash
git clone <repo-url>
cd claude-vector-memory
uv sync --all-extras
```

설치 후 모든 명령은 **`uv run memory-index ...`** 형태로 실행합니다.

예:

```bash
uv run memory-index --help
```

---

## Step 3. 싱글 에이전트 설정

예를 들어 `coding_agent` 하나만 있다고 가정하겠습니다.

```text
~/.openclaw/workspace-coding_agent/
├── MEMORY.md
├── memory/
│   ├── 2026-04-19.md
│   └── lessons.md
└── .memory_index.db
```

### 중요: `--source` 와 `--index-file` 는 반드시 같은 workspace 루트 아래에 있어야 합니다

예를 들어 아래 조합은 **올바릅니다**.

- `--source ~/.openclaw/workspace-coding_agent/memory`
- `--index-file ~/.openclaw/workspace-coding_agent/MEMORY.md`

반대로 아래처럼 서로 다른 루트를 섞으면 **안 됩니다**.

- `--source ~/.openclaw/agents/coding_agent/memory`
- `--index-file ~/.openclaw/workspace-coding_agent/MEMORY.md`

즉 원칙은 다음과 같습니다.
- `source`와 `index-file`는 같은 workspace 안에 있어야 함
- 일반적으로 둘 다 `workspace-<agent>/...` 아래를 가리키게 설정할 것

최초 인덱스 생성:

```bash
uv run memory-index \
  --source ~/.openclaw/workspace-coding_agent/memory \
  --index-file ~/.openclaw/workspace-coding_agent/MEMORY.md \
  rebuild
```

상태 점검:

```bash
uv run memory-index \
  --source ~/.openclaw/workspace-coding_agent/memory \
  --index-file ~/.openclaw/workspace-coding_agent/MEMORY.md \
  doctor
```

검색 테스트:

```bash
uv run memory-index \
  --source ~/.openclaw/workspace-coding_agent/memory \
  --index-file ~/.openclaw/workspace-coding_agent/MEMORY.md \
  search "deployment rule"
```

일상 운영:

```bash
uv run memory-index \
  --source ~/.openclaw/workspace-coding_agent/memory \
  --index-file ~/.openclaw/workspace-coding_agent/MEMORY.md \
  sync
```

---

## Step 4. 멀티 에이전트 설정

가장 안전한 권장 방식은 다음입니다.

- 메모리 엔진은 공용
- 메모리 원본 파일은 에이전트별 분리
- DB 파일도 에이전트별 분리
- 각 에이전트마다 `--source` 와 `--index-file` 는 반드시 같은 workspace 루트 아래에서 짝을 맞출 것

예시:

```text
~/.openclaw/
├── workspace-coding_agent/
│   ├── MEMORY.md
│   ├── memory/
│   └── .memory_index.db
│
├── workspace-research_agent/
│   ├── MEMORY.md
│   ├── memory/
│   └── .memory_index.db
│
└── workspace-support_agent/
    ├── MEMORY.md
    ├── memory/
    └── .memory_index.db
```

올바른 예:
- `coding_agent`
  - `--source ~/.openclaw/workspace-coding_agent/memory`
  - `--index-file ~/.openclaw/workspace-coding_agent/MEMORY.md`
- `research_agent`
  - `--source ~/.openclaw/workspace-research_agent/memory`
  - `--index-file ~/.openclaw/workspace-research_agent/MEMORY.md`

잘못된 예:
- `--source ~/.openclaw/agents/coding_agent/memory`
- `--index-file ~/.openclaw/workspace-coding_agent/MEMORY.md`

이처럼 `agents/...` 경로와 `workspace-...` 경로를 섞으면 인덱싱 중 경로 계산 오류가 발생할 수 있습니다.

최초 인덱스 생성:

```bash
uv run memory-index \
  --source ~/.openclaw/workspace-coding_agent/memory \
  --index-file ~/.openclaw/workspace-coding_agent/MEMORY.md \
  rebuild

uv run memory-index \
  --source ~/.openclaw/workspace-research_agent/memory \
  --index-file ~/.openclaw/workspace-research_agent/MEMORY.md \
  rebuild

uv run memory-index \
  --source ~/.openclaw/workspace-support_agent/memory \
  --index-file ~/.openclaw/workspace-support_agent/MEMORY.md \
  rebuild
```

이후 일상 운영:

```bash
uv run memory-index \
  --source ~/.openclaw/workspace-coding_agent/memory \
  --index-file ~/.openclaw/workspace-coding_agent/MEMORY.md \
  sync

uv run memory-index \
  --source ~/.openclaw/workspace-research_agent/memory \
  --index-file ~/.openclaw/workspace-research_agent/MEMORY.md \
  sync
```

---

## Step 5. OpenClaw에 연결

이 프로젝트는 OpenClaw 코어를 직접 수정하지 않고도 사용할 수 있습니다.

### 방법 A. 수동 호출

에이전트가 필요할 때마다 아래처럼 실행합니다.

```bash
uv run memory-index --source <agent-memory-dir> --index-file <agent-memory-md> sync
uv run memory-index --source <agent-memory-dir> --index-file <agent-memory-md> search "query"
```

### 방법 B. hook 또는 wrapper에 연결

예:

```bash
#!/usr/bin/env bash
AGENT_ID="${OPENCLAW_AGENT_ID:-main}"
SOURCE_DIR="$HOME/.openclaw/workspace-${AGENT_ID}/memory"
INDEX_FILE="$HOME/.openclaw/workspace-${AGENT_ID}/MEMORY.md"

if [ -d "$SOURCE_DIR" ]; then
  uv run memory-index --source "$SOURCE_DIR" --index-file "$INDEX_FILE" --quiet sync
fi
```

예제 파일:
- `examples/openclaw_hook.sh`
- `examples/openclaw_integration.py`

---

## Step 6. crontab으로 자동 sync 설정

메모리 파일이 자주 바뀌는 환경에서는 cron으로 주기적으로 `sync`를 돌리는 것이 실용적입니다.

### 단일 에이전트 예시, 10분마다 sync

```bash
*/10 * * * * cd /path/to/claude-vector-memory && uv run memory-index --source ~/.openclaw/workspace-coding_agent/memory --index-file ~/.openclaw/workspace-coding_agent/MEMORY.md sync >/tmp/coding-agent-memory-sync.log 2>&1
```

### 여러 에이전트를 함께 sync하는 스크립트 예시

예를 들어 `sync-all-memory.sh`:

```bash
#!/bin/bash
set -euo pipefail

cd /path/to/claude-vector-memory

uv run memory-index \
  --source ~/.openclaw/workspace-coding_agent/memory \
  --index-file ~/.openclaw/workspace-coding_agent/MEMORY.md \
  sync

uv run memory-index \
  --source ~/.openclaw/workspace-research_agent/memory \
  --index-file ~/.openclaw/workspace-research_agent/MEMORY.md \
  sync
```

실행 권한 부여:

```bash
chmod +x /path/to/claude-vector-memory/sync-all-memory.sh
```

crontab 등록:

```bash
(crontab -l 2>/dev/null; echo '*/10 * * * * /path/to/claude-vector-memory/sync-all-memory.sh >/tmp/all-memory-sync.log 2>&1') | crontab -
```

현재 repo에는 자동화 스크립트 예시도 포함되어 있습니다.
- `install-and-rebuild-all.sh`
- `sync-all-memory.sh`
- `setup-memory-sync-cron.sh`

---

## Step 7. 에이전트 운영 규칙 적용

이 프로젝트를 설치했다고 해서 에이전트가 자동으로 새 메모리 시스템을 우선 사용하게 되지는 않습니다.

즉, 다른 에이전트에게는 단순히 "claude-vector-memory를 우선 사용하라"고만 말하면 부족할 수 있습니다.
운영 규칙, 프로젝트 위치, 실행 방식, 경로 규칙까지 함께 전달하는 것이 좋습니다.

실제 운영에서는 아래 규칙을 적용하는 것을 권장합니다.

### 권장 운영 규칙

메모리 회상, 과거 결정, 사용자 선호, 작업 이력, 규칙, 교훈 등을 찾아야 할 때는 **기존 file-based memory 검색보다 `claude-vector-memory`를 우선 사용**하세요.

기본 원칙:
1. 메모리 관련 질문이 들어오면 먼저 해당 에이전트 workspace 기준으로 `claude-vector-memory` 검색을 수행할 것
2. 가능하면 검색 전에 `sync`를 먼저 실행해 최신 상태를 반영할 것
3. 우선 `search` 또는 `retrieve` 결과를 기준으로 회상할 것
4. 결과가 약하거나 확신이 낮을 때만 기존 `memory_search`, `memory_get`를 보조적으로 사용할 것
5. 최종 답변은 항상 자기 에이전트의 메모리 범위 안에서만 수행할 것
6. 멀티 에이전트 환경에서는 다른 에이전트 메모리와 섞지 말 것

짧은 버전:
- 메모리 회상은 앞으로 **`claude-vector-memory` 우선**
- 먼저 `sync`
- 그 다음 `search` 또는 `retrieve`
- 기존 `memory_search`는 fallback
- 다른 에이전트 메모리와 섞지 말 것

### 다른 OpenClaw 에이전트에게 전달할 때

권장 운영 규칙 섹션은 그대로 복사해서 OpenClaw 에이전트에게 메시지로 전달하는 용도로 사용할 수 있습니다.
다만 실제 적용을 위해서는 아래 정보도 함께 전달하는 것을 권장합니다.

- 프로젝트 위치
  - 예: `/Users/lucas/working/claude-vector-memory`
- 실행 방식
  - 예: `cd /Users/lucas/working/claude-vector-memory && uv run memory-index ...`
- 경로 규칙
  - `--source <workspace>/memory`
  - `--index-file <workspace>/MEMORY.md`
  - 두 경로는 반드시 같은 workspace 루트 아래여야 함

즉, README의 이 섹션을 복사해서 OpenClaw 에이전트에게 전달하면 좋고,
필요하면 에이전트별 workspace 경로만 알맞게 바꿔서 보내면 됩니다.

---

## Step 8. Gateway restart가 필요한가?

대부분의 경우 **재시작은 필요 없습니다.**

### 재시작이 필요 없는 경우
- `claude-vector-memory`를 외부 독립 CLI / Python 라이브러리로 설치해서 사용하는 경우
- `uv run memory-index ...` 명령을 직접 호출하는 경우
- OpenClaw hook, wrapper, agent 운영 규칙에서 이 프로젝트를 호출하는 경우
- AGENTS.md / SOUL.md / 운영 프롬프트에 "vector memory를 우선 사용" 규칙만 추가하는 경우

즉, 현재 README에서 설명하는 일반적인 사용 방식은 **OpenClaw Gateway restart 없이 바로 적용 가능**합니다.

### 재시작이 필요할 가능성이 높은 경우
- OpenClaw 코어에 직접 tool/plugin으로 등록하는 경우
- 기존 `memory_search`를 OpenClaw 내부에서 직접 대체하는 경우
- gateway config, plugin registry, tool registry 변경이 필요한 경우

---

## 6. 파일 기반 메모리 시스템에서 사용하는 방법

이 프로젝트는 **특정 OpenClaw 전용 구조만 요구하지 않습니다.**
기본적으로는 Markdown 파일이 있는 어떤 디렉토리든 인덱싱할 수 있습니다.

예시:

```text
project/
├── MEMORY.md
├── memory/
│   ├── 2026-01-15.md
│   ├── 2026-01-16.md
│   ├── lessons.md
│   └── process-notes.md
└── .memory_index.db
```

분류 규칙:
- `YYYY-MM-DD.md` → `daily`
- `MEMORY.md` → `index`
- 그 외 → `lesson`

Chunking 규칙:
- `##` 헤딩 단위로 chunk를 나눕니다
- 첫 `##` 이전 내용도 별도 chunk로 보존합니다

즉 기존 file-based memory 시스템에 이 프로젝트를 추가하려면,
**Markdown 파일은 그대로 두고 인덱스만 옆에 생성하면 됩니다.**

---

## 7. Python API 사용 예시

```python
from claude_vector_memory import MemoryIndex

with MemoryIndex(source_dir="./memory", index_file="./MEMORY.md") as idx:
    idx.sync()
    results = idx.search("SL bug", limit=5)
    context = idx.retrieve("위험 관리 관련 실수")
    print(context)
```

---

## 8. 주요 명령어

### sync
변경된 파일만 반영합니다. 일상 운영에서 가장 자주 쓰는 명령입니다.

```bash
uv run memory-index --source ./memory --index-file ./MEMORY.md sync
```

### rebuild
전체 인덱스를 처음부터 다시 만듭니다.
provider를 바꾸거나 인덱스 구조를 바꿨을 때 사용합니다.

```bash
uv run memory-index --source ./memory --index-file ./MEMORY.md rebuild
```

### search
검색을 수행합니다.

```bash
uv run memory-index --source ./memory --index-file ./MEMORY.md search "위험 관리 교훈"
```

### status
인덱스 상태와 staleness 정보를 봅니다.

```bash
uv run memory-index --source ./memory --index-file ./MEMORY.md status
```

### tags
자동 추론된 태그 목록을 봅니다.

```bash
uv run memory-index --source ./memory --index-file ./MEMORY.md tags
```

### doctor
환경과 인덱스 상태를 검사합니다.

```bash
uv run memory-index --source ./memory --index-file ./MEMORY.md doctor
```

### verify
FTS / vector / hybrid 품질을 비교합니다.

```bash
uv run memory-index --source ./memory --index-file ./MEMORY.md verify
```

---

## 9. 포함된 예제 파일

- `examples/single_agent.py`
  - 단일 에이전트 예제
- `examples/multi_agent.py`
  - 멀티 에이전트 예제
- `examples/openclaw_integration.py`
  - OpenClaw 설정을 읽어서 연동하는 예제
- `examples/openclaw_hook.sh`
  - hook 또는 wrapper에 붙일 수 있는 쉘 예제

---

## 10. 주의사항

- DB 파일은 **원본 데이터가 아닙니다**
- Markdown 메모리 파일이 원본입니다
- `.memory_index.db` 같은 인덱스 파일은 git에 넣지 않는 것을 권장합니다
- 멀티 에이전트 환경에서는 **DB를 에이전트별로 분리**하는 것을 강하게 권장합니다
- 공용 DB 하나에 여러 에이전트를 합치는 구조는 초기에는 추천하지 않습니다

---

## 11. 요약

이 프로젝트는 다음을 위한 도구입니다.

- Markdown 기반 메모리를 유지하면서
- SQLite + vector search 기반의 고품질 검색을 추가하고
- OpenClaw와도 함께 쓰고
- 싱글 에이전트 / 멀티 에이전트 환경에서도 안전하게 운영하는 것

가장 추천하는 구조는 항상 같습니다.

- **공용 엔진 코드**
- **에이전트별 memory source path 분리**
- **에이전트별 DB 파일 분리**

즉, 엔진은 하나로 유지하고, 메모리 원본과 인덱스만 에이전트별로 분리하는 방식입니다.

이 방식이 가장 안전하고, 유지보수도 가장 쉽습니다.
