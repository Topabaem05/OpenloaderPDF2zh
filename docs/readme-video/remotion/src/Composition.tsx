import {
  AbsoluteFill,
  Img,
  Sequence,
  interpolate,
  staticFile,
  spring,
  useCurrentFrame,
} from "remotion";
import React from "react";

type ParseMetric = {
  run: string;
  parseSeconds: number;
  pages: number;
  source: "legacy" | "pretext" | "mixed";
  note: string;
  speedClass: "fast" | "neutral" | "slow";
};

type Bubble = {
  start: number;
  text: string;
  x: number;
  y: number;
  align: "left" | "right";
};

const assets = {
  ui: staticFile("openpdf2zh-ui-current.png"),
};

const palette = {
  backgroundStart: "#000212",
  backgroundEnd: "#070c21",
  card: "rgba(255, 255, 255, 0.94)",
  cardBorder: "rgba(255, 255, 255, 0.18)",
  text: "#f5f7ff",
  ink: "#17253f",
  muted: "#a3b1c8",
  accent: "#3d82ff",
  accentStrong: "#0f5ce0",
  success: "#2dd4bf",
  warn: "#ffd166",
};

const parseData: ParseMetric[] = [
  {
    run: "legacy quickmt",
    parseSeconds: 1,
    pages: 12,
    source: "legacy",
    note: "PDF2ZH 기본 모드",
    speedClass: "fast",
  },
  {
    run: "legacy nllb",
    parseSeconds: 2,
    pages: 12,
    source: "legacy",
    note: "번역기 전환 테스트",
    speedClass: "neutral",
  },
  {
    run: "pretext v1",
    parseSeconds: 5,
    pages: 7,
    source: "pretext",
    note: "백테스트 재실행",
    speedClass: "slow",
  },
  {
    run: "pretext v2",
    parseSeconds: 5,
    pages: 7,
    source: "pretext",
    note: "렌더 파이프라인 안정화",
    speedClass: "slow",
  },
  {
    run: "pretext v3",
    parseSeconds: 6,
    pages: 7,
    source: "pretext",
    note: "확장 실험",
    speedClass: "slow",
  },
];

const legacyRuns = parseData.filter((item) => item.source !== "pretext");
const pretextRuns = parseData.filter((item) => item.source === "pretext");

const maxParseSeconds = Math.max(...parseData.map((item) => item.parseSeconds));
const bestParseSeconds = Math.min(...parseData.map((item) => item.parseSeconds));
const avgLegacyParse =
  legacyRuns.reduce((sum, item) => sum + item.parseSeconds, 0) / legacyRuns.length;
const avgPretextParse =
  pretextRuns.reduce((sum, item) => sum + item.parseSeconds, 0) / pretextRuns.length;

const clamp = (value: number, min: number, max: number) =>
  Math.max(min, Math.min(max, value));

const springIn = (frame: number, startFrame: number): number =>
  spring({
    frame: frame - startFrame,
    fps: 30,
    config: {
      damping: 12,
      mass: 0.75,
      stiffness: 110,
      overshootClamping: false,
    },
    from: 0,
    to: 1,
  });

const reveal = (frame: number, start: number, duration: number): number =>
  interpolate(
    clamp((frame - start) / duration, 0, 1),
    [0, 1],
    [0, 1],
    {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    },
  );

const GlassPanel: React.FC<{
  children: React.ReactNode;
  top: number;
  left: number;
  width: number;
  height?: number;
  frame: number;
  delay: number;
  zIndex?: number;
}> = ({ children, top, left, width, height, frame, delay, zIndex = 1 }) => {
  const inValue = springIn(frame, delay);

  return (
    <div
      style={{
        position: "absolute",
        top,
        left,
        width,
        height: height ?? "auto",
        padding: "24px",
        borderRadius: 26,
        background: palette.card,
        border: `1px solid ${palette.cardBorder}`,
        boxShadow: "0 22px 64px rgba(5, 8, 25, 0.45)",
        transform: `translateY(${interpolate(inValue, [0, 0.8, 1], [14, 0, 0])}px) scale(${interpolate(
          inValue,
          [0, 1],
          [0.99, 1],
        )})`,
        opacity: inValue,
        zIndex,
      }}
    >
      {children}
    </div>
  );
};

