import React from "react";
import {
  AbsoluteFill,
  Sequence,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

const W = 1920;
const H = 1080;
const FRAME_RATE = 30;

const sections = [
  {id: "01", title: "OpenPDF2ZH Workbench", subtitle: "Translate PDFs and preserve layout in one workbench"},
  {id: "02", title: "Parsing Backtest", subtitle: "The first step finishes faster than PDF2zh"},
  {id: "03", title: "Pipeline", subtitle: "From upload to translated PDF in one flow"},
  {id: "04", title: "Project Structure", subtitle: "A Python-first structure connecting Gradio and FastAPI"},
  {id: "05", title: "Quick Start", subtitle: "Run locally with Docker"},
  {id: "06", title: "Gradio UI", subtitle: "Upload, configure, run, and download"},
  {id: "07", title: "Strengths", subtitle: "The MVP has a clear product flow"},
  {id: "08", title: "Next Steps", subtitle: "Keep adding README assets, sample outputs, and benchmarks"},
  {id: "09", title: "Wrap Up", subtitle: "clone, run, translate"},
];

const sectionDurations = [126, 144, 126, 114, 114, 168, 114, 108, 96];

const sumBefore = (index: number) =>
  sectionDurations.slice(0, index).reduce((total, duration) => total + duration, 0);

const clamp = (value: number, min = 0, max = 1) => Math.max(min, Math.min(max, value));

const ease = (frame: number, start: number, duration = 24) =>
  interpolate(clamp((frame - start) / duration), [0, 1], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

const s = (frame: number, start: number, damping = 18) =>
  spring({
    frame: Math.max(0, frame - start),
    fps: FRAME_RATE,
    config: {damping, stiffness: 92, mass: 0.75},
  });

const FadeUp = ({
  frame,
  start,
  children,
  y = 34,
  scale = 0.98,
}: {
  frame: number;
  start: number;
  children: React.ReactNode;
  y?: number;
  scale?: number;
}) => {
  const p = clamp(s(frame, start));
  return (
    <g
      opacity={p}
      transform={`translate(0 ${interpolate(p, [0, 1], [y, 0])}) scale(${interpolate(p, [0, 1], [scale, 1])})`}
    >
      {children}
    </g>
  );
};

const Shell = ({
  frame,
  index,
  children,
}: {
  frame: number;
  index: number;
  children: React.ReactNode;
}) => {
  const meta = sections[index];
  const shell = clamp(s(frame, 0, 22));
  return (
    <AbsoluteFill style={{background: "#f5f5f7"}}>
      <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H}>
        <defs>
          <linearGradient id={`bg-${index}`} x1="0" x2="1" y1="0" y2="1">
            <stop offset="0" stopColor="#fbfbfd" />
            <stop offset="0.52" stopColor="#f5f5f7" />
            <stop offset="1" stopColor="#ebedf0" />
          </linearGradient>
          <filter id={`soft-${index}`} x="-20%" y="-20%" width="140%" height="140%">
            <feDropShadow dx="0" dy="28" stdDeviation="28" floodColor="#000" floodOpacity="0.13" />
          </filter>
        </defs>
        <rect width={W} height={H} fill={`url(#bg-${index})`} />
        <g opacity={shell}>
          <text x={96} y={84} fontSize={25} fontWeight={700} fill="#151515">
            {meta.id}
          </text>
          <text x={146} y={84} fontSize={25} fontWeight={650} fill="#151515">
            {meta.title}
          </text>
          <text x={146} y={118} fontSize={17} fill="#6e6e73">
            {meta.subtitle}
          </text>
          <g transform="translate(1590 72)">
            {sections.map((item, i) => (
              <circle
                key={item.id}
                cx={i * 24}
                cy={0}
                r={i === index ? 5.6 : 3.4}
                fill={i === index ? "#111" : "#c7c7cc"}
              />
            ))}
          </g>
        </g>
        {children}
      </svg>
    </AbsoluteFill>
  );
};

const TitleBlock = ({frame, title, subtitle, y = 245}: {frame: number; title: string; subtitle: string; y?: number}) => (
  <FadeUp frame={frame} start={4}>
    <text x={W / 2} y={y} textAnchor="middle" fontSize={92} fontWeight={860} fill="#050505">
      {title}
    </text>
    <text x={W / 2} y={y + 70} textAnchor="middle" fontSize={30} fontWeight={520} fill="#6e6e73">
      {subtitle}
    </text>
  </FadeUp>
);

const DocumentCard = ({x, y, label, color, progress = 1}: {x: number; y: number; label: string; color: string; progress?: number}) => (
  <g transform={`translate(${x} ${y})`}>
    <rect width={350} height={468} rx={34} fill="#fff" stroke="#dedede" filter="url(#soft-0)" />
    <path d="M 276 0 L 350 74 L 276 74 Z" fill="#f1f1f3" stroke="#dedede" />
    <rect x={42} y={48} width={82} height={42} rx={10} fill={color} />
    <text x={83} y={77} textAnchor="middle" fontSize={18} fontWeight={800} fill="#fff">
      PDF
    </text>
    <text x={42} y={150} fontSize={32} fontWeight={760} fill="#111">
      {label}
    </text>
    {[0, 1, 2, 3].map((line) => (
      <rect key={line} x={42} y={196 + line * 40} width={210 + line * 18} height={10} rx={5} fill="#d6d6d9" />
    ))}
    <rect x={42} y={392} width={266} height={18} rx={9} fill="#e8e8ed" />
    <rect x={42} y={392} width={266 * progress} height={18} rx={9} fill={color} />
  </g>
);

const Section01 = ({frame}: {frame: number}) => {
  const arrow = ease(frame, 46, 40);
  return (
    <Shell frame={frame} index={0}>
      <TitleBlock frame={frame} title="Workbench for PDFs" subtitle="Reduce parsing wait time before translation starts" />
      <FadeUp frame={frame} start={24}>
        <DocumentCard x={430} y={410} label="source.pdf" color="#111" />
      </FadeUp>
      <g opacity={arrow} transform={`translate(${interpolate(arrow, [0, 1], [850, 908])} 622)`}>
        <line x1={0} y1={0} x2={170} y2={0} stroke="#111" strokeWidth={6} strokeLinecap="round" />
        <path d="M 150 -22 L 180 0 L 150 22" fill="none" stroke="#111" strokeWidth={6} strokeLinecap="round" strokeLinejoin="round" />
      </g>
      <FadeUp frame={frame} start={58}>
        <DocumentCard x={1160} y={410} label="translated.pdf" color="#0071e3" progress={0.92} />
      </FadeUp>
      <FadeUp frame={frame} start={82}>
        <text x={W / 2} y={915} textAnchor="middle" fontSize={44} fontWeight={820} fill="#111">
          parse fast. keep layout. finish clean.
        </text>
      </FadeUp>
    </Shell>
  );
};

const VerticalBar = ({
  x,
  baseline,
  maxHeight,
  value,
  color,
  label,
  time,
  delay,
  frame,
}: {
  x: number;
  baseline: number;
  maxHeight: number;
  value: number;
  color: string;
  label: string;
  time: string;
  delay: number;
  frame: number;
}) => {
  const p = ease(frame, delay, 28);
  const height = maxHeight * value * p;
  return (
    <g>
      <rect x={x - 78} y={baseline - maxHeight} width={156} height={maxHeight} rx={30} fill="#e5e5ea" />
      <rect x={x - 78} y={baseline - height} width={156} height={height} rx={30} fill={color} />
      <text x={x} y={baseline - height - 30} textAnchor="middle" fontSize={40} fontWeight={860} fill={color} opacity={p}>
        {time}
      </text>
      <text x={x} y={baseline + 52} textAnchor="middle" fontSize={27} fontWeight={760} fill="#111">
      {label}
      </text>
    </g>
  );
};

const Section02 = ({frame}: {frame: number}) => {
  const open = ease(frame, 36, 36);
  const pdf2zh = ease(frame, 58, 46);
  const number = Math.round(interpolate(open, [0, 1], [0, 12]));
  return (
    <Shell frame={frame} index={1}>
      <TitleBlock frame={frame} title="Parsing first." subtitle="Backtest data makes the gap visible" y={220} />
      <FadeUp frame={frame} start={24}>
        <rect x={270} y={375} width={1380} height={560} rx={44} fill="#fff" filter="url(#soft-1)" />
        <text x={350} y={475} fontSize={28} fill="#6e6e73">
          Local parsing backtest snapshot
        </text>
        <text x={350} y={560} fontSize={86} fontWeight={880} fill="#111">
          {number} pages parsed in about 1s
        </text>
        <text x={350} y={622} fontSize={26} fill="#6e6e73">
          OpenPDF2ZH run log: 2026-04-11, phase=parse:start to phase=parse:done
        </text>
      </FadeUp>
      <FadeUp frame={frame} start={44}>
        <g>
          <line x1={690} y1={878} x2={1268} y2={878} stroke="#d2d2d7" strokeWidth={3} />
          <VerticalBar
            x={790}
            baseline={878}
            maxHeight={148}
            value={open * 0.18}
            color="#0071e3"
            label="OpenPDF2ZH"
            time="~1s / 12p"
            delay={44}
            frame={frame}
          />
          <VerticalBar
            x={1165}
            baseline={878}
            maxHeight={148}
            value={pdf2zh}
            color="#86868b"
            label="PDF2zh warm run"
            time="10.89s / 1p"
            delay={58}
            frame={frame}
          />
        </g>
      </FadeUp>
      <FadeUp frame={frame} start={94}>
        <text x={1430} y={840} textAnchor="middle" fontSize={48} fontWeight={860} fill="#111">
          less waiting.
        </text>
      </FadeUp>
    </Shell>
  );
};

const pipeline = ["Upload", "Parse", "Translate", "Layout", "PDF"];

const Section03 = ({frame}: {frame: number}) => (
  <Shell frame={frame} index={2}>
    <TitleBlock frame={frame} title="One continuous pipeline" subtitle="A single action moves through the full workflow" y={225} />
    <g transform="translate(245 575)">
      <line x1={0} y1={0} x2={1430} y2={0} stroke="#d2d2d7" strokeWidth={10} strokeLinecap="round" />
      {pipeline.map((item, i) => {
        const p = clamp(s(frame, 28 + i * 13));
        const x = i * 357;
        return (
          <g key={item} opacity={p} transform={`translate(${x} ${interpolate(p, [0, 1], [38, 0])})`}>
            <circle cx={0} cy={0} r={60} fill={i === 1 ? "#0071e3" : "#fff"} stroke="#111" strokeWidth={3} />
            <text x={0} y={13} textAnchor="middle" fontSize={38} fontWeight={820} fill={i === 1 ? "#fff" : "#111"}>
              {i + 1}
            </text>
            <text x={0} y={125} textAnchor="middle" fontSize={30} fontWeight={760} fill="#111">
              {item}
            </text>
          </g>
        );
      })}
    </g>
    <FadeUp frame={frame} start={94}>
      <text x={W / 2} y={895} textAnchor="middle" fontSize={42} fontWeight={820} fill="#111">
        Faster parsing makes the entire experience feel lighter.
      </text>
    </FadeUp>
  </Shell>
);

const Section04 = ({frame}: {frame: number}) => (
  <Shell frame={frame} index={3}>
    <TitleBlock frame={frame} title="Clear Python structure" subtitle="UI, pipeline, and services stay separated by role" y={210} />
    <FadeUp frame={frame} start={26}>
      <rect x={548} y={365} width={824} height={500} rx={38} fill="#111" filter="url(#soft-3)" />
      {["src/openpdf2zh/__main__.py", "src/openpdf2zh/ui.py", "src/openpdf2zh/pipeline.py", "services/parser_service.py", "services/render_service.py"].map((item, i) => (
        <text key={item} x={620} y={455 + i * 72} fontSize={34} fontWeight={650} fill={i === 3 ? "#7ab8ff" : "#f5f5f7"}>
          {item}
        </text>
      ))}
      <rect x={360} y={555} width={210} height={94} rx={28} fill="#fff" stroke="#d2d2d7" />
      <text x={465} y={612} textAnchor="middle" fontSize={31} fontWeight={760}>
        Gradio
      </text>
      <rect x={1350} y={555} width={210} height={94} rx={28} fill="#fff" stroke="#d2d2d7" />
      <text x={1455} y={612} textAnchor="middle" fontSize={31} fontWeight={760}>
        FastAPI
      </text>
    </FadeUp>
  </Shell>
);

const Section05 = ({frame}: {frame: number}) => (
  <Shell frame={frame} index={4}>
    <TitleBlock frame={frame} title="Run it locally" subtitle="Docker quick start" y={220} />
    <FadeUp frame={frame} start={26}>
      <rect x={348} y={375} width={1224} height={420} rx={38} fill="#171717" filter="url(#soft-4)" />
      <rect x={348} y={375} width={1224} height={72} rx={38} fill="#f5f5f7" />
      <circle cx={400} cy={411} r={10} fill="#ff5f57" />
      <circle cx={432} cy={411} r={10} fill="#ffbd2e" />
      <circle cx={464} cy={411} r={10} fill="#28c840" />
      {["cp .env.example .env", "docker compose up --build", "open http://localhost:7860/gradio"].map((line, i) => {
        const p = ease(frame, 42 + i * 16, 10);
        return (
          <text key={line} x={450} y={535 + i * 86} fontSize={42} fontWeight={620} fill="#f5f5f7" opacity={p}>
            <tspan fill="#00a7ff">$ </tspan>
            {line}
          </text>
        );
      })}
    </FadeUp>
  </Shell>
);

const Section06 = ({frame}: {frame: number}) => {
  const progress = interpolate(ease(frame, 96, 34), [0, 1], [0.08, 0.94]);
  return (
    <Shell frame={frame} index={5}>
      <TitleBlock frame={frame} title="Gradio, only the controls" subtitle="No side explanation box. Just the UI flow." y={155} />
      <FadeUp frame={frame} start={22}>
        <rect x={190} y={285} width={1540} height={670} rx={42} fill="#fff" stroke="#d2d2d7" filter="url(#soft-5)" />
        <text x={260} y={365} fontSize={34} fontWeight={820} fill="#111">
          OpenPDF2ZH
        </text>
        <rect x={260} y={430} width={350} height={390} rx={26} fill="#f7f7f9" stroke="#d2d2d7" />
        <text x={435} y={535} textAnchor="middle" fontSize={76} fontWeight={650} fill="#0071e3">
          UP
        </text>
        <text x={435} y={592} textAnchor="middle" fontSize={25} fill="#6e6e73">
          sample-benchmark.pdf
        </text>
        <rect x={298} y={740} width={274} height={56} rx={16} fill="#111" />
        <text x={435} y={776} textAnchor="middle" fontSize={23} fontWeight={760} fill="#fff">
          file selected
        </text>

        <g transform="translate(690 430)">
          {["Provider: OpenRouter", "Model: quickmt", "Target: Korean"].map((label, i) => (
            <g key={label} transform={`translate(0 ${i * 116})`}>
              <text x={0} y={0} fontSize={22} fontWeight={700} fill="#6e6e73">
                {label.split(":")[0]}
              </text>
              <rect x={0} y={22} width={380} height={62} rx={18} fill="#f7f7f9" stroke="#d2d2d7" />
              <text x={24} y={63} fontSize={25} fontWeight={680} fill="#111">
                {label.split(": ")[1]}
              </text>
            </g>
          ))}
          <rect x={0} y={370} width={380} height={70} rx={20} fill="#0071e3" />
          <text x={190} y={415} textAnchor="middle" fontSize={28} fontWeight={820} fill="#fff">
            Translate
          </text>
        </g>

        <g transform="translate(1195 430)">
          <circle cx={170} cy={132} r={94} fill="none" stroke="#e5e5ea" strokeWidth={24} />
          <path
            d="M 170 38 A 94 94 0 1 1 88 180"
            fill="none"
            stroke="#0071e3"
            strokeWidth={24}
            strokeLinecap="round"
            strokeDasharray={`${590 * progress} 590`}
          />
          <text x={170} y={146} textAnchor="middle" fontSize={42} fontWeight={820} fill="#111">
            {Math.round(progress * 100)}%
          </text>
          <rect x={0} y={320} width={340} height={66} rx={20} fill="#111" />
          <text x={170} y={362} textAnchor="middle" fontSize={26} fontWeight={800} fill="#fff">
            Download PDF
          </text>
        </g>
      </FadeUp>
    </Shell>
  );
};

const strengths = ["Fast parse", "Gradio-first", "Docker start", "Local models", "Persistent workspace"];

const Section07 = ({frame}: {frame: number}) => (
  <Shell frame={frame} index={6}>
    <TitleBlock frame={frame} title="What works well" subtitle="Even the MVP has a clear product flow" y={220} />
    <g transform="translate(230 475)">
      {strengths.map((item, i) => {
        const p = clamp(s(frame, 30 + i * 9));
        return (
          <g key={item} opacity={p} transform={`translate(${i * 300} ${interpolate(p, [0, 1], [40, 0])})`}>
            <rect width={250} height={220} rx={32} fill="#fff" stroke="#d2d2d7" filter="url(#soft-6)" />
            <text x={125} y={104} textAnchor="middle" fontSize={52} fontWeight={860} fill={i === 0 ? "#0071e3" : "#111"}>
              {i + 1}
            </text>
            <text x={125} y={162} textAnchor="middle" fontSize={24} fontWeight={760} fill="#111">
              {item}
            </text>
          </g>
        );
      })}
    </g>
  </Shell>
);

const Section08 = ({frame}: {frame: number}) => (
  <Shell frame={frame} index={7}>
    <TitleBlock frame={frame} title="Next, measure more" subtitle="Keep adding sample outputs and benchmark runs to the README" y={220} />
    <FadeUp frame={frame} start={28}>
      {[
        ["README video", "done"],
        ["Sample outputs", "next"],
        ["More PDF2zh runs", "next"],
      ].map(([title, state], i) => (
        <g key={title} transform={`translate(${360 + i * 420} 500)`}>
          <rect width={320} height={250} rx={36} fill="#fff" stroke="#d2d2d7" filter="url(#soft-7)" />
          <text x={160} y={116} textAnchor="middle" fontSize={30} fontWeight={800} fill="#111">
            {title}
          </text>
          <rect x={92} y={165} width={136} height={46} rx={23} fill={state === "done" ? "#0071e3" : "#e5e5ea"} />
          <text x={160} y={196} textAnchor="middle" fontSize={19} fontWeight={820} fill={state === "done" ? "#fff" : "#6e6e73"}>
            {state}
          </text>
        </g>
      ))}
    </FadeUp>
  </Shell>
);

const Section09 = ({frame}: {frame: number}) => (
  <Shell frame={frame} index={8}>
    <FadeUp frame={frame} start={8}>
      <text x={W / 2} y={360} textAnchor="middle" fontSize={118} fontWeight={880} fill="#050505">
        Fast parsing.
      </text>
      <text x={W / 2} y={470} textAnchor="middle" fontSize={118} fontWeight={880} fill="#050505">
        Clean control.
      </text>
      <text x={W / 2} y={610} textAnchor="middle" fontSize={34} fontWeight={560} fill="#6e6e73">
        OpenPDF2ZH Workbench for Gradio-first PDF translation.
      </text>
    </FadeUp>
    <FadeUp frame={frame} start={54}>
      <text x={W / 2} y={825} textAnchor="middle" fontSize={62} fontWeight={840} fill="#111">
        clone  run  translate
      </text>
    </FadeUp>
  </Shell>
);

const scenes = [Section01, Section02, Section03, Section04, Section05, Section06, Section07, Section08, Section09];

export const MyComposition = () => {
  const frame = useCurrentFrame();
  const {durationInFrames} = useVideoConfig();
  const total = sectionDurations.reduce((sum, duration) => sum + duration, 0);
  const overflow = Math.max(0, durationInFrames - total);

  return (
    <AbsoluteFill>
      {scenes.map((Scene, index) => {
        const from = sumBefore(index) + (index === scenes.length - 1 ? overflow : 0);
        return (
          <Sequence key={sections[index].id} from={from} durationInFrames={sectionDurations[index]}>
            <Scene frame={frame - from} />
          </Sequence>
        );
      })}
    </AbsoluteFill>
  );
};

export const TOTAL_FRAMES = sectionDurations.reduce((sum, duration) => sum + duration, 0);
