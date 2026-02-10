#!/usr/bin/env python3
"""
═══════════════════════════════════════════════════════════════
  MARS — Multi-AI Research Orchestrator v2.0

  v2 변경사항:
  ● Phase 0 — 파일 기반 Q&A (질문 파일 → 사용자 편집 → 프로그램 읽기)
  ● 모든 Phase·Round마다 결과 출력 + 계속/건너뛰기/중단 확인
  ● AGENTS.md 기반 역할 셋(research/market/technical/general)
  ● 중단 시점까지 결과 보존 → 재실행 없이 파일 확인 가능
═══════════════════════════════════════════════════════════════
"""

import os, sys, json, yaml, asyncio, logging, argparse, textwrap, re
from datetime import datetime
from pathlib import Path

from providers import create_provider, AIProvider

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("mars")

# ═══════════════════════════════════════════════════════════════
#  역할 셋 (AGENTS.md 참조)
# ═══════════════════════════════════════════════════════════════
ROLE_SETS = {
    # ── 학술/기술 연구 ──
    "research": {
        "claude": {
            "name": "Domain Architect (도메인 설계자)",
            "persona": (
                "해당 분야 20년 경력의 시스템 아키텍트. "
                "복잡한 시스템 설계와 기술적 트레이드오프 분석에 탁월하다."
            ),
            "focus": "시스템 설계·트레이드오프 비교·기술 장벽 식별·확장성/유지보수성 평가",
            "style": "분석적·구조화. 모든 주장에 기술적 근거 포함. '어떤 조건에서 최선인가'를 중시.",
        },
        "gemini": {
            "name": "Literature Researcher (문헌 조사관)",
            "persona": (
                "NLP/AI 분야 연구원이자 기술 트렌드 분석가. "
                "최신 논문·오픈소스를 광범위하게 조사하고 핵심을 정리한다."
            ),
            "focus": "최신 논문/기술 동향·오픈소스 비교·벤치마크 데이터·업계 사례",
            "style": "증거 중심. 출처(논문명, URL, 날짜) 필수. 데이터·수치 적극 활용.",
        },
        "gpt": {
            "name": "Critical Analyst (비판적 분석가)",
            "persona": (
                "기술 실사(due diligence) 전문 시니어 컨설턴트. "
                "낙관적 제안의 약점을 찾아내는 데 탁월하다."
            ),
            "focus": "현실 실행 가능성·숨겨진 리스크/비용·악마의 변호인·대안 비교",
            "style": "'이론적으로 맞지만 실제로는…'. 구체적 수치/사례로 반박. 약점 후 개선안 필수.",
        },
    },
    # ── 시장 분석 ──
    "market": {
        "claude": {
            "name": "Strategy Architect (전략 설계자)",
            "persona": "B2B SaaS 15년 경력 전략 컨설턴트. 시장 진입·포지셔닝·GTM에 정통.",
            "focus": "TAM/SAM/SOM·진입 전략·비즈니스 모델·고객 세그먼테이션",
            "style": "Porter's 5 Forces, SWOT 등 프레임워크. 정량 데이터. 경쟁사 벤치마킹.",
        },
        "gemini": {
            "name": "Market Intelligence (시장 정보 수집가)",
            "persona": "시장 조사 전문 애널리스트. 공개 정보에서 숨겨진 인사이트 발견.",
            "focus": "경쟁 솔루션 비교·산업 트렌드/규제·고객 리뷰·해외 시장",
            "style": "팩트 중심. 비교 표 적극 활용. 출처·데이터 시점 명시.",
        },
        "gpt": {
            "name": "Venture Critic (벤처 비평가)",
            "persona": "기술 스타트업 투자 심사역 경력. '이 사업이 왜 실패할 수 있는가'를 먼저 생각.",
            "focus": "사업 모델 약점/리스크·경쟁 우위 지속 가능성·MVP/PMF 검증",
            "style": "투자자 관점. Unit Economics·Moat 질문. 비판 후 개선안 필수.",
        },
    },
    # ── 기술 평가/아키텍처 ──
    "technical": {
        "claude": {
            "name": "Systems Architect (시스템 아키텍트)",
            "persona": "대규모 분산 시스템 수석 아키텍트. 수만 대 규모 운영 경험.",
            "focus": "전체 아키텍처·모듈 분리/인터페이스·확장성/성능·배포/운영",
            "style": "다이어그램 활용. '10배 규모에서도 작동하는가?' 기준. 대안 함께 제시.",
        },
        "gemini": {
            "name": "Tech Scout (기술 스카우트)",
            "persona": "최신 기술 스택/도구 생태계 추적 전문가.",
            "focus": "기술 스택 벤치마크·최신 도구/프레임워크·오픈소스·커뮤니티 활성도",
            "style": "비교표+벤치마크. GitHub 스타·다운로드수 등 정량 지표. 최신 정보 우선.",
        },
        "gpt": {
            "name": "Implementation Engineer (구현 엔지니어)",
            "persona": "실제 코드를 작성하는 시니어 개발자. 아키텍처→코드 전환 시 문제를 잘 앎.",
            "focus": "구현 난이도/공수 추정·프로젝트 구조·테스트/CI/CD·소규모 팀 로드맵",
            "style": "코드 스니펫으로 뒷받침. '구현하면 ~3일/~2주' 구체적 추정. 현실 검증.",
        },
    },
    # ── 범용 ──
    "general": {
        "claude": {
            "name": "Lead Analyst (수석 분석가)",
            "persona": "맥킨지/BCG 출신 수석 컨설턴트. 복잡한 문제를 구조화하여 분석.",
            "focus": "문제 구조화·핵심 이슈 도출·프레임워크 적용·실행 가능한 Next Steps",
            "style": "MECE 원칙. 피라미드 구조(결론 먼저, 근거 뒷받침).",
        },
        "gemini": {
            "name": "Research Investigator (조사 수사관)",
            "persona": "탐사 보도 기자 출신 리서치 전문가. 교차 검증·다양한 관점 수집.",
            "focus": "광범위한 자료 수집·교차 검증·이해관계자 관점·데이터 신뢰성",
            "style": "5W1H. 모든 주장에 최소 2개 출처 교차 검증.",
        },
        "gpt": {
            "name": "Devil's Advocate (반론 전문가)",
            "persona": "철학·논리학 전공 토론 전문가. 어떤 결론이든 반대 입장에서 논증 가능.",
            "focus": "논리적 약점/편향 식별·반례 제시·전제 타당성 검증·대안적 해석",
            "style": "'만약 ~라면?' 사고 실험. 소크라테스식 질문. 반박 후 더 나은 결론 제시.",
        },
    },
}