const Kicker = ({ text, frame, delay }: { text: string; frame: number; delay: number }) => {
  const revealValue = reveal(frame, delay, 12);

  return (
    <div
      style={{
        position: "absolute",
        top: 34,
        left: 52,
        zIndex: 10,
        color: "rgba(255,255,255,0.78)",
        letterSpacing: 2,
        fontSize: 18,
        fontWeight: 600,
        textTransform: "uppercase",
        opacity: revealValue,
      }}
    >
      {text}
    </div>
  );
};

const H1 = ({ children }: { children: React.ReactNode }) => (
  <div
    style={{
      fontSize: 56,
      color: palette.text,
      letterSpacing: -1.2,
      fontWeight: 800,
      lineHeight: 1.04,
    }}
  >
    {children}
  </div>
);

const Paragraph = ({
  children,
  small = false,
}: {
  children: React.ReactNode;
  small?: boolean;
}) => (
  <div
    style={{
      marginTop: 14,
      color: "rgba(255,255,255,0.84)",
      fontSize: small ? 28 : 32,
      fontWeight: small ? 500 : 600,
      lineHeight: 1.4,
    }}
  >
    {children}
  </div>
);

const MetricBar: React.FC<{
  title: string;
  value: number;
  max: number;
  tone: "fast" | "neutral" | "slow";
  rank: string;
  frame: number;
  delay: number;
  detail: string;
}> = ({ title, value, max, tone, rank, frame, delay, detail }) => {
  const grow = springIn(frame, delay);
  const ratio = (value / max) * 100;
  const barColor =
    tone === "fast"
      ? palette.success
      : tone === "neutral"
        ? palette.warn
        : "#ef4444";

  return (
    <div
      style={{
        marginBottom: 16,
        opacity: reveal(frame, delay, 10),
        transform: `translateX(${interpolate(grow, [0, 1], [18, 0])}px)`,
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          color: "#0f1933",
          fontWeight: 700,
          fontSize: 24,
        }}
      >
        <span>{title}</span>
        <span style={{ color: palette.muted }}>{rank}</span>
      </div>
      <div
        style={{
          marginTop: 8,
          height: 14,
          borderRadius: 999,
          background: "rgba(15, 25, 45, 0.12)",
          overflow: "hidden",
        }}
      >
        <div
          style={{
            height: "100%",
            width: `${ratio}%`,
            background: barColor,
            boxShadow: `0 0 10px ${barColor}`,
            borderRadius: 999,
          }}
        />
      </div>
      <div style={{ marginTop: 6, color: palette.ink, fontWeight: 600, fontSize: 18 }}>{detail}</div>
    </div>
  );
};

const UiFrame = ({ frame, delay }: { frame: number; delay: number }) => {
  const float = interpolate(springIn(frame, delay), [0, 1], [6, 0]);
  return (
    <div
      style={{
        position: "absolute",
        left: "50%",
        top: 54,
        width: 1140,
        height: 1018,
        boxSizing: "border-box",
        transform: `translate(-50%, ${float}px)`,
        borderRadius: 28,
        padding: 14,
        background: "rgba(255,255,255,0.96)",
        boxShadow: "0 35px 95px rgba(3, 6, 20, 0.55)",
        border: `1px solid ${palette.cardBorder}`,
        overflow: "hidden",
      }}
    >
      <Img
        src={assets.ui}
        style={{
          width: "100%",
          height: "100%",
          objectFit: "contain",
          objectPosition: "top center",
          borderRadius: 20,
        }}
      />
    </div>
  );
};

const FloatingBubble = ({ frame, bubble }: { frame: number; bubble: Bubble }) => {
  const progress = springIn(frame, bubble.start);
  return (
    <div
      style={{
        position: "absolute",
        left: bubble.x,
        top: bubble.y,
        padding: "12px 18px",
        borderRadius: 16,
        fontSize: 24,
        fontWeight: 700,
        color: bubble.align === "left" ? palette.text : "#15203a",
        background:
          bubble.align === "left" ? "rgba(13, 27, 52, 0.92)" : "rgba(255,255,255,0.96)",
        border: `1px solid ${palette.cardBorder}`,
        boxShadow: "0 14px 34px rgba(6,10,20,0.25)",
        opacity: reveal(frame, bubble.start - 2, 10),
        transform: `translateY(${interpolate(progress, [0, 1], [10, 0])}px)`,
        zIndex: 4,
      }}
    >
      {bubble.text}
    </div>
  );
};

