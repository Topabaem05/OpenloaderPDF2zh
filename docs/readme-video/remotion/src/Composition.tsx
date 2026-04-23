import {
  AbsoluteFill,
  Img,
  Sequence,
  spring,
  staticFile,
  useCurrentFrame,
  interpolate,
} from "remotion";
import React from "react";

const assets = {
  ui: staticFile("openpdf2zh-ui-current.png"),
  controls: staticFile("openpdf2zh-service-dropdown.png"),
  translated: staticFile("openpdf2zh-translated-page.png"),
};

const palette = {
  bg1: "#f8f4ee",
  bg2: "#eff4ff",
  ink: "#14203a",
  accent: "#4f63ff",
};

const pulse = (
  frame: number,
  startFrame: number,
  stiffness = 150,
): number => {
  if (frame <= startFrame) {
    return 0;
  }

  return spring({
    frame: frame - startFrame,
    fps: 30,
    config: {
      damping: 13,
      mass: 0.65,
      stiffness,
    },
    from: 0,
    to: 1,
  });
};

const clamp = (value: number, min: number, max: number) =>
  Math.max(min, Math.min(max, value));

const sceneReveal = (frame: number, start: number, length: number): number => {
  const normalized = clamp((frame - start) / length, 0, 1);
  return interpolate(normalized, [0, 0.45, 1], [0, 1, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
};

const Bubble = ({
  frame,
  start,
  text,
  x,
  y,
  accent,
}: {
  frame: number;
  start: number;
  text: string;
  x: number;
  y: number;
  accent?: boolean;
}) => {
  const bounce = pulse(frame, start, 180);
  const opacity = sceneReveal(frame, start - 2, 12);
  const yOffset = interpolate(bounce, [0, 0.45, 1], [24, -4, 0]);

  return (
    <div
      style={{
        position: "absolute",
        left: x,
        top: y,
        transform: `translateY(${yOffset}px) scale(${1 + bounce * 0.06})`,
        transformOrigin: "center bottom",
        borderRadius: 24,
        padding: "22px 24px",
        maxWidth: 390,
        background: accent
          ? "rgba(255, 255, 255, 0.94)"
          : "rgba(20, 32, 58, 0.9)",
        color: accent ? "#14203a" : "#f6f8fb",
        fontSize: 34,
        fontWeight: 800,
        letterSpacing: -0.3,
        lineHeight: 1.2,
        boxShadow: accent
          ? "0 16px 44px rgba(20, 32, 58, 0.14)"
          : "0 16px 40px rgba(10, 16, 30, 0.25)",
        opacity,
        zIndex: 4,
      }}
    >
      {text}
      <div
        style={{
          position: "absolute",
          width: 16,
          height: 16,
          borderRadius: 99,
          background: accent ? palette.accent : "#ffd66d",
          right: 18,
          bottom: -8,
          transform: `rotate(${bounce * 18}deg)`,
        }}
      />
    </div>
  );
};

const SceneCard = ({
  frame,
  shot,
  label,
  title,
  description,
  bubbles,
  x = 0,
}: {
  frame: number;
  shot: keyof typeof assets;
  label: string;
  title: string;
  description: string;
  bubbles: Array<{
    text: string;
    x: number;
    y: number;
    accent?: boolean;
    delay: number;
  }>;
  x?: number;
}) => {
  const inShot = pulse(frame, 2, 110);
  const zoom = interpolate(inShot, [0, 0.6, 1], [1.06, 0.99, 1]);
  const moveX = interpolate(inShot, [0, 1], [x - 60, x]);

  return (
    <AbsoluteFill
      style={{
        opacity: sceneReveal(frame, 0, 14),
        overflow: "hidden",
      }}
    >
      <div
        style={{
          position: "absolute",
          left: moveX,
          top: 86,
          right: 32,
          bottom: 40,
          borderRadius: 32,
          background: "rgba(255,255,255,0.88)",
          boxShadow: "0 42px 110px rgba(16, 24, 44, 0.2)",
          border: "1px solid rgba(255,255,255,0.8)",
          overflow: "hidden",
        }}
      >
        <Img
          src={assets[shot]}
          style={{
            width: "100%",
            height: "100%",
            objectFit: "cover",
            transform: `scale(${zoom})`,
            transformOrigin: "center center",
          }}
        />
      </div>

      <div
        style={{
          position: "absolute",
          top: 34,
          left: 56,
          right: 56,
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          zIndex: 3,
          opacity: sceneReveal(frame, 2, 12),
          transform: `translateY(${interpolate(inShot, [0, 1], [12, 0])}px)`,
        }}
      >
        <div
          style={{
            borderRadius: 999,
            padding: "14px 18px",
            background: "rgba(14, 25, 45, 0.86)",
            color: "white",
            fontSize: 24,
            fontWeight: 800,
            letterSpacing: 0.2,
          }}
        >
          {label}
        </div>
        <div
          style={{
            borderRadius: 999,
            padding: "14px 18px",
            background: "rgba(79, 99, 255, 0.16)",
            color: palette.accent,
            fontSize: 20,
            fontWeight: 700,
          }}
        >
          OpenPDF2ZH
        </div>
      </div>

      <div
        style={{
          position: "absolute",
          left: 56,
          top: 132,
          color: palette.ink,
          zIndex: 3,
          opacity: sceneReveal(frame, 6, 20),
          textShadow: "0 4px 14px rgba(255,255,255,0.65)",
        }}
      >
        <div style={{ fontSize: 26, fontWeight: 700, opacity: 0.78 }}>{title}</div>
        <div style={{ fontSize: 56, lineHeight: 1.05, fontWeight: 800, maxWidth: 760 }}>
          {description}
        </div>
      </div>

      {bubbles.map((bubble, index) => (
        <Bubble
          key={`${bubble.text}-${index}`}
          frame={frame}
          start={bubble.delay}
          text={bubble.text}
          x={bubble.x}
          y={bubble.y}
          accent={bubble.accent}
        />
      ))}
    </AbsoluteFill>
  );
};

export const MyComposition = () => {
  const frame = useCurrentFrame();
  const intro = sceneReveal(frame, 0, 20);

  return (
    <AbsoluteFill style={{ background: `linear-gradient(140deg, ${palette.bg1}, ${palette.bg2})` }}>
      <div
        style={{
          position: "absolute",
          inset: 0,
          backgroundImage: `radial-gradient(circle at 13% 20%, rgba(79, 99, 255, 0.18) 0, transparent 420px), radial-gradient(circle at 84% 78%, rgba(255, 212, 106, 0.24) 0, transparent 360px)`,
        }}
      />

      <Sequence from={0} durationInFrames={120}>
        <AbsoluteFill>
          <div
            style={{
              position: "absolute",
              left: "calc(50% - 560px)",
              top: 280,
              width: 1120,
              display: "flex",
              flexDirection: "column",
              gap: 22,
              alignItems: "center",
              textAlign: "center",
              opacity: interpolate(intro, [0, 0.2, 1], [0, 1, 1]),
              transform: `translateY(${interpolate(intro, [0, 0.5, 1], [30, -6, 0])}px)`,
            }}
          >
            <div
              style={{
                fontSize: 26,
                color: "#4e5a6f",
                letterSpacing: 1.3,
                fontWeight: 800,
                textTransform: "uppercase",
              }}
            >
              Gradio usage walkthrough
            </div>
            <div
              style={{
                fontSize: 90,
                color: "#15203a",
                fontWeight: 900,
                lineHeight: 1,
                letterSpacing: -1.8,
              }}
            >
              Playful UI guide for your PDF translator
            </div>
            <div
              style={{
                marginTop: 6,
                maxWidth: 720,
                color: "#314159",
                fontSize: 32,
                lineHeight: 1.4,
                opacity: 0.94,
              }}
            >
              Bounce through the main interactions: upload file, set options, translate, then
              review output.
            </div>
          </div>
          <div
            style={{
              position: "absolute",
              left: "50%",
              top: 520,
              transform: `translateX(-50%) translateY(${interpolate(pulse(frame, 12, 120), [0, 1], [0, -12])}px)`,
              opacity: sceneReveal(frame, 8, 20),
              color: palette.accent,
              fontSize: 36,
              fontWeight: 900,
              letterSpacing: -0.6,
              background: "rgba(255, 255, 255, 0.78)",
              padding: "14px 26px",
              borderRadius: 999,
              border: "1px solid rgba(255,255,255,0.8)",
            }}
          >
            클릭 가능한 곳만 따라가세요
          </div>

          <SceneCard
            frame={frame}
            shot="ui"
            label="01 / UPLOAD"
            title="Step 1"
            description="Upload your PDF to unlock translation actions"
            bubbles={[
              {
                text: "Drop or select a PDF file",
                x: 520,
                y: 310,
                accent: false,
                delay: 30,
              },
              {
                text: "Input area expands with bounce",
                x: 760,
                y: 760,
                accent: true,
                delay: 62,
              },
            ]}
            x={0}
          />
        </AbsoluteFill>
      </Sequence>

      <Sequence from={120} durationInFrames={100}>
        <SceneCard
          frame={frame - 120}
          shot="controls"
          label="02 / SETUP"
          title="Step 2"
          description="Choose service, language, and page options"
          bubbles={[
            {
              text: "Pick service stack",
              x: 700,
              y: 290,
              accent: false,
              delay: 130,
            },
            {
              text: "Set source and target languages",
              x: 1160,
              y: 320,
              accent: true,
              delay: 152,
            },
            {
              text: "Use page range when needed",
              x: 1180,
              y: 710,
              accent: false,
              delay: 178,
            },
          ]}
          x={-30}
        />
      </Sequence>

      <Sequence from={220} durationInFrames={110}>
        <AbsoluteFill>
          <div
            style={{
              position: "absolute",
              left: 48,
              top: 48,
              right: 48,
              height: 980,
              borderRadius: 28,
              overflow: "hidden",
              background: "rgba(255, 255, 255, 0.94)",
              boxShadow: "0 38px 110px rgba(14, 17, 29, 0.2)",
            }}
          >
            <Img
              src={assets.ui}
              style={{ width: "100%", height: "100%", objectFit: "cover" }}
            />
          </div>

          <div
            style={{
              position: "absolute",
              left: 760,
              top: 220,
              fontSize: 52,
              fontWeight: 900,
              color: "#0f1833",
              textShadow: "0 10px 24px rgba(255,255,255,0.7)",
            }}
          >
            Hit <span style={{ color: palette.accent }}>Translate</span>
            <br />
            to start processing
          </div>

          <Bubble
            frame={frame - 220}
            start={226}
            text="Tap Translate"
            x={560}
            y={760}
            accent
          />
          <Bubble
            frame={frame - 220}
            start={246}
            text="Progress appears immediately below"
            x={980}
            y={850}
          />

          <div
            style={{
              position: "absolute",
              left: 620,
              top: 760,
              width: 680,
              height: 6,
              background: "linear-gradient(90deg, #4f63ff, #ffd66d)",
              boxShadow: "0 0 18px rgba(79, 99, 255, 0.35)",
              transform: `scaleX(${sceneReveal(frame - 220, 258, 20)})`,
              transformOrigin: "left center",
              borderRadius: 3,
            }}
          />
        </AbsoluteFill>
      </Sequence>

      <Sequence from={330} durationInFrames={120}>
        <AbsoluteFill>
          <div
            style={{
              position: "absolute",
              inset: 52,
              borderRadius: 28,
              overflow: "hidden",
              background: "rgba(255,255,255,0.95)",
              boxShadow: "0 34px 120px rgba(10, 16, 28, 0.18)",
            }}
          >
            <Img
              src={assets.ui}
              style={{
                position: "absolute",
                inset: 0,
                width: "100%",
                height: "100%",
                objectFit: "cover",
                opacity: interpolate(sceneReveal(frame - 330, 0, 20), [0, 1], [0.94, 1]),
              }}
            />
            <div
              style={{
                position: "absolute",
                left: 980,
                top: 154,
                width: 390,
                height: 780,
                background: "rgba(255,255,255,0.93)",
                borderRadius: 16,
                overflow: "hidden",
                border: `4px solid ${palette.accent}`,
                boxShadow: "0 20px 40px rgba(20, 32, 58, 0.2)",
              }}
            >
              <Img
                src={assets.translated}
                style={{
                  width: "100%",
                  height: "100%",
                  objectFit: "contain",
                  transform: `scale(${1 + sceneReveal(frame - 330, 8, 28) * 0.045})`,
                  transformOrigin: "center center",
                }}
              />
            </div>
          </div>

          <div
            style={{
              position: "absolute",
              left: 72,
              top: 180,
              color: "#18294a",
              fontSize: 58,
              fontWeight: 900,
              textShadow: "0 4px 14px rgba(255,255,255,0.55)",
            }}
          >
            Review translated preview, then download
          </div>
          <div
            style={{
              position: "absolute",
              left: 72,
              top: 255,
              fontSize: 30,
              color: "#36466a",
              fontWeight: 700,
              maxWidth: 760,
            }}
          >
            Inspect page-by-page changes in the result viewer.
          </div>

          <Bubble
            frame={frame - 330}
            start={346}
            text="Check translated page"
            x={760}
            y={260}
            accent
          />
          <Bubble
            frame={frame - 330}
            start={372}
            text="Use arrows to move pages"
            x={760}
            y={730}
          />
          <Bubble
            frame={frame - 330}
            start={400}
            text="Download generated files"
            x={760}
            y={915}
            accent
          />
        </AbsoluteFill>
      </Sequence>
    </AbsoluteFill>
  );
};