# ═══════════════════════════════════════════════════════════════
#  유틸리티
# ═══════════════════════════════════════════════════════════════
def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def save(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    log.info(f"  📄 저장: {path}")

def banner(text: str):
    w = 60
    print(f"\n{'═'*w}\n  {text}\n{'═'*w}\n")

def section(text: str):
    print(f"\n{'─'*50}\n  {text}\n{'─'*50}")

def extract_json(text: str) -> dict:
    m = re.search(r'```json\s*(.*?)\s*```', text, re.DOTALL)
    if m:
        try: return json.loads(m.group(1))
        except: pass
    m = re.search(r'\{[^{}]*"questions"[^{}]*\}', text, re.DOTALL)
    if m:
        try: return json.loads(m.group(0))
        except: pass
    return {"questions": []}

def detect_role_set(query: str) -> str:
    q = query.lower()
    kw = {
        "market":    ["시장","경쟁","진입","전략","사업","비즈니스","market","competitor","business","pricing"],
        "technical": ["아키텍처","설계","구현","기술 스택","프레임워크","architecture","implementation","stack","framework"],
        "research":  ["모델","논문","알고리즘","벤치마크","NER","NLP","ML","model","paper","algorithm","survey"],
    }
    scores = {k: sum(1 for w in ws if w in q) for k, ws in kw.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "general"


# ═══════════════════════════════════════════════════════════════
#  체크포인트 — Phase·Round마다 확인
# ═══════════════════════════════════════════════════════════════
class Gate:
    """결과 출력 + 계속/건너뛰기/중단 확인"""

    @staticmethod
    def _show_files(files: list[str]):
        if not files:
            return
        print("  생성된 파일:")
        for f in files[:8]:
            print(f"    📄 {Path(f).name}")
        if len(files) > 8:
            print(f"    … 외 {len(files)-8}개")

    @staticmethod
    def ask(title: str, desc: str, files: list[str] = None) -> str:
        """
        Returns:
          'c' → continue
          's' → skip this phase
          'q' → quit entirely
        """
        print()
        print(f"  ┌{'─'*56}┐")
        print(f"  │ ✅ {title:<52}│")
        print(f"  │    {desc[:52]:<52}│")
        print(f"  └{'─'*56}┘")
        Gate._show_files(files)
        print()
        print("  [Enter] 다음 단계 진행")
        print("  [s]     이 단계 건너뛰기")
        print("  [q]     여기서 중단 (결과 보존)")
        try:
            ch = input("\n  선택 > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            ch = "q"
        if ch == "q":
            print("\n  ⏹  중단합니다. 지금까지의 결과는 출력 폴더에 보존되어 있습니다.\n")
            return "q"
        if ch == "s":
            print("  ⏭  건너뜁니다.\n")
            return "s"
        return "c"

    @staticmethod
    def ask_round(rnd: int, total: int, files: list[str] = None) -> str:
        print()
        print(f"  ── Round {rnd}/{total} 완료 ──")
        Gate._show_files(files)
        print()
        print(f"  [Enter] Round {rnd+1} 진행  |  [q] 토론 종료 → 합의 도출")
        try:
            ch = input("  선택 > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            ch = "q"
        return "q" if ch == "q" else "c"


# ═══════════════════════════════════════════════════════════════
#  오케스트레이터
# ═══════════════════════════════════════════════════════════════
class Orchestrator:

    def __init__(self, config: dict, query: str, *,
                 deep_research=False, role_set=None):
        self.cfg       = config
        self.query     = query
        self.deep      = deep_research or config.get("deep_research", False)
        self.rounds    = min(config.get("debate_rounds", 3), 5)
        self.rs_name   = role_set or detect_role_set(query)
        self.roles     = ROLE_SETS.get(self.rs_name, ROLE_SETS["general"])

        # 출력 디렉토리
        ts   = datetime.now().strftime("%Y%m%d-%H%M%S")
        slug = re.sub(r'[^가-힣a-zA-Z0-9]+', '-', query)[:30].strip('-')
        base = config.get("output_dir", "./research_output")
        self.out = Path(base) / f"{ts}-{slug}"
        self.out.mkdir(parents=True, exist_ok=True)

        # 프로바이더 초기화 (역할 주입)
        self.ai: dict[str, AIProvider] = {}
        for name, pcfg in config.get("providers", {}).items():
            if not pcfg.get("enabled", True):
                continue
            ri = self.roles.get(name, {})
            if ri:
                pcfg = {**pcfg, "role": self._role_prompt(ri)}
            try:
                self.ai[name] = create_provider(name, pcfg)
                log.info(f"  ✅ {name} ({ri.get('name','')}) 활성")
            except Exception as e:
                log.warning(f"  ⚠️ {name} 실패: {e}")

        if not self.ai:
            raise RuntimeError("활성화된 AI 프로바이더가 없습니다.")

        # 상태
        self.ctx      = ""          # 사용자 추가 맥락
        self.research  = {}         # {name: report_text}
        self.debate    = []         # [{round, type, provider, content}]
        self.consensus = ""

    # ── helpers ──
    def _role_prompt(self, ri: dict) -> str:
        return "\n".join(filter(None, [
            f"역할: {ri.get('name','')}",
            f"페르소나: {ri.get('persona','')}",
            f"집중 영역: {ri.get('focus','')}",
            f"소통 스타일: {ri.get('style','')}",
        ]))

    def _rname(self, name: str) -> str:
        return self.roles.get(name, {}).get("name", name)

    def _save_state(self):
        save(self.out / "state.json", json.dumps({
            "query": self.query, "context": self.ctx,
            "role_set": self.rs_name,
            "research": self.research,
            "debate": self.debate,
            "consensus": self.consensus,
        }, ensure_ascii=False, indent=2, default=str))

    # ═══════════════════════════════════════════════════════════
    #  Phase 0 — 파일 기반 질문 명확화
    # ═══════════════════════════════════════════════════════════
    async def phase0_clarify(self) -> str:
        banner("Phase 0: 연구 질문 명확화")
        print(f"  📝 질문: {self.query}")
        print(f"  🎭 역할셋: {self.rs_name}")
        for n in self.ai:
            print(f"     • {n} → {self._rname(n)}")

        # ① 각 AI에게 명확화 질문 요청 (병렬)
        print("\n  각 AI에게 명확화 질문을 요청합니다…\n")
        tmpl = (
            "너는 {role}이다.\n"
            "사용자가 다음 주제에 대해 연구를 의뢰했다:\n\n\"{query}\"\n\n"
            "연구를 가장 효과적으로 수행하기 위해 사용자에게 물어봐야 할 "
            "핵심 질문 3~5개를 만들어라.\n"
            "질문은 연구 범위·깊이·관점·기대 산출물을 명확히 하는 데 집중.\n\n"
            'JSON 형식: {{"questions": ["질문1", "질문2", …]}}'
        )

        async def _ask(name, prov):
            p = tmpl.format(role=prov.role, query=self.query)
            try:
                r = await prov.query_with_fallback(p, deep_research=False)
                return name, extract_json(r).get("questions", [])
            except Exception as e:
                log.warning(f"  [{name}] 질문 생성 실패: {e}")
                return name, []

        results = await asyncio.gather(*[_ask(n,p) for n,p in self.ai.items()])
        all_qs = dict(results)

        # ② 질문 파일 생성
        qa_path = self.out / "00-질문과답변.md"
        save(qa_path, self._build_qa_file(all_qs))

        # ③ 사용자에게 편집 요청
        print(f"""
  ┌────────────────────────────────────────────────────────┐
  │  📋 질문 파일이 생성되었습니다                          │
  │                                                        │
  │  파일: {str(qa_path):<48}│
  │                                                        │
  │  사용법:                                               │
  │   1. 위 파일을 텍스트 편집기로 여세요                  │
  │   2. 각 질문 아래 "답변:" 뒤에 내용을 작성하세요       │
  │   3. 불필요한 질문은 삭제, 새 질문은 추가 가능         │
  │   4. 파일을 저장하세요                                 │
  │   5. 여기로 돌아와서 Enter를 누르세요                  │
  │                                                        │
  │  💡 프로그램을 종료해도 됩니다.                         │
  │     다음에 같은 명령을 실행하면 이 파일을 읽습니다.    │
  └────────────────────────────────────────────────────────┘
""")
        print("  준비되면 Enter, 건너뛰려면 's' 입력:")
        try:
            ch = input("  > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            ch = "s"

        # ④ 파일 읽기
        if ch != "s" and qa_path.exists():
            self.ctx = self._parse_qa_file(qa_path)
            if self.ctx:
                print(f"\n  ✅ 사용자 답변 로드 완료 ({len(self.ctx)} 글자)")
            else:
                print("  ℹ️  답변이 비어있습니다. 원본 질문으로 진행합니다.")
        else:
            print("  ℹ️  명확화 단계를 건너뜁니다.")

        self._save_state()

        # ⑤ 체크포인트
        return Gate.ask("Phase 0 완료", "질문 명확화 + 사용자 맥락 수집",
                        [str(qa_path)])

    def _build_qa_file(self, all_qs: dict) -> str:
        lines = [
            f"# 연구 질문 명확화",
            f"",
            f"> 📝 연구 주제: {self.query}",
            f"> 🎭 역할 셋: {self.rs_name}",
            f"> 📅 생성: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            f"",
            f"---",
            f"",
            f"## 사용법",
            f"",
            f"- 각 질문 아래 `답변:` 뒤에 내용을 작성하세요.",
            f"- 불필요한 질문은 삭제해도 됩니다.",
            f"- 새 질문을 추가해도 됩니다 (### Q숫자. 형식).",
            f"- 파일을 저장한 뒤 프로그램으로 돌아가 Enter를 누르세요.",
            f"",
            f"---",
            f"",
        ]
        num = 1
        for ai_name, qs in all_qs.items():
            rn = self._rname(ai_name)
            lines.append(f"## {ai_name} — {rn}")
            lines.append("")
            if qs:
                for q in qs:
                    lines.append(f"### Q{num}. {q}")
                    lines.append("")
                    lines.append("답변: ")
                    lines.append("")
                    num += 1
            else:
                lines.append("_(질문 생성 실패)_")
                lines.append("")

        lines += [
            "---", "",
            "## 추가 맥락 (자유 기술)", "",
            "위 질문과 무관하게 연구에 참고할 맥락이 있으면 여기에 자유롭게 쓰세요:", "",
            "",
        ]
        return "\n".join(lines)

    def _parse_qa_file(self, path: Path) -> str:
        content = path.read_text(encoding="utf-8")
        answers, cur_q, free = [], None, []
        in_free = False
        skip_lines = {"위 질문과 무관하게", "위 질문 외에"}

        for line in content.split("\n"):
            s = line.strip()
            if s.startswith("### Q"):
                # "### Q1. 타겟…" → "타겟…"
                m = re.match(r'### Q\d+\.\s*(.*)', s)
                cur_q = m.group(1) if m else s[5:]
            elif s.startswith("답변:"):
                ans = s[3:].strip()
                if ans and cur_q:
                    answers.append(f"Q: {cur_q}\nA: {ans}")
                cur_q = None
            elif s.startswith("## 추가 맥락"):
                in_free = True
            elif in_free and s and not s.startswith("---") and not s.startswith(">"):
                if not any(sk in s for sk in skip_lines):
                    free.append(s)

        out = "\n\n".join(answers)
        if free:
            out += "\n\n## 추가 맥락\n" + "\n".join(free)
        return out

    # ═══════════════════════════════════════════════════════════
    #  Phase A — 병렬 독립 조사
    # ═══════════════════════════════════════════════════════════
    async def phaseA_research(self) -> str:
        banner("Phase A: 병렬 독립 조사")
        mode = "🔬 심층 연구" if self.deep else "📊 일반 연구"
        print(f"  {mode} 모드")
        if self.deep:
            print("  ⏳ AI당 5~20분 소요될 수 있습니다.")
        print()

        files = []

        async def _do(name, prov):
            rn = self._rname(name)
            section(f"{name} ({rn}) 조사 시작…")
            prompt = (
                f"너는 {prov.role}이다.\n\n"
                f"## 연구 주제\n{self.query}\n\n"
                f"## 추가 맥락\n{self.ctx or '(없음)'}\n\n"
                f"## 요청\n"
                f"너의 전문성을 최대한 발휘하여 심층 조사해라.\n"
                f"포함할 내용:\n"
                f"1. 현황 분석\n"
                f"2. 핵심 발견사항 (근거 포함)\n"
                f"3. 기회와 위험 요소\n"
                f"4. 구체적 권장사항\n\n"
                f"모든 주장에 근거를 포함해라.\n"
                f"불확실한 부분은 명시적으로 '⚠️ 불확실:' 로 표기해라."
            )
            try:
                result = await prov.query_with_fallback(prompt, deep_research=self.deep)
                self.research[name] = result
                fp = self.out / "research" / f"{name}-report.md"
                save(fp, f"# {name} ({rn}) 연구 보고서\n\n{result}")
                files.append(str(fp))
                log.info(f"  ✅ {name} 완료 ({len(result):,} 글자)")
            except Exception as e:
                log.error(f"  ❌ {name} 실패: {e}")
                self.research[name] = f"[조사 실패: {e}]"

        await asyncio.gather(*[_do(n,p) for n,p in self.ai.items()])

        ok = sum(1 for v in self.research.values() if not v.startswith("["))
        print(f"\n  📋 조사 완료: {ok}/{len(self.ai)}개 AI")
        self._save_state()

        return Gate.ask(
            "Phase A 완료",
            f"{ok}개 AI 독립 조사 완료 — 각 보고서를 확인해 보세요.",
            files)

    # ═══════════════════════════════════════════════════════════
    #  Phase B — 다회전 교차 토론
    # ═══════════════════════════════════════════════════════════
    async def phaseB_debate(self) -> str:
        banner(f"Phase B: 다회전 교차 토론 ({self.rounds}라운드)")

        actual_rounds = 0

        for rnd in range(1, self.rounds + 1):
            is_last = (rnd == self.rounds)

            if rnd == 1:
                files = await self._round_critique(rnd)
            elif is_last:
                files = await self._round_consensus(rnd)
                actual_rounds = rnd
                break
            else:
                files = await self._round_respond(rnd)

            actual_rounds = rnd
            self._save_state()

            # 라운드별 체크포인트 (마지막 라운드 제외 — 합의는 Phase 체크포인트에서)
            if not is_last:
                g = Gate.ask_round(rnd, self.rounds, files)
                if g == "q":
                    log.info("  토론 조기 종료 → 합의 도출")
                    await self._round_consensus(rnd + 1)
                    break

        self._save_state()
        return Gate.ask(
            "Phase B 완료",
            f"{actual_rounds}라운드 토론 + 합의 도출 완료",
            [str(p) for p in (self.out / "debate").glob("*")])

    # ── Round 1: 교차 비평 ──
    async def _round_critique(self, rnd: int) -> list[str]:
        section(f"Round {rnd}: 교차 비평")
        files = []

        async def _do(name, prov):
            others = "\n\n".join(
                f"### {on} ({self._rname(on)})\n{orpt[:6000]}"
                for on, orpt in self.research.items()
                if on != name and not orpt.startswith("["))
            own = self.research.get(name, "")[:6000]

            prompt = (
                f"너는 {prov.role}이다.\n\n"
                f"## 다른 AI 보고서\n{others}\n\n"
                f"## 너의 보고서\n{own}\n\n"
                f"## 요청\n"
                f"핵심 논점 5개 이상을 선정하고 각각 비평해라:\n\n"
                f"### 논점 N: (제목)\n"
                f"- **다른 AI 의견 요약**\n"
                f"- **내 입장**: [동의]/[부분 동의]/[반대]/[대안]\n"
                f"- **근거**: (구체적)\n\n"
                f"근거 없는 의견 금지. 추가 논점 자유롭게 추가 가능."
            )
            try:
                r = await prov.query_with_fallback(prompt)
                self.debate.append({"round": rnd, "type": "critique",
                                    "provider": name, "content": r})
                fp = self.out/"debate"/f"round{rnd}-{name}-critique.md"
                save(fp, f"# Round {rnd}: {name} 비평\n\n{r}")
                files.append(str(fp))
            except Exception as e:
                log.error(f"  ❌ {name} 비평 실패: {e}")

        await asyncio.gather(*[_do(n,p) for n,p in self.ai.items()])
        return files

    # ── Round 2+: 반론/수용 ──
    async def _round_respond(self, rnd: int) -> list[str]:
        section(f"Round {rnd}: 반론 및 수용")
        files = []
        prev = rnd - 1

        async def _do(name, prov):
            crits = "\n\n".join(
                f"### {rec['provider']} ({self._rname(rec['provider'])})\n{rec['content'][:5000]}"
                for rec in self.debate
                if rec["round"] == prev and rec["provider"] != name)

            prompt = (
                f"너는 {prov.role}이다.\n\n"
                f"이전 라운드 비평:\n{crits or '(없음)'}\n\n"
                f"## 요청\n"
                f"각 논점에 응답:\n\n"
                f"### 논점 N: (제목)\n"
                f"**받은 비평**: (요약)\n"
                f"**응답**: [수용]/[부분 수용]/[반박]\n"
                f"- 수용 → 어떻게 수정하는지\n"
                f"- 반박 → 왜 기존 의견이 타당한지 (추가 근거)\n\n"
                f"모든 논점에 빠짐없이 응답."
            )
            try:
                r = await prov.query_with_fallback(prompt)
                self.debate.append({"round": rnd, "type": "respond",
                                    "provider": name, "content": r})
                fp = self.out/"debate"/f"round{rnd}-{name}-response.md"
                save(fp, f"# Round {rnd}: {name} 반론/수용\n\n{r}")
                files.append(str(fp))
            except Exception as e:
                log.error(f"  ❌ {name} 응답 실패: {e}")

        await asyncio.gather(*[_do(n,p) for n,p in self.ai.items()])
        return files

    # ── 합의 도출 ──
    async def _round_consensus(self, rnd: int) -> list[str]:
        section(f"Round {rnd}: 합의 도출")
        files = []

        history = "\n\n---\n\n".join(
            f"## R{rec['round']} — {rec['provider']} ({self._rname(rec['provider'])}) [{rec['type']}]\n{rec['content'][:4000]}"
            for rec in self.debate)

        lead_n = "claude" if "claude" in self.ai else list(self.ai)[0]
        lead   = self.ai[lead_n]

        prompt = (
            f"3개 AI가 교차 토론한 결과를 공정하게 분석하여 정리해라.\n\n"
            f"## 토론 기록\n{history[:30000]}\n\n"
            f"## 출력 형식\n\n"
            f"### PART 1: 합의 사항 (CONSENSUS)\n"
            f"논점별:\n- **결론**\n- **합의 수준**: ⭐⭐⭐/⭐⭐/⭐\n"
            f"- **근거 요약**\n- **조건/유보사항**\n\n"
            f"### PART 2: 미합의 사항 (UNRESOLVED)\n"
            f"- **대립 입장들**\n- **합의 실패 이유**\n- **잠정 추천안**"
        )
        consensus = await lead.query_with_fallback(prompt)
        self.consensus = consensus
        fp = self.out/"debate"/f"round{rnd}-consensus.md"
        save(fp, f"# 합의 결과 (Round {rnd})\n\n{consensus}")
        files.append(str(fp))

        # 다른 AI 검증
        verify_prompt = (
            f"아래 합의 결과가 공정한지 검증해라:\n\n"
            f"{consensus[:8000]}\n\n"
            f"1. 네 의견이 잘못 반영된 것?\n"
            f"2. 분류가 적절한가?\n"
            f"3. 빠진 논점?"
        )
        feedbacks = []
        for name, prov in self.ai.items():
            if name == lead_n:
                continue
            try:
                vr = await prov.query_with_fallback(verify_prompt)
                vfp = self.out/"debate"/f"round{rnd}-{name}-verify.md"
                save(vfp, f"# {name} 합의 검증\n\n{vr}")
                files.append(str(vfp))
                feedbacks.append(f"### {name}\n{vr}")
            except Exception as e:
                log.error(f"  [{name}] 검증 실패: {e}")

        # 피드백 반영
        if feedbacks:
            amend = (
                f"원본 합의:\n{consensus[:8000]}\n\n"
                f"검증 피드백:\n{''.join(feedbacks)[:6000]}\n\n"
                f"피드백을 반영하여 최종 수정해라."
            )
            final = await lead.query_with_fallback(amend)
            self.consensus = final
            ffp = self.out/"debate"/"consensus-final.md"
            save(ffp, f"# 최종 합의 (검증 반영)\n\n{final}")
            files.append(str(ffp))

        return files

    # ═══════════════════════════════════════════════════════════
    #  Phase C — 미합의 추가 토론
    # ═══════════════════════════════════════════════════════════
    async def phaseC_extra(self) -> str:
        banner("Phase C: 미합의 항목 추가 토론")
        print("  합의 결과를 확인한 뒤, 추가 토론할 항목을 입력하세요.")
        cf = self.out/"debate"/"consensus-final.md"
        if cf.exists():
            print(f"  📄 합의 파일: {cf}")
        print("  (빈 줄 입력 → 건너뛰기)")

        topics, files = [], []
        while True:
            try:
                t = input("\n  추가 토론 항목: ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not t:
                break
            topics.append(t)

        for i, topic in enumerate(topics, 1):
            section(f"추가 토론 {i}: {topic}")
            fs = await self._focused(topic, i)
            files.extend(fs)
            self._save_state()
            if i < len(topics):
                g = Gate.ask_round(i, len(topics), fs)
                if g == "q":
                    break

        if files:
            return Gate.ask("Phase C 완료",
                            f"{len(topics)}개 항목 추가 토론", files)
        return "c"

    async def _focused(self, topic: str, idx: int) -> list[str]:
        files = []
        prompt = (
            f"논점 '{topic}'에 대해 집중 분석해라.\n\n"
            f"기존 합의:\n{self.consensus[:4000]}\n\n"
            f"가능한 모든 선택지의 장단점을 비교하고 조건부 결론을 제시해라."
        )
        results = []
        async def _do(name, prov):
            try:
                r = await prov.query_with_fallback(prompt)
                fp = self.out/"debate"/f"extra-{idx}-{name}.md"
                save(fp, f"# 추가 토론 {idx}: {topic} — {name}\n\n{r}")
                files.append(str(fp))
                results.append((name, r))
            except Exception as e:
                log.error(f"  {name} 실패: {e}")

        await asyncio.gather(*[_do(n,p) for n,p in self.ai.items()])

        # 종합
        views = "\n\n---\n\n".join(f"## {n}\n{r[:4000]}" for n,r in results)
        lead = list(self.ai.values())[0]
        syn = await lead.query_with_fallback(
            f"'{topic}'에 대한 의견 종합:\n\n{views}\n\n결론을 내려라.")
        sfp = self.out/"debate"/f"extra-{idx}-synthesis.md"
        save(sfp, f"# 추가 토론 {idx} 종합: {topic}\n\n{syn}")
        files.append(str(sfp))
        return files

    # ═══════════════════════════════════════════════════════════
    #  Phase D — 최종 보고서
    # ═══════════════════════════════════════════════════════════
    async def phaseD_report(self) -> str:
        banner("Phase D: 최종 보고서 생성")

        rsumm = "\n\n---\n\n".join(
            f"## {n} ({self._rname(n)})\n{r[:5000]}"
            for n,r in self.research.items() if not r.startswith("["))

        prompt = (
            f"# 최종 연구 보고서 작성\n\n"
            f"## 원본 질문\n{self.query}\n\n"
            f"## 추가 맥락\n{self.ctx or '(없음)'}\n\n"
            f"## 개별 연구 요약\n{rsumm[:10000]}\n\n"
            f"## 토론 합의\n{self.consensus[:8000]}\n\n"
            f"## 구조\n"
            f"1. **요약 (Executive Summary)** — 핵심 발견 3~5개\n"
            f"2. **상세 분석** — 합의 결론 중심, 근거 포함\n"
            f"3. **대안과 트레이드오프** — 미합의 사항의 조건부 결론\n"
            f"4. **권장사항** — 우선순위 포함 액션 아이템\n"
            f"5. **향후 조사 필요 사항**\n\n"
            f"모호한 표현 금지. 모든 결론에 근거 포함."
        )

        lead_n = "claude" if "claude" in self.ai else list(self.ai)[0]
        report = await self.ai[lead_n].query_with_fallback(prompt)

        rp = self.out / "FINAL-REPORT.md"
        meta = (
            f"> 연구 질문: {self.query}\n"
            f"> 참여 AI: {', '.join(f'{n} ({self._rname(n)})' for n in self.ai)}\n"
            f"> 역할 셋: {self.rs_name}\n"
            f"> 모드: {'심층 연구' if self.deep else '일반'}\n"
            f"> 생성일: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        )
        save(rp, f"# 최종 연구 보고서\n\n{meta}\n---\n\n{report}")
        self._save_state()

        return Gate.ask("Phase D 완료", "최종 보고서 생성 완료", [str(rp)])

    # ═══════════════════════════════════════════════════════════
    #  실행
    # ═══════════════════════════════════════════════════════════
    async def run(self, *, skip_clarify=False, skip_extra=False):
        print()
        print("  ╔═══════════════════════════════════════════════╗")
        print("  ║  MARS — Multi-AI Research Orchestrator v2.0   ║")
        print("  ╚═══════════════════════════════════════════════╝")
        print()
        print(f"  📝 질문     : {self.query}")
        print(f"  🎭 역할 셋  : {self.rs_name}")
        for n in self.ai:
            print(f"      {n:8s} → {self._rname(n)}")
        print(f"  🔬 연구 모드 : {'심층' if self.deep else '일반'}")
        print(f"  💬 토론 라운드: {self.rounds}")
        print(f"  📁 출력      : {self.out}")

        # Phase 0
        if not skip_clarify:
            g = await self.phase0_clarify()
            if g == "q": return self.out

        # Phase A
        g = await self.phaseA_research()
        if g == "q": return self.out

        # Phase B
        g = await self.phaseB_debate()
        if g == "q": return self.out

        # Phase C
        if not skip_extra:
            g = await self.phaseC_extra()
            if g == "q": return self.out

        # Phase D
        await self.phaseD_report()

        banner("🎉 연구 완료!")
        print(f"  📁 전체 결과  : {self.out}")
        print(f"  📊 최종 보고서: {self.out / 'FINAL-REPORT.md'}")
        print()
        return self.out


# ═══════════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════════
def main():
    p = argparse.ArgumentParser(
        description="MARS — Multi-AI Research Orchestrator v2.0",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""
  예시:
    python researcher.py "한국어 NER 모델 비교"
    python researcher.py "DLP 시장 분석" -d --role-set market
    python researcher.py "Rust vs Go" -r 4 --role-set technical
    python researcher.py "주제" --no-clarify --no-extra
        """))
    p.add_argument("query", help="연구 질문")
    p.add_argument("--config",        default="config.yaml")
    p.add_argument("--deep-research", "-d", action="store_true",
                   help="심층 연구 모드")
    p.add_argument("--rounds",   "-r", type=int, default=None)
    p.add_argument("--role-set", choices=list(ROLE_SETS), default=None,
                   help="역할 셋 (자동 감지 또는 수동 지정)")
    p.add_argument("--no-clarify", action="store_true")
    p.add_argument("--no-extra",   action="store_true")
    p.add_argument("--output", "-o", default=None)

    args = p.parse_args()

    # config
    cp = Path(args.config)
    if cp.exists():
        cfg = load_config(str(cp))
    else:
        cfg = {"providers": {
            "claude": {"enabled":True,"mode":"api",
                       "api_key":"${ANTHROPIC_API_KEY}",
                       "model":"claude-sonnet-4-5-20250929"},
            "gemini": {"enabled":True,"mode":"api",
                       "api_key":"${GOOGLE_API_KEY}",
                       "model":"gemini-2.5-pro"},
            "gpt":    {"enabled":True,"mode":"api",
                       "api_key":"${OPENAI_API_KEY}",
                       "model":"gpt-4.1"},
        }, "debate_rounds": 3, "prompts": {}}

    if args.rounds:  cfg["debate_rounds"] = min(args.rounds, 5)
    if args.output:  cfg["output_dir"] = args.output

    orc = Orchestrator(cfg, args.query,
                       deep_research=args.deep_research,
                       role_set=args.role_set)
    asyncio.run(orc.run(skip_clarify=args.no_clarify,
                        skip_extra=args.no_extra))


if __name__ == "__main__":
    main()