export const MyComposition = () => {
  const frame = useCurrentFrame();
  const introProgress = reveal(frame, 0, 18);

  return (
    <AbsoluteFill
      style={{
        background: `linear-gradient(155deg, ${palette.backgroundStart} 0%, ${palette.backgroundEnd} 58%, #060f24 100%)`,
      }}
    >
      <div
        style={{
          position: "absolute",
          inset: 0,
          backgroundImage:
            "radial-gradient(circle at 14% 16%, rgba(61,130,255,0.16) 0, transparent 430px), radial-gradient(circle at 88% 86%, rgba(45,212,191,0.18) 0, transparent 380px)",
        }}
      />

      <Sequence from={0} durationInFrames={120}>
        <div
          style={{
            position: "absolute",
            inset: 0,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            opacity: introProgress,
            transform: `translateY(${interpolate(introProgress, [0, 1], [12, 0])}px)`,
            textAlign: "left",
            paddingLeft: 72,
          }}
        >
          <div style={{ width: 1120 }}>
            <div
              style={{
                display: "inline-block",
                padding: "12px 16px",
                borderRadius: 999,
                background: "rgba(13, 27, 52, 0.7)",
                border: "1px solid rgba(255,255,255,0.16)",
                color: "#cfe0ff",
                fontSize: 20,
                fontWeight: 700,
                letterSpacing: 1,
              }}
            >
              Gradio-first walkthrough
            </div>
            <H1>파싱 속도로 시작되는 UX</H1>
            <Paragraph>PDF 업로드 다음, 가장 먼저 확인해야 하는 건 번역 품질보다 파싱 속도입니다.</Paragraph>
            <Paragraph small={false}>백테스트 로그를 바탕으로 한 그레이스풀한 파싱 비교</Paragraph>
            <div
              style={{
                marginTop: 28,
                display: "inline-flex",
                alignItems: "center",
                gap: 10,
                padding: "14px 18px",
                borderRadius: 14,
                background: "rgba(255,255,255,0.9)",
                color: palette.ink,
                fontSize: 26,
                fontWeight: 700,
              }}
            >
              <span
                style={{
                  display: "inline-block",
                  width: 11,
                  height: 11,
                  borderRadius: 999,
                  background: palette.success,
                }}
              />
              파싱 단축이 체감 속도를 바꿉니다
            </div>
          </div>
        </div>
      </Sequence>

      <Sequence from={120} durationInFrames={140}>
        <Kicker text="01. 파싱 백테스트" frame={frame - 120} delay={120} />
        <UiFrame frame={frame - 120} delay={132} />
        <GlassPanel top={156} left={110} width={460} frame={frame - 120} delay={150}>
          <div style={{ color: palette.ink }}>
            <div
              style={{
                fontSize: 16,
                color: palette.accentStrong,
                fontWeight: 800,
                letterSpacing: 1.4,
              }}
            >
              목표: 파싱 가시성
            </div>
            <div style={{ marginTop: 6, fontSize: 42, fontWeight: 800, color: "#0f1c35" }}>
              Backtest
            </div>
            <div style={{ marginTop: 8, fontSize: 21, color: "#274067", lineHeight: 1.4 }}>
              같은 PDF에서 여러 설정으로 돌린 파싱 속도와 처리율을 비교합니다.
            </div>
            <div
              style={{
                marginTop: 12,
                borderRadius: 12,
                padding: "10px 14px",
                fontSize: 20,
                fontWeight: 700,
                color: palette.success,
                background: "rgba(45,212,191,0.1)",
                display: "inline-block",
              }}
            >
              베스트: {bestParseSeconds.toFixed(1)}초
              <br />
              (PDF2ZH legacy quickmt 기준)
            </div>
          </div>
        </GlassPanel>
      </Sequence>

      <Sequence from={260} durationInFrames={130}>
        <Kicker text="파싱 로그 기반 비교" frame={frame - 260} delay={260} />
        <UiFrame frame={frame - 260} delay={262} />

        <GlassPanel top={176} left={96} width={640} frame={frame - 260} delay={274}>
          <div style={{ color: palette.ink }}>
            <div style={{ fontSize: 44, fontWeight: 800, color: "#0f1f3a" }}>파싱 메트릭</div>
            <div style={{ marginTop: 10, marginBottom: 18, color: palette.ink, fontSize: 18 }}>
              비교 대상: PDF2ZH legacy 2종 vs pretext 3회
            </div>
            {parseData.map((item, index) => (
              <MetricBar
                key={item.run}
                title={item.run}
                value={item.parseSeconds}
                max={maxParseSeconds}
                tone={item.speedClass}
                rank={`${item.parseSeconds.toFixed(1)}초 / ${item.pages}페이지`}
                frame={frame - 260}
                delay={282 + index * 15}
                detail={`${item.note} / 페이지당 ${(item.parseSeconds / item.pages).toFixed(2)}초`}
              />
            ))}
          </div>
        </GlassPanel>

        <GlassPanel top={186} left={1068} width={300} frame={frame - 260} delay={325} zIndex={2}>
          <div style={{ color: palette.ink, fontWeight: 700, lineHeight: 1.45 }}>
            <div style={{ fontSize: 18, color: palette.muted }}>요약</div>
            <div style={{ marginTop: 8, fontSize: 24 }}>legacy avg {avgLegacyParse.toFixed(1)}초</div>
            <div style={{ marginTop: 10, fontSize: 24 }}>pretext avg {avgPretextParse.toFixed(1)}초</div>
            <div
              style={{
                marginTop: 14,
                fontSize: 22,
                color: palette.success,
                padding: "10px 12px",
                background: "rgba(45, 212, 191, 0.14)",
                borderRadius: 11,
              }}
            >
              파싱이 빠른 경로 우선
            </div>
          </div>
        </GlassPanel>
      </Sequence>

      <Sequence from={390} durationInFrames={90}>
        <Kicker text="02. Gradio 조작" frame={frame - 390} delay={390} />
        <UiFrame frame={frame - 390} delay={398} />
        <FloatingBubble
          frame={frame - 390}
          bubble={{ start: 408, x: 108, y: 248, text: "PDF 업로드", align: "left" }}
        />
        <FloatingBubble
          frame={frame - 390}
          bubble={{
            start: 432,
            x: 108,
            y: 360,
            text: "서비스/언어 옵션",
            align: "left",
          }}
        />
        <FloatingBubble
          frame={frame - 390}
          bubble={{ start: 456, x: 108, y: 482, text: "페이지 범위", align: "left" }}
        />
      </Sequence>

      <Sequence from={480} durationInFrames={90}>
        <Kicker text="03. 번역 실행" frame={frame - 480} delay={480} />
        <UiFrame frame={frame - 480} delay={486} />
        <FloatingBubble
          frame={frame - 480}
          bubble={{ start: 496, x: 118, y: 760, text: "Run/Translate", align: "left" }}
        />
        <FloatingBubble
          frame={frame - 480}
          bubble={{
            start: 514,
            x: 116,
            y: 840,
            text: "진행 로그: 파싱 → 번역 → 렌더",
            align: "left",
          }}
        />
      </Sequence>

      <Sequence from={570} durationInFrames={90}>
        <Kicker text="04. 결과 확인 후 다운로드" frame={frame - 570} delay={570} />
        <UiFrame frame={frame - 570} delay={576} />
        <FloatingBubble
          frame={frame - 570}
          bubble={{ start: 590, x: 112, y: 276, text: "번역 미리보기", align: "left" }}
        />
        <FloatingBubble
          frame={frame - 570}
          bubble={{ start: 610, x: 112, y: 830, text: "파일 다운로드", align: "left" }}
        />
        <GlassPanel top={690} left={1040} width={320} frame={frame - 570} delay={620} zIndex={3}>
          <div style={{ color: palette.ink, fontWeight: 700, lineHeight: 1.35, fontSize: 22 }}>
            핵심 정리
            <div style={{ marginTop: 10, color: palette.accentStrong }}>파싱 단계는 먼저 확인.</div>
            <div style={{ marginTop: 4 }}>조작은 업로드 → 설정 → 실행 → 다운로드.</div>
          </div>
        </GlassPanel>
      </Sequence>
    </AbsoluteFill>
  );
};
